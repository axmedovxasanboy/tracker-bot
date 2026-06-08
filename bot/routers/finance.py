"""Finance: read views (7 sections), money actions (repay/mark-returned/pay), and create."""
import datetime as dt

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from . import wizard
from .. import api, common, keyboards
from ..keyboards import esc, fmt_money, fmt_pct, ikb
from ..session import store
from ..states import FinAction, GoalValue

router = Router()
MAX_ROWS = 10


def _today() -> str:
    return dt.date.today().isoformat()


def _month_now() -> str:
    return dt.date.today().strftime("%Y-%m")


def _find(items, cid):
    return next((c for c in items if c.get("id") == cid), None)


def _menu_kb():
    return ikb([
        [("📕 Debts", "fin:debt"), ("📗 Loans given", "fin:loangiven")],
        [("📘 Loans taken", "fin:loantaken"), ("🏛 Bank loans", "fin:bankloan")],
        [("🔁 Subscriptions", "fin:monthly"), ("🎁 Donations", "fin:donation")],
        [("📈 Investments", "fin:investment"), ("🎯 Savings goals", "fin:savings")],
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
        "investment": show_investments, "savings": show_savings,
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
    plain = [i for i in rows if not i.get("savingsGoal")]
    lines = ["📈 <b>Investments</b>\n"]
    if not plain:
        lines.append("Nothing here yet.")
    for i in plain[:20]:
        cur = i.get("currency")
        typ = esc(str(i.get("type", "")).replace("_", " ").title())
        tag = " · <i>opening</i>" if i.get("openingBalance") else ""
        lines.append(f"• {esc(i.get('name'))} ({typ}): {fmt_money(i.get('investedAmount'), cur)}{tag}")
    await cb.message.edit_text("\n".join(lines), reply_markup=_section_kb("investment"))


async def show_savings(cb: CallbackQuery) -> None:
    rows = await _fetch(cb, "/finance/investments")
    if rows is None:
        return
    goals = [i for i in rows if i.get("savingsGoal")]
    lines, actions = ["🎯 <b>Savings goals</b> · optional, apart from the 4 buckets\n"], []
    if not goals:
        lines.append("No savings goals yet. Tap ➕ Add to start one.")
    for g in goals:
        cur = g.get("currency")
        value = g.get("currentValue")
        if value is None:
            value = g.get("investedAmount")
        tgt = f" / {fmt_money(g.get('targetAmount'), cur)}" if g.get("targetAmount") is not None else ""
        prog = f" · {fmt_pct(g.get('progressPercent'))}" if g.get("progressPercent") is not None else ""
        lines.append(f"• {esc(g.get('name'))}: {fmt_money(value, cur)}{tgt}{prog}")
        if len(actions) < MAX_ROWS:
            actions.append([(f"💰 Add to {str(g.get('name'))[:14]}", f"fact:goalcontrib:{g['id']}"),
                            ("📈 Value", f"goal:value:{g['id']}")])
    await cb.message.edit_text("\n".join(lines), reply_markup=_section_kb("goal", actions))


# ── action conversation: repay / mark-returned / pay ───────────────────────
KIND_CFG = {
    "debt": {"list": "/finance/debts", "name": "creditorName", "suggest": "remainingAmount",
             "verb": "Repay debt to", "endpoint": "/finance/debts/{id}/repay", "action": "repay",
             "markkind": "DEBT"},
    "loantaken": {"list": "/finance/loans-taken", "name": "lenderName", "suggest": "remainingAmount",
                  "verb": "Repay loan from", "endpoint": "/finance/loans-taken/{id}/repay", "action": "repay",
                  "markkind": "PERSONAL_LOAN"},
    "loangiven": {"list": "/finance/loans-given", "name": "debtorName", "suggest": "pendingAmount",
                  "verb": "Mark returned by", "endpoint": "/finance/loans-given/{id}/mark-returned",
                  "action": "markreturned"},
    "monthly": {"list": "/finance/monthly-payments", "name": "name", "suggest": "amount",
                "verb": "Pay", "endpoint": "/finance/monthly-payments/{id}/pay", "action": "pay",
                "markkind": "SUBSCRIPTION"},
    # Savings-goal contribution — reuses the amount→source→confirm flow. No suggested amount
    # (investments have no "remainingAmount" key, so the "Use …" button is skipped).
    "goalcontrib": {"list": "/finance/investments", "name": "name", "suggest": "remainingAmount",
                    "verb": "Contribute to", "endpoint": "/finance/investments/{id}/contribute",
                    "action": "contribute"},
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
                            fa_currency=rec.get("currency"), fa_name=rec.get(cfg["name"], "?"),
                            fa_markkind=cfg.get("markkind"), fa_refid=rid, fa_mark=False)
    kb_rows = []
    if suggested and suggested > 0:
        kb_rows.append([(f"Use {fmt_money(suggested, rec.get('currency'))}", "fause")])
        await state.update_data(fa_suggested=suggested)
    # "Already paid" — mark satisfied for the month with no transaction (debts / loans / subscriptions).
    if cfg.get("markkind"):
        kb_rows.append([("✅ Already paid", "famark")])
    kb_rows.append([("✖️ Cancel", "fact:cancel")])
    await cb.message.edit_text(
        f"{cfg['verb']} <b>{esc(rec.get(cfg['name']))}</b>\nSend the amount in {rec.get('currency')}:",
        reply_markup=ikb(kb_rows))


@router.callback_query(StateFilter(FinAction.amount), F.data == "famark")
async def fa_mark_start(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    await state.update_data(fa_mark=True)
    d = await state.get_data()
    cur = d["fa_currency"]
    kb_rows = []
    sug = d.get("fa_suggested")
    if sug and sug > 0:
        kb_rows.append([(f"Use {fmt_money(sug, cur)}", "fause")])
    kb_rows.append([("✖️ Cancel", "fact:cancel")])
    await cb.message.edit_text(
        f"Mark <b>{esc(d['fa_name'])}</b> as already paid.\n"
        f"Send the amount in {cur} — <i>no transaction will be recorded</i>:",
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
        await message.answer("Send a positive number.")
        return
    await state.update_data(fa_amount=amt)
    await _fa_after_amount(message, state)


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
    # Contributions can be recorded WITHOUT moving money (funds already in the investment account).
    if d.get("fa_action") == "contribute":
        rows.append([("🚫 None — just record (no wallet)", "fasrc:none")])
    rows.append([("✖️ Cancel", "fact:cancel")])
    await state.set_state(FinAction.source)
    await common.show(event, f"Pay from ({cur}):", ikb(rows))


@router.callback_query(StateFilter(FinAction.source), F.data.startswith("fasrc:"))
async def fa_src(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    if cb.data == "fasrc:none":
        await state.update_data(fa_cardId=None, fa_noWallet=True)
        d = await state.get_data()
        await state.set_state(FinAction.confirm)
        await cb.message.edit_text(
            f"Confirm:\n\n{esc(d['fa_name'])}\nAmount: <b>{fmt_money(d['fa_amount'], d['fa_currency'])}</b>\n"
            f"From: None — <i>record only, no money moved</i>",
            reply_markup=ikb([[("✅ Confirm", "faok"), ("✖️ Cancel", "fact:cancel")]]))
        return
    card_id = None if cb.data == "fasrc:cash" else int(cb.data.split(":")[2])
    await state.update_data(fa_cardId=card_id, fa_noWallet=False)
    d = await state.get_data()
    src = "Cash" if card_id is None else next(
        (c.get("name", "Card") for c in d.get("fa_cards", []) if c["id"] == card_id), "Card")
    await state.set_state(FinAction.confirm)
    await cb.message.edit_text(
        f"Confirm:\n\n{esc(d['fa_name'])}\nAmount: <b>{fmt_money(d['fa_amount'], d['fa_currency'])}</b>\n"
        f"From: {esc(src)}",
        reply_markup=ikb([[("✅ Confirm", "faok"), ("✖️ Cancel", "fact:cancel")]]))


async def _fa_mark_confirm(event, state: FSMContext) -> None:
    d = await state.get_data()
    await state.set_state(FinAction.confirm)
    await common.show(
        event,
        f"Mark as <b>already paid</b> (no transaction, no money moved):\n\n"
        f"{esc(d['fa_name'])}\nAmount: <b>{fmt_money(d['fa_amount'], d['fa_currency'])}</b>",
        ikb([[("✅ Confirm", "famarkok"), ("✖️ Cancel", "fact:cancel")]]))


@router.callback_query(StateFilter(FinAction.confirm), F.data == "famarkok")
async def fa_mark_ok(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    d = await state.get_data()
    payload = {"kind": d["fa_markkind"], "refId": d.get("fa_refid"),
               "amount": d["fa_amount"], "currency": d["fa_currency"], "month": _month_now()}
    try:
        await api.request(cb.message.chat.id, "POST", "/finance/mark-paid", json=payload)
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
        f"✅ Marked already paid: <b>{fmt_money(d['fa_amount'], d['fa_currency'])}</b> · {esc(d['fa_name'])}.",
        reply_markup=_back_kb())


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
# Must match the backend InvestmentType enum (STOCKS & CRYPTO were removed — stocks are
# tracked via the STOCK_PURCHASE transaction sub-type / "Stocks" category, not here).
INVESTMENT_TYPES = [("REAL_ESTATE", "Real estate"), ("BONDS", "Bonds"),
                    ("MUTUAL_FUND", "Mutual fund"), ("GOLD", "Gold"), ("OTHER", "Other")]

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
                       {"key": "openingBalance", "kind": "bool", "required": True,
                        "label": "Do you already own this? An opening balance is tracked for net worth only — "
                                 "no money leaves your wallet and it isn't counted in this month's allocation.",
                        "yes_label": "✅ I already own it (opening balance)", "no_label": "🆕 New purchase"},
                       {"key": "broker", "label": "Broker / platform", "kind": "text", "required": False},
                       {"key": "purchaseDate", "label": "Purchase date", "kind": "date", "required": True, "today": True},
                       {"key": "description", "label": "Description", "kind": "text", "required": False},
                   ]},
    "goal": {"title": "New savings goal", "endpoint": "/finance/investments", "back": "fin:savings",
             "success": "Savings goal created.", "auto_currency": True,
             "fixed": {"savingsGoal": True, "type": "OTHER"}, "fields": [
                 {"key": "name", "label": "Goal name (e.g. iPhone, Home)", "kind": "text", "required": True},
                 {"key": "investedAmount", "label": "Amount saved so far", "kind": "amount", "required": True},
                 {"key": "targetAmount", "label": "Target amount", "kind": "amount", "required": False},
                 {"key": "currentValue", "label": "Current value (if grown)", "kind": "amount", "required": False},
                 {"key": "purchaseDate", "label": "Start date", "kind": "date", "required": True, "today": True},
                 {"key": "description", "label": "Notes", "kind": "text", "required": False},
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


# ── savings goal: update current value ──────────────────────────────────────
@router.callback_query(F.data.startswith("goal:value:"))
async def gv_entry(cb: CallbackQuery, state: FSMContext) -> None:
    if not await common.gate(cb):
        return
    await cb.answer()
    gid = int(cb.data.split(":")[2])
    rows = await _fetch(cb, "/finance/investments")
    if rows is None:
        return
    rec = _find(rows, gid)
    if rec is None:
        await cb.message.edit_text("That goal no longer exists.", reply_markup=_back_kb())
        return
    cur = rec.get("currency")
    current = rec.get("currentValue")
    if current is None:
        current = rec.get("investedAmount")
    await state.set_state(GoalValue.amount)
    await state.update_data(gv_id=gid, gv_currency=cur, gv_name=rec.get("name", "?"))
    await cb.message.edit_text(
        f"📈 Update value of <b>{esc(rec.get('name'))}</b>\n"
        f"Current: {fmt_money(current, cur)}\n\nSend the new current value in {cur}:",
        reply_markup=ikb([[("✖️ Cancel", "fact:cancel")]]))


@router.message(StateFilter(GoalValue.amount))
async def gv_amount(message: Message, state: FSMContext) -> None:
    from .transactions import parse_amount
    val = parse_amount(message.text)
    if val is None:
        await message.answer("Send a positive number.")
        return
    d = await state.get_data()
    try:
        await api.request(message.chat.id, "POST", f"/finance/investments/{d['gv_id']}/value",
                          json={"currentValue": val})
    except api.NeedsLogin:
        await state.clear()
        await message.answer("🔒 Session expired. Please log in.", reply_markup=keyboards.login_kb())
        return
    except api.ApiError as exc:
        await state.clear()
        await message.answer(f"❌ {esc(exc.message)}", reply_markup=_back_kb())
        return
    except Exception:  # noqa: BLE001
        await state.clear()
        await message.answer("❌ Couldn't reach the server.", reply_markup=_back_kb())
        return
    await state.clear()
    await message.answer(
        f"✅ Updated <b>{esc(d['gv_name'])}</b> value to {fmt_money(val, d['gv_currency'])}.",
        reply_markup=_back_kb())
