"""Reusable screen pieces: button grids, the navigation row, short dates.

Two rules the builders here enforce: Back on the left, Cancel on the right — always, so the thumb
learns one position; and a keyboard never carries an empty row (`keyboards.ikb` drops them).
"""
import datetime as dt

from . import clock
from .i18n import t
from .keyboards import ikb

__all__ = ["day", "grid", "ikb", "nav"]

Row = list[tuple[str, str]]

# Listed literally so tools/check.py can see every key is used.
_MONTHS = ("common.mon.1", "common.mon.2", "common.mon.3", "common.mon.4", "common.mon.5",
           "common.mon.6", "common.mon.7", "common.mon.8", "common.mon.9", "common.mon.10",
           "common.mon.11", "common.mon.12")
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
