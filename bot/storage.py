"""The little the bot remembers across restarts, in one JSON file.

Everything else stays in memory on purpose. This file holds exactly three things, all about the
owner, and only when the owner has been pinned with `OWNER_CHAT_ID` (a chat that merely claimed
the bot by logging in first is never written down):

* **the login** — the token pair, so a restart or a redeploy does not log the owner out. The
  owner asked for "stay logged in": the advisor messages them every evening, and it cannot do
  that as someone the bot has forgotten. The refresh token rotates on every use and lives seven
  days, so an evening check that refreshes it keeps the login alive indefinitely;
* **the language** they picked, which used to reset to English on every restart;
* **which reminders went out when**, so a restart at 21:30 does not repeat the evening message.

The file is written atomically (temp file + rename) with 0600 permissions: it holds a refresh
token, which is as good as the password for seven days. /lock deletes the login from it.

`SESSION_FILE` points at it; in Docker, mount a volume there (see DEPLOY.md) or the file dies
with the container and the owner logs in again after every deploy — annoying, never unsafe.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from .config import OWNER_CHAT_ID, SESSION_FILE, STAY_LOGGED_IN

log = logging.getLogger(__name__)

_state: dict[str, Any] = {}
_loaded = False


def enabled() -> bool:
    """Whether anything is persisted at all: an owner is pinned and they want to stay logged in."""
    return STAY_LOGGED_IN and OWNER_CHAT_ID is not None and bool(SESSION_FILE)


def _path() -> Path:
    return Path(SESSION_FILE)


def _load() -> None:
    global _state, _loaded
    _loaded = True
    if not enabled():
        return
    try:
        raw = _path().read_text(encoding="utf-8")
    except FileNotFoundError:
        return
    except OSError:
        log.warning("Couldn't read %s — starting with nothing remembered.", SESSION_FILE, exc_info=True)
        return
    try:
        data = json.loads(raw)
    except ValueError:
        log.warning("%s is not valid JSON — ignoring it.", SESSION_FILE)
        return
    if not isinstance(data, dict):
        return
    # A file written for a different owner (the id in .env changed) is not this owner's.
    if data.get("owner_chat_id") != OWNER_CHAT_ID:
        log.info("%s belongs to another chat id — ignoring it.", SESSION_FILE)
        return
    _state = data


def get(key: str, default: Any = None) -> Any:
    if not _loaded:
        _load()
    return _state.get(key, default)


def put(key: str, value: Any) -> None:
    """Set one top-level key and write the file. A failed write is logged, never raised: losing
    what the bot remembers costs a login, raising here would cost the handler that called it."""
    if not _loaded:
        _load()
    if not enabled():
        return
    if value is None:
        _state.pop(key, None)
    else:
        _state[key] = value
    _state["owner_chat_id"] = OWNER_CHAT_ID
    path = _path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".session-", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(_state, f)
            os.chmod(tmp, 0o600)
            os.replace(tmp, path)
        except BaseException:
            _unlink_quietly(tmp)
            raise
    except OSError:
        log.warning("Couldn't write %s — the bot will forget this on restart.", SESSION_FILE, exc_info=True)


def _unlink_quietly(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass
