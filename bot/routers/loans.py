"""💳 Loans & bills — the web's Loans page (tracker-frontend pages/Loans.tsx), in the bot.

The page, top to bottom: what leaves every month (bills + loans on a monthly plan), "You owe
(repay fast)" and "Owed to you"; then Monthly bills (✓ Paid or Pay), Loans you pay monthly (bank
loans + MONTHLY borrowed money, next date, left to repay), Repay as fast as possible (ASAP borrowed
money + debts: "All due now" / "34% this month: X"), Owed to you ("Got money back"), and the people
lists ("You borrowed most from" / "Borrowed most from you", top 5). Every record opens on its own
screen: Pay, Edit, Pause/Resume (bills), History, Delete.

Figures follow the web exactly (ALLOCATION-EXPLAINED §6): a MONTHLY loan asks its plan (else 34 % of
the original), capped at what is left; an ASAP loan or a debt asks all of what is left once that
is ≤ 70 % of the monthly income, else 34 % of what is left — and where the advisor already dates
this month's ask (`daily.upcoming`), its figure wins, because it knows what this month has paid.
A bill is paid this month when the advisor no longer lists it among the month's bills.

Callbacks owned here: `loan` and `loan:*`.
"""
from __future__ import annotations

import asyncio
from typing import Any

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, TelegramObject

from .. import api, clock, common, ui
from ..config import CURRENCY
from ..i18n import cat_name, t
from ..keyboards import esc, ikb
from ..money import fmt_money
from . import home, pay
from .pay import Field, Spec

router = Router(name="loans")

# BOT-A's "☰ More" menu, where Loans & bills is opened from.
MORE = "more"
_SHARE = 0.34     # of what is left, each month, on money repaid as fast as possible
_ALL_DUE = 0.7    # at or below this share of the monthly income, all that is left is due now
_EPS = 0.5
_MAX_PAY = 6
_HISTORY = 20
_PEOPLE = 5
_n = home.n
_KINDS = ("bill", "bank", "taken", "debt", "given")
_PATH = {"bill": "monthly-payments", "bank": "bank-loans", "taken": "loans-taken", "debt": "debts",
         "given": "loans-given"}
_UPCOMING = {"bill": "BILL", "bank": "BANK", "taken": "LOAN", "debt": "DEBT"}
_ICON = {"bill": "📅", "bank": "🏦", "taken": "💵", "debt": "🧾", "given": "🤝"}
# Bank loans made from the web no longer ask for a product name; the server still needs one.
_DEFAULT_LOAN_NAMES = {"loan", "kredit"}


# ── Loading ─────────────────────────────────────────────────────────────────
async def _list(chat_id: int, path: str) -> list[dict]:
    return [x for x in await api.request(chat_id, "GET", path) or [] if isinstance(x, dict)]


async def _month_tx(chat_id: int, month: str) -> list[dict]:
    """This month's transactions — which loans are already paid for the month."""
    rows: list[dict] = []
    seen: set[Any] = set()
    try:
        for page in range(5):
            res = await api.request(chat_id, "GET", "/transactions", params={
                "page": page, "size": 100, "sortBy": "transactionDate", "sortDir": "desc",
                "startDate": f"{month}-01", "endDate": pay.last_day(month)}) or {}
            for tx in res.get("content") or []:
                if isinstance(tx, dict) and tx.get("id") not in seen:
                    seen.add(tx.get("id"))
                    rows.append(tx)
            if page + 1 >= int(res.get("totalPages") or 1):
                break
    except api.NeedsLogin:
        raise
    except Exception:  # noqa: BLE001 — only the "next payment" wording leans on it
        return rows
    return rows


async def _load(chat_id: int) -> dict[str, Any]:
    month = clock.month()
    bills, banks, taken, debts, given, adv, settings, txs = await asyncio.gather(
        _list(chat_id, "/finance/monthly-payments"), _list(chat_id, "/finance/bank-loans"),
        _list(chat_id, "/finance/loans-taken"), _list(chat_id, "/finance/debts"),
        _list(chat_id, "/finance/loans-given"), home.fetch(chat_id),
        api.request(chat_id, "GET", "/settings"), _month_tx(chat_id, month))
    settings = settings if isinstance(settings, dict) else {}
    income = _n(settings.get("monthlyStableIncome")) or None
    d = {"month": month, "today": clock.today_iso(), "bills": bills, "banks": banks, "taken": taken,
         "debts": debts, "given": given, "adv": adv, "settings": settings, "income": income, "txs": txs}
    d["due"] = _next_due(adv)
    d["billRows"] = _bill_rows(d)
    d["obligations"] = _obligations(d)
    return d


# ── The web's arithmetic ────────────────────────────────────────────────────
def _ym(value: Any) -> str | None:
    return str(value)[:7] if value else None


def repayment_of(loan: dict) -> str:
    """MONTHLY or ASAP. An older server does not say: a plan then means monthly."""
    if loan.get("repaymentType") in ("MONTHLY", "ASAP"):
        return loan["repaymentType"]
    return "MONTHLY" if _n(loan.get("plannedMonthlyPayment")) > 0 else "ASAP"


def taken_monthly(loan: dict) -> float:
    left = max(0.0, _n(loan.get("remainingAmount")))
    if left <= 0:
        return 0.0
    plan = _n(loan.get("plannedMonthlyPayment"))
    return min(plan if plan > 0 else _n(loan.get("totalAmount")) * _SHARE, left)


def asap_due(left: float, income: float | None) -> tuple[float, bool]:
    """All of what is left once it is ≤ 70 % of the monthly income, else 34 % of it."""
    rest = max(0.0, left)
    all_now = bool(income) and rest <= income * _ALL_DUE
    return round(rest if all_now else rest * _SHARE), all_now


def _next_due(adv: dict) -> dict[tuple[str, Any], dict]:
    """Each bill's and loan's next payment within the advisor's five weeks, still to make."""
    out: dict[tuple[str, Any], dict] = {}
    daily = adv.get("daily") if isinstance(adv.get("daily"), dict) else {}
    for u in daily.get("upcoming") or []:
        if not isinstance(u, dict) or u.get("recorded"):
            continue
        key = (u.get("kind"), u.get("refId"))
        if key not in out or str(u.get("date")) < str(out[key].get("date")):
            out[key] = u
    return out


def _bill_rows(d: dict) -> list[dict]:
    """Each bill with whether this month is paid (None when the advisor cannot tell) and what is left."""
    adv, month = d["adv"], d["month"]
    start = _ym(d["settings"].get("allocationTrackingStartMonth"))
    knows = not adv.get("missingStableIncome") and not (start and start > month)
    left = {b.get("refId"): _n(b.get("amount")) for b in adv.get("bills") or []
            if isinstance(b, dict) and b.get("kind") == "SUBSCRIPTION" and b.get("refId") is not None}
    return [{"record": m, "paid": (m.get("id") not in left) if knows else None,
             "left": left.get(m.get("id")) if knows else None} for m in d["bills"]]


def _bank_paid(running: list[dict], payments: list[dict]) -> dict[Any, float]:
    """This month's bank instalments, per loan — they carry only the bank's name in their note."""
    paid: dict[Any, float] = {}
    if not running:
        return paid

    def add(ref: Any, amount: float) -> None:
        paid[ref] = paid.get(ref, 0.0) + amount

    if len(running) == 1:
        for tx in payments:
            add(running[0].get("id"), _n(tx.get("amount")))
        return paid
    unmatched = 0.0
    for tx in payments:
        text = str(tx.get("description") or "").lower()
        named = [b for b in running if b.get("bankName") and str(b["bankName"]).lower() in text]
        hit = next((b for b in named if b.get("loanName") and str(b["loanName"]).lower() in text),
                   named[0] if named else None)
        if hit:
            add(hit.get("id"), _n(tx.get("amount")))
        else:
            unmatched += _n(tx.get("amount"))
    for b in running:
        if unmatched <= 0:
            break
        short = _n(b.get("monthlyPayment")) - paid.get(b.get("id"), 0.0)
        if short > 0:
            take = min(short, unmatched)
            add(b.get("id"), take)
            unmatched -= take
    return paid


def _obligations(d: dict) -> list[dict]:
    """Bank loans, borrowed money and debts — what a month costs, what is left, when next."""
    month, income = d["month"], d["income"]
    repaid_taken: dict[Any, float] = {}
    repaid_debt: dict[Any, float] = {}
    bank_payments = []
    for tx in d["txs"]:
        sub = tx.get("subType")
        if sub == "LOAN_REPAYMENT":
            if tx.get("repaidLoanTakenId") is not None:
                repaid_taken[tx["repaidLoanTakenId"]] = repaid_taken.get(tx["repaidLoanTakenId"], 0.0) + _n(tx.get("amount"))
            elif tx.get("repaidDebtId") is not None:
                repaid_debt[tx["repaidDebtId"]] = repaid_debt.get(tx["repaidDebtId"], 0.0) + _n(tx.get("amount"))
        elif sub == "BANK_LOAN_PAYMENT":
            bank_payments.append(tx)
    out: list[dict] = []
    running = [b for b in d["banks"] if (not _ym(b.get("takenDate")) or _ym(b.get("takenDate")) <= month)
               and (not _ym(b.get("endDate")) or _ym(b.get("endDate")) >= month)]
    bank_paid = _bank_paid(running, bank_payments)
    for b in d["banks"]:
        monthly = _n(b.get("monthlyPayment")) or None
        taken = _ym(b.get("takenDate")) or month
        end = _ym(b.get("endDate"))
        not_started = taken > month
        paid_now = not not_started and monthly is not None and bank_paid.get(b.get("id"), 0.0) >= monthly - _EPS
        nxt = taken if not_started else pay.shift_month(month, 1) if paid_now else month
        paid_off = bool(end) and nxt > end
        left = (pay.months_between(nxt, end) + 1) * monthly if not paid_off and monthly and end else None
        out.append({"kind": "bank", "id": b.get("id"), "record": b, "name": str(b.get("bankName") or "—"),
                    "monthly": monthly, "remaining": 0.0 if paid_off else left, "estimated": left is not None,
                    "paidOff": paid_off, "paidThisMonth": paid_now, "asap": False,
                    "next": None if paid_off else {"month": nxt, "first": not_started}})

    def personal(kind: str, r: dict, name: str, monthly: float, paid_so_far: float, asap: bool) -> dict:
        paid_off = r.get("status") == "PAID" or _n(r.get("remainingAmount")) <= _EPS
        start = _ym(r.get("paymentStartDate"))
        not_started = bool(start) and start > month
        paid_now = not paid_off and not not_started and monthly > 0 and paid_so_far >= monthly - _EPS
        nxt = None if paid_off else {"month": start, "first": True} if not_started else \
            {"month": pay.shift_month(month, 1) if paid_now else month, "first": False}
        return {"kind": kind, "id": r.get("id"), "record": r, "name": name,
                "monthly": None if paid_off else monthly,
                "remaining": 0.0 if paid_off else max(0.0, _n(r.get("remainingAmount"))), "estimated": False,
                "paidOff": paid_off, "paidThisMonth": paid_now, "asap": asap, "next": nxt}

    for loan in d["taken"]:
        asap = repayment_of(loan) == "ASAP"
        monthly = asap_due(_n(loan.get("remainingAmount")), income)[0] if asap else taken_monthly(loan)
        out.append(personal("taken", loan, str(loan.get("lenderName") or "—"), monthly,
                            repaid_taken.get(loan.get("id"), 0.0), asap))
    for debt in d["debts"]:  # every debt is repaid as fast as possible
        out.append(personal("debt", debt, str(debt.get("creditorName") or "—"),
                            asap_due(_n(debt.get("remainingAmount")), income)[0],
                            repaid_debt.get(debt.get("id"), 0.0), True))
    return sorted(out, key=lambda o: ((o["next"] or {}).get("month") or "9999-99", o["name"]))


def _asap_now(d: dict, o: dict) -> tuple[float, bool]:
    """This month's ask on a fast-repaid loan: the advisor's, when it dates one; else the rule."""
    left = o["remaining"] or 0.0
    due = d["due"].get((_UPCOMING[o["kind"]], o["id"]))
    if due is not None:
        return _n(due.get("amount")), _n(due.get("amount")) >= left - _EPS
    return asap_due(left, d["income"])


def _owed_done(r: dict) -> bool:
    return r.get("status") == "PAID" or _n(r.get("pendingAmount")) <= _EPS


# ── Lines ───────────────────────────────────────────────────────────────────
def _next_line(chat_id: int, d: dict, o: dict) -> str | None:
    if not o["next"]:
        return None
    due = d["due"].get((_UPCOMING[o["kind"]], o["id"]))
    if due is not None:
        if str(due.get("date")) == d["today"]:
            return t(chat_id, "loans.nextToday")
        when = ui.day(chat_id, due.get("date"))
        return t(chat_id, "loans.firstOn" if o["next"]["first"] else "loans.nextOn", when=when)
    when = pay.month_label(chat_id, o["next"]["month"])
    if o["next"]["first"]:
        return t(chat_id, "loans.firstOn", when=when)
    return t(chat_id, "loans.nextThisMonth") if o["next"]["month"] == d["month"] else t(chat_id, "loans.nextOn", when=when)


def _left_line(chat_id: int, o: dict) -> str:
    if o["remaining"] is None:
        return t(chat_id, "loans.borrowedTotal", amount=fmt_money(_n(o["record"].get("totalAmount"))))
    key = "loans.leftToRepayAbout" if o["estimated"] else "loans.leftToRepay"
    return t(chat_id, key, amount=fmt_money(o["remaining"]))


def _bill_line(chat_id: int, d: dict, row: dict) -> str:
    m = row["record"]
    parts = [f"{_ICON['bill']} <b>{esc(m.get('name') or '—')}</b>",
             t(chat_id, "loans.aMonth", amount=fmt_money(_n(m.get("amount"))))]
    if not m.get("active", True):
        parts.append(t(chat_id, "loans.bills.paused"))
        return " · ".join(parts)
    due = d["due"].get(("BILL", m.get("id")))
    if due is None:
        parts.append(t(chat_id, "loans.bills.dueOn", day=m.get("dueDay") or "—"))
    elif str(due.get("date")) == d["today"]:
        parts.append(t(chat_id, "loans.bills.dueToday"))
    else:
        parts.append(t(chat_id, "loans.bills.dueDate", date=ui.day(chat_id, due.get("date"))))
    if row["paid"]:
        parts.append(t(chat_id, "loans.bills.paid"))
    elif due is not None and due.get("overdue"):
        parts.append(t(chat_id, "loans.overdue"))
    return " · ".join(parts)


def _monthly_line(chat_id: int, d: dict, o: dict) -> str:
    head = f"{_ICON[o['kind']]} <b>{esc(o['name'])}</b>"
    loan_name = str(o["record"].get("loanName") or "") if o["kind"] == "bank" else ""
    if loan_name and loan_name != o["name"] and loan_name.strip().lower() not in _DEFAULT_LOAN_NAMES:
        head += f" ({esc(loan_name)})"
    if o["paidOff"]:
        return " · ".join([head, t(chat_id, "loans.paidOff"),
                           t(chat_id, "loans.total", amount=fmt_money(_n(o["record"].get("totalAmount"))))])
    parts = [head, t(chat_id, "loans.aMonth", amount=fmt_money(o["monthly"])) if o["monthly"] is not None else "—",
             _left_line(chat_id, o)]
    nxt = _next_line(chat_id, d, o)
    if nxt:
        parts.append(nxt)
    due = d["due"].get((_UPCOMING[o["kind"]], o["id"]))
    if due and due.get("overdue"):
        parts.append(t(chat_id, "loans.overdue"))
    return " · ".join(parts)


def _asap_line(chat_id: int, d: dict, o: dict) -> str:
    head = f"{_ICON[o['kind']]} <b>{esc(o['name'])}</b>"
    if o["paidOff"]:
        return " · ".join([head, t(chat_id, "loans.paidOff"),
                           t(chat_id, "loans.total", amount=fmt_money(_n(o["record"].get("totalAmount"))))])
    amount, all_now = _asap_now(d, o)
    parts = [head, t(chat_id, "loans.leftToRepay", amount=fmt_money(o["remaining"] or 0)),
             t(chat_id, "loans.allDueNow") if all_now else t(chat_id, "loans.dueThisMonth", amount=fmt_money(amount))]
    due = d["due"].get((_UPCOMING[o["kind"]], o["id"]))
    if due and due.get("overdue"):
        parts.append(t(chat_id, "loans.overdue"))
    return " · ".join(parts)


def _owed_line(chat_id: int, r: dict) -> str:
    done = _owed_done(r)
    parts = [f"{_ICON['given']} <b>{esc(r.get('debtorName') or '—')}</b>",
             t(chat_id, "loans.owed.returned", amount=fmt_money(_n(r.get("totalAmount")))) if done
             else t(chat_id, "loans.owed.stillOwed", amount=fmt_money(_n(r.get("pendingAmount")))),
             t(chat_id, "loans.owed.lentOn", amount=fmt_money(_n(r.get("totalAmount"))),
               date=pay.date_label(chat_id, r.get("lentDate")))]
    if not done and r.get("expectedReturnDate"):
        parts.append(t(chat_id, "loans.owed.backBy", date=pay.date_label(chat_id, r.get("expectedReturnDate"))))
    return " · ".join(parts)


def _sections(d: dict) -> dict[str, list[dict]]:
    obligations = d["obligations"]
    return {"mon": [o for o in obligations if not o["asap"]],
            "asap": [o for o in obligations if o["asap"]]}


def _with_notice(notice: str | None, text: str) -> str:
    return f"{notice}\n\n{text}" if notice else text


async def _enter(cb: CallbackQuery, state: FSMContext) -> bool:
    await common.ack(cb)
    await state.clear()
    return await common.gate(cb)


# ── The page ────────────────────────────────────────────────────────────────
@router.callback_query(F.data == "loan")
async def on_loans(cb: CallbackQuery, state: FSMContext) -> None:
    if await _enter(cb, state):
        await show_loans(cb)


async def show_loans(event: TelegramObject, notice: str | None = None) -> None:
    chat_id = common.chat_id_of(event)
    try:
        d = await _load(chat_id)
    except Exception as exc:  # noqa: BLE001
        await pay.report(event, exc, "loan")
        return
    month = d["month"]
    sec = _sections(d)
    active_mon = [o for o in sec["mon"] if not o["paidOff"]]
    active_asap = [o for o in sec["asap"] if not o["paidOff"]]
    waiting = [r for r in d["given"] if not _owed_done(r)]
    bills_monthly = sum(_n(m.get("amount")) for m in d["bills"] if m.get("active", True))
    loans_monthly = sum(o["monthly"] or 0 for o in active_mon)
    lines = [t(chat_id, "loans.title"), "",
             t(chat_id, "loans.everyMonth", amount=fmt_money(bills_monthly + loans_monthly)),
             t(chat_id, "loans.everyMonthSplit", bills=fmt_money(bills_monthly), loans=fmt_money(loans_monthly)),
             t(chat_id, "loans.youOwe", amount=fmt_money(sum(o["remaining"] or 0 for o in active_asap))),
             t(chat_id, "loans.owedToYou", amount=fmt_money(sum(_n(r.get("pendingAmount")) for r in waiting)))]
    if d["adv"].get("missingStableIncome"):
        lines += ["", t(chat_id, "loans.noIncome")]

    lines += ["", t(chat_id, "loans.bills.title")]
    lines += [_bill_line(chat_id, d, row) for row in d["billRows"]] or [t(chat_id, "loans.bills.none")]
    lines += ["", t(chat_id, "loans.mon.title")]
    lines += [_monthly_line(chat_id, d, o) for o in active_mon] or [t(chat_id, "loans.mon.none")]
    if len(sec["mon"]) > len(active_mon):
        lines.append(t(chat_id, "loans.paidOffCount", count=len(sec["mon"]) - len(active_mon)))
    lines += ["", t(chat_id, "loans.asap.title")]
    lines += [_asap_line(chat_id, d, o) for o in active_asap] or [t(chat_id, "loans.asap.none")]
    if len(sec["asap"]) > len(active_asap):
        lines.append(t(chat_id, "loans.paidOffCount", count=len(sec["asap"]) - len(active_asap)))
    lines += ["", t(chat_id, "loans.owed.title")]
    lines += [_owed_line(chat_id, r) for r in waiting] or [t(chat_id, "loans.owed.none")]
    if len(d["given"]) > len(waiting):
        lines.append(t(chat_id, "loans.owed.returnedCount", count=len(d["given"]) - len(waiting)))

    # Pay buttons where something is due this month and not paid yet — the rest are one tap away.
    pays: list[tuple[str, str]] = []
    for row in d["billRows"]:
        m = row["record"]
        if m.get("active", True) and row["paid"] is not True:
            pays.append((home.clip("💳 " + str(m.get("name") or "—")), f"loan:pay:bill:{m['id']}"))
    for o in active_mon + active_asap:
        due_now = (o["next"] or {}).get("month") == month and not o["paidThisMonth"]
        if due_now and (o["kind"] != "bank" or o["monthly"] is not None):
            pays.append((home.clip("💳 " + o["name"]), f"loan:pay:{o['kind']}:{o['id']}"))
    kb = ui.grid(pays[:_MAX_PAY], 2)
    kb += [[(t(chat_id, "loans.btn.bills"), "loan:s:bill"), (t(chat_id, "loans.btn.mon"), "loan:s:mon")],
           [(t(chat_id, "loans.btn.asap"), "loan:s:asap"), (t(chat_id, "loans.btn.owed"), "loan:s:owed")],
           [(t(chat_id, "loans.btn.people"), "loan:ppl"), (t(chat_id, "loans.btn.add"), "loan:add")],
           ui.nav(chat_id, back=MORE, home=True)]
    await common.show(event, _with_notice(notice, "\n".join(lines)), ikb(kb))


# ── Sections ────────────────────────────────────────────────────────────────
_SECTIONS = ("bill", "mon", "asap", "owed")


@router.callback_query(F.data.startswith("loan:s:"))
async def on_section(cb: CallbackQuery, state: FSMContext) -> None:
    parts = cb.data.split(":")
    if len(parts) < 3 or parts[2] not in _SECTIONS or not await _enter(cb, state):
        return
    await show_section(cb, parts[2], show_all=len(parts) > 3 and parts[3] == "all")


async def show_section(event: TelegramObject, sec: str, notice: str | None = None, show_all: bool = False) -> None:
    chat_id = common.chat_id_of(event)
    try:
        d = await _load(chat_id)
    except Exception as exc:  # noqa: BLE001
        await pay.report(event, exc, f"loan:s:{sec}")
        return
    if sec == "bill":
        items = [("bill", row["record"]["id"], row["record"].get("name"), _bill_line(chat_id, d, row), False)
                 for row in d["billRows"]]
        title, empty, add = "loans.bills.title", "loans.bills.none", [("loans.btn.addBill", "loan:add:bill")]
    elif sec == "owed":
        items = [("given", r["id"], r.get("debtorName"), _owed_line(chat_id, r), _owed_done(r)) for r in d["given"]]
        title, empty, add = "loans.owed.title", "loans.owed.none", [("loans.btn.addLent", "loan:add:lent")]
    else:
        line = _monthly_line if sec == "mon" else _asap_line
        items = [(o["kind"], o["id"], o["name"], line(chat_id, d, o), o["paidOff"]) for o in _sections(d)[sec]]
        title = "loans.mon.title" if sec == "mon" else "loans.asap.title"
        empty = "loans.mon.none" if sec == "mon" else "loans.asap.none"
        add = [("loans.btn.addBank", "loan:add:bank"), ("loans.btn.addBorrowed", "loan:add:borrowed")] \
            if sec == "mon" else [("loans.btn.addBorrowed", "loan:add:borrowed")]
    done = [i for i in items if i[4]]
    shown = items if show_all else [i for i in items if not i[4]]
    lines = [t(chat_id, title), ""]
    lines += [i[3] for i in shown] or [t(chat_id, empty)]
    kb = ui.grid([(home.clip(f"{_ICON[k]} {name or '—'}"), f"loan:r:{k}:{ref}") for k, ref, name, _, _ in shown], 2)
    if done:
        label = t(chat_id, "loans.showLess") if show_all else t(
            chat_id, "loans.owed.returnedCount" if sec == "owed" else "loans.paidOffCount", count=len(done))
        kb.append([(label, f"loan:s:{sec}" if show_all else f"loan:s:{sec}:all")])
    kb.append([(t(chat_id, key), cb) for key, cb in add])
    kb.append(ui.nav(chat_id, back="loan", home=True))
    await common.show(event, _with_notice(notice, "\n".join(lines)), ikb(kb))


def _section_of(kind: str, record: dict) -> str:
    if kind == "bill":
        return "bill"
    if kind == "given":
        return "owed"
    if kind == "bank" or (kind == "taken" and repayment_of(record) == "MONTHLY"):
        return "mon"
    return "asap"


def _parse(data: str, prefix_parts: int = 2) -> tuple[str, int] | None:
    """`loan:<verb>:<kind>:<id>[:…]` → (kind, id)."""
    parts = data.split(":")
    if len(parts) < prefix_parts + 2 or parts[prefix_parts] not in _KINDS or not parts[prefix_parts + 1].isdigit():
        return None
    return parts[prefix_parts], int(parts[prefix_parts + 1])


def _find(d: dict, kind: str, ref: int) -> dict | None:
    source = {"bill": d["bills"], "bank": d["banks"], "taken": d["taken"], "debt": d["debts"], "given": d["given"]}[kind]
    return next((r for r in source if r.get("id") == ref), None)


def _obligation(d: dict, kind: str, ref: int) -> dict | None:
    return next((o for o in d["obligations"] if o["kind"] == kind and o["id"] == ref), None)


# ── One record ──────────────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("loan:r:"))
async def on_record(cb: CallbackQuery, state: FSMContext) -> None:
    target = _parse(cb.data)
    if target is not None and await _enter(cb, state):
        await show_record(cb, *target)


async def show_record(event: TelegramObject, kind: str, ref: int, notice: str | None = None) -> None:
    chat_id = common.chat_id_of(event)
    try:
        d = await _load(chat_id)
    except Exception as exc:  # noqa: BLE001
        await pay.report(event, exc, f"loan:r:{kind}:{ref}")
        return
    r = _find(d, kind, ref)
    if r is None:
        await show_loans(event, notice or t(chat_id, "loans.gone"))
        return
    lines: list[str] = []
    actions: list[list[tuple[str, str]]] = []
    back = f"loan:s:{_section_of(kind, r)}"
    if kind == "bill":
        row = next(x for x in d["billRows"] if x["record"] is r)
        lines.append(_bill_line(chat_id, d, row))
        lines.append(t(chat_id, "loans.f.category") + ": " + esc(cat_name(chat_id, r.get("category"))
                                                               if r.get("category") else t(chat_id, "pay.f.noCategory")))
        if r.get("active", True) and row["paid"] is not True:
            actions.append([(t(chat_id, "loans.btn.pay"), f"loan:pay:bill:{ref}:r")])
        actions.append([(t(chat_id, "loans.btn.pause" if r.get("active", True) else "loans.btn.resume"), f"loan:t:{ref}")])
    elif kind == "given":
        lines.append(_owed_line(chat_id, r))
        if not _owed_done(r):
            actions.append([(t(chat_id, "loans.btn.gotBack"), f"loan:pay:given:{ref}:r")])
    else:
        o = _obligation(d, kind, ref)
        lines.append((_asap_line if o["asap"] else _monthly_line)(chat_id, d, o))
        if kind == "bank":
            lines.append(t(chat_id, "loans.bank.facts", total=fmt_money(_n(r.get("totalAmount"))),
                           date=pay.date_label(chat_id, r.get("takenDate")))
                         + (" · " + t(chat_id, "loans.bank.ends", date=pay.date_label(chat_id, r.get("endDate")))
                            if r.get("endDate") else ""))
        else:
            date = r.get("borrowedDate")
            lines.append(t(chat_id, "loans.personal.facts", total=fmt_money(_n(r.get("totalAmount"))),
                           paid=fmt_money(_n(r.get("paidAmount"))), date=pay.date_label(chat_id, date)))
            if kind == "taken":
                lines.append(t(chat_id, "pay.f.row", label=t(chat_id, "loans.f.howRepay"),
                               value=t(chat_id, "loans.f.repayAsap" if o["asap"] else "loans.f.repayMonthly")))
        if not o["paidOff"] and (kind != "bank" or o["monthly"] is not None):
            actions.append([(t(chat_id, "loans.btn.pay"), f"loan:pay:{kind}:{ref}:r")])
    actions.append([(t(chat_id, "loans.btn.edit"), f"loan:e:{kind}:{ref}"),
                    (t(chat_id, "loans.btn.history"), f"loan:h:{kind}:{ref}")])
    actions.append([(t(chat_id, "loans.btn.delete"), f"loan:d:{kind}:{ref}")])
    actions.append(ui.nav(chat_id, back=back, home=True))
    await common.show(event, _with_notice(notice, "\n".join(lines)), ikb(actions))


# ── Pay / Got money back ────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("loan:pay:"))
async def on_pay(cb: CallbackQuery, state: FSMContext) -> None:
    """Pay what is due now — re-read first, so an old screen never pays an old figure."""
    chat_id = common.chat_id_of(cb)
    target = _parse(cb.data)
    if target is None or not await _enter(cb, state):
        return
    kind, ref = target
    ret = f"loan:r:{kind}:{ref}" if cb.data.endswith(":r") else "loan"
    try:
        d = await _load(chat_id)
    except Exception as exc:  # noqa: BLE001
        await pay.report(cb, exc, ret)
        return
    r = _find(d, kind, ref)
    if r is None:
        await show_loans(cb, t(chat_id, "loans.gone"))
        return
    flow: dict[str, Any] = {"kind": {"bill": "BILL", "bank": "BANK", "taken": "LOAN", "debt": "DEBT",
                                     "given": "GIVEN"}[kind], "ref": ref, "ret": ret}
    if kind == "bill":
        row = next(x for x in d["billRows"] if x["record"] is r)
        flow.update(name=str(r.get("name") or "—"),
                    amount=row["left"] if row["left"] else _n(r.get("amount")))
        if row["left"] and abs(row["left"] - _n(r.get("amount"))) > _EPS:
            flow["note"] = t(chat_id, "loans.usually", amount=fmt_money(_n(r.get("amount"))))
    elif kind == "given":
        pending = _n(r.get("pendingAmount"))
        if pending <= 0:
            await back_with(cb, ret, t(chat_id, "pay.gone"))
            return
        flow.update(name=str(r.get("debtorName") or "—"), amount=pending, max=pending, incoming=True,
                    quick=[[t(chat_id, "loans.full", amount=fmt_money(pending)), pending]])
    else:
        o = _obligation(d, kind, ref)
        if o is None or o["paidOff"]:
            await back_with(cb, ret, t(chat_id, "pay.gone"))
            return
        amount = _asap_now(d, o)[0] if o["asap"] else (o["monthly"] or 0.0)
        flow.update(name=o["name"], amount=amount if amount > 0 else None)
        if kind != "bank":
            left = o["remaining"] or 0.0
            flow.update(max=left, quick=[[t(chat_id, "loans.full", amount=fmt_money(left)), left]])
            if flow["amount"] is not None:
                flow["amount"] = min(flow["amount"], left)
    await pay.start_quick(cb, state, flow, d["adv"])


async def back_with(event: TelegramObject, ret: str, notice: str) -> None:
    await pay.back_to(event, ret, notice)


# ── History ─────────────────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("loan:h:"))
async def on_history(cb: CallbackQuery, state: FSMContext) -> None:
    chat_id = common.chat_id_of(cb)
    target = _parse(cb.data)
    if target is None or not await _enter(cb, state):
        return
    kind, ref = target
    back = f"loan:r:{kind}:{ref}"
    try:
        records = await _list(chat_id, f"/finance/{_PATH[kind]}")
        r = next((x for x in records if x.get("id") == ref), None)
        if r is None:
            await show_loans(cb, t(chat_id, "loans.gone"))
            return
        name = str(r.get("name") or r.get("bankName") or r.get("lenderName") or r.get("creditorName")
                   or r.get("debtorName") or "—")
        if kind == "bank":
            res = await api.request(chat_id, "GET", "/transactions", params={
                "page": 0, "size": 100, "sortBy": "transactionDate", "sortDir": "desc", "search": name}) or {}
            rows = [x for x in res.get("content") or [] if isinstance(x, dict) and x.get("subType") == "BANK_LOAN_PAYMENT"]
        else:
            path = {"bill": f"/finance/monthly-payments/{ref}/payments", "taken": f"/finance/loans-taken/{ref}/repayments",
                    "debt": f"/finance/debts/{ref}/repayments", "given": f"/finance/loans-given/{ref}/repayments"}[kind]
            rows = await _list(chat_id, path)
    except Exception as exc:  # noqa: BLE001
        await pay.report(cb, exc, back)
        return
    rows.sort(key=lambda x: str(x.get("transactionDate") or ""), reverse=True)
    lines = [t(chat_id, "loans.history.title", name=esc(name)), ""]
    if not rows:
        lines.append(t(chat_id, "loans.history.none"))
    for tx in rows[:_HISTORY]:
        card = tx.get("card") if isinstance(tx.get("card"), dict) else None
        wallet = f"{card.get('name') or ''} •••• {card.get('lastFourDigits') or ''}".strip() if card \
            else t(chat_id, "common.cash")
        sign = "+" if tx.get("type") == "INCOME" else "−"
        lines.append(t(chat_id, "loans.history.row", date=pay.date_label(chat_id, tx.get("transactionDate")),
                       wallet=esc(wallet), amount=f"{sign}{fmt_money(_n(tx.get('amount')))}"))
    if len(rows) > _HISTORY:
        lines.append(t(chat_id, "loans.history.more", count=len(rows) - _HISTORY))
    await common.show(cb, "\n".join(lines), ikb([ui.nav(chat_id, back=back, home=True)]))


# ── Pause / resume a bill ───────────────────────────────────────────────────
def _bill_body(m: dict, **patch: Any) -> dict:
    """A bill's request with everything the form does not ask carried over untouched."""
    body = {"name": m.get("name"), "amount": _n(m.get("amount")), "currency": m.get("currency") or CURRENCY,
            "dueDay": m.get("dueDay") or 1, "active": m.get("active", True), "description": m.get("description"),
            "nextDueDate": m.get("nextDueDate"), "subscribedSince": m.get("subscribedSince"),
            "categoryId": (m.get("category") or {}).get("id")}
    body.update(patch)
    return body


@router.callback_query(F.data.startswith("loan:t:"))
async def on_toggle(cb: CallbackQuery, state: FSMContext) -> None:
    chat_id = common.chat_id_of(cb)
    raw = cb.data.rsplit(":", 1)[1]
    if not raw.isdigit() or not await _enter(cb, state):
        return
    ref = int(raw)
    try:
        m = next((x for x in await _list(chat_id, "/finance/monthly-payments") if x.get("id") == ref), None)
        if m is None:
            await show_loans(cb, t(chat_id, "loans.gone"))
            return
        active = not m.get("active", True)
        await common.begin_write(cb, chat_id)
        await api.request(chat_id, "PUT", f"/finance/monthly-payments/{ref}", json=_bill_body(m, active=active))
    except Exception as exc:  # noqa: BLE001
        await pay.report(cb, exc, f"loan:r:bill:{ref}")
        return
    await show_record(cb, "bill", ref, "✅ " + t(chat_id, "loans.bills.resumed" if active else "loans.bills.pausedDone"))


# ── Delete ──────────────────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("loan:d:"))
async def on_delete(cb: CallbackQuery, state: FSMContext) -> None:
    chat_id = common.chat_id_of(cb)
    target = _parse(cb.data)
    if target is None or not await _enter(cb, state):
        return
    kind, ref = target
    await pay.confirm(cb, t(chat_id, "loans.del.ask"), f"loan:dy:{kind}:{ref}", f"loan:r:{kind}:{ref}")


@router.callback_query(F.data.startswith("loan:dy:"))
async def on_delete_yes(cb: CallbackQuery, state: FSMContext) -> None:
    chat_id = common.chat_id_of(cb)
    target = _parse(cb.data)
    if target is None or not await _enter(cb, state):
        return
    kind, ref = target
    await common.begin_write(cb, chat_id)
    try:
        await api.request(chat_id, "DELETE", f"/finance/{_PATH[kind]}/{ref}")
    except Exception as exc:  # noqa: BLE001
        await pay.report(cb, exc, f"loan:r:{kind}:{ref}")
        return
    await show_loans(cb, "✅ " + t(chat_id, "loans.del.done"))


# ── People ──────────────────────────────────────────────────────────────────
@router.callback_query(F.data == "loan:ppl")
async def on_people(cb: CallbackQuery, state: FSMContext) -> None:
    chat_id = common.chat_id_of(cb)
    if not await _enter(cb, state):
        return
    lines = [t(chat_id, "loans.people.title")]
    try:
        lenders, borrowers = await asyncio.gather(_people(chat_id, "lenders"), _people(chat_id, "borrowers"))
    except Exception as exc:  # noqa: BLE001
        await pay.report(cb, exc, "loan:ppl")
        return
    for title, people in (("loans.people.lenders", lenders), ("loans.people.borrowers", borrowers)):
        lines += ["", t(chat_id, title)]
        if people is None:
            lines.append(t(chat_id, "loans.people.unavailable"))
            continue
        top = sorted(people, key=lambda p: -_n(p.get("total")))[:_PEOPLE]
        if not top:
            lines.append(t(chat_id, "loans.people.none"))
        for p in top:
            times = int(_n(p.get("times")))
            detail = pay.plural(chat_id, times, "loans.people.timesOne", "loans.people.timesMany")
            if _n(p.get("open")) > 0:
                detail += " · " + t(chat_id, "loans.people.open", amount=fmt_money(_n(p.get("open"))))
            lines.append(t(chat_id, "loans.people.row", name=esc(p.get("name") or "—"),
                           amount=fmt_money(_n(p.get("total"))), detail=detail))
    await common.show(cb, "\n".join(lines), ikb([ui.nav(chat_id, back="loan", home=True)]))


async def _people(chat_id: int, which: str) -> list[dict] | None:
    """A people list — or None from a server that keeps no people (404)."""
    try:
        return await _list(chat_id, f"/people/{which}")
    except api.ApiError as exc:
        if exc.status == 404:
            return None
        raise


# ── Add / edit ──────────────────────────────────────────────────────────────
@router.callback_query(F.data == "loan:add")
async def on_add(cb: CallbackQuery, state: FSMContext) -> None:
    chat_id = common.chat_id_of(cb)
    if not await _enter(cb, state):
        return
    await common.show(cb, t(chat_id, "loans.add.title"), ikb([
        [(t(chat_id, "loans.btn.addBill"), "loan:add:bill")],
        [(t(chat_id, "loans.btn.addBank"), "loan:add:bank")],
        [(t(chat_id, "loans.btn.addBorrowed"), "loan:add:borrowed")],
        [(t(chat_id, "loans.btn.addLent"), "loan:add:lent")],
        ui.nav(chat_id, back="loan", home=True)]))


@router.callback_query(F.data.startswith("loan:add:"))
async def on_add_kind(cb: CallbackQuery, state: FSMContext) -> None:
    chat_id = common.chat_id_of(cb)
    what = cb.data.split(":", 2)[2]
    if not await _enter(cb, state):
        return
    today = clock.today_iso()
    if what == "bill":
        await pay.open_form(cb, state, "loan.bill", ret="loan:s:bill")
    elif what == "bank":
        await pay.open_form(cb, state, "loan.bank", ret="loan:s:mon")
    elif what in ("borrowed", "lent"):
        try:
            settings = await api.request(chat_id, "GET", "/settings") or {}
        except Exception as exc:  # noqa: BLE001
            await pay.report(cb, exc, "loan")
            return
        income = _n(settings.get("monthlyStableIncome")) if isinstance(settings, dict) else 0.0
        vals = {"date": today, "first": pay.shift_month(clock.month(), 1)} if what == "borrowed" else {"date": today}
        await pay.open_form(cb, state, f"loan.{what}", vals=vals, ctx={"income": income or None},
                            ret="loan" if what == "borrowed" else "loan:s:owed")
    else:
        await show_loans(cb)


@router.callback_query(F.data.startswith("loan:e:"))
async def on_edit(cb: CallbackQuery, state: FSMContext) -> None:
    chat_id = common.chat_id_of(cb)
    target = _parse(cb.data)
    if target is None or not await _enter(cb, state):
        return
    kind, ref = target
    ret = f"loan:r:{kind}:{ref}"
    try:
        d = await _load(chat_id)
    except Exception as exc:  # noqa: BLE001
        await pay.report(cb, exc, ret)
        return
    r = _find(d, kind, ref)
    if r is None:
        await show_loans(cb, t(chat_id, "loans.gone"))
        return
    ctx: dict[str, Any] = {"id": ref, "record": r, "income": d["income"]}
    if kind == "bill":
        row = next(x for x in d["billRows"] if x["record"] is r)
        ctx["paid"] = row["paid"]
        cat = r.get("category") if isinstance(r.get("category"), dict) else None
        vals = {"name": r.get("name") or "", "amount": _n(r.get("amount")), "day": r.get("dueDay") or 1,
                "category": cat.get("id") if cat else None,
                "categoryName": cat_name(chat_id, cat) if cat else t(chat_id, "pay.f.noCategory")}
        spec = "loan.bill"
    elif kind == "bank":
        vals = {"bank": r.get("bankName") or "", "monthly": _n(r.get("monthlyPayment")) or None,
                "total": _n(r.get("totalAmount")), "taken": r.get("takenDate"), "end": r.get("endDate")}
        spec = "loan.bank"
    elif kind == "taken":
        vals = {"person": r.get("lenderName") or "", "personId": r.get("lenderId"),
                "amount": _n(r.get("totalAmount")), "date": r.get("borrowedDate"), "repay": repayment_of(r),
                "monthly": _n(r.get("plannedMonthlyPayment")) or None,
                "first": _ym(r.get("paymentStartDate")) or pay.shift_month(clock.month(), 1)}
        spec = "loan.borrowed"
    elif kind == "given":
        vals = {"person": r.get("debtorName") or "", "personId": r.get("borrowerId"),
                "amount": _n(r.get("totalAmount")), "date": r.get("lentDate"), "expected": r.get("expectedReturnDate")}
        spec = "loan.lent"
    else:
        vals = {"name": r.get("creditorName") or "", "amount": _n(r.get("totalAmount")),
                "first": _ym(r.get("paymentStartDate"))}
        spec = "loan.debt"
    await pay.open_form(cb, state, spec, vals=vals, ctx=ctx, ret=ret, card=True)


# ── Where a flow comes back to ──────────────────────────────────────────────
async def route(event: TelegramObject, notice: str | None, ret: str) -> None:
    """Render the Loans screen a callback names, with `notice` on top."""
    parts = ret.split(":")
    if len(parts) >= 3 and parts[1] == "s" and parts[2] in _SECTIONS:
        await show_section(event, parts[2], notice)
    elif len(parts) >= 4 and parts[1] == "r" and parts[2] in _KINDS and parts[3].isdigit():
        await show_record(event, parts[2], int(parts[3]), notice)
    else:
        await show_loans(event, notice)


pay.register_return("loan", route)


# ── Forms ───────────────────────────────────────────────────────────────────
def _editing(form: dict) -> bool:
    return "id" in form["ctx"]


def _title(add: str, chat_id: int, form: dict) -> str:
    if _editing(form):
        r = form["ctx"]["record"]
        name = r.get("name") or r.get("bankName") or r.get("lenderName") or r.get("creditorName") or r.get("debtorName")
        return t(chat_id, "loans.f.editTitle", name=esc(name or "—"))
    return t(chat_id, add)


def _status(paid: float, total: float) -> str:
    """The server's own rule, sent with every edit so a raised total reopens a paid-off record."""
    if paid <= 0:
        return "PENDING"
    return "PAID" if paid >= total else "PARTIALLY_PAID"


def _move(vals: dict) -> dict:
    """A new loan's money: into / out of a wallet in the same step, or not moved at all."""
    w = vals.get("wallet")
    if w == "none" or w is None:
        return {"moveMoney": False, "cardId": None}
    return {"moveMoney": True, "cardId": w if isinstance(w, int) and not isinstance(w, bool) else None}


def _remember(vals: dict) -> None:
    w = vals.get("wallet")
    if w == "cash":
        pay.remember_wallet(None, "pay")
    elif isinstance(w, int) and not isinstance(w, bool):
        pay.remember_wallet(w, "pay")


async def _person(chat_id: int, vals: dict, kind: str) -> tuple[int | None, str]:
    """The person a form names: the one picked, or the one the server files a typed name under."""
    name = str(vals.get("person") or "").strip()
    if vals.get("personId"):
        return vals["personId"], name
    try:
        res = await api.request(chat_id, "POST", "/people", json={"name": name, "kind": kind}) or {}
    except api.ApiError as exc:
        if exc.status == 404:  # an older server keeps no people; the name alone is sent
            return None, name
        raise
    return res.get("id"), str(res.get("name") or name)


def _wallet_lines(chat_id: int, form: dict) -> list[str]:
    return [t(chat_id, "loans.f.noWalletHint")] if form["vals"].get("wallet") == "none" else []


def _moved_toast(chat_id: int, key: str, vals: dict, name: str) -> str:
    if vals.get("wallet") in (None, "none"):
        return "✅ " + t(chat_id, "loans.added")
    return "✅ " + t(chat_id, key, amount=fmt_money(vals["amount"]), name=esc(name),
                     wallet=esc(vals.get("walletName") or ""))


# Monthly bill: name, amount, due day, category.
def _bill_fields(form: dict) -> list[Field]:
    return [Field("name", "loans.f.name", "text"), Field("amount", "loans.f.amount", "amount"),
            Field("day", "loans.f.dueDay", "day", hint="loans.f.dueDayHelp"),
            Field("category", "loans.f.category", "category")]


def next_due_for(due_day: int, stored: str | None, paid_this_month: bool | None) -> str:
    """A bill's next due date once its due day moves (the web's nextDueFor)."""
    current = clock.month()
    month = _ym(stored) if stored and _ym(stored) > current else current
    if paid_this_month and month == current:
        month = pay.shift_month(current, 1)
    last = int(pay.last_day(month)[8:10])
    return f"{month}-{min(max(due_day, 1), last):02d}"


async def _bill_save(event: TelegramObject, chat_id: int, form: dict) -> tuple[str, str | None]:
    v, ctx = form["vals"], form["ctx"]
    patch = {"name": str(v["name"]).strip(), "amount": v["amount"], "dueDay": int(v["day"]),
             "categoryId": v.get("category")}
    if _editing(form):
        m = ctx["record"]
        if int(m.get("dueDay") or 0) != int(v["day"]):
            patch["nextDueDate"] = next_due_for(int(v["day"]), m.get("nextDueDate"), ctx.get("paid"))
        await api.request(chat_id, "PUT", f"/finance/monthly-payments/{ctx['id']}", json=_bill_body(m, **patch))
        return "✅ " + t(chat_id, "loans.saved"), None
    await api.request(chat_id, "POST", "/finance/monthly-payments", json={**patch, "currency": CURRENCY, "active": True})
    return "✅ " + t(chat_id, "loans.added"), None


pay.FORMS["loan.bill"] = Spec(title=lambda c, f: _title("loans.f.addBill", c, f), fields=_bill_fields,
                              save=_bill_save)


# Bank loan: bank, monthly payment, total, taken on (and an end date, on the card).
def _bank_fields(form: dict) -> list[Field]:
    return [Field("bank", "loans.f.bank", "text"), Field("monthly", "loans.f.monthly", "amount"),
            Field("total", "loans.f.total", "amount"), Field("taken", "loans.f.takenOn", "date"),
            Field("end", "loans.f.endDate", "date", optional=True, walk=False, future=True)]


def _bank_check(chat_id: int, form: dict) -> str | None:
    v = form["vals"]
    if v.get("end") and v.get("taken") and str(v["end"]) < str(v["taken"]):
        return t(chat_id, "loans.f.errDateBefore", date=pay.date_label(chat_id, v["taken"]))
    return None


async def _bank_save(event: TelegramObject, chat_id: int, form: dict) -> tuple[str, str | None]:
    v, ctx = form["vals"], form["ctx"]
    existing = ctx.get("record") or {}
    body = {"bankName": str(v["bank"]).strip(), "loanName": existing.get("loanName") or t(chat_id, "loans.f.defaultLoanName"),
            "totalAmount": v["total"], "currency": existing.get("currency") or CURRENCY, "takenDate": v["taken"],
            "endDate": v.get("end") or None, "monthlyPayment": v["monthly"]}
    if _editing(form):
        await api.request(chat_id, "PUT", f"/finance/bank-loans/{ctx['id']}", json=body)
        return "✅ " + t(chat_id, "loans.saved"), None
    await api.request(chat_id, "POST", "/finance/bank-loans", json=body)
    return "✅ " + t(chat_id, "loans.added"), None


pay.FORMS["loan.bank"] = Spec(title=lambda c, f: _title("loans.f.addBank", c, f), fields=_bank_fields,
                              save=_bank_save, check=_bank_check)


# Money I borrowed: lender, amount, into wallet, date, how will you repay (+ monthly plan).
_REPAY = (("MONTHLY", "loans.f.repayMonthly"), ("ASAP", "loans.f.repayAsap"))


def _borrowed_fields(form: dict) -> list[Field]:
    fields = [Field("person", "loans.f.lender", "person", person="LENDER", new_label="loans.f.newLender"),
              Field("amount", "loans.f.amount", "amount")]
    if not _editing(form):
        fields.append(Field("wallet", "loans.f.intoWallet", "wallet", incoming=True, none_label="loans.f.noWallet"))
    fields += [Field("date", "loans.f.date", "date", walk=False),
               Field("repay", "loans.f.howRepay", "choice", options=_REPAY)]
    if form["vals"].get("repay") == "MONTHLY":
        fields += [Field("monthly", "loans.f.monthly", "amount", hint="loans.f.monthlyHelp"),
                   Field("first", "loans.f.firstMonth", "month")]
    return fields


def _borrowed_lines(chat_id: int, form: dict) -> list[str]:
    lines = _wallet_lines(chat_id, form)
    if form["vals"].get("repay") == "ASAP":
        income = form["ctx"].get("income")
        lines.append(t(chat_id, "loans.f.asapRule", limit=fmt_money(round(income * _ALL_DUE))) if income
                     else t(chat_id, "loans.f.asapRuleNoIncome"))
    return lines


def _borrowed_check(chat_id: int, form: dict) -> str | None:
    v = form["vals"]
    if v.get("repay") == "MONTHLY" and _n(v.get("monthly")) > _n(v.get("amount")):
        return t(chat_id, "loans.f.errMonthlyTooBig")
    return None


async def _borrowed_save(event: TelegramObject, chat_id: int, form: dict) -> tuple[str, str | None]:
    v, ctx = form["vals"], form["ctx"]
    person_id, name = await _person(chat_id, v, "LENDER")
    monthly = v.get("repay") == "MONTHLY"
    existing = ctx.get("record") or {}
    body = {"lenderName": name, "lenderId": person_id, "totalAmount": v["amount"],
            "currency": existing.get("currency") or CURRENCY, "borrowedDate": v.get("date") or clock.today_iso(),
            "dueDate": existing.get("dueDate"), "description": existing.get("description"),
            "repaymentType": v["repay"],
            "paymentStartDate": f"{v['first']}-01" if monthly and v.get("first") else None,
            "plannedMonthlyPayment": v["monthly"] if monthly else None}
    if _editing(form):
        body["status"] = _status(_n(existing.get("paidAmount")), _n(v["amount"]))
        await api.request(chat_id, "PUT", f"/finance/loans-taken/{ctx['id']}", json=body)
        return "✅ " + t(chat_id, "loans.saved"), None
    await api.request(chat_id, "POST", "/finance/loans-taken", json={**body, **_move(v)})
    _remember(v)
    return _moved_toast(chat_id, "loans.borrowedToast", v, name), None


pay.FORMS["loan.borrowed"] = Spec(title=lambda c, f: _title("loans.f.addBorrowed", c, f),
                                  fields=_borrowed_fields, save=_borrowed_save, lines=_borrowed_lines,
                                  check=_borrowed_check)


# Money I lent: borrower, amount, from wallet, date, expected back (optional).
def _lent_fields(form: dict) -> list[Field]:
    fields = [Field("person", "loans.f.borrower", "person", person="BORROWER", new_label="loans.f.newPerson"),
              Field("amount", "loans.f.amount", "amount")]
    if not _editing(form):
        fields.append(Field("wallet", "loans.f.fromWallet", "wallet", none_label="loans.f.noWallet"))
    fields += [Field("date", "loans.f.date", "date", walk=False),
               Field("expected", "loans.f.expectedBack", "date", optional=True, future=True)]
    return fields


def _lent_check(chat_id: int, form: dict) -> str | None:
    v = form["vals"]
    if v.get("expected") and v.get("date") and str(v["expected"]) < str(v["date"]):
        return t(chat_id, "loans.f.errDateBefore", date=pay.date_label(chat_id, v["date"]))
    return None


async def _lent_save(event: TelegramObject, chat_id: int, form: dict) -> tuple[str, str | None]:
    v, ctx = form["vals"], form["ctx"]
    person_id, name = await _person(chat_id, v, "BORROWER")
    existing = ctx.get("record") or {}
    body = {"debtorName": name, "borrowerId": person_id, "totalAmount": v["amount"],
            "currency": existing.get("currency") or CURRENCY, "lentDate": v.get("date") or clock.today_iso(),
            "expectedReturnDate": v.get("expected") or None, "description": existing.get("description")}
    if _editing(form):
        body["status"] = _status(_n(existing.get("receivedAmount")), _n(v["amount"]))
        await api.request(chat_id, "PUT", f"/finance/loans-given/{ctx['id']}", json=body)
        return "✅ " + t(chat_id, "loans.saved"), None
    await api.request(chat_id, "POST", "/finance/loans-given", json={**body, **_move(v)})
    _remember(v)
    return _moved_toast(chat_id, "loans.lentToast", v, name), None


pay.FORMS["loan.lent"] = Spec(title=lambda c, f: _title("loans.f.addLent", c, f), fields=_lent_fields,
                              save=_lent_save, lines=_wallet_lines, check=_lent_check)


# A debt (edit only — debts are no longer added, as on the web): who, amount, first payment month.
def _debt_fields(form: dict) -> list[Field]:
    return [Field("name", "loans.f.whoYouOwe", "text"), Field("amount", "loans.f.amount", "amount"),
            Field("first", "loans.f.firstMonth", "month", optional=True)]


async def _debt_save(event: TelegramObject, chat_id: int, form: dict) -> tuple[str, str | None]:
    v, ctx = form["vals"], form["ctx"]
    d = ctx["record"]
    body = {"creditorName": str(v["name"]).strip(), "totalAmount": v["amount"], "currency": d.get("currency") or CURRENCY,
            "borrowedDate": d.get("borrowedDate"), "dueDate": d.get("dueDate"), "description": d.get("description"),
            "paymentStartDate": f"{v['first']}-01" if v.get("first") else None,
            "status": _status(_n(d.get("paidAmount")), _n(v["amount"])), "lenderId": d.get("lenderId")}
    await api.request(chat_id, "PUT", f"/finance/debts/{ctx['id']}", json=body)
    return "✅ " + t(chat_id, "loans.saved"), None


pay.FORMS["loan.debt"] = Spec(title=lambda c, f: _title("loans.f.addBorrowed", c, f), fields=_debt_fields,
                              save=_debt_save)
