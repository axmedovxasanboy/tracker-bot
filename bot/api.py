"""Async API client (httpx) for the Tracker backend.

Auth calls are token-less. `request()` attaches the session Bearer token and transparently
refreshes once on a 401, locking the session and raising NeedsLogin if refresh fails.
"""
from typing import Any

import httpx

from .config import API_BASE_URL, REQUEST_TIMEOUT
from .session import store


class ApiError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


class NeedsLogin(Exception):
    """No valid session — the user must (re)authenticate."""


def _msg(resp: httpx.Response) -> str:
    try:
        data = resp.json()
        if isinstance(data, dict):
            errors = data.get("errors")
            if isinstance(errors, dict) and errors:
                return "; ".join(str(v) for v in errors.values())
            return str(data.get("message") or data.get("error") or f"Request failed ({resp.status_code})")
    except Exception:  # noqa: BLE001
        pass
    return f"Request failed ({resp.status_code})"


async def auth_status() -> dict[str, Any]:
    async with httpx.AsyncClient(base_url=API_BASE_URL, timeout=REQUEST_TIMEOUT) as c:
        r = await c.get("/auth/status")
        if r.status_code >= 400:
            raise ApiError(r.status_code, _msg(r))
        return r.json()


async def telegram_config() -> dict[str, Any]:
    """Public, token-less: { webhookUrl, webViewUrl } set in the web app's Developer page."""
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
    async with httpx.AsyncClient(base_url=API_BASE_URL, timeout=REQUEST_TIMEOUT) as c:
        r = await c.post(path, json={"username": username, "password": password})
        if r.status_code >= 400:
            raise ApiError(r.status_code, _msg(r))
        return r.json()


async def reset(chat_id: int, password: str) -> None:
    """Factory reset (Danger Zone): POST /settings/reset {password}. Re-verified server-side,
    this wipes ALL data including the account, so the session is dead afterwards — callers
    should lock the session and send the user back to login/signup."""
    await request(chat_id, "POST", "/settings/reset", json={"password": password})


async def request(chat_id: int, method: str, path: str, *,
                  params: dict[str, Any] | None = None,
                  json: dict[str, Any] | list[Any] | None = None) -> Any:
    s = store.get(chat_id)
    if s is None:
        raise NeedsLogin()
    async with httpx.AsyncClient(base_url=API_BASE_URL, timeout=REQUEST_TIMEOUT) as c:
        r = await c.request(method, path, params=params, json=json,
                            headers={"Authorization": f"Bearer {s.access}"})
        if r.status_code == 401:
            try:
                tok = await c.post("/auth/refresh", json={"refreshToken": s.refresh})
                tok.raise_for_status()
                data = tok.json()
                s.access, s.refresh = data["accessToken"], data["refreshToken"]
            except Exception as exc:  # noqa: BLE001
                store.lock(chat_id)
                raise NeedsLogin() from exc
            r = await c.request(method, path, params=params, json=json,
                                headers={"Authorization": f"Bearer {s.access}"})
            if r.status_code == 401:
                store.lock(chat_id)
                raise NeedsLogin()
        if r.status_code >= 400:
            raise ApiError(r.status_code, _msg(r))
        if r.status_code == 204 or not r.content:
            return None
        return r.json()
