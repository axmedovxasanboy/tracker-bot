"""The only message this bot sends that nobody asked for.

Tracker's whole shape is monthly — subscriptions fall due on a day, a month is closed once and
permanently, buckets are funded before the month ends — and until now the bot said nothing
unless it was tapped. A person who forgets to open it simply loses the month.

So: one wake-up a day at a civilised local hour, and **at most one message**, only when there
is something worth saying. Four constraints shape everything below.

*It needs a session.* The API is reached as the owner, sessions live in memory with a 24h TTL,
and there is no stored refresh token to fall back on. No session means the bot stays quiet —
nagging someone to log in so that it can nag them about a subscription is not a product.

*It must not repeat itself.* Every line carries a notice id and the day it was last sent; a
line already sent today is dropped, and if that empties the message, nothing is sent at all.

*It must not be able to take the bot down.* Every API call, the composition and the send are
each contained; a failed check costs that day's reminder and nothing else. `CancelledError` is
the one thing allowed through, because that is shutdown asking the loop to stop.

*It is off unless the owner turns it on.* `REMINDERS_ENABLED` defaults to false, and `start()`
returns None in that case — main.py logs "Reminders: disabled" and carries on.
"""
from __future__ import annotations

import asyncio
import calendar
import datetime as dt
import logging
from contextlib import suppress
from typing import Any

from aiogram import Bot

from . import api, clock, config, ui
from .i18n import t
from .keyboards import esc
from .money import fmt_money
from .session import store

log = logging.getLogger(__name__)

# Never sleep longer than this in one go. The loop is a clock-watcher, not a timer: waking
# every few minutes and comparing the local hour is what makes it survive a container that was
# suspended, a host that stepped its clock, or a `REMINDER_HOUR` that is hours away. The cost
# is a datetime comparison 288 times a day.
_POLL_CEILING = 300.0
_MIN_NAP = 5.0

# How close to the end of the month each kind of nudge starts. A month can technically be
# closed from its first day (the backend only requires the previous one to be closed), and a
# bucket is "unfunded" from the 1st — saying so on the 3rd would be noise, not a reminder.
_MONTH_CLOSE_WINDOW = 3
_BUCKET_WINDOW = 5

# A reminder is a nudge, not a report. Past this many lines a section is summarised.
_MAX_LINES = 5

# The four buckets the allocation lines can name. Mapped to keys of our own rather than
# printed from `AllocationLine.label`, which is English prose composed on the Java side.
_BUCKETS = ("DONATION", "EMERGENCY", "INVESTMENTS", "STOCKS")

# Main-menu pages a nudge can point at. The callback shape is `keyboards.PAGES`'s own.
_PAGES = {
    "months": "menu.page.months",
    "finance": "menu.page.finance",
    "overview": "menu.page.overview",
}

_task: asyncio.Task[None] | None = None
# notice id -> the ISO date it was last delivered on.
_sent: dict[str, str] = {}
# The ISO date the daily check last ran, so a poll every five minutes fires once.
_last_run: str | None = None


# ── Lifecycle (called from main.py's dp.startup / dp.shutdown) ──────────────
async def start(bot: Bot) -> asyncio.Task[None] | None:
    """Start the daily loop, or return None when reminders are switched off."""
    global _task, _last_run
    if not config.REMINDERS_ENABLED:
        return None
    if _task is not None and not _task.done():
        return _task

    now = clock.now()
    # Booting after today's slot counts as "today is handled". The already-sent memory lives
    # in this process, so a restart at 21:40 with REMINDER_HOUR=21 would otherwise re-send
    # everything the process before it had already delivered at 21:00. A reminder missed on
    # the day of a restart is quieter than a duplicate, and the owner is at the keyboard.
    _last_run = clock.today_iso() if now.hour >= config.REMINDER_HOUR else None
    _sent.clear()
    _task = asyncio.create_task(_loop(bot), name="tracker-reminders")
    log.info("Reminders on: one check a day at %02d:00 %s.",
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
        try:
            await _tick(bot, today)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("The daily reminder check failed — the loop carries on.")


async def _tick(bot: Bot, today: dt.date) -> None:
    chat_id = _owner_chat()
    if chat_id is None:
        log.debug("Reminders: no owner chat is bound yet — nothing to send to.")
        return
    if store.get(chat_id) is None:
        # Expected, not exceptional: the session is in memory with a 24h TTL, so a day the
        # owner never opened the bot is a day it has no way to call the API as them.
        log.info("Reminders: chat %s has no live session — staying quiet today.", chat_id)
        return

    _forget_all_but(today.isoformat())
    lines, pages, notices = await _compose(chat_id, today)
    if not lines:
        return

    # `grid` returns ROWS, so it is splatted into the keyboard rather than nested as one row.
    keyboard = ui.ikb([
        *ui.grid([(t(chat_id, _PAGES[p]), f"menu:{p}") for p in pages], 2),
        ui.nav(chat_id, menu=True),
    ])
    try:
        await bot.send_message(chat_id, "\n".join(lines), reply_markup=keyboard)
    except Exception:  # noqa: BLE001
        # Not marked as sent: whatever went wrong (the owner blocked the bot, a flood wait) is
        # worth one more attempt tomorrow rather than being silently written off.
        log.warning("Reminders: couldn't deliver to chat %s", chat_id, exc_info=True)
        return
    for notice in notices:
        _sent[notice] = today.isoformat()
    log.info("Reminder sent to chat %s (%d item(s)).", chat_id, len(notices))


def _owner_chat() -> int | None:
    """The chat a reminder may be sent to, or None while nobody owns this bot."""
    bound = store.owner_id()
    if bound is not None:
        return bound
    return config.OWNER_CHAT_ID


def _forget_all_but(today: str) -> None:
    """Drop yesterday's notices. The map is the only state that grows, and this bounds it."""
    for notice in [k for k, day in _sent.items() if day != today]:
        del _sent[notice]


# ── Composing the message ───────────────────────────────────────────────────
async def _compose(chat_id: int, today: dt.date) -> tuple[list[str], list[str], list[str]]:
    """Build the whole message. Returns (lines, menu pages to link, notice ids).

    `today` is passed in rather than read again: one tick must agree with itself about what
    day it is, and the dedupe map is keyed by that same date.
    """
    today_iso = today.isoformat()
    month = clock.month_of(today)
    last_day = calendar.monthrange(today.year, today.month)[1]
    days_left = last_day - today.day

    lines: list[str] = []
    pages: list[str] = []
    notices: list[str] = []

    due = await _due_subscriptions(chat_id, today)
    # One tier read serves both checks, and is skipped when neither needs it. It answers
    # "which subscriptions are still unpaid this month" — the half `nextDueDate` cannot know
    # about, because an "already paid" mark settles a subscription with no transaction behind
    # it and leaves the due date where it was.
    tier: Any = None
    if due or days_left <= _BUCKET_WINDOW:
        tier = await _get(chat_id, "/overview/tier", {"month": month})

    _add_subscriptions(chat_id, today_iso, _still_unpaid(due, tier), lines, pages, notices)
    if days_left <= _MONTH_CLOSE_WINDOW:
        await _add_month_close(chat_id, today_iso, month, last_day, lines, pages, notices)
    if days_left <= _BUCKET_WINDOW:
        _add_buckets(chat_id, today_iso, month, tier, lines, pages, notices)

    if not lines:
        return [], [], []
    # Each section ends with a blank line so two of them do not run together; the last one's
    # is trimmed rather than trailing off the bottom of the message.
    while lines and not lines[-1]:
        lines.pop()
    return [t(chat_id, "auth.remind.title"), "", *lines], pages, notices


async def _due_subscriptions(chat_id: int, today: dt.date) -> list[tuple[dict[str, Any], dt.date]]:
    """Active subscriptions whose due date has arrived or passed, soonest first.

    `nextDueDate` is the "is it due" half. `FinanceService.payMonthlyPayment` advances it a
    month on every recorded payment (anchored to `dueDay`), so a subscription still pointing at
    today or a past date has not been paid *through a transaction* for this cycle. The other
    half — an "already paid" mark, which settles a subscription with no transaction behind it
    and leaves the due date exactly where it was — is `_still_unpaid`'s job.
    """
    rows = await _get(chat_id, "/finance/monthly-payments")
    if not isinstance(rows, list):
        return []
    due: list[tuple[dict[str, Any], dt.date]] = []
    for row in rows:
        if not isinstance(row, dict) or row.get("active") is False:
            continue
        when = _date(row.get("nextDueDate"))
        if when is None or when > today:
            continue
        due.append((row, when))
    due.sort(key=lambda pair: pair[1])
    return due


def _still_unpaid(due: list[tuple[dict[str, Any], dt.date]],
                  tier: Any) -> list[tuple[dict[str, Any], dt.date]]:
    """Narrow the due list to what the backend itself still counts as unpaid this month.

    `OverviewService.pendingSubscriptions` measures recorded payments dated inside the month
    AND the month's SUBSCRIPTION marks, which is the only place the two are added up. It is
    withheld while the income is unset or the month predates the allocation ledger, and the
    call can simply fail — in every one of those cases the due date alone is the best answer
    available, and a nudge about a bill that is genuinely past its date is the safer error.
    """
    if not isinstance(tier, dict) or tier.get("missingStableIncome") or tier.get("beforeTrackingStart"):
        return due
    pending = tier.get("pendingSubscriptions")
    if not isinstance(pending, list):
        return due
    unpaid = {row.get("id") for row in pending if isinstance(row, dict)}
    return [(row, when) for row, when in due if row.get("id") in unpaid]


def _add_subscriptions(chat_id: int, today_iso: str,
                       due: list[tuple[dict[str, Any], dt.date]],
                       lines: list[str], pages: list[str], notices: list[str]) -> None:
    fresh = [(row, when) for row, when in due if _sent.get(f"sub:{row.get('id')}") != today_iso]
    if not fresh:
        return
    lines.append(t(chat_id, "auth.remind.subsHeader"))
    for row, when in fresh[:_MAX_LINES]:
        key = "auth.remind.subToday" if when.isoformat() == today_iso else "auth.remind.subOverdue"
        lines.append(t(chat_id, key,
                       name=esc(row.get("name") or "—"),
                       amount=fmt_money(row.get("amount")),
                       date=when.isoformat()))
    if len(fresh) > _MAX_LINES:
        lines.append(t(chat_id, "auth.remind.subsMore", count=len(fresh) - _MAX_LINES))
    lines.append("")
    pages.append("finance")
    notices.extend(f"sub:{row.get('id')}" for row, _ in fresh)


async def _add_month_close(chat_id: int, today_iso: str, month: str, last_day: int,
                           lines: list[str], pages: list[str], notices: list[str]) -> None:
    notice = f"month:{month}"
    if _sent.get(notice) == today_iso:
        return
    preview = await _get(chat_id, "/months/preview", {"month": month})
    if not isinstance(preview, dict):
        return
    if preview.get("alreadyClosed") or not preview.get("closeable"):
        # `blockedReason` is English prose from the Java side, so it is not shown — and it is
        # not news anyway: "close months in order" is a thing to discover on the Months screen,
        # not a reason to interrupt someone's evening.
        return
    lines.append(t(chat_id, "auth.remind.monthHeader", month=month))
    lines.append(t(chat_id, "auth.remind.monthBody", date=f"{month}-{last_day:02d}"))
    lines.append("")
    pages.append("months")
    notices.append(notice)


def _add_buckets(chat_id: int, today_iso: str, month: str, tier: Any,
                 lines: list[str], pages: list[str], notices: list[str]) -> None:
    if not isinstance(tier, dict):
        return
    # Each of these means the plan has nothing to ask for yet: no stable income to compute a
    # bucket from, a month before the allocation ledger starts, or subscriptions that come off
    # the top first — the backend itself withholds the allocation while that last one is true.
    if (tier.get("missingStableIncome") or tier.get("beforeTrackingStart")
            or tier.get("subscriptionsPending")):
        return
    allocation = tier.get("allocation")
    if not isinstance(allocation, dict):
        return

    unfunded: list[str] = []
    for line in allocation.get("lines") or []:
        if not isinstance(line, dict) or not line.get("recommended"):
            continue
        bucket = str(line.get("bucket") or "").upper()
        remaining = _number(line.get("remainingAmount"))
        target = _number(line.get("minAmount"))
        if remaining <= 0 or target <= 0 or bucket not in _BUCKETS:
            continue
        notice = f"bucket:{bucket}:{month}"
        if _sent.get(notice) == today_iso:
            continue
        unfunded.append(t(chat_id, "auth.remind.bucketLine",
                          bucket=t(chat_id, f"auth.remind.bucket.{bucket}"),
                          remaining=fmt_money(remaining), target=fmt_money(target)))
        notices.append(notice)

    if not unfunded:
        return
    lines.append(t(chat_id, "auth.remind.bucketsHeader"))
    lines.extend(unfunded)
    lines.append(t(chat_id, "auth.remind.bucketsFoot"))
    lines.append("")
    pages.append("overview")


# ── Reading the API without ever raising ────────────────────────────────────
async def _get(chat_id: int, path: str, params: dict[str, Any] | None = None) -> Any:
    """GET as the owner. Any failure — including an expired session — yields None.

    A reminder is best-effort by definition: one endpoint being unavailable should cost that
    one line, not the other two checks and not the loop.
    """
    try:
        return await api.request(chat_id, "GET", path, params=params)
    except Exception:  # noqa: BLE001
        log.warning("Reminders: GET %s failed", path, exc_info=True)
        return None


def _date(value: Any) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
