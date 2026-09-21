"""The evening message: the advisor, sent to the owner when something needs them.

The owner asked for an advisor that messages them rather than an app they have to remember to
open. So once a day, at `REMINDER_HOUR` local time, this loop reads `GET /advisor` as the owner
and sends the home screen itself — the same text and the same buttons (`advisor.compose`) — when
there is a reason to:

* **something new is due** — a bill, a wallet check, a month to close, money to set aside. Each
  "do this" suggestion has an id, and one that was already sent is repeated only after
  `_REPEAT_DAYS`, so an unpaid rent is a reminder every few days, not a nag every evening;
* **it is Sunday** — a short weekly look at the month, even when nothing is due, which is also
  when the "start a goal" and "you have spare money" ideas get their say.

Otherwise the evening is quiet. Ideas alone never trigger a message.

*It needs the owner's login.* `bot/storage.py` keeps it across restarts, and this daily call is
what keeps it alive: every refresh returns a new seven-day refresh token. If the backend rejects
the login anyway, the owner is told once, so the silence that follows is not a mystery.

*It must not repeat itself.* What was sent when is kept with the login (`storage`), so a restart
at 21:30 neither repeats the evening's message nor loses the repeat timers.

*It must not be able to take the bot down.* The call, the composition and the send are each
contained; a failed check costs that day's message and nothing else. `CancelledError` is the one
thing allowed through, because that is shutdown asking the loop to stop.

*It is on by default* but needs someone to talk to: `OWNER_CHAT_ID`, or a chat that logged in.
`REMINDERS_ENABLED=false` switches it off.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
from contextlib import suppress
from typing import Any

from aiogram import Bot

from . import api, clock, config, keyboards, storage
from .i18n import t
from .session import store

log = logging.getLogger(__name__)

# Never sleep longer than this in one go. The loop is a clock-watcher, not a timer: waking
# every few minutes and comparing the local hour is what makes it survive a container that was
# suspended, a host that stepped its clock, or a `REMINDER_HOUR` that is hours away. The cost
# is a datetime comparison 288 times a day.
_POLL_CEILING = 300.0
_MIN_NAP = 5.0

# An unchanged "do this" is repeated after this many days: often enough that a bill is not
# forgotten, rarely enough that the message is not the thing the owner learns to ignore.
_REPEAT_DAYS = 3
# Sunday (Monday is 0): the weekly look at the month.
_WEEKLY_DAY = 6
# Sent-notice history older than this is dropped; nothing repeats on a longer cycle.
_KEEP_DAYS = 40

_task: asyncio.Task[None] | None = None
# notice id -> the ISO date it was last delivered on.
_sent: dict[str, str] = {}
# The ISO date the daily check last ran, so a poll every five minutes fires once.
_last_run: str | None = None


# ── Lifecycle (called from main.py's dp.startup / dp.shutdown) ──────────────
async def start(bot: Bot) -> asyncio.Task[None] | None:
    """Start the daily loop, or return None when reminders are switched off."""
    global _task, _last_run, _sent
    if not config.REMINDERS_ENABLED:
        return None
    if _task is not None and not _task.done():
        return _task

    saved = storage.get("reminders") or {}
    _sent = dict(saved.get("sent") or {}) if isinstance(saved, dict) else {}
    if storage.enabled():
        # The history is on disk, so a restart after today's slot knows whether today's message
        # actually went out — and sends it if the bot was down at REMINDER_HOUR.
        _last_run = saved.get("last_run") if isinstance(saved, dict) else None
    else:
        # Nothing remembered: booting after today's slot counts as "today is handled", because a
        # message missed on the day of a restart is quieter than a duplicate.
        _last_run = clock.today_iso() if clock.now().hour >= config.REMINDER_HOUR else None
    _task = asyncio.create_task(_loop(bot), name="tracker-reminders")
    log.info("Reminders on: one advisor check a day at %02d:00 %s.",
             config.REMINDER_HOUR, clock.TZ.tzname(None) or "local time")
    return _task


async def stop() -> None:
    """Cancel the loop and wait for it to unwind. Safe to call when it never started."""
    global _task
    task, _task = _task, None
    if task is None:
        return
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
    log.info("Reminders stopped.")


# ── The loop ────────────────────────────────────────────────────────────────
def _nap_seconds() -> float:
    """How long to sleep before looking at the clock again.

    Converges on the target rather than aiming at it: far away it returns the ceiling, and
    within five minutes it returns the exact remainder, so the check lands on the hour without
    the loop ever holding a multi-hour sleep that a clock change could invalidate.
    """
    now = clock.now()
    target = now.replace(hour=config.REMINDER_HOUR, minute=0, second=0, microsecond=0)
    if target <= now:
        target += dt.timedelta(days=1)
    return min(max((target - now).total_seconds(), _MIN_NAP), _POLL_CEILING)


async def _loop(bot: Bot) -> None:
    global _last_run
    while True:
        await asyncio.sleep(_nap_seconds())
        today = clock.today()
        if clock.now().hour < config.REMINDER_HOUR or _last_run == today.isoformat():
            continue
        # Stamped BEFORE the run, deliberately: a check that dies half way through has
        # possibly already sent, and a retry would be the duplicate this whole module is
        # arranged to avoid. The cost of the other reading is one missed day.
        _last_run = today.isoformat()
        _remember()
        try:
            await _tick(bot, today)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("The daily advisor check failed — the loop carries on.")


def _owner_chat() -> int | None:
    """The chat a reminder may be sent to, or None while nobody owns this bot."""
    bound = store.owner_id()
    if bound is not None:
        return bound
    return config.OWNER_CHAT_ID


def _remember() -> None:
    storage.put("reminders", {"sent": _sent, "last_run": _last_run})


def notice_id(s: dict[str, Any], month: str) -> str:
    """Who a "do this" is about, stable across days: the same unpaid rent is the same notice."""
    p = s.get("params") or {}
    subject = s.get("refId") or s.get("bucket") or p.get("month") or ""
    return f"{s.get('code')}:{subject}:{month}"


def due_notices(data: dict[str, Any], today: dt.date, sent: dict[str, str]) -> list[str]:
    """The "do this" notices worth a message today: never sent, or last sent `_REPEAT_DAYS` ago."""
    month = clock.month_of(today)
    fresh: list[str] = []
    for s in data.get("suggestions") or []:
        if not isinstance(s, dict) or s.get("kind") != "DO":
            continue
        nid = notice_id(s, month)
        last = sent.get(nid)
        try:
            stale = last is None or (today - dt.date.fromisoformat(last)).days >= _REPEAT_DAYS
        except ValueError:
            stale = True
        if stale:
            fresh.append(nid)
    return fresh


async def _tick(bot: Bot, today: dt.date) -> None:
    from .routers import advisor  # the router imports aiogram handlers; keep it off the import path

    chat_id = _owner_chat()
    if chat_id is None:
        log.debug("Reminders: no owner chat is bound yet — nothing to send to.")
        return
    if store.get(chat_id) is None:
        # The owner locked the bot (or never logged in): they chose silence.
        log.info("Reminders: chat %s is not logged in — staying quiet today.", chat_id)
        return

    try:
        data = await advisor.fetch(chat_id)
    except api.NeedsLogin:
        # The backend rejected the saved login (the refresh token ran out while the bot was
        # down for a week, or the JWT secret changed). Say so once: the next evenings are quiet
        # because the session is gone, and that should not look like the advisor gave up.
        log.info("Reminders: the login for chat %s was rejected — asking the owner to log in.", chat_id)
        with suppress(Exception):
            await bot.send_message(chat_id, t(chat_id, "adv.remind.loggedOut"),
                                   reply_markup=keyboards.login_kb(chat_id))
        return
    except Exception:  # noqa: BLE001
        log.warning("Reminders: couldn't read the advisor for chat %s", chat_id, exc_info=True)
        return

    _forget_before(today)
    fresh = due_notices(data, today, _sent)
    weekly = today.weekday() == _WEEKLY_DAY
    if not fresh and not weekly:
        log.info("Reminders: nothing new for chat %s today.", chat_id)
        return

    header = t(chat_id, "adv.remind.weekly" if weekly else "adv.remind.evening")
    text, kb = advisor.compose(chat_id, data, header=header)
    try:
        await bot.send_message(chat_id, text, reply_markup=kb)
    except Exception:  # noqa: BLE001
        # Not marked as sent: whatever went wrong (the owner blocked the bot, a flood wait) is
        # worth one more attempt tomorrow rather than being silently written off.
        log.warning("Reminders: couldn't deliver to chat %s", chat_id, exc_info=True)
        return
    # Everything due was on screen, so every "do this" restarts its repeat timer today.
    month = clock.month_of(today)
    for s in data.get("suggestions") or []:
        if isinstance(s, dict) and s.get("kind") == "DO":
            _sent[notice_id(s, month)] = today.isoformat()
    _remember()
    log.info("Advisor message sent to chat %s (%d new item(s)%s).",
             chat_id, len(fresh), ", weekly" if weekly else "")


def _forget_before(today: dt.date) -> None:
    """Drop notices older than `_KEEP_DAYS`: the map is the only state that grows."""
    for nid, day in list(_sent.items()):
        try:
            old = (today - dt.date.fromisoformat(day)).days > _KEEP_DAYS
        except ValueError:
            old = True
        if old:
            del _sent[nid]
