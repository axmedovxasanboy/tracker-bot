"""The bot's calendar: today, in the owner's timezone rather than the container's.

The container runs on UTC and Tashkent is UTC+5, so between 00:00 and 05:00 local a bare
`dt.date.today()` still says YESTERDAY. Every date this bot writes is a coordinate in the
monthly envelope — a transaction's `date`, the `YYYY-MM` a month screen loads, the month a
close is booked against — so a UTC "today" files the money into the wrong day and, on the
1st, into the PREVIOUS month, where the backend either books it in the wrong envelope or
refuses it outright because that month is already closed. Nothing warns anyone: the amount
is right, the screen says saved, and the figure lands somewhere the owner will not look.

A fixed offset is the correct rule, not a shortcut. Uzbekistan abolished DST in 1995 and has
been on UTC+5 since, so there is no transition table to consult; reading zoneinfo would make
the bot depend on tzdata being present in a slim image, which is a runtime failure waiting
for a value that never changes. The offset is configurable (`TZ_OFFSET_HOURS`) so that the
one thing that could ever change is an env var and not a code edit.

Import this module wherever you would have written `dt.date.today()`, `dt.datetime.now()` or
`strftime("%Y-%m")`.
"""
import datetime as dt

from .config import TZ_OFFSET_HOURS

_OFFSET = dt.timedelta(hours=TZ_OFFSET_HOURS)
# The name is only ever surfaced by tzname()/%Z, so it is claimed only when the offset really
# is Tashkent's — an overridden offset labelled "Asia/Tashkent" would be a lie in a log line.
TZ = dt.timezone(_OFFSET, "Asia/Tashkent") if TZ_OFFSET_HOURS == 5 else dt.timezone(_OFFSET)

__all__ = ["TZ", "month", "month_of", "now", "today", "today_iso"]


def now() -> dt.datetime:
    """Timezone-aware current moment. Aware, so arithmetic against it can never be silently
    mixed with a UTC-naive value."""
    return dt.datetime.now(TZ)


def today() -> dt.date:
    return now().date()


def today_iso() -> str:
    """`2026-09-07` — the shape every date field in the API takes."""
    return today().isoformat()


def month() -> str:
    """`2026-09` — the shape the months and overview endpoints take."""
    return month_of(today())


def month_of(d: dt.date) -> str:
    # Formatted by hand rather than with strftime("%Y-%m"): the width of %Y is
    # platform-dependent, and this string is a lookup key on the backend.
    return f"{d.year:04d}-{d.month:02d}"
