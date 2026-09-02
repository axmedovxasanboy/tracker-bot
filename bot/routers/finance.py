"""Finance: read views (7 sections), money actions (repay/mark-returned/pay), and create."""
import datetime as dt

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from . import wizard
from .. import api, common, keyboards
from ..config import CURRENCY
from ..i18n import t
from ..keyboards import esc, fmt_money, fmt_pct, ikb
from ..states import FinAction, GoalValue

router = Router()
MAX_ROWS = 10


def _today() -> str:
    return dt.date.today().isoformat()


def _month_now() -> str:
    return dt.date.today().strftime("%Y-%m")


def _find(items, cid):
    return next((c for c in items if c.get("id") == cid), None)


def _menu_kb(chat_id: int):
    return ikb([
        [(t(chat_id, "fin.menu.debts"), "fin:debt"), (t(chat_id, "fin.menu.loanGiven"), "fin:loangiven")],
        [(t(chat_id, "fin.menu.loanTaken"), "fin:loantaken"), (t(chat_id, "fin.menu.bankLoan"), "fin:bankloan")],
        [(t(chat_id, "fin.menu.subscriptions"), "fin:monthly"), (t(chat_id, "fin.menu.donations"), "fin:donation")],
        [(t(chat_id, "fin.menu.investments"), "fin:investment"), (t(chat_id, "fin.menu.savingsGoals"), "fin:savings")],
        [(t(chat_id, "common.menu"), "menu:home")],
    ])


def _back_kb(chat_id: int):
    return ikb([[(t(chat_id, "fin.backToFinance"), "menu:finance")]])


def _section_kb(chat_id: int, section, action_rows=None):
    rows = list(action_rows or [])
    rows.append([(t(chat_id, "common.add"), f"fcreate:{section}")])
    rows.append([(t(chat_id, "fin.backToFinance"), "menu:finance")])
    return ikb(rows)


async def show_menu(cb: CallbackQuery) -> None:
    chat_id = cb.message.chat.id
    await cb.message.edit_text(t(chat_id, "fin.menuTitle"), reply_markup=_menu_kb(chat_id))


async def _fetch(cb: CallbackQuery, path: str):
    chat_id = cb.message.chat.id
    try:
        return await api.request(chat_id, "GET", path) or []
    except api.NeedsLogin:
        await cb.message.edit_text(t(chat_id, "common.sessionExpired"), reply_markup=keyboards.login_kb(chat_id))
    except Exception:  # noqa: BLE001
        await cb.message.edit_text(t(chat_id, "fin.sectionLoadError"), reply_markup=_back_kb(chat_id))
    return None


@router.callback_query(F.data.startswith("fin:"))
async def on_section(cb: CallbackQuery) -> None:
    await cb.answer()
    if not await common.gate(cb):
        return
    section = cb.data.split(":", 1)[1]
    fn = {
        "debt": show_debts, "loangiven": show_loans_given, "loantaken": show_loans_taken,
        "bankloan": show_bank_loans, "monthly": show_monthly, "donation": show_donations,
        "investment": show_investments, "savings": show_savings,
    }.get(section)
    if fn:
        await fn(cb)


async def show_debts(cb: CallbackQuery) -> None:
    chat_id = cb.message.chat.id
    rows = await _fetch(cb, "/finance/debts")
    if rows is None:
        return
    lines, actions = [t(chat_id, "fin.debtsTitle")], []
    if not rows:
        lines.append(t(chat_id, "common.nothingHere"))
    for d in rows:
        due = t(chat_id, "fin.suffixDue", date=d['dueDate']) if d.get("dueDate") else ""
        lines.append("• " + t(
            chat_id, "fin.debtLine", name=esc(d.get('creditorName')),
            remaining=fmt_money(d.get('remainingAmount')), total=fmt_money(d.get('totalAmount')), due=due))
        if (d.get("remainingAmount") or 0) > 0 and len(actions) < MAX_ROWS:
            actions.append([(t(chat_id, "fin.repayBtn", name=str(d.get('creditorName'))[:18]), f"fact:debt:{d['id']}")])
    await cb.message.edit_text("\n".join(lines), reply_markup=_section_kb(chat_id, "debt", actions))


async def show_loans_taken(cb: CallbackQuery) -> None:
    chat_id = cb.message.chat.id
    rows = await _fetch(cb, "/finance/loans-taken")
    if rows is None:
        return
    lines, actions = [t(chat_id, "fin.loansTakenTitle")], []
    if not rows:
        lines.append(t(chat_id, "common.nothingHere"))
    for l in rows:
        due = t(chat_id, "fin.suffixDue", date=l['dueDate']) if l.get("dueDate") else ""
        start = t(chat_id, "fin.suffixPaysFrom", month=l['paymentStartDate'][:7]) if l.get("paymentStartDate") else ""
        lines.append("• " + t(
            chat_id, "fin.loanTakenLine", name=esc(l.get('lenderName')),
            remaining=fmt_money(l.get('remainingAmount')), total=fmt_money(l.get('totalAmount')),
            due=due, start=start))
        if (l.get("remainingAmount") or 0) > 0 and len(actions) < MAX_ROWS:
            actions.append([(t(chat_id, "fin.repayBtn", name=str(l.get('lenderName'))[:18]), f"fact:loantaken:{l['id']}")])
    await cb.message.edit_text("\n".join(lines), reply_markup=_section_kb(chat_id, "loantaken", actions))


async def show_loans_given(cb: CallbackQuery) -> None:
    chat_id = cb.message.chat.id
    rows = await _fetch(cb, "/finance/loans-given")
    if rows is None:
        return
    lines, actions = [t(chat_id, "fin.loansGivenTitle")], []
    if not rows:
        lines.append(t(chat_id, "common.nothingHere"))
    for l in rows:
        exp = t(chat_id, "fin.suffixExpect", date=l['expectedReturnDate']) if l.get("expectedReturnDate") else ""
        lines.append("• " + t(
            chat_id, "fin.loanGivenLine", name=esc(l.get('debtorName')),
            pending=fmt_money(l.get('pendingAmount')), total=fmt_money(l.get('totalAmount')), exp=exp))
        if (l.get("pendingAmount") or 0) > 0 and len(actions) < MAX_ROWS:
            actions.append([(t(chat_id, "fin.returnedByBtn", name=str(l.get('debtorName'))[:16]), f"fact:loangiven:{l['id']}")])
    await cb.message.edit_text("\n".join(lines), reply_markup=_section_kb(chat_id, "loangiven", actions))


async def show_monthly(cb: CallbackQuery) -> None:
    chat_id = cb.message.chat.id
    rows = await _fetch(cb, "/finance/monthly-payments")
    if rows is None:
        return
    lines, actions = [t(chat_id, "fin.subscriptionsTitle")], []
    if not rows:
        lines.append(t(chat_id, "common.nothingHere"))
    for m in rows:
        active = "" if m.get("active", True) else t(chat_id, "fin.suffixPaused")
        due = t(chat_id, "fin.suffixDay", day=m['dueDay']) if m.get("dueDay") else ""
        lines.append("• " + t(
            chat_id, "fin.monthlyLine", name=esc(m.get('name')), amount=fmt_money(m.get('amount')),
            due=due, active=active))
        if m.get("active", True) and len(actions) < MAX_ROWS:
            actions.append([(t(chat_id, "fin.payBtn", name=str(m.get('name'))[:20]), f"fact:monthly:{m['id']}")])
    await cb.message.edit_text("\n".join(lines), reply_markup=_section_kb(chat_id, "monthly", actions))


async def show_bank_loans(cb: CallbackQuery) -> None:
    chat_id = cb.message.chat.id
    rows = await _fetch(cb, "/finance/bank-loans")
    if rows is None:
        return
    lines = [t(chat_id, "fin.bankLoansTitle")]
    if not rows:
        lines.append(t(chat_id, "common.nothingHere"))
    for b in rows:
        monthly = t(chat_id, "fin.suffixMonthly", amount=fmt_money(b.get('monthlyPayment'))) if b.get("monthlyPayment") else ""
        end = t(chat_id, "fin.suffixEnds", date=b['endDate']) if b.get("endDate") else ""
        lines.append("• " + t(
            chat_id, "fin.bankLoanLine", bank=esc(b.get('bankName')), loan=esc(b.get('loanName')),
            total=fmt_money(b.get('totalAmount')), monthly=monthly, end=end))
    await cb.message.edit_text("\n".join(lines), reply_markup=_section_kb(chat_id, "bankloan"))


async def show_donations(cb: CallbackQuery) -> None:
    chat_id = cb.message.chat.id
    rows = await _fetch(cb, "/finance/donations")
    if rows is None:
        return
    lines = [t(chat_id, "fin.donationsTitle")]
    if not rows:
        lines.append(t(chat_id, "common.nothingHere"))
    for d in rows[:20]:
        who = d.get("displayName") or d.get("recipientName") or "—"
        lines.append("• " + t(
            chat_id, "fin.donationLine", date=d.get('donationDate', ''), who=esc(who), amount=fmt_money(d.get('amount'))))
    await cb.message.edit_text("\n".join(lines), reply_markup=_section_kb(chat_id, "donation"))


async def show_investments(cb: CallbackQuery) -> None:
    chat_id = cb.message.chat.id
    rows = await _fetch(cb, "/finance/investments")
    if rows is None:
        return
    plain = [i for i in rows if not i.get("savingsGoal")]
    lines = [t(chat_id, "fin.investmentsTitle")]
    if not plain:
        lines.append(t(chat_id, "common.nothingHere"))
    for i in plain[:20]:
        typ = esc(str(i.get("type", "")).replace("_", " ").title())
        tag = t(chat_id, "fin.suffixOpening") if i.get("openingBalance") else ""
        lines.append("• " + t(
            chat_id, "fin.investmentLine", name=esc(i.get('name')), type=typ,
            amount=fmt_money(i.get('investedAmount')), tag=tag))
    await cb.message.edit_text("\n".join(lines), reply_markup=_section_kb(chat_id, "investment"))


async def show_savings(cb: CallbackQuery) -> None:
    chat_id = cb.message.chat.id
    rows = await _fetch(cb, "/finance/investments")
    if rows is None:
        return
    goals = [i for i in rows if i.get("savingsGoal")]
    lines, actions = [t(chat_id, "fin.savingsTitle")], []
    if not goals:
        lines.append(t(chat_id, "fin.noSavingsGoalsYet"))
    for g in goals:
        value = g.get("currentValue")
        if value is None:
            value = g.get("investedAmount")
        tgt = f" / {fmt_money(g.get('targetAmount'))}" if g.get("targetAmount") is not None else ""
        prog = f" · {fmt_pct(g.get('progressPercent'))}" if g.get("progressPercent") is not None else ""
        lines.append("• " + t(chat_id, "fin.savingsLine", name=esc(g.get('name')), value=fmt_money(value), target=tgt, progress=prog))
        if len(actions) < MAX_ROWS:
            actions.append([(t(chat_id, "fin.addToGoalBtn", name=str(g.get('name'))[:14]), f"fact:goalcontrib:{g['id']}"),
                            (t(chat_id, "fin.valueBtn"), f"goal:value:{g['id']}")])
    await cb.message.edit_text("\n".join(lines), reply_markup=_section_kb(chat_id, "goal", actions))


# ── action conversation: repay / mark-returned / pay ───────────────────────
KIND_CFG = {
    "debt": {"list": "/finance/debts", "name": "creditorName", "suggest": "remainingAmount",
             "verb": "fin.verbRepayDebt", "endpoint": "/finance/debts/{id}/repay", "action": "repay",
             "markkind": "DEBT"},
    "loantaken": {"list": "/finance/loans-taken", "name": "lenderName", "suggest": "remainingAmount",
                  "verb": "fin.verbRepayLoan", "endpoint": "/finance/loans-taken/{id}/repay", "action": "repay",
                  "markkind": "PERSONAL_LOAN"},
    "loangiven": {"list": "/finance/loans-given", "name": "debtorName", "suggest": "pendingAmount",
                  "verb": "fin.verbMarkReturned", "endpoint": "/finance/loans-given/{id}/mark-returned",
                  "action": "markreturned"},
    "monthly": {"list": "/finance/monthly-payments", "name": "name", "suggest": "amount",
                "verb": "fin.verbPay", "endpoint": "/finance/monthly-payments/{id}/pay", "action": "pay",
                "markkind": "SUBSCRIPTION"},
    # Savings-goal contribution — reuses the amount→source→confirm flow. No suggested amount
    # (investments have no "remainingAmount" key, so the "Use …" button is skipped).
    "goalcontrib": {"list": "/finance/investments", "name": "name", "suggest": "remainingAmount",
                    "verb": "fin.verbContribute", "endpoint": "/finance/investments/{id}/contribute",
                    "action": "contribute"},
}


@router.callback_query(F.data.startswith("fact:cancel"))
async def fa_cancel(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    chat_id = cb.message.chat.id
    await state.clear()
    await cb.message.edit_text(t(chat_id, "common.cancelled"), reply_markup=_back_kb(chat_id))


@router.callback_query(F.data.startswith("fact:"))
async def fa_entry(cb: CallbackQuery, state: FSMContext) -> None:
    if not await common.gate(cb):
        return
    await cb.answer()
    if not await common.stable_income_set(cb):
        return
    chat_id = cb.message.chat.id
    _, kind, sid = cb.data.split(":")
    cfg = KIND_CFG[kind]
    rid = int(sid)
    rows = await _fetch(cb, cfg["list"])
    if rows is None:
        return
    rec = _find(rows, rid)
    if rec is None:
        await cb.message.edit_text(t(chat_id, "fin.recordGone"), reply_markup=_back_kb(chat_id))
        return
    suggested = rec.get(cfg["suggest"]) or 0
    await state.set_state(FinAction.amount)
    await state.update_data(fa_action=cfg["action"], fa_endpoint=cfg["endpoint"].format(id=rid),
                            fa_currency=CURRENCY, fa_name=rec.get(cfg["name"], "?"),
                            fa_markkind=cfg.get("markkind"), fa_refid=rid, fa_mark=False)
    kb_rows = []
    if suggested and suggested > 0:
        kb_rows.append([(t(chat_id, "fin.useSuggested", amount=fmt_money(suggested)), "fause")])
        await state.update_data(fa_suggested=suggested)
    # "Already paid" — mark satisfied for the month with no transaction (debts / loans / subscriptions).
    if cfg.get("markkind"):
        kb_rows.append([(t(chat_id, "fin.alreadyPaidBtn"), "famark")])
    kb_rows.append([(t(chat_id, "common.cancel"), "fact:cancel")])
    await cb.message.edit_text(
        t(chat_id, "fin.sendAmountPrompt", verb=t(chat_id, cfg["verb"]), name=esc(rec.get(cfg['name'])), currency=CURRENCY),
        reply_markup=ikb(kb_rows))


@router.callback_query(StateFilter(FinAction.amount), F.data == "famark")
async def fa_mark_start(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    chat_id = cb.message.chat.id
    await state.update_data(fa_mark=True)
    d = await state.get_data()
    kb_rows = []
    sug = d.get("fa_suggested")
    if sug and sug > 0:
        kb_rows.append([(t(chat_id, "fin.useSuggested", amount=fmt_money(sug)), "fause")])
    kb_rows.append([(t(chat_id, "common.cancel"), "fact:cancel")])
    await cb.message.edit_text(
        t(chat_id, "fin.markAlreadyPaid", name=esc(d['fa_name']), currency=CURRENCY),
        reply_markup=ikb(kb_rows))


async def _fa_after_amount(event, state: FSMContext) -> None:
    """Branch once the amount is captured: already-paid → mark confirm; else → pick a source."""
    d = await state.get_data()
    if d.get("fa_mark"):
        await _fa_mark_confirm(event, state)
    else:
        await _fa_source(event, state)


@router.callback_query(StateFilter(FinAction.amount), F.data == "fause")
async def fa_use(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    d = await state.get_data()
    await state.update_data(fa_amount=d.get("fa_suggested"))
    await _fa_after_amount(cb, state)


@router.message(StateFilter(FinAction.amount))
async def fa_amount(message: Message, state: FSMContext) -> None:
    from .transactions import parse_amount
    amt = parse_amount(message.text)
    if amt is None:
        await message.answer(t(message.chat.id, "common.positiveNumber"))
        return
    await state.update_data(fa_amount=amt)
    await _fa_after_amount(message, state)


async def _fa_source(event, state: FSMContext) -> None:
    chat_id = common.chat_id_of(event)
    d = await state.get_data()
    try:
        cards = await api.request(chat_id, "GET", "/cards") or []
    except Exception:  # noqa: BLE001
        cards = []
    cards = [c for c in cards if c.get("currency") == CURRENCY and c.get("type") != "CASH"]
    await state.update_data(fa_cards=cards)
    rows = [[(t(chat_id, "common.cashBtn"), "fasrc:cash")]]
    for c in cards:
        rows.append([(f"💳 {c.get('name', 'Card')} ···{c.get('lastFourDigits', '')}", f"fasrc:card:{c['id']}")])
    # Contributions can be recorded WITHOUT moving money (funds already in the investment account).
    if d.get("fa_action") == "contribute":
        rows.append([(t(chat_id, "fin.noneRecordOnly"), "fasrc:none")])
    rows.append([(t(chat_id, "common.cancel"), "fact:cancel")])
    await state.set_state(FinAction.source)
    await common.show(event, t(chat_id, "fin.payFrom", currency=CURRENCY), ikb(rows))


@router.callback_query(StateFilter(FinAction.source), F.data.startswith("fasrc:"))
async def fa_src(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    chat_id = cb.message.chat.id
    if cb.data == "fasrc:none":
        await state.update_data(fa_cardId=None, fa_noWallet=True)
        d = await state.get_data()
        await state.set_state(FinAction.confirm)
        await cb.message.edit_text(
            t(chat_id, "fin.confirmHeader", name=esc(d['fa_name']), amount=fmt_money(d['fa_amount']))
            + t(chat_id, "fin.fromNone"),
            reply_markup=ikb([[(t(chat_id, "common.confirm"), "faok"), (t(chat_id, "common.cancel"), "fact:cancel")]]))
        return
    card_id = None if cb.data == "fasrc:cash" else int(cb.data.split(":")[2])
    await state.update_data(fa_cardId=card_id, fa_noWallet=False)
    d = await state.get_data()
    src = t(chat_id, "common.cash") if card_id is None else next(
        (c.get("name", "Card") for c in d.get("fa_cards", []) if c["id"] == card_id), "Card")
    await state.set_state(FinAction.confirm)
    await cb.message.edit_text(
        t(chat_id, "fin.confirmHeader", name=esc(d['fa_name']), amount=fmt_money(d['fa_amount']))
        + t(chat_id, "fin.fromSource", source=esc(src)),
        reply_markup=ikb([[(t(chat_id, "common.confirm"), "faok"), (t(chat_id, "common.cancel"), "fact:cancel")]]))


async def _fa_mark_confirm(event, state: FSMContext) -> None:
    chat_id = common.chat_id_of(event)
    d = await state.get_data()
    await state.set_state(FinAction.confirm)
    await common.show(
        event,
        t(chat_id, "fin.markConfirmHeader", name=esc(d['fa_name']), amount=fmt_money(d['fa_amount'])),
        ikb([[(t(chat_id, "common.confirm"), "famarkok"), (t(chat_id, "common.cancel"), "fact:cancel")]]))


@router.callback_query(StateFilter(FinAction.confirm), F.data == "famarkok")
async def fa_mark_ok(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    chat_id = cb.message.chat.id
    d = await state.get_data()
    payload = {"kind": d["fa_markkind"], "refId": d.get("fa_refid"),
               "amount": d["fa_amount"], "currency": d["fa_currency"], "month": _month_now()}
    try:
        await api.request(chat_id, "POST", "/finance/mark-paid", json=payload)
    except api.NeedsLogin:
        await state.clear()
        await cb.message.edit_text(t(chat_id, "common.sessionExpired"), reply_markup=keyboards.login_kb(chat_id))
        return
    except api.ApiError as exc:
        await state.clear()
        await cb.message.edit_text(f"❌ {esc(exc.message)}", reply_markup=_back_kb(chat_id))
        return
    except Exception:  # noqa: BLE001
        await state.clear()
        await cb.message.edit_text(t(chat_id, "common.serverUnreachable"), reply_markup=_back_kb(chat_id))
        return
    await state.clear()
    await cb.message.edit_text(
        t(chat_id, "fin.markedPaid", amount=fmt_money(d['fa_amount']), name=esc(d['fa_name'])),
        reply_markup=_back_kb(chat_id))


@router.callback_query(StateFilter(FinAction.confirm), F.data == "faok")
async def fa_confirm(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    chat_id = cb.message.chat.id
    d = await state.get_data()
    card_id = d.get("fa_cardId")
    if d["fa_action"] == "pay":
        payload = {"amount": d["fa_amount"], "paymentDate": _today(),
                   "mode": "CARD" if card_id is not None else "CASH"}
        if card_id is not None:
            payload["cardId"] = card_id
    elif d["fa_action"] == "contribute":
        payload = {"amount": d["fa_amount"], "currency": d["fa_currency"], "date": _today()}
        if d.get("fa_noWallet"):
            payload["noWallet"] = True
        elif card_id is not None:
            payload["cardId"] = card_id
    else:
        payload = {"amount": d["fa_amount"], "paymentDate": _today()}
        if card_id is not None:
            payload["cardId"] = card_id
    try:
        await api.request(chat_id, "POST", d["fa_endpoint"], json=payload)
    except api.NeedsLogin:
        await state.clear()
        await cb.message.edit_text(t(chat_id, "common.sessionExpired"), reply_markup=keyboards.login_kb(chat_id))
        return
    except api.ApiError as exc:
        await state.clear()
        await cb.message.edit_text(f"❌ {esc(exc.message)}", reply_markup=_back_kb(chat_id))
        return
    except Exception:  # noqa: BLE001
        await state.clear()
        await cb.message.edit_text(t(chat_id, "common.serverUnreachable"), reply_markup=_back_kb(chat_id))
        return
    await state.clear()
    await cb.message.edit_text(
        t(chat_id, "fin.recorded", amount=fmt_money(d['fa_amount']), name=esc(d['fa_name'])),
        reply_markup=_back_kb(chat_id))


# ── create (generic wizard) ─────────────────────────────────────────────────
# Must match the backend InvestmentType enum (STOCKS & CRYPTO were removed — stocks are
# tracked via the STOCK_PURCHASE transaction sub-type / "Stocks" category, not here).
INVESTMENT_TYPES = [
    ("REAL_ESTATE", "fin.investmentType.realEstate"), ("BONDS", "fin.investmentType.bonds"),
    ("MUTUAL_FUND", "fin.investmentType.mutualFund"), ("GOLD", "fin.investmentType.gold"),
    ("OTHER", "fin.investmentType.other"),
]

CREATE_SECTIONS = {
    "debt": {"title": "fin.create.debt.title", "endpoint": "/finance/debts", "back": "fin:debt",
             "success": "fin.create.debt.success", "auto_currency": True, "fields": [
                 {"key": "creditorName", "label": "fin.create.debt.creditorName", "kind": "text", "required": True},
                 {"key": "totalAmount", "label": "fin.field.totalAmount", "kind": "amount", "required": True},
                 {"key": "borrowedDate", "label": "fin.create.debt.borrowedDate", "kind": "date", "required": True, "today": True},
                 {"key": "dueDate", "label": "fin.field.dueDate", "kind": "date", "required": False},
                 {"key": "paymentStartDate", "label": "fin.field.paymentStartMonth", "kind": "month", "required": False},
                 {"key": "description", "label": "fin.field.description", "kind": "text", "required": False},
             ]},
    "loangiven": {"title": "fin.create.loanGiven.title", "endpoint": "/finance/loans-given", "back": "fin:loangiven",
                  "success": "fin.create.loanGiven.success", "auto_currency": True, "fields": [
                      {"key": "debtorName", "label": "fin.create.loanGiven.debtorName", "kind": "text", "required": True},
                      {"key": "totalAmount", "label": "fin.create.loanGiven.amountLent", "kind": "amount", "required": True},
                      {"key": "lentDate", "label": "fin.create.loanGiven.lentDate", "kind": "date", "required": True, "today": True},
                      {"key": "expectedReturnDate", "label": "fin.create.loanGiven.expectedReturnDate", "kind": "date", "required": False},
                      {"key": "description", "label": "fin.field.description", "kind": "text", "required": False},
                  ]},
    "loantaken": {"title": "fin.create.loanTaken.title", "endpoint": "/finance/loans-taken", "back": "fin:loantaken",
                  "success": "fin.create.loanTaken.success", "auto_currency": True, "fields": [
                      {"key": "lenderName", "label": "fin.create.loanTaken.lenderName", "kind": "text", "required": True},
                      {"key": "totalAmount", "label": "fin.field.totalAmount", "kind": "amount", "required": True},
                      {"key": "borrowedDate", "label": "fin.create.loanTaken.borrowedDate", "kind": "date", "required": True, "today": True},
                      {"key": "dueDate", "label": "fin.field.dueDate", "kind": "date", "required": False},
                      {"key": "paymentStartDate", "label": "fin.field.paymentStartMonth", "kind": "month", "required": False},
                      {"key": "description", "label": "fin.field.description", "kind": "text", "required": False},
                  ]},
    "bankloan": {"title": "fin.create.bankLoan.title", "endpoint": "/finance/bank-loans", "back": "fin:bankloan",
                 "success": "fin.create.bankLoan.success", "auto_currency": True, "fields": [
                     {"key": "bankName", "label": "fin.create.bankLoan.bankName", "kind": "text", "required": True},
                     {"key": "loanName", "label": "fin.create.bankLoan.loanNameType", "kind": "text", "required": True},
                     {"key": "totalAmount", "label": "fin.field.totalAmount", "kind": "amount", "required": True},
                     {"key": "monthlyPayment", "label": "fin.create.bankLoan.monthlyPayment", "kind": "amount", "required": False},
                     {"key": "takenDate", "label": "fin.create.bankLoan.takenDate", "kind": "date", "required": True, "today": True},
                     {"key": "endDate", "label": "fin.create.bankLoan.endDate", "kind": "date", "required": False},
                 ]},
    "monthly": {"title": "fin.create.monthly.title", "endpoint": "/finance/monthly-payments", "back": "fin:monthly",
                "success": "fin.create.monthly.success", "auto_currency": True, "fields": [
                    {"key": "name", "label": "fin.field.name", "kind": "text", "required": True},
                    {"key": "amount", "label": "fin.create.monthly.monthlyAmount", "kind": "amount", "required": True},
                    {"key": "dueDay", "label": "fin.create.monthly.dueDay", "kind": "int", "required": True, "min": 1, "max": 31},
                    {"key": "description", "label": "fin.field.description", "kind": "text", "required": False},
                ]},
    "donation": {"title": "fin.create.donation.title", "endpoint": "/finance/donations", "back": "fin:donation",
                 "success": "fin.create.donation.success", "auto_currency": True, "fields": [
                     {"key": "recipientName", "label": "fin.create.donation.recipient", "kind": "text", "required": True},
                     {"key": "amount", "label": "fin.field.amount", "kind": "amount", "required": True},
                     {"key": "donationDate", "label": "fin.field.date", "kind": "date", "required": True, "today": True},
                     {"key": "description", "label": "fin.field.description", "kind": "text", "required": False},
                 ]},
    "investment": {"title": "fin.create.investment.title", "endpoint": "/finance/investments", "back": "fin:investment",
                   "success": "fin.create.investment.success", "auto_currency": True, "fields": [
                       {"key": "name", "label": "fin.field.name", "kind": "text", "required": True},
                       {"key": "type", "label": "fin.field.type", "kind": "choice", "required": True, "choices": INVESTMENT_TYPES},
                       {"key": "investedAmount", "label": "fin.create.investment.amountInvested", "kind": "amount", "required": True},
                       {"key": "openingBalance", "kind": "bool", "required": True,
                        "label": "fin.create.investment.openingBalanceQ",
                        "yes_label": "fin.create.investment.openingYes", "no_label": "fin.create.investment.openingNo"},
                       {"key": "broker", "label": "fin.create.investment.broker", "kind": "text", "required": False},
                       {"key": "purchaseDate", "label": "fin.create.investment.purchaseDate", "kind": "date", "required": True, "today": True},
                       {"key": "description", "label": "fin.field.description", "kind": "text", "required": False},
                   ]},
    "goal": {"title": "fin.create.goal.title", "endpoint": "/finance/investments", "back": "fin:savings",
             "success": "fin.create.goal.success", "auto_currency": True,
             "fixed": {"savingsGoal": True, "type": "OTHER"}, "fields": [
                 {"key": "name", "label": "fin.create.goal.goalName", "kind": "text", "required": True},
                 {"key": "investedAmount", "label": "fin.create.goal.amountSaved", "kind": "amount", "required": True},
                 {"key": "openingBalance", "kind": "bool", "required": True,
                  "label": "fin.create.goal.openingQ",
                  "yes_label": "fin.create.goal.openingYes",
                  "no_label": "fin.create.goal.openingNo"},
                 {"key": "targetAmount", "label": "fin.create.goal.targetAmount", "kind": "amount", "required": False},
                 {"key": "currentValue", "label": "fin.create.goal.currentValue", "kind": "amount", "required": False},
                 {"key": "purchaseDate", "label": "fin.create.goal.startDate", "kind": "date", "required": True, "today": True},
                 {"key": "description", "label": "fin.create.goal.notes", "kind": "text", "required": False},
             ]},
}


@router.callback_query(F.data.startswith("fcreate:"))
async def create_entry(cb: CallbackQuery, state: FSMContext) -> None:
    if not await common.gate(cb):
        return
    await cb.answer()
    if not await common.stable_income_set(cb):
        return
    chat_id = cb.message.chat.id
    section = cb.data.split(":", 1)[1]
    spec = CREATE_SECTIONS.get(section)
    if not spec:
        await cb.message.edit_text(t(chat_id, "common.unknownSection"), reply_markup=_back_kb(chat_id))
        return
    await wizard.start(cb, state, spec)


# ── savings goal: update current value ──────────────────────────────────────
@router.callback_query(F.data.startswith("goal:value:"))
async def gv_entry(cb: CallbackQuery, state: FSMContext) -> None:
    if not await common.gate(cb):
        return
    await cb.answer()
    chat_id = cb.message.chat.id
    gid = int(cb.data.split(":")[2])
    rows = await _fetch(cb, "/finance/investments")
    if rows is None:
        return
    rec = _find(rows, gid)
    if rec is None:
        await cb.message.edit_text(t(chat_id, "fin.goalGone"), reply_markup=_back_kb(chat_id))
        return
    current = rec.get("currentValue")
    if current is None:
        current = rec.get("investedAmount")
    await state.set_state(GoalValue.amount)
    await state.update_data(gv_id=gid, gv_name=rec.get("name", "?"))
    await cb.message.edit_text(
        t(chat_id, "fin.updateValueHeader", name=esc(rec.get('name')), current=fmt_money(current), currency=CURRENCY),
        reply_markup=ikb([[(t(chat_id, "common.cancel"), "fact:cancel")]]))


@router.message(StateFilter(GoalValue.amount))
async def gv_amount(message: Message, state: FSMContext) -> None:
    chat_id = message.chat.id
    from .transactions import parse_amount
    val = parse_amount(message.text)
    if val is None:
        await message.answer(t(chat_id, "common.positiveNumber"))
        return
    d = await state.get_data()
    try:
        await api.request(chat_id, "POST", f"/finance/investments/{d['gv_id']}/value",
                          json={"currentValue": val})
    except api.NeedsLogin:
        await state.clear()
        await message.answer(t(chat_id, "common.sessionExpired"), reply_markup=keyboards.login_kb(chat_id))
        return
    except api.ApiError as exc:
        await state.clear()
        await message.answer(f"❌ {esc(exc.message)}", reply_markup=_back_kb(chat_id))
        return
    except Exception:  # noqa: BLE001
        await state.clear()
        await message.answer(t(chat_id, "common.serverUnreachable"), reply_markup=_back_kb(chat_id))
        return
    await state.clear()
    await message.answer(
        t(chat_id, "fin.updatedValue", name=esc(d['gv_name']), value=fmt_money(val)),
        reply_markup=_back_kb(chat_id))
