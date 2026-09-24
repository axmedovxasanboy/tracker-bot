"""Keeps the owner logged in through a quiet week.

The refresh token lives seven days and every request rotates it once it is two days old
(`api.REFRESH_MARGIN`). A week without a single tap would still let it run out, so this loop
rotates it every few hours whether or not anything else happens. The owner is asked to log in
again only when the backend actually rejects the refresh — and then told once, with a button.

A backend that cannot be reached is not a rejection: the loop tries again next time.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import suppress

from aiogram import Bot

from . import api, keyboards
from .i18n import t
from .session import store

log = logging.getLogger(__name__)

_FIRST_CHECK = 60.0
_INTERVAL = 6 * 3600.0

_task: asyncio.Task[None] | None = None


async def start(bot: Bot) -> asyncio.Task[None]:
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(_loop(bot), name="tracker-keepalive")
    return _task


async def stop() -> None:
    global _task
    task, _task = _task, None
    if task is None:
        return
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


async def _loop(bot: Bot) -> None:
    await asyncio.sleep(_FIRST_CHECK)
    while True:
        for chat_id in store.chats():
            await _check(bot, chat_id)
        await asyncio.sleep(_INTERVAL)


async def _check(bot: Bot, chat_id: int) -> None:
    try:
        await api.keep_fresh(chat_id)
    except asyncio.CancelledError:
        raise
    except api.NeedsLogin:
        log.info("Keep-alive: the login for chat %s was rejected — asking to log in again.", chat_id)
        with suppress(Exception):
            await bot.send_message(chat_id, t(chat_id, "auth.loggedOut"),
                                   reply_markup=keyboards.login_kb(chat_id))
    except Exception:  # noqa: BLE001 — unreachable backend: try again next round
        log.warning("Keep-alive: couldn't refresh chat %s's login this time.", chat_id, exc_info=True)
