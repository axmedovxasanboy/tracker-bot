"""Finance: read views (7 sections), money actions (repay/mark-returned/pay), and create."""
import datetime as dt

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from . import wizard
from .. import api, common, keyboards
from ..keyboards import esc, fmt_money, ikb
from ..session import store
from ..states import FinAction

router = Router()
MAX_ROWS = 10


def _today() -> str:
    return dt.date.today().isoformat()


def _find(items, cid):
    return next((c for c in items if c.get("id") == cid), None)


def _menu_kb():
    return ikb([
        [("📕 Debts", "fin:debt"), ("📗 Loans given", "fin:loangiven")],
        [("📘 Loans taken", "fin:loantaken"), ("🏛 Bank loans", "fin:bankloan")],
        [("🔁 Subscriptions", "fin:monthly"), ("🎁 Donations", "fin:donation")],
        [("📈 Investments", "fin:investment")],
        [("⬅️ Menu", "menu:home")],
    ])


def _back_kb():
    return ikb([[("⬅️ Finance", "menu:finance")]])


def _section_kb(section, action_rows=None):
    rows = list(action_rows or [])
    rows.append([("➕ Add", f"fcreate:{section}")])
    rows.append([("⬅️ Finance", "menu:finance")])
    return ikb(rows)


async def show_menu(cb: CallbackQuery) -> None:
    await cb.message.edit_text("🏦 <b>Finance</b>\nPick a section:", reply_markup=_menu_kb())


async def _fetch(cb: CallbackQuery, path: str):
    try:
        return await api.request(cb.message.chat.id, "GET", path) or []
    except api.NeedsLogin:
        await cb.message.edit_text("🔒 Session expired. Please log in.", reply_markup=keyboards.login_kb())
    except Exception:  # noqa: BLE001
        await cb.message.edit_text("❌ Couldn't load that section.", reply_markup=_back_kb())
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
        "investment": show_investments,
    }.get(section)
    if fn:
        await fn(cb)


async def show_debts(cb: CallbackQuery) -> None:
    rows = await _fetch(cb, "/finance/debts")
    if rows is None:
        return
    lines, actions = ["📕 <b>Debts</b> (you owe)\n"], []
    if not rows:
        lines.append("Nothing here yet.")
    for d in rows:
        cur = d.get("currency")
        due = f" · due {d['dueDate']}" if d.get("dueDate") else ""
        lines.append(f"• {esc(d.get('creditorName'))}: {fmt_money(d.get('remainingAmount'), cur)} left "
                     f"/ {fmt_money(d.get('totalAmount'), cur)}{due}")
        if (d.get("remainingAmount") or 0) > 0 and len(actions) < MAX_ROWS:
            actions.append([(f"💸 Repay {str(d.get('creditorName'))[:18]}", f"fact:debt:{d['id']}")])
    await cb.message.edit_text("\n".join(lines), reply_markup=_section_kb("debt", actions))


async def show_loans_taken(cb: CallbackQuery) -> None:
    rows = await _fetch(cb, "/finance/loans-taken")
    if rows is None:
        return
    lines, actions = ["📘 <b>Loans taken</b> (you borrowed)\n"], []
    if not rows:
        lines.append("Nothing here yet.")
    for l in rows:
        cur = l.get("currency")
        due = f" · due {l['dueDate']}" if l.get("dueDate") else ""
        start = f" · pays from {l['paymentStartDate'][:7]}" if l.get("paymentStartDate") else ""
        lines.append(f"• {esc(l.get('lenderName'))}: {fmt_money(l.get('remainingAmount'), cur)} left "
                     f"/ {fmt_money(l.get('totalAmount'), cur)}{due}{start}")
        if (l.get("remainingAmount") or 0) > 0 and len(actions) < MAX_ROWS:
            actions.append([(f"💸 Repay {str(l.get('lenderName'))[:18]}", f"fact:loantaken:{l['id']}")])
    await cb.message.edit_text("\n".join(lines), reply_markup=_section_kb("loantaken", actions))


async def show_loans_given(cb: CallbackQuery) -> None:
    rows = await _fetch(cb, "/finance/loans-given")
    if rows is None:
        return
    lines, actions = ["📗 <b>Loans given</b> (owed to you)\n"], []
    if not rows:
        lines.append("Nothing here yet.")
    for l in rows:
        cur = l.get("currency")
        exp = f" · expect {l['expectedReturnDate']}" if l.get("expectedReturnDate") else ""
        lines.append(f"• {esc(l.get('debtorName'))}: {fmt_money(l.get('pendingAmount'), cur)} pending "
                     f"/ {fmt_money(l.get('totalAmount'), cur)}{exp}")
        if (l.get("pendingAmount") or 0) > 0 and len(actions) < MAX_ROWS:
            actions.append([(f"✅ Returned by {str(l.get('debtorName'))[:16]}", f"fact:loangiven:{l['id']}")])
    await cb.message.edit_text("\n".join(lines), reply_markup=_section_kb("loangiven", actions))


async def show_monthly(cb: CallbackQuery) -> None:
    rows = await _fetch(cb, "/finance/monthly-payments")
    if rows is None:
        return
    lines, actions = ["🔁 <b>Subscriptions</b>\n"], []
    if not rows:
        lines.append("Nothing here yet.")
    for m in rows:
        cur = m.get("currency")
        active = "" if m.get("active", True) else " · paused"
        due = f" · day {m['dueDay']}" if m.get("dueDay") else ""
        lines.append(f"• {esc(m.get('name'))}: {fmt_money(m.get('amount'), cur)}{due}{active}")
        if m.get("active", True) and len(actions) < MAX_ROWS:
            actions.append([(f"💸 Pay {str(m.get('name'))[:20]}", f"fact:monthly:{m['id']}")])
    await cb.message.edit_text("\n".join(lines), reply_markup=_section_kb("monthly", actions))


async def show_bank_loans(cb: CallbackQuery) -> None:
    rows = await _fetch(cb, "/finance/bank-loans")
    if rows is None:
        return
    lines = ["🏛 <b>Bank loans</b>\n"]
    if not rows:
        lines.append("Nothing here yet.")
    for b in rows:
        cur = b.get("currency")
        monthly = f" · {fmt_money(b.get('monthlyPayment'), cur)}/mo" if b.get("monthlyPayment") else ""
        end = f" · ends {b['endDate']}" if b.get("endDate") else ""
        lines.append(f"• {esc(b.get('bankName'))} — {esc(b.get('loanName'))}: "
                     f"{fmt_money(b.get('totalAmount'), cur)}{monthly}{end}")
    await cb.message.edit_text("\n".join(lines), reply_markup=_section_kb("bankloan"))


async def show_donations(cb: CallbackQuery) -> None:
    rows = await _fetch(cb, "/finance/donations")
    if rows is None:
        return
    lines = ["🎁 <b>Donations</b>\n"]
    if not rows:
        lines.append("Nothing here yet.")
    for d in rows[:20]:
        cur = d.get("currency")
        who = d.get("displayName") or d.get("recipientName") or "—"
        lines.append(f"• {d.get('donationDate', '')} · {esc(who)}: {fmt_money(d.get('amount'), cur)}")
    await cb.message.edit_text("\n".join(lines), reply_markup=_section_kb("donation"))


async def show_investments(cb: CallbackQuery) -> None:
    rows = await _fetch(cb, "/finance/investments")
    if rows is None:
        return
    lines = ["📈 <b>Investments</b>\n"]
    if not rows:
        lines.append("Nothing here yet.")
    for i in rows[:20]:
        cur = i.get("currency")
        typ = str(i.get("type", "")).replace("_", " ").title()
        lines.append(f"• {esc(i.get('name'))} ({typ}): {fmt_money(i.get('investedAmount'), cur)}")
    await cb.message.edit_text("\n".join(lines), reply_markup=_section_kb("investment"))


# ── action conversation: repay / mark-returned / pay ───────────────────────
KIND_CFG = {
    "debt": {"list": "/finance/debts", "name": "creditorName", "suggest": "remainingAmount",
             "verb": "Repay debt to", "endpoint": "/finance/debts/{id}/repay", "action": "repay"},
    "loantaken": {"list": "/finance/loans-taken", "name": "lenderName", "suggest": "remainingAmount",
                  "verb": "Repay loan from", "endpoint": "/finance/loans-taken/{id}/repay", "action": "repay"},
    "loangiven": {"list": "/finance/loans-given", "name": "debtorName", "suggest": "pendingAmount",
                  "verb": "Mark returned by", "endpoint": "/finance/loans-given/{id}/mark-returned",
                  "action": "markreturned"},
    "monthly": {"list": "/finance/monthly-payments", "name": "name", "suggest": "amount",
                "verb": "Pay", "endpoint": "/finance/monthly-payments/{id}/pay", "action": "pay"},
}


@router.callback_query(F.data.startswith("fact:cancel"))
async def fa_cancel(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    await state.clear()
    await cb.message.edit_text("Cancelled.", reply_markup=_back_kb())


@router.callback_query(F.data.startswith("fact:"))
async def fa_entry(cb: CallbackQuery, state: FSMContext) -> None:
    if not await common.gate(cb):
        return
    await cb.answer()
    _, kind, sid = cb.data.split(":")
    cfg = KIND_CFG[kind]
    rid = int(sid)
    rows = await _fetch(cb, cfg["list"])
    if rows is None:
        return
    rec = _find(rows, rid)
    if rec is None:
        await cb.message.edit_text("That record no longer exists.", reply_markup=_back_kb())
        return
    suggested = rec.get(cfg["suggest"]) or 0
    await state.set_state(FinAction.amount)
    await state.update_data(fa_action=cfg["action"], fa_endpoint=cfg["endpoint"].format(id=rid),
                            fa_currency=rec.get("currency"), fa_name=rec.get(cfg["name"], "?"))
    kb_rows = []
    if suggested and suggested > 0:
        kb_rows.append([(f"Use {fmt_money(suggested, rec.get('currency'))}", "fause")])
        await state.update_data(fa_suggested=suggested)
    kb_rows.append([("✖️ Cancel", "fact:cancel")])
    await cb.message.edit_text(
        f"{cfg['verb']} <b>{esc(rec.get(cfg['name']))}</b>\nSend the amount in {rec.get('currency')}:",
        reply_markup=ikb(kb_rows))


@router.callback_query(StateFilter(FinAction.amount), F.data == "fause")
async def fa_use(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    d = await state.get_data()
    await state.update_data(fa_amount=d.get("fa_suggested"))
    await _fa_source(cb, state)


@router.message(StateFilter(FinAction.amount))
async def fa_amount(message: Message, state: FSMContext) -> None:
    from .transactions import parse_amount
    amt = parse_amount(message.text)
    if amt is None:
        await message.answer("Send a positive number.")
        return
    await state.update_data(fa_amount=amt)
    await _fa_source(message, state)


async def _fa_source(event, state: FSMContext) -> None:
    chat_id = common.chat_id_of(event)
    d = await state.get_data()
    cur = d["fa_currency"]
    try:
        cards = await api.request(chat_id, "GET", "/cards") or []
    except Exception:  # noqa: BLE001
        cards = []
    cards = [c for c in cards if c.get("currency") == cur and c.get("type") != "CASH"]
    await state.update_data(fa_cards=cards)
    rows = [[("💵 Cash", "fasrc:cash")]]
    for c in cards:
        rows.append([(f"💳 {c.get('name', 'Card')} ···{c.get('lastFourDigits', '')}", f"fasrc:card:{c['id']}")])
    rows.append([("✖️ Cancel", "fact:cancel")])
    await state.set_state(FinAction.source)
    await common.show(event, f"Pay from ({cur}):", ikb(rows))


@router.callback_query(StateFilter(FinAction.source), F.data.startswith("fasrc:"))
async def fa_src(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    card_id = None if cb.data == "fasrc:cash" else int(cb.data.split(":")[2])
    await state.update_data(fa_cardId=card_id)
    d = await state.get_data()
    src = "Cash" if card_id is None else next(
        (c.get("name", "Card") for c in d.get("fa_cards", []) if c["id"] == card_id), "Card")
    await state.set_state(FinAction.confirm)
    await cb.message.edit_text(
        f"Confirm:\n\n{esc(d['fa_name'])}\nAmount: <b>{fmt_money(d['fa_amount'], d['fa_currency'])}</b>\n"
        f"From: {esc(src)}",
        reply_markup=ikb([[("✅ Confirm", "faok"), ("✖️ Cancel", "fact:cancel")]]))


@router.callback_query(StateFilter(FinAction.confirm), F.data == "faok")
async def fa_confirm(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    d = await state.get_data()
    card_id = d.get("fa_cardId")
    if d["fa_action"] == "pay":
        payload = {"amount": d["fa_amount"], "paymentDate": _today(),
                   "mode": "CARD" if card_id is not None else "CASH"}
        if card_id is not None:
            payload["cardId"] = card_id
    else:
        payload = {"amount": d["fa_amount"], "paymentDate": _today()}
        if card_id is not None:
            payload["cardId"] = card_id
    try:
        await api.request(cb.message.chat.id, "POST", d["fa_endpoint"], json=payload)
    except api.NeedsLogin:
        await state.clear()
        await cb.message.edit_text("🔒 Session expired. Please log in.", reply_markup=keyboards.login_kb())
        return
    except api.ApiError as exc:
        await state.clear()
        await cb.message.edit_text(f"❌ {esc(exc.message)}", reply_markup=_back_kb())
        return
    except Exception:  # noqa: BLE001
        await state.clear()
        await cb.message.edit_text("❌ Couldn't reach the server.", reply_markup=_back_kb())
        return
    await state.clear()
    await cb.message.edit_text(
        f"✅ Recorded: <b>{fmt_money(d['fa_amount'], d['fa_currency'])}</b> · {esc(d['fa_name'])}.",
        reply_markup=_back_kb())


# ── create (generic wizard) ─────────────────────────────────────────────────
INVESTMENT_TYPES = [("STOCKS", "Stocks"), ("CRYPTO", "Crypto"), ("REAL_ESTATE", "Real estate"),
                    ("BONDS", "Bonds"), ("MUTUAL_FUND", "Mutual fund"), ("GOLD", "Gold"), ("OTHER", "Other")]

CREATE_SECTIONS = {
    "debt": {"title": "New debt", "endpoint": "/finance/debts", "back": "fin:debt",
             "success": "Debt created.", "auto_currency": True, "fields": [
                 {"key": "creditorName", "label": "Creditor (who you owe)", "kind": "text", "required": True},
                 {"key": "totalAmount", "label": "Total amount", "kind": "amount", "required": True},
                 {"key": "borrowedDate", "label": "Borrowed date", "kind": "date", "required": True, "today": True},
                 {"key": "dueDate", "label": "Due date", "kind": "date", "required": False},
                 {"key": "paymentStartDate", "label": "Payments start month", "kind": "month", "required": False},
                 {"key": "description", "label": "Description", "kind": "text", "required": False},
             ]},
    "loangiven": {"title": "New loan given", "endpoint": "/finance/loans-given", "back": "fin:loangiven",
                  "success": "Loan given created.", "auto_currency": True, "fields": [
                      {"key": "debtorName", "label": "Debtor (who owes you)", "kind": "text", "required": True},
                      {"key": "totalAmount", "label": "Amount lent", "kind": "amount", "required": True},
                      {"key": "lentDate", "label": "Lent date", "kind": "date", "required": True, "today": True},
                      {"key": "expectedReturnDate", "label": "Expected return date", "kind": "date", "required": False},
                      {"key": "description", "label": "Description", "kind": "text", "required": False},
                  ]},
    "loantaken": {"title": "New loan taken", "endpoint": "/finance/loans-taken", "back": "fin:loantaken",
                  "success": "Loan taken created.", "auto_currency": True, "fields": [
                      {"key": "lenderName", "label": "Lender (who lent you)", "kind": "text", "required": True},
                      {"key": "totalAmount", "label": "Total amount", "kind": "amount", "required": True},
                      {"key": "borrowedDate", "label": "Borrowed date", "kind": "date", "required": True, "today": True},
                      {"key": "dueDate", "label": "Due date", "kind": "date", "required": False},
                      {"key": "paymentStartDate", "label": "Payments start month", "kind": "month", "required": False},
                      {"key": "description", "label": "Description", "kind": "text", "required": False},
                  ]},
    "bankloan": {"title": "New bank loan", "endpoint": "/finance/bank-loans", "back": "fin:bankloan",
                 "success": "Bank loan created.", "auto_currency": True, "fields": [
                     {"key": "bankName", "label": "Bank name", "kind": "text", "required": True},
                     {"key": "loanName", "label": "Loan name / type", "kind": "text", "required": True},
                     {"key": "totalAmount", "label": "Total amount", "kind": "amount", "required": True},
                     {"key": "monthlyPayment", "label": "Monthly payment", "kind": "amount", "required": False},
                     {"key": "takenDate", "label": "Taken date", "kind": "date", "required": True, "today": True},
                     {"key": "endDate", "label": "End date", "kind": "date", "required": False},
                 ]},
    "monthly": {"title": "New subscription", "endpoint": "/finance/monthly-payments", "back": "fin:monthly",
                "success": "Subscription created.", "auto_currency": True, "fields": [
                    {"key": "name", "label": "Name", "kind": "text", "required": True},
                    {"key": "amount", "label": "Monthly amount", "kind": "amount", "required": True},
                    {"key": "dueDay", "label": "Due day of month", "kind": "int", "required": True, "min": 1, "max": 31},
                    {"key": "description", "label": "Description", "kind": "text", "required": False},
                ]},
    "donation": {"title": "New donation", "endpoint": "/finance/donations", "back": "fin:donation",
                 "success": "Donation created.", "auto_currency": True, "fields": [
                     {"key": "recipientName", "label": "Recipient", "kind": "text", "required": True},
                     {"key": "amount", "label": "Amount", "kind": "amount", "required": True},
                     {"key": "donationDate", "label": "Date", "kind": "date", "required": True, "today": True},
                     {"key": "description", "label": "Description", "kind": "text", "required": False},
                 ]},
    "investment": {"title": "New investment", "endpoint": "/finance/investments", "back": "fin:investment",
                   "success": "Investment created.", "auto_currency": True, "fields": [
                       {"key": "name", "label": "Name", "kind": "text", "required": True},
                       {"key": "type", "label": "Type", "kind": "choice", "required": True, "choices": INVESTMENT_TYPES},
                       {"key": "investedAmount", "label": "Amount invested", "kind": "amount", "required": True},
                       {"key": "broker", "label": "Broker / platform", "kind": "text", "required": False},
                       {"key": "purchaseDate", "label": "Purchase date", "kind": "date", "required": True, "today": True},
                       {"key": "description", "label": "Description", "kind": "text", "required": False},
                   ]},
}


@router.callback_query(F.data.startswith("fcreate:"))
async def create_entry(cb: CallbackQuery, state: FSMContext) -> None:
    if not await common.gate(cb):
        return
    await cb.answer()
    section = cb.data.split(":", 1)[1]
    spec = CREATE_SECTIONS.get(section)
    if not spec:
        await cb.message.edit_text("Unknown section.", reply_markup=_back_kb())
        return
    await wizard.start(cb, state, spec)
