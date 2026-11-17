"""Nasiya (e.g. Uzum Nasiya, Batch 75): borrowed money paid in full by a deadline for a small fee,
or — once the owner switches it on the web — in monthly installments.

Pure helpers over `GET /finance/loans-taken` rows, shared by the Loans screens (the line) and the
evening reminders (the deadline notices). Creating a nasiya, switching it to installments and
"update what's left" are web-only; the bot never sends `nasiya` / `principalAmount`, so its edits
keep them.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

_EPS = 0.5

# Days before the deadline a reminder goes out on; 0 is the day itself. Each is sent once per loan
# and deadline. A notice missed (the bot was down) is caught up by the next one that still applies:
# 4 or 3 days left counts as the "5 days" notice, so it still goes out once.
STAGES = (5, 2, 1, 0)


def _n(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def is_nasiya(loan: dict) -> bool:
    return bool(loan.get("nasiya"))


def is_switched(loan: dict) -> bool:
    """Switched to monthly installments by the owner."""
    return is_nasiya(loan) and bool(loan.get("installmentsSince"))


def is_open(loan: dict) -> bool:
    """Still to be paid in full by its deadline: a nasiya, not switched, not paid off, with a deadline."""
    return (is_nasiya(loan) and not loan.get("installmentsSince") and loan.get("status") != "PAID"
            and _n(loan.get("remainingAmount")) > _EPS and bool(loan.get("dueDate")))


def deadline(loan: dict) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(loan.get("dueDate"))[:10])
    except (TypeError, ValueError):
        return None


def days_left(loan: dict, today: dt.date) -> int | None:
    """Whole days to the deadline; negative once it has passed; None without one."""
    due = deadline(loan)
    return None if due is None else (due - today).days


def cost(loan: dict) -> float:
    """What it costs on top of the money received — the server's figure, else worked out."""
    if loan.get("extraCost") is not None:
        return max(0.0, _n(loan.get("extraCost")))
    if loan.get("principalAmount") is None:
        return 0.0
    return max(0.0, _n(loan.get("totalAmount")) - _n(loan.get("principalAmount")))


def stage(days: int) -> str | None:
    """Which notice `days` left falls under: d5 / d2 / d1 / d0 / over, or None when not yet."""
    if days < 0:
        return "over"
    for s in sorted(STAGES):
        if days <= s:
            return f"d{s}"
    return None


def notice_id(loan: dict, st: str) -> str:
    """Stable per loan, deadline and stage: a moved deadline starts its notices over."""
    return f"nasiya:{loan.get('id')}:{str(loan.get('dueDate'))[:10]}:{st}"


def due_notices(loans: list[dict], today: dt.date, sent: dict[str, str]) -> list[tuple[str, dict, int]]:
    """The deadline notices worth sending today, never sent before: (id, loan, days left)."""
    out: list[tuple[str, dict, int]] = []
    for loan in loans:
        if not isinstance(loan, dict) or not is_open(loan):
            continue
        days = days_left(loan, today)
        if days is None:
            continue
        st = stage(days)
        if st is None:
            continue
        nid = notice_id(loan, st)
        if nid not in sent:
            out.append((nid, loan, days))
    return sorted(out, key=lambda x: (x[2], str(x[1].get("id"))))
