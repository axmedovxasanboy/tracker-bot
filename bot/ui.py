"""Reusable screen pieces: button grids, the navigation row, short dates.

Two rules the builders here enforce: Back on the left, Cancel on the right — always, so the thumb
learns one position; and a keyboard never carries an empty row (`keyboards.ikb` drops them).
"""
import datetime as dt

from . import clock
from .i18n import t
from .keyboards import ikb

__all__ = ["day", "grid", "ikb", "month_name", "month_short", "month_text", "nav", "shift_month"]

Row = list[tuple[str, str]]

# Listed literally so tools/check.py can see every key is used.
_MONTHS = ("common.mon.1", "common.mon.2", "common.mon.3", "common.mon.4", "common.mon.5",
           "common.mon.6", "common.mon.7", "common.mon.8", "common.mon.9", "common.mon.10",
           "common.mon.11", "common.mon.12")
_MONTHS_FULL = ("common.monthFull.1", "common.monthFull.2", "common.monthFull.3", "common.monthFull.4",
                "common.monthFull.5", "common.monthFull.6", "common.monthFull.7", "common.monthFull.8",
                "common.monthFull.9", "common.monthFull.10", "common.monthFull.11", "common.monthFull.12")
# Monday first, as `date.weekday()` counts.
_WEEKDAYS = ("common.wd.0", "common.wd.1", "common.wd.2", "common.wd.3", "common.wd.4",
             "common.wd.5", "common.wd.6")


def grid(items: list[tuple[str, str]], per_row: int = 2) -> list[Row]:
    """Lay (text, callback_data) pairs out N to a row."""
    per_row = max(1, per_row)
    return [items[i:i + per_row] for i in range(0, len(items), per_row)]


def nav(chat_id: int | None, back: str | None = None, cancel: str | None = None,
        home: bool = False) -> Row:
    """Back on the left, Home in the middle, Cancel on the right. Empty when nothing is asked."""
    row: Row = []
    if back:
        row.append((t(chat_id, "common.back"), back))
    if home:
        row.append((t(chat_id, "common.home"), "home"))
    if cancel:
        row.append((t(chat_id, "common.cancel"), cancel))
    return row


def day(chat_id: int | None, value, *, weekday: bool = False, relative: bool = False) -> str:
    """`2026-09-24` → "24 Sep" (or "Wed 24 Sep"; or "Today" / "Tomorrow" when `relative`)."""
    try:
        d = value if isinstance(value, dt.date) else dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        return str(value or "—")
    if relative:
        today = clock.today()
        if d == today:
            return t(chat_id, "common.today")
        if d == today + dt.timedelta(days=1):
            return t(chat_id, "common.tomorrow")
        if d == today - dt.timedelta(days=1):
            return t(chat_id, "common.yesterday")
    text = f"{d.day} {t(chat_id, _MONTHS[d.month - 1])}"
    return f"{t(chat_id, _WEEKDAYS[d.weekday()])} {text}" if weekday else text


def shift_month(ym: str, delta: int) -> str:
    """`2026-01`, -1 → `2025-12`."""
    total = int(ym[:4]) * 12 + int(ym[5:7]) - 1 + delta
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def month_name(chat_id: int | None, ym: str) -> str:
    """`2026-09` → "September"."""
    return t(chat_id, _MONTHS_FULL[int(str(ym)[5:7]) - 1])


def month_short(chat_id: int | None, ym: str) -> str:
    """`2026-08` → "Aug"."""
    return t(chat_id, _MONTHS[int(str(ym)[5:7]) - 1])


def month_text(chat_id: int | None, ym: str) -> str:
    """"September", or "December 2025" when it is not this year."""
    if str(ym)[:4] == str(clock.today().year):
        return month_name(chat_id, ym)
    return t(chat_id, "common.monthYear", month=month_name(chat_id, ym), year=str(ym)[:4])
