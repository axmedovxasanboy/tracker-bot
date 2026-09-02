"""In-memory session store (24h TTL + /lock)."""
import time
from dataclasses import dataclass

from .config import SESSION_TTL_HOURS


@dataclass
class Session:
    username: str
    access: str
    refresh: str
    login_at: float


class SessionStore:
    def __init__(self, ttl_hours: float = SESSION_TTL_HOURS) -> None:
        self._ttl = ttl_hours * 3600
        self._sessions: dict[int, Session] = {}

    def start(self, chat_id: int, username: str, access: str, refresh: str) -> Session:
        s = Session(username=username, access=access, refresh=refresh, login_at=time.time())
        self._sessions[chat_id] = s
        return s

    def get(self, chat_id: int) -> Session | None:
        return self._sessions.get(chat_id)

    def lock(self, chat_id: int) -> None:
        self._sessions.pop(chat_id, None)

    def is_active(self, chat_id: int) -> bool:
        s = self._sessions.get(chat_id)
        return s is not None and (time.time() - s.login_at) < self._ttl


# Shared singleton.
store = SessionStore()
