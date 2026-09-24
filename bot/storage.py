"""The little the bot remembers about its owner, in one JSON file.

Everything here is about the one person the bot serves:

* **who that is** — `OWNER_CHAT_ID`, or else the chat that logged in first. The binding is written
  down, so a restart does not reopen the door to whoever writes next;
* **the login** — the token pair, so a restart or a redeploy does not log the owner out. A login
  lasts until /lock: `bot/keepalive.py` refreshes it before the seven-day refresh token runs out;
* **preferences** — the language, the wallet used last, which category a word meant last time,
  the savings account used last;
* **which reminders went out when**, for the optional evening message.

Values are always kept in memory; the file is written only when `STAY_LOGGED_IN` is on and an
owner is known. It is written atomically (temp file + rename) with 0600 permissions: it holds a
refresh token, which is as good as the password for seven days. /lock deletes the login from it.

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
    """Whether anything is written to disk at all."""
    return STAY_LOGGED_IN and bool(SESSION_FILE)


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
    saved_owner = data.get("owner_chat_id")
    if OWNER_CHAT_ID is not None and saved_owner != OWNER_CHAT_ID:
        log.info("%s belongs to another chat id — ignoring it.", SESSION_FILE)
        return
    if not isinstance(saved_owner, int):
        return
    _state = data


def _ensure() -> None:
    if not _loaded:
        _load()


def owner() -> int | None:
    """The owner's chat id: pinned in .env, else the one that logged in first (as saved)."""
    _ensure()
    if OWNER_CHAT_ID is not None:
        return OWNER_CHAT_ID
    saved = _state.get("owner_chat_id")
    return saved if isinstance(saved, int) else None


def bind(chat_id: int) -> None:
    """Remember who the owner is. A no-op once someone is bound."""
    _ensure()
    if owner() is None:
        _state["owner_chat_id"] = chat_id
        _write()


def get(key: str, default: Any = None) -> Any:
    _ensure()
    return _state.get(key, default)


def put(key: str, value: Any) -> None:
    """Set one top-level key (None deletes it) and write the file.

    A failed write is logged, never raised: losing what the bot remembers costs a login or a
    guess, raising here would cost the handler that called it.
    """
    _ensure()
    if value is None:
        _state.pop(key, None)
    else:
        _state[key] = value
    _write()


def pref(name: str, default: Any = None) -> Any:
    prefs = get("prefs")
    return prefs.get(name, default) if isinstance(prefs, dict) else default


def set_pref(name: str, value: Any) -> None:
    prefs = dict(get("prefs") or {})
    if value is None:
        prefs.pop(name, None)
    else:
        prefs[name] = value
    put("prefs", prefs)


def _write() -> None:
    who = owner()
    if not enabled() or who is None:
        return
    _state["owner_chat_id"] = who
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
