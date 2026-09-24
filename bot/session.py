"""Session store: one token pair per chat, plus the owner binding.

A login lasts until /lock. There is no time limit of our own: the access token is refreshed
before it expires (`bot/api.py`), the refresh token before IT expires (`bot/keepalive.py` and
every request), and the owner's pair is kept on disk (`bot/storage.py`) so a restart does not
log them out. The owner is asked to log in again only when the backend rejects the refresh.

Nothing here is locked: the bot is single-threaded on one event loop, and every mutation is
a plain dict operation with no await in the middle.
"""
import logging
from dataclasses import dataclass

from . import storage

logger = logging.getLogger(__name__)


@dataclass
class Session:
    username: str
    access: str
    refresh: str


class SessionStore:
    """Sessions keyed by Telegram chat id."""

    def __init__(self) -> None:
        self._sessions: dict[int, Session] = {}
        self._owner: int | None = None
        self._restore()

    # ── Staying logged in ───────────────────────────────────────────────────
    def _kept(self, chat_id: int) -> bool:
        """Only the owner's login is written to disk."""
        return storage.enabled() and chat_id == self._owner

    def _restore(self) -> None:
        owner = storage.owner()
        if owner is None:
            return
        self._owner = owner
        saved = storage.get("session")
        if not isinstance(saved, dict):
            return
        try:
            s = Session(username=str(saved["username"]), access=str(saved["access"]),
                        refresh=str(saved["refresh"]))
        except (KeyError, TypeError, ValueError):
            logger.warning("The saved login is incomplete — ignoring it.")
            return
        self._sessions[owner] = s
        logger.info("Restored the owner's login (chat %s) — no need to log in again.", owner)

    def _save(self, chat_id: int) -> None:
        if not self._kept(chat_id):
            return
        s = self._sessions.get(chat_id)
        storage.put("session", None if s is None else {
            "username": s.username, "access": s.access, "refresh": s.refresh,
        })

    def update_tokens(self, chat_id: int, access: str, refresh: str) -> None:
        """A refresh rotated the pair: keep the new one, on disk too for the owner."""
        s = self._sessions.get(chat_id)
        if s is None:
            return
        s.access, s.refresh = access, refresh
        self._save(chat_id)

    # ── Sessions ────────────────────────────────────────────────────────────
    def start(self, chat_id: int, username: str, access: str, refresh: str) -> Session:
        s = Session(username=username, access=access, refresh=refresh)
        self._sessions[chat_id] = s
        # The one place a successful authentication lands, so the binding happens here. A chat
        # already bound (pinned in .env, or saved) is not displaced by a later login.
        self.bind_owner(chat_id)
        self._save(chat_id)
        return s

    def get(self, chat_id: int) -> Session | None:
        return self._sessions.get(chat_id)

    def chats(self) -> list[int]:
        """Every chat with a live login — the keep-alive walks these."""
        return list(self._sessions)

    def lock(self, chat_id: int) -> None:
        """Log this chat out — and forget the saved login, so /lock survives a restart too."""
        self._sessions.pop(chat_id, None)
        self._save(chat_id)

    def is_active(self, chat_id: int) -> bool:
        return self.get(chat_id) is not None

    # ── Owner binding ───────────────────────────────────────────────────────
    # The bot serves exactly one person. With OWNER_CHAT_ID unset, the first chat to log in
    # claims it (trust on first login), and the claim is saved so a restart keeps it.
    def bind_owner(self, chat_id: int) -> int:
        """Claim the bot for `chat_id` if nobody holds it yet; return the owning id."""
        if self._owner is None:
            self._owner = chat_id
            storage.bind(chat_id)
            logger.info("Owner chat bound to %s — pin it with OWNER_CHAT_ID=%s in .env",
                        chat_id, chat_id)
        return self._owner

    def owner_id(self) -> int | None:
        """The bound owner, or None while the bot is still waiting for a first login."""
        return self._owner


# Shared singleton.
store = SessionStore()
