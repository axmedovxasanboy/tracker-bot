"""Async API client (httpx) for the Tracker backend.

One pooled AsyncClient for the whole process. Constructing an `httpx.AsyncClient` costs
~16 ms of *synchronous* work on the event loop — almost all of it in
`ssl.create_default_context()`, which parses certifi's 236 KB CA bundle off disk — and the
add-a-transaction flow alone makes six calls. The old `async with httpx.AsyncClient(...)`
around every call paid that six times, reused no socket, and did it for an API that is
plain HTTP inside the compose network, so the TLS setup was pure waste.

`request()` attaches the session Bearer, keeps the token pair fresh, and raises exactly two
things every router already catches:
  * `NeedsLogin` — there is no usable session; show the login screen.
  * `ApiError`   — we have something to tell the user, in `.message`.
`Unreachable` is an `ApiError` subclass for "we never reached the backend at all".
"""
import asyncio
import base64
import logging
import time
from json import loads as json_loads
from typing import Any

import httpx

from .config import API_BASE_URL, REQUEST_TIMEOUT
from .session import store

logger = logging.getLogger(__name__)

# What Spring Security's entry point writes when no valid access token reached the controller
# at all (SecurityConfig.java:47-51). A 401 carrying any other message came out of a service
# and is that endpoint's own answer, not a verdict on the token.
_TOKEN_401 = "Authentication required"

# Refresh this many seconds before the access token's own `exp`. The backend signs standard
# HS256 JWTs (JwtService.build) with app.jwt.access-ttl-seconds = 900, so the expiry is
# visible in the token and does not have to be discovered by spending a request on a 401.
_EXPIRY_LEEWAY = 30.0

# An error line is interpolated into a message that already has a header and a keyboard, so
# a pathological validation map must not eat the 4096-char budget on its own.
_MAX_MSG = 500


class ApiError(Exception):
    """The call finished and we have something to show. `status` is the HTTP status, or 0
    when there never was one (see `Unreachable`)."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


class Unreachable(ApiError):
    """We could not talk to the backend: connection refused, DNS, timeout, dropped socket.

    A subclass rather than a new top-level type so every existing `except api.ApiError`
    keeps working. Callers that want the translated `common.serverUnreachable` instead of
    httpx's English sentence should catch `api.Unreachable` *before* `api.ApiError`.
    """

    def __init__(self, exc: Exception) -> None:
        super().__init__(0, str(exc) or exc.__class__.__name__)


class NeedsLogin(Exception):
    """No valid session — the user must (re)authenticate."""


def _clip(text: str) -> str:
    """One tidy line: collapse the whitespace (a stray newline would break the layout of the
    message it is spliced into) and cap the length."""
    text = " ".join(text.split())
    return text if len(text) <= _MAX_MSG else text[: _MAX_MSG - 1] + "…"


def _msg(resp: httpx.Response) -> str:
    """Turn an error body into one line the owner can act on.

    Validation failures arrive as `{"errors": {"<field>": "<constraint>"}}`
    (GlobalExceptionHandler.handleValidation) and roughly a third of the DTO constraints
    carry no custom `message=`, so the value on its own is a sentence fragment: "must not be
    null", "must be greater than or equal to 0". After a six-field form — or three wallet
    balances at month close — that tells the owner nothing about *which* number to fix, so
    the field name is kept. The key is kept whole, brackets included: `wallets[1].
    enteredBalance` names the second wallet, and dropping the index would lose that.
    """
    data: Any = None
    try:
        data = resp.json()
    except Exception:  # noqa: BLE001
        pass
    if isinstance(data, dict):
        errors = data.get("errors")
        if isinstance(errors, dict) and errors:
            return _clip("; ".join(f"{k}: {v}" for k, v in errors.items()))
        text = data.get("message") or data.get("error")
        if text:
            return _clip(str(text))
    return f"Request failed ({resp.status_code})"


def _expiry(token: str) -> float | None:
    """The `exp` claim of a JWT, read without verifying anything.

    We are not the party that validates this token — the backend is. We only want to know
    whether it is still worth sending. Anything we cannot parse returns None, and the caller
    falls back to discovering the expiry the old way, as a 401.
    """
    try:
        payload = token.split(".")[1]
        # JWT uses base64url with the padding stripped; b64decode insists on having it.
        raw = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
        exp = json_loads(raw).get("exp")
    except (AttributeError, IndexError, TypeError, ValueError):
        return None
    try:
        return float(exp)
    except (TypeError, ValueError):
        return None


# ── The pooled client ───────────────────────────────────────────────────────
_client: httpx.AsyncClient | None = None
_client_loop: asyncio.AbstractEventLoop | None = None

# One refresh at a time per chat. Bounded by the number of chats that ever logged in, which
# the owner guard (FIX-CONTRACT §2) pins to one.
_refresh_locks: dict[int, asyncio.Lock] = {}


def _new_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=API_BASE_URL,
        timeout=REQUEST_TIMEOUT,
        # A single-user bot never needs a wide pool; keep-alive is the part that matters, so
        # an idle connection outlives the pause between two taps on the same screen.
        limits=httpx.Limits(max_connections=10, max_keepalive_connections=5,
                            keepalive_expiry=60.0),
    )


async def client() -> httpx.AsyncClient:
    """The process-wide client, built on first use and reused from then on.

    Rebuilt if the running loop has changed. A connection pool holds sockets belonging to the
    loop that opened them, so a client carried across loops fails with "Event loop is closed"
    on the first request. Nothing can be awaited on a loop that is already gone, so the old
    client is dropped rather than closed; the per-chat `asyncio.Lock`s go with it, because a
    Lock binds itself to the first loop that awaits it and refuses every other one.
    """
    global _client, _client_loop
    loop = asyncio.get_running_loop()
    if _client is not None and _client_loop is loop:
        return _client
    if _client is not None:
        logger.debug("Event loop changed — rebuilding the HTTP connection pool")
    _refresh_locks.clear()
    _client, _client_loop = _new_client(), loop
    return _client


async def aclose() -> None:
    """Close the pooled client. Register on the dispatcher's shutdown so keep-alive sockets
    are shut down cleanly instead of being reset when the process dies."""
    global _client, _client_loop
    c, loop = _client, _client_loop
    _client, _client_loop = None, None
    _refresh_locks.clear()
    if c is None:
        return
    if loop is not None and loop is not asyncio.get_running_loop():
        return  # belongs to a loop we are not running on; there is nothing we can await
    try:
        await c.aclose()
    except Exception:  # noqa: BLE001
        logger.debug("Ignoring error while closing the HTTP client", exc_info=True)


# ── Token-less endpoints ────────────────────────────────────────────────────
async def auth_status() -> dict[str, Any]:
    c = await client()
    r = await c.get("/auth/status")
    if r.status_code >= 400:
        raise ApiError(r.status_code, _msg(r))
    return r.json()


async def telegram_config() -> dict[str, Any]:
    """Public, token-less: { webhookUrl, webViewUrl } set in the web app's Developer page.

    Deliberately NOT on the pooled client. This is read once at boot, from a throwaway loop
    (`asyncio.run` in main._load_config) that is closed before the server starts, and a pool
    created there would be useless — or worse, an idle socket owned by a dead loop.
    """
    async with httpx.AsyncClient(base_url=API_BASE_URL, timeout=REQUEST_TIMEOUT) as c:
        r = await c.get("/settings/telegram")
        if r.status_code >= 400:
            raise ApiError(r.status_code, _msg(r))
        return r.json()


async def login(username: str, password: str) -> dict[str, Any]:
    return await _auth_post("/auth/login", username, password)


async def signup(username: str, password: str) -> dict[str, Any]:
    return await _auth_post("/auth/signup", username, password)


async def _auth_post(path: str, username: str, password: str) -> dict[str, Any]:
    c = await client()
    r = await c.post(path, json={"username": username, "password": password})
    if r.status_code >= 400:
        raise ApiError(r.status_code, _msg(r))
    return r.json()


# ── Authenticated endpoints ─────────────────────────────────────────────────
async def reset(chat_id: int, password: str) -> None:
    """Factory reset (Danger Zone): POST /settings/reset {password}.

    `auth_retry=False` because the backend answers a WRONG PASSWORD with 401 "Incorrect
    password." (ResetService.java:52 → GlobalExceptionHandler.java:29-32) — the same status
    a dead access token gets. With the retry on, one mistyped character re-fired a
    truncate-everything endpoint and then told the owner their session had expired, so the
    natural next move was to retype their credentials into the chat. The 401 now reaches
    menu.reset_password as an ApiError carrying the server's own sentence.

    On success the account itself is gone, so callers must lock the session afterwards.
    """
    await request(chat_id, "POST", "/settings/reset", json={"password": password},
                  auth_retry=False)


async def request(chat_id: int, method: str, path: str, *,
                  params: dict[str, Any] | None = None,
                  json: dict[str, Any] | list[Any] | None = None,
                  auth_retry: bool = True) -> Any:
    """Call the backend as `chat_id`.

    `auth_retry=False` marks an endpoint whose 401 is its own answer rather than a verdict on
    the token: don't refresh, don't re-send, hand the message back. The access token is still
    refreshed *before* the call when it has already expired, so switching the retry off costs
    such an endpoint nothing — see `reset()`.
    """
    # store.get() enforces the TTL and drops the row, so an expired chat can no longer write
    # money from a flow it started yesterday while the menu tells it the session is over.
    s = store.get(chat_id)
    if s is None:
        raise NeedsLogin()

    c = await client()
    access = s.access
    exp = _expiry(access)
    if exp is not None and exp - _EXPIRY_LEEWAY <= time.time():
        access = await _refresh(chat_id, access)

    r = await c.request(method, path, params=params, json=json,
                        headers={"Authorization": f"Bearer {access}"})

    if r.status_code == 401:
        if not auth_retry:
            message = _msg(r)
            if message == _TOKEN_401:
                # Not the endpoint's answer after all: the token really was rejected. Say so
                # rather than showing Spring's sentence — but still do NOT re-send, because
                # the caller marked this endpoint as one that must never fire twice.
                store.lock(chat_id)
                raise NeedsLogin()
            raise ApiError(401, message)
        access = await _refresh(chat_id, access)
        r = await c.request(method, path, params=params, json=json,
                            headers={"Authorization": f"Bearer {access}"})
        if r.status_code == 401:
            store.lock(chat_id)
            raise NeedsLogin()

    if r.status_code >= 400:
        raise ApiError(r.status_code, _msg(r))
    if r.status_code == 204 or not r.content:
        return None
    return r.json()


async def _refresh(chat_id: int, seen: str) -> str:
    """Exchange the refresh token for a new pair and return the new access token.

    Serialised per chat. One screen can fire several calls at once (Plan makes four) and
    AuthService.refresh ROTATES the refresh token, so two concurrent refreshes mean the
    loser replays a token the server has already retired — which comes back as "Invalid or
    expired refresh token" and logs the owner out for nothing. Whoever wins the lock updates
    the Session in place; everyone waiting behind them sees the access token has moved on
    and uses the new one instead of refreshing again.
    """
    lock = _refresh_locks.setdefault(chat_id, asyncio.Lock())
    async with lock:
        s = store.get(chat_id)
        if s is None:
            raise NeedsLogin()
        if s.access != seen:
            return s.access
        c = await client()
        try:
            r = await c.post("/auth/refresh", json={"refreshToken": s.refresh})
        except httpx.HTTPError as exc:
            # We never heard back, so we know nothing about the token — and keeping the
            # session is the whole point: a five-second blip used to cost the owner a full
            # username+password re-login while their refresh token was good for another week.
            logger.warning("Token refresh could not reach the backend: %r", exc)
            raise Unreachable(exc) from exc
        if r.status_code >= 400:
            # The server ruled on it: spent, rotated away, revoked, or signed with an old key.
            logger.info("Token refresh rejected (%s) — locking chat %s", r.status_code, chat_id)
            store.lock(chat_id)
            raise NeedsLogin()
        try:
            data = r.json()
            s.access, s.refresh = data["accessToken"], data["refreshToken"]
        except Exception as exc:  # noqa: BLE001
            # A 2xx we cannot read is a backend bug, not a verdict on the session.
            raise ApiError(r.status_code, "Unreadable refresh response") from exc
        return s.access
