"""In-memory session store: one token pair per chat, plus the owner binding.

The TTL is enforced in `get()` — the one function that actually hands out the tokens —
rather than in a separate `is_active()` that every call site had to remember to consult.
That split is what let a chat be "expired" on the menu and still write money from a
half-finished flow: `api.request()` read `get()`, saw a Session object and sent its Bearer.
The 15-minute access token was long dead, but the stored refresh token is rotated on every
use (AuthService.refresh), so a session used at least weekly never actually ended and the
advertised 24h was decoration.

Nothing here is locked: the bot is single-threaded on one event loop, and every mutation is
a plain dict operation with no await in the middle.
"""
import logging
import time
from dataclasses import dataclass

from .config import SESSION_TTL_HOURS

logger = logging.getLogger(__name__)


@dataclass
class Session:
    username: str
    access: str
    refresh: str
    login_at: float


class SessionStore:
    """Sessions keyed by Telegram chat id, with a fixed (non-sliding) TTL.

    `ttl_hours <= 0` disables expiry. The old code read 0 as "already expired", which made
    the bot answer "Session expired" to every single tap — not a setting anyone would want.
    """

    def __init__(self, ttl_hours: float = SESSION_TTL_HOURS) -> None:
        self._ttl = ttl_hours * 3600
        self._sessions: dict[int, Session] = {}
        self._owner: int | None = None

    # ── Sessions ────────────────────────────────────────────────────────────
    def start(self, chat_id: int, username: str, access: str, refresh: str) -> Session:
        s = Session(username=username, access=access, refresh=refresh, login_at=time.time())
        self._sessions[chat_id] = s
        # "The first chat that authenticates successfully binds itself as the owner" — and
        # this is the one place a successful authentication lands, so the binding happens
        # here rather than depending on every caller remembering it. Idempotent: a chat id
        # pinned from OWNER_CHAT_ID at boot is not displaced by a later login.
        self.bind_owner(chat_id)
        return s

    def get(self, chat_id: int) -> Session | None:
        """The live session for this chat, or None once it is past its TTL.

        Expiry drops the row rather than merely reporting it: this is the store's only
        eviction path, and a row left in place keeps a refresh token that is good for
        another seven days sitting in process memory.
        """
        s = self._sessions.get(chat_id)
        if s is None:
            return None
        if self._ttl > 0 and (time.time() - s.login_at) >= self._ttl:
            del self._sessions[chat_id]
            logger.info("Session for chat %s expired after %.0fh", chat_id, self._ttl / 3600)
            return None
        return s

    def lock(self, chat_id: int) -> None:
        self._sessions.pop(chat_id, None)

    def is_active(self, chat_id: int) -> bool:
        """Exactly the question `get()` answers, so a screen can never disagree with a write."""
        return self.get(chat_id) is not None

    # ── Owner binding (FIX-CONTRACT §2) ─────────────────────────────────────
    # The webhook secret ships blank and aiogram's verify_secret returns True unconditionally
    # when it is, so anyone who learns the public URL can POST forged updates. The bot serves
    # exactly one person, so the cheap mitigation is to remember which chat that is.
    def bind_owner(self, chat_id: int) -> int:
        """Claim this process for `chat_id` if nobody holds it yet; return the owning id.

        Trust-on-first-login: OWNER_CHAT_ID is optional, so the first chat to authenticate
        binds itself for the life of the process. The return value is the *current* owner,
        which is not necessarily `chat_id` — a caller decides what to do when they differ.
        """
        if self._owner is None:
            self._owner = chat_id
            logger.info("Owner chat bound to %s — pin it with OWNER_CHAT_ID=%s in .env",
                        chat_id, chat_id)
        return self._owner

    def owner_id(self) -> int | None:
        """The bound owner, or None while the bot is still waiting for a first login.

        The guard's predicate is `owner_id() in (None, chat_id)`: nobody bound yet means the
        door is still open, anything else means this chat is not the owner.
        """
        return self._owner


# Shared singleton.
store = SessionStore()
