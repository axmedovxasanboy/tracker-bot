"""The advisor — the bot's home screen, and the message it sends in the evening.

The owner stopped opening Tracker because it behaved like a bookkeeper: every screen asked for
input or explained the allocation engine. What they asked for instead is an advisor — tell me
what I have, what is coming, what I still need to pay and set aside, what is left, and nudge me
towards goals. `GET /advisor` answers all of that in one response (the web Home renders the same
one), and this module turns it into:

* **the home screen** — five short lines and a "next" list, with a button per next step. The
  eight sections, levels and ledgers are one tap away under More and Details, not in the way;
* **two-tap payments** — tap "💳 Rent", tap the wallet, done. Today's date, the amount the
  advisor just quoted, no review screen: the screen the wallet buttons sit on already says
  exactly what will be recorded. "Other amount" and "Already paid" cover the exceptions;
* **`compose()`** — shared with `bot/reminders.py`, so the evening message IS the home screen.

The existing flows are reused rather than rebuilt: a wallet check opens `ci:start`, a month
close `months:close`, a new goal `fcreate:goal`, the income `settings:income`.

Every button that spends money re-reads the advisor first and acts on the CURRENT figure, so a
screen scrolled up from yesterday cannot pay yesterday's amount, and a bill paid from the web in
the meantime answers "already taken care of" instead of being paid twice.

Callback namespace owned here: `adv:*`.
"""
from __future__ import annotations

import logging
from typing import Any

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from .. import api, clock, common, keyboards, ui
from ..config import CURRENCY
from ..i18n import t
from ..keyboards import esc, ikb
from ..money import fmt_money, parse_amount
from ..states import Advise

router = Router(name="advisor")
log = logging.getLogger(__name__)

# `AdvisorResponse.Suggestion.code` → our sentence. A code this file has not been taught falls
# back to the server's English `text`.
_SUGGESTION_KEY = {
    "advisor.s.setIncome": "adv.s.setIncome",
    "advisor.s.paySubscription": "adv.s.paySubscription",
    "advisor.s.payBank": "adv.s.payBank",
    "advisor.s.payLoanPlan": "adv.s.payLoanPlan",
    "advisor.s.payDebts": "adv.s.payDebts",
    "advisor.s.closeMonth": "adv.s.closeMonth",
    "advisor.s.checkWallets": "adv.s.checkWallets",
    "advisor.s.checkWalletsFirst": "adv.s.checkWalletsFirst",
    "advisor.s.setAside": "adv.s.setAside",
    "advisor.s.startEmergency": "adv.s.startEmergency",
    "advisor.s.short": "adv.s.short",
    "advisor.s.addGoal": "adv.s.addGoal",
    "advisor.s.extraToGoal": "adv.s.extraToGoal",
    "advisor.s.extraToEmergency": "adv.s.extraToEmergency",
    "advisor.s.extraToInvestments": "adv.s.extraToInvestments",
}

_BUCKET_KEY = {
    "DONATION": "menu.bucket.donation",
    "EMERGENCY": "menu.bucket.emergency",
    "INVESTMENTS": "menu.bucket.investments",
    "SAVINGS": "menu.bucket.savings",
}
_BUCKET_ICON = {"DONATION": "🤲", "EMERGENCY": "🛟", "INVESTMENTS": "📈", "SAVINGS": "🎯"}
_BILL_KEY = {"BANK": "adv.bill.bank", "LOAN_PLAN": "adv.bill.loanPlan", "DEBTS": "adv.bill.debts"}

# More than this many step buttons and the screen is a menu again.
_MAX_STEP_BUTTONS = 5
# A button label is plain text and a phone shows ~25 characters of it.
_LABEL_LIMIT = 24


# ── Reading ─────────────────────────────────────────────────────────────────
async def fetch(chat_id: int) -> dict[str, Any]:
    """`GET /advisor` for the owner's today. Raises what `api.request` raises."""
    data = await api.request(chat_id, "GET", "/advisor", params={"date": clock.today_iso()})
    return data if isinstance(data, dict) else {}


def _n(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def month_name(chat_id: int | None, ym: str | None) -> str:
    """"2026-08" → "August" / "avgust"."""
    try:
        return t(chat_id, f"adv.month.{int(str(ym)[5:7])}")
    except (TypeError, ValueError):
        return esc(ym or "")


def _bucket(chat_id: int | None, bucket: str | None) -> str:
    key = _BUCKET_KEY.get(str(bucket or "").upper())
    return t(chat_id, key) if key else esc(bucket or "")


def _clip(label: str) -> str:
    return label if len(label) <= _LABEL_LIMIT else label[:_LABEL_LIMIT - 1] + "…"


def _wallet_name(chat_id: int | None, w: dict) -> str:
    return t(chat_id, "adv.details.cash") if w.get("type") == "CASH" else str(w.get("label") or "—")


# ── The home screen ─────────────────────────────────────────────────────────
def suggestion_text(chat_id: int | None, s: dict) -> str:
    key = _SUGGESTION_KEY.get(s.get("code"))
    if not key:
        return "👉 " + esc(s.get("text") or "")
    p = s.get("params") or {}
    month = month_name(chat_id, p.get("month")) if p.get("month") else ""
    return t(chat_id, key,
             name=esc(p.get("name") or ""),
             month=month[:1].upper() + month[1:],
             days=esc(p.get("days") or ""),
             bucket=_bucket(chat_id, p.get("bucket") or s.get("bucket")),
             amount=fmt_money(s.get("amount")))


def _step_button(chat_id: int | None, s: dict) -> tuple[str, str] | None:
    """The button for one suggestion, or None when it has nothing to tap."""
    action = s.get("action")
    p = s.get("params") or {}
    bucket = str(s.get("bucket") or "").upper()
    if action == "PAY_SUBSCRIPTION" and s.get("refId") is not None:
        return _clip(t(chat_id, "adv.btn.pay", name=p.get("name") or "—")), f"adv:sub:{s['refId']}"
    if action == "PAY_BANK":
        return t(chat_id, "adv.btn.bank"), "adv:bank"
    if action == "PAY_DEBT":
        return t(chat_id, "adv.btn.debt"), ("adv:debt:plan" if s.get("code") == "advisor.s.payLoanPlan"
                                            else "adv:debt:rule")
    if action == "CLOSE_MONTH":
        return t(chat_id, "adv.btn.close", month=month_name(chat_id, p.get("month"))), "months:close"
    if action == "CHECK_IN":
        return t(chat_id, "adv.btn.checkIn"), "ci:start"
    if action == "ADD_GOAL":
        return t(chat_id, "adv.btn.addGoal"), "fcreate:goal"
    if action == "SET_INCOME":
        return t(chat_id, "adv.btn.setIncome"), "settings:income"
    if action == "SET_ASIDE" and bucket in _BUCKET_KEY:
        label = p.get("name") if bucket == "SAVINGS" and p.get("name") else _bucket(chat_id, bucket)
        if s.get("kind") == "IDEA":
            tail = f":{s['refId']}" if bucket == "SAVINGS" and s.get("refId") is not None else ""
            return _clip(t(chat_id, "adv.btn.aside", bucket=label)), f"adv:extra:{bucket}{tail}"
        return _clip(t(chat_id, "adv.btn.aside", bucket=label)), f"adv:aside:{bucket}"
    return None


def compose(chat_id: int | None, data: dict, header: str | None = None) -> tuple[str, InlineKeyboardMarkup]:
    """The advisor as one message: the four figures, then what to do next, with a button each."""
    lines: list[str] = []
    if header:
        lines += [header, ""]
    date = str(data.get("date") or clock.today_iso())
    try:
        day = int(date[8:10])
    except ValueError:
        day = clock.today().day
    lines.append(t(chat_id, "adv.title", day=day, month=month_name(chat_id, date[:7])))
    lines.append("")

    ago = data.get("balanceCheckedDaysAgo")
    checked = (t(chat_id, "adv.neverChecked") if ago is None
               else t(chat_id, "adv.checkedToday") if int(ago) == 0
               else t(chat_id, "adv.checkedAgo", days=int(ago)))
    lines.append(t(chat_id, "adv.have", amount=fmt_money(_n(data.get("have")))) + checked)

    missing = bool(data.get("missingStableIncome"))
    if missing:
        lines += ["", t(chat_id, "adv.noIncome")]
    else:
        if _n(data.get("salaryComing")) > 0:
            lines.append(t(chat_id, "adv.coming", amount=fmt_money(_n(data.get("salaryComing")))))
        for o in (data.get("owedToYou") or [])[:2]:
            lines.append(t(chat_id, "adv.owed", name=esc(o.get("name") or "—"),
                           amount=fmt_money(_n(o.get("amount")))))
        bills, aside = _n(data.get("billsLeft")), _n(data.get("setAsideLeft"))
        if bills + aside > 0:
            lines.append(t(chat_id, "adv.still", amount=fmt_money(bills + aside)))
            if bills > 0 and aside > 0:
                part = t(chat_id, "adv.stillBoth", bills=fmt_money(bills), aside=fmt_money(aside))
            elif bills > 0:
                part = t(chat_id, "adv.stillBills", bills=fmt_money(bills))
            else:
                part = t(chat_id, "adv.stillAside", aside=fmt_money(aside))
            if aside > 0 and data.get("setAsideAfterBills"):
                part += t(chat_id, "adv.afterBills")
            lines.append(part)
        free = _n(data.get("free"))
        lines.append(t(chat_id, "adv.free", amount=fmt_money(free)) if free >= 0
                     else t(chat_id, "adv.shortBy", amount=fmt_money(-free)))

    # "Short" is already the Free line above; saying it twice is the noise this screen removes.
    steps = [s for s in (data.get("suggestions") or [])
             if isinstance(s, dict) and s.get("code") != "advisor.s.short"]
    lines.append("")
    if steps:
        lines += [suggestion_text(chat_id, s) for s in steps]
    elif not missing:
        lines.append(t(chat_id, "adv.allDone"))

    buttons: list[tuple[str, str]] = []
    for s in steps:
        b = _step_button(chat_id, s)
        if b and b[1] not in {cb for _, cb in buttons}:
            buttons.append(b)
    rows = ui.grid(buttons[:_MAX_STEP_BUTTONS], 2)
    rows.append([(t(chat_id, "adv.btn.record"), "qa:new"), (t(chat_id, "adv.btn.details"), "adv:details")])
    rows.append([(t(chat_id, "adv.btn.more"), "menu:more"), (t(chat_id, "adv.btn.refresh"), "adv:home")])
    return "\n".join(lines), ikb(rows)


async def _report(event, exc: BaseException) -> None:
    chat_id = common.chat_id_of(event)
    home = ikb([[(t(chat_id, "adv.btn.home"), "adv:home"), (t(chat_id, "adv.btn.more"), "menu:more")]])
    if isinstance(exc, api.NeedsLogin):
        await common.show(event, t(chat_id, "common.sessionExpired"), keyboards.login_kb(chat_id))
    elif isinstance(exc, api.Unreachable):
        await common.show(event, t(chat_id, "common.serverUnreachable"), home)
    elif isinstance(exc, api.ApiError):
        await common.show(event, f"❌ {esc(exc.message)}", home)
    else:
        log.warning("Advisor call failed", exc_info=exc)
        await common.show(event, t(chat_id, "adv.loadError"), home)


async def show_advisor(event, notice: str | None = None) -> None:
    """Render the home screen, with an optional one-line outcome ("✅ Recorded …") above it."""
    chat_id = common.chat_id_of(event)
    try:
        data = await fetch(chat_id)
    except Exception as exc:  # noqa: BLE001 — dispatched by type in _report
        await _report(event, exc)
        return
    text, kb = compose(chat_id, data)
    await common.show(event, f"{notice}\n\n{text}" if notice else text, kb)


@router.callback_query(F.data == "adv:home")
async def on_home(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    await state.clear()
    if not await common.gate(cb):
        return
    await show_advisor(cb)


# ── Details ─────────────────────────────────────────────────────────────────
@router.callback_query(F.data == "adv:details")
async def on_details(cb: CallbackQuery) -> None:
    await common.ack(cb)
    if not await common.gate(cb):
        return
    chat_id = common.chat_id_of(cb)
    try:
        d = await fetch(chat_id)
    except Exception as exc:  # noqa: BLE001
        await _report(cb, exc)
        return

    lines = [t(chat_id, "adv.details.title", month=month_name(chat_id, d.get("month"))), ""]
    lines.append(t(chat_id, "adv.details.wallets"))
    wallets = d.get("wallets") or []
    lines += [t(chat_id, "adv.details.wallet", name=esc(_wallet_name(chat_id, w)),
                amount=fmt_money(_n(w.get("balance")))) for w in wallets] or [t(chat_id, "adv.details.none")]

    if not d.get("missingStableIncome"):
        lines += ["", t(chat_id, "adv.details.income"),
                  t(chat_id, "adv.details.salary", received=fmt_money(_n(d.get("salaryReceived"))),
                    expected=fmt_money(_n(d.get("salaryExpected"))))]
        if _n(d.get("bonusReceived")) > 0:
            lines.append(t(chat_id, "adv.details.bonus", amount=fmt_money(_n(d.get("bonusReceived")))))
        for o in d.get("owedToYou") or []:
            key = "adv.details.owedOn" if o.get("expectedOn") else "adv.details.owed"
            lines.append(t(chat_id, key, name=esc(o.get("name") or "—"),
                           amount=fmt_money(_n(o.get("amount"))), date=esc(o.get("expectedOn") or "")))

        lines += ["", t(chat_id, "adv.details.bills")]
        bills = d.get("bills") or []
        for b in bills:
            name = esc(b.get("name")) if b.get("kind") == "SUBSCRIPTION" else t(chat_id, _BILL_KEY.get(b.get("kind"), "adv.bill.debts"))
            if _n(b.get("paid")) > 0:
                lines.append(t(chat_id, "adv.details.billPaid", name=name, amount=fmt_money(_n(b.get("amount"))),
                               paid=fmt_money(_n(b.get("paid"))), target=fmt_money(_n(b.get("target")))))
            else:
                lines.append(t(chat_id, "adv.details.bill", name=name, amount=fmt_money(_n(b.get("amount")))))
        if not bills:
            lines.append(t(chat_id, "adv.details.none"))

        heading = t(chat_id, "adv.details.aside")
        if d.get("setAsideAfterBills") and d.get("setAside"):
            heading += t(chat_id, "adv.afterBills")
        lines += ["", heading]
        for a in d.get("setAside") or []:
            pct = f"{_n(a.get('percent')):g}%" if a.get("percent") is not None else ""
            key = "adv.details.bucketPaid" if _n(a.get("paid")) > 0 else "adv.details.bucket"
            lines.append(t(chat_id, key, bucket=_bucket(chat_id, a.get("bucket")), pct=pct,
                           amount=fmt_money(_n(a.get("remaining"))), paid=fmt_money(_n(a.get("paid"))),
                           target=fmt_money(_n(a.get("target")))))
        if not d.get("setAside"):
            lines.append(t(chat_id, "adv.details.none"))

        lines += ["", t(chat_id, "adv.details.freeMath",
                        have=fmt_money(_n(d.get("have"))), coming=fmt_money(_n(d.get("salaryComing"))),
                        bills=fmt_money(_n(d.get("billsLeft"))), aside=fmt_money(_n(d.get("setAsideLeft"))),
                        free=fmt_money(_n(d.get("free"))))]
    lines += ["", t(chat_id, "adv.details.planHint")]
    await common.show(cb, "\n".join(lines), ikb([
        [(t(chat_id, "adv.btn.home"), "adv:home"), (t(chat_id, "menu.page.overview"), "menu:overview")],
    ]))


# ── Two-tap payments ────────────────────────────────────────────────────────
# FSM data: `adv` is the flow — {kind, endpoint, name, icon, amount, mark?, desc?} — and
# `adv_wallets` the wallet list the buttons index into, both set when the flow starts.

def _find(data: dict, pred) -> dict | None:
    return next((s for s in data.get("suggestions") or [] if isinstance(s, dict) and pred(s)), None)


async def _fresh(cb: CallbackQuery) -> dict | None:
    """Re-read the advisor before acting on a button, or None having shown why not."""
    await common.ack(cb)
    if not await common.gate(cb):
        return None
    try:
        return await fetch(common.chat_id_of(cb))
    except Exception as exc:  # noqa: BLE001
        await _report(cb, exc)
        return None


async def _gone(cb: CallbackQuery, state: FSMContext) -> None:
    """The step this button was for is no longer due — paid from the web, or a stale screen."""
    await state.clear()
    await show_advisor(cb, t(common.chat_id_of(cb), "adv.pay.gone"))


def _wallets(data: dict) -> list[dict]:
    wallets = [w for w in data.get("wallets") or [] if isinstance(w, dict)]
    # Cash is always a place money can come from, even before the cash pot has a row.
    if not any(w.get("type") == "CASH" for w in wallets):
        wallets.append({"type": "CASH", "cardId": None, "label": "Cash", "balance": 0})
    return wallets


async def _start(cb: CallbackQuery, state: FSMContext, data: dict, flow: dict) -> None:
    await state.set_state(Advise.pick)
    await state.set_data({"adv": flow, "adv_wallets": _wallets(data)})
    await _pick_screen(cb, state)


async def _pick_screen(event, state: FSMContext) -> None:
    chat_id = common.chat_id_of(event)
    d = await state.get_data()
    flow = d.get("adv") or {}
    text = (t(chat_id, "adv.pay.header", icon=flow.get("icon", "💳"), name=esc(flow.get("name") or ""),
              amount=fmt_money(flow.get("amount")))
            + "\n\n" + t(chat_id, "adv.pay.fromWhich"))
    rows: list[list[tuple[str, str]]] = []
    for i, w in enumerate(d.get("adv_wallets") or []):
        icon = "💵" if w.get("type") == "CASH" else "💳"
        rows.append([(f"{icon} " + t(chat_id, "adv.pay.wallet", name=_wallet_name(chat_id, w),
                                     amount=fmt_money(_n(w.get("balance")))), f"adv:w:{i}")])
    extra = [(t(chat_id, "adv.pay.otherAmount"), "adv:amt")]
    if flow.get("mark"):
        extra.append((t(chat_id, "adv.pay.alreadyPaid"), "adv:mark"))
    rows.append(extra)
    rows.append(ui.nav(chat_id, cancel="adv:home"))
    await state.set_state(Advise.pick)
    await common.show(event, text, ikb(rows))


@router.callback_query(F.data.startswith("adv:sub:"))
async def on_subscription(cb: CallbackQuery, state: FSMContext) -> None:
    data = await _fresh(cb)
    if data is None:
        return
    raw = cb.data.split(":")[2]
    sid = int(raw) if raw.isdigit() else -1
    s = _find(data, lambda s: s.get("action") == "PAY_SUBSCRIPTION" and s.get("refId") == sid)
    if s is None:
        await _gone(cb, state)
        return
    name = (s.get("params") or {}).get("name") or "—"
    await _start(cb, state, data, {
        "kind": "pay", "endpoint": f"/finance/monthly-payments/{sid}/pay", "name": name, "icon": "💳",
        "amount": _n(s.get("amount")), "mark": {"kind": "SUBSCRIPTION", "refId": sid},
    })


@router.callback_query(F.data == "adv:bank")
async def on_bank(cb: CallbackQuery, state: FSMContext) -> None:
    data = await _fresh(cb)
    if data is None:
        return
    chat_id = common.chat_id_of(cb)
    s = _find(data, lambda s: s.get("action") == "PAY_BANK")
    if s is None:
        await _gone(cb, state)
        return
    # A bank installment is a BANK_LOAN_PAYMENT transaction (no /repay endpoint exists); the
    # description names the loan when there is exactly one running, as the web app does.
    desc = t(chat_id, "adv.bill.bank")
    try:
        loans = await api.request(chat_id, "GET", "/finance/bank-loans") or []
        month = clock.month()
        running = [b for b in loans if isinstance(b, dict)
                   and str(b.get("takenDate") or "0000-00")[:7] <= month
                   and str(b.get("endDate") or "9999-12")[:7] >= month]
        if len(running) == 1:
            desc = t(chat_id, "fin.bankInstallmentDesc", bank=running[0].get("bankName") or "",
                     loan=running[0].get("loanName") or "")
    except Exception:  # noqa: BLE001 — a generic description is fine; the payment is what matters
        log.debug("bank loans lookup failed", exc_info=True)
    await _start(cb, state, data, {
        "kind": "bankpay", "endpoint": "/transactions", "name": t(chat_id, "adv.bill.bank"),
        "icon": "🏦", "amount": _n(s.get("amount")), "desc": desc,
    })


def _started(rec: dict) -> bool:
    start = rec.get("paymentStartDate")
    return not start or str(start)[:7] <= clock.month()


@router.callback_query(F.data.startswith("adv:debt:"))
async def on_debt(cb: CallbackQuery, state: FSMContext) -> None:
    data = await _fresh(cb)
    if data is None:
        return
    chat_id = common.chat_id_of(cb)
    plan = cb.data.endswith(":plan")
    code = "advisor.s.payLoanPlan" if plan else "advisor.s.payDebts"
    s = _find(data, lambda s: s.get("code") == code)
    if s is None:
        await _gone(cb, state)
        return
    try:
        loans = await api.request(chat_id, "GET", "/finance/loans-taken") or []
        debts = [] if plan else (await api.request(chat_id, "GET", "/finance/debts") or [])
    except Exception as exc:  # noqa: BLE001
        await _report(cb, exc)
        return
    # The same split the backend makes: a loan on a repayment plan belongs to the plan ask,
    # every other loan and every debt to the 34% pay-down.
    candidates: list[tuple[str, dict, float]] = []
    for loan in loans:
        has_plan = _n(loan.get("plannedMonthlyPayment")) > 0
        if has_plan != plan or _n(loan.get("remainingAmount")) <= 0 or not _started(loan):
            continue
        charge = _n(loan.get("plannedMonthlyPayment")) if has_plan else 0.34 * _n(loan.get("totalAmount"))
        candidates.append(("loan", loan, min(charge, _n(loan.get("remainingAmount")))))
    for debt in debts:
        if _n(debt.get("remainingAmount")) <= 0 or not _started(debt):
            continue
        candidates.append(("debt", debt, min(0.34 * _n(debt.get("totalAmount")), _n(debt.get("remainingAmount")))))
    if not candidates:
        await _gone(cb, state)
        return
    if len(candidates) == 1:
        kind, rec, _charge = candidates[0]
        amount = min(_n(s.get("amount")), _n(rec.get("remainingAmount")))
        await _start(cb, state, data, _debt_flow(kind, rec, amount))
        return
    await state.set_state(Advise.pick)
    await state.set_data({"adv_debts": [(k, r, c) for k, r, c in candidates], "adv_wallets": _wallets(data)})
    rows = [[(_clip(t(chat_id, "adv.pay.debtLine", name=_debt_name(k, r), amount=fmt_money(_n(r.get("remainingAmount"))))),
              f"adv:dp:{i}")] for i, (k, r, _c) in enumerate(candidates)]
    rows.append(ui.nav(chat_id, cancel="adv:home"))
    await common.show(cb, t(chat_id, "adv.pay.pickDebt"), ikb(rows))


def _debt_name(kind: str, rec: dict) -> str:
    return str((rec.get("lenderName") if kind == "loan" else rec.get("creditorName")) or "—")


def _debt_flow(kind: str, rec: dict, amount: float) -> dict:
    rid = rec.get("id")
    return {
        "kind": "repay",
        "endpoint": f"/finance/loans-taken/{rid}/repay" if kind == "loan" else f"/finance/debts/{rid}/repay",
        "name": _debt_name(kind, rec), "icon": "🤝", "amount": amount,
        "mark": {"kind": "PERSONAL_LOAN" if kind == "loan" else "DEBT", "refId": rid},
    }


@router.callback_query(F.data.startswith("adv:dp:"))
async def on_debt_picked(cb: CallbackQuery, state: FSMContext) -> None:
    d = await state.get_data()
    raw = cb.data.split(":")[2]
    debts = d.get("adv_debts") or []
    if not raw.isdigit() or int(raw) >= len(debts):
        await _stale(cb, state)
        return
    await common.ack(cb)
    kind, rec, charge = debts[int(raw)]
    await state.update_data(adv=_debt_flow(kind, rec, charge), adv_debts=None)
    await _pick_screen(cb, state)


@router.callback_query(F.data.startswith("adv:aside:") | F.data.startswith("adv:extra:"))
async def on_set_aside(cb: CallbackQuery, state: FSMContext) -> None:
    data = await _fresh(cb)
    if data is None:
        return
    chat_id = common.chat_id_of(cb)
    parts = cb.data.split(":")
    idea = parts[1] == "extra"
    bucket = parts[2] if len(parts) > 2 else ""
    ref = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else None
    s = _find(data, lambda s: s.get("action") == "SET_ASIDE" and s.get("bucket") == bucket
              and (s.get("kind") == "IDEA") == idea and (ref is None or s.get("refId") == ref))
    if s is None:
        await _gone(cb, state)
        return
    amount = _n(s.get("amount"))
    label = _bucket(chat_id, bucket)
    icon = _BUCKET_ICON.get(bucket, "➕")

    if bucket == "DONATION":
        await _start(cb, state, data, {"kind": "donation", "endpoint": "/finance/donations",
                                       "name": label, "icon": icon, "amount": amount})
        return
    if bucket == "SAVINGS" and s.get("refId") is not None:
        name = (s.get("params") or {}).get("name") or label
        await _start(cb, state, data, {"kind": "contribute", "icon": icon, "amount": amount, "name": name,
                                       "endpoint": f"/finance/investments/{s['refId']}/contribute"})
        return

    try:
        holdings = [i for i in await api.request(chat_id, "GET", "/finance/investments") or []
                    if isinstance(i, dict) and not i.get("openingBalance")]
    except Exception as exc:  # noqa: BLE001
        await _report(cb, exc)
        return
    if bucket == "EMERGENCY":
        # An emergency fund kept as a holding is topped up as one; otherwise the Emergencies list.
        fund = next((i for i in holdings if i.get("emergencyFund")), None)
        if fund is not None:
            flow = {"kind": "contribute", "endpoint": f"/finance/investments/{fund['id']}/contribute",
                    "name": fund.get("name") or label, "icon": icon, "amount": amount}
        else:
            flow = {"kind": "emergency", "endpoint": "/emergencies", "name": label, "icon": icon, "amount": amount}
        await _start(cb, state, data, flow)
        return

    plain = [i for i in holdings if not i.get("savingsGoal") and not i.get("emergencyFund")]
    if not plain:
        await state.clear()
        await common.show(cb, t(chat_id, "adv.pay.noInvestment"), ikb([
            [(t(chat_id, "adv.pay.createInvestment"), "fcreate:investment")],
            ui.nav(chat_id, cancel="adv:home"),
        ]))
        return
    if len(plain) == 1:
        inv = plain[0]
        await _start(cb, state, data, {"kind": "contribute", "icon": icon, "amount": amount,
                                       "name": inv.get("name") or label,
                                       "endpoint": f"/finance/investments/{inv['id']}/contribute"})
        return
    await state.set_state(Advise.pick)
    await state.set_data({"adv_invest": {"amount": amount, "options": [
        {"id": i["id"], "name": i.get("name") or label} for i in plain]}, "adv_wallets": _wallets(data)})
    rows = [[(_clip(f"📈 {i.get('name') or label}"), f"adv:inv:{n}")] for n, i in enumerate(plain)]
    rows.append(ui.nav(chat_id, cancel="adv:home"))
    await common.show(cb, t(chat_id, "adv.pay.pickInvestment"), ikb(rows))


@router.callback_query(F.data.startswith("adv:inv:"))
async def on_investment_picked(cb: CallbackQuery, state: FSMContext) -> None:
    d = await state.get_data()
    pending = d.get("adv_invest") or {}
    options = pending.get("options") or []
    raw = cb.data.split(":")[2]
    if not raw.isdigit() or int(raw) >= len(options):
        await _stale(cb, state)
        return
    await common.ack(cb)
    inv = options[int(raw)]
    await state.update_data(adv={"kind": "contribute", "icon": "📈", "amount": pending.get("amount"),
                                 "name": inv["name"], "endpoint": f"/finance/investments/{inv['id']}/contribute"},
                            adv_invest=None)
    await _pick_screen(cb, state)


# ── Recording ───────────────────────────────────────────────────────────────
def _payload(chat_id: int, flow: dict, wallet: dict) -> dict:
    """The request body for this flow, paid from `wallet`, dated today."""
    amount, today = flow["amount"], clock.today_iso()
    card_id = wallet.get("cardId") if wallet.get("type") != "CASH" else None
    kind = flow["kind"]
    if kind == "pay":
        body: dict[str, Any] = {"amount": amount, "paymentDate": today,
                                "mode": "CARD" if card_id is not None else "CASH"}
    elif kind == "bankpay":
        body = {"type": "EXPENSE", "subType": "BANK_LOAN_PAYMENT", "amount": amount, "currency": CURRENCY,
                "transactionDate": today, "description": flow.get("desc") or "",
                "cashAmount": 0 if card_id is not None else amount}
    elif kind == "repay":
        body = {"amount": amount, "paymentDate": today}
    elif kind == "donation":
        body = {"amount": amount, "currency": CURRENCY, "donationDate": today, "anonymous": False,
                "description": t(chat_id, "adv.pay.donationDesc")}
    elif kind == "emergency":
        body = {"amount": amount, "currency": CURRENCY, "date": today,
                "description": t(chat_id, "adv.pay.emergencyDesc")}
    else:  # contribute
        body = {"amount": amount, "currency": CURRENCY, "date": today}
    if card_id is not None:
        body["cardId"] = card_id
    return body


async def _stale(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb, t(common.chat_id_of(cb), "adv.pay.stale"), alert=True)
    await state.clear()
    await show_advisor(cb)


@router.callback_query(F.data.startswith("adv:w:"))
async def on_wallet(cb: CallbackQuery, state: FSMContext) -> None:
    """The second tap: record it from this wallet, then show the advisor again."""
    chat_id = common.chat_id_of(cb)
    d = await state.get_data()
    flow, wallets = d.get("adv"), d.get("adv_wallets") or []
    raw = cb.data.split(":")[2]
    if not flow or not raw.isdigit() or int(raw) >= len(wallets):
        await _stale(cb, state)
        return
    await common.ack(cb)
    if not await common.gate(cb):
        return
    await common.begin_write(cb, chat_id)
    try:
        await api.request(chat_id, "POST", flow["endpoint"], json=_payload(chat_id, flow, wallets[int(raw)]))
    except Exception as exc:  # noqa: BLE001
        await state.clear()
        await _report(cb, exc)
        return
    await state.clear()
    await show_advisor(cb, t(chat_id, "adv.pay.done", amount=fmt_money(flow["amount"]), name=esc(flow["name"])))


@router.callback_query(F.data == "adv:mark")
async def on_mark(cb: CallbackQuery, state: FSMContext) -> None:
    """Paid already, from money the app does not track: settle it without moving a wallet."""
    chat_id = common.chat_id_of(cb)
    d = await state.get_data()
    flow = d.get("adv") or {}
    mark = flow.get("mark")
    if not mark:
        await _stale(cb, state)
        return
    await common.ack(cb)
    if not await common.gate(cb):
        return
    await common.begin_write(cb, chat_id)
    try:
        await api.request(chat_id, "POST", "/finance/mark-paid", json={
            "kind": mark["kind"], "refId": mark["refId"], "amount": flow["amount"],
            "currency": CURRENCY, "month": clock.month()})
    except Exception as exc:  # noqa: BLE001
        await state.clear()
        await _report(cb, exc)
        return
    await state.clear()
    await show_advisor(cb, t(chat_id, "adv.pay.marked", amount=fmt_money(flow["amount"]), name=esc(flow["name"])))


@router.callback_query(F.data == "adv:amt")
async def on_other_amount(cb: CallbackQuery, state: FSMContext) -> None:
    chat_id = common.chat_id_of(cb)
    d = await state.get_data()
    if not d.get("adv"):
        await _stale(cb, state)
        return
    await common.ack(cb)
    await state.set_state(Advise.amount)
    await common.show(cb, t(chat_id, "adv.pay.sendAmount", name=esc(d["adv"].get("name") or "")),
                      ikb([ui.nav(chat_id, cancel="adv:home")]))


@router.message(StateFilter(Advise.amount))
async def on_amount_typed(message: Message, state: FSMContext) -> None:
    amount = parse_amount(message.text)
    if amount is None:
        await message.answer(t(message.chat.id, "common.positiveNumber"))
        return
    d = await state.get_data()
    flow = dict(d.get("adv") or {})
    if not flow:
        await state.clear()
        await show_advisor(message)
        return
    flow["amount"] = amount
    await state.update_data(adv=flow)
    await _pick_screen(message, state)
