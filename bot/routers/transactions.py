"""Transactions: add (guided), recent + delete, exchange, bulk add."""
import datetime as dt

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from .. import api, common, keyboards
from ..keyboards import esc, fmt_money, ikb
from ..session import store
from ..states import AddTx, Bulk, Exchange

router = Router()
PAGE_SIZE = 6


def _today() -> str:
    return dt.date.today().isoformat()


def parse_amount(text: str):
    t = (text or "").strip().replace(" ", "").replace(",", "")
    try:
        v = float(t)
    except ValueError:
        return None
    return v if v > 0 else None


def _menu_kb():
    return ikb([
        [("➕ Add", "tx:add"), ("📋 Recent", "tx:recent")],
        [("🔁 Exchange", "tx:exchange"), ("📥 Bulk add", "tx:bulk")],
        [("⬅️ Menu", "menu:home")],
    ])


async def show_menu(cb: CallbackQuery) -> None:
    await cb.message.edit_text("💸 <b>Transactions</b>\nChoose an action:", reply_markup=_menu_kb())


@router.callback_query(F.data == "tx:menu")
async def tx_menu(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    await state.clear()
    await show_menu(cb)


@router.callback_query(F.data == "tx:cancel")
async def tx_cancel(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    await state.clear()
    await cb.message.edit_text("Cancelled.", reply_markup=_menu_kb())


# ── Add ──────────────────────────────────────────────────────────────────
@router.callback_query(F.data == "tx:add")
async def add_entry(cb: CallbackQuery, state: FSMContext) -> None:
    if not await common.gate(cb):
        return
    await cb.answer()
    await state.set_state(AddTx.type)
    await cb.message.edit_text("➕ <b>Add transaction</b>\nIncome or expense?", reply_markup=ikb([
        [("📈 Income", "atype:INCOME"), ("📉 Expense", "atype:EXPENSE")],
        [("✖️ Cancel", "tx:cancel")],
    ]))


@router.callback_query(StateFilter(AddTx.type), F.data.startswith("atype:"))
async def add_type(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    t = cb.data.split(":", 1)[1]
    await state.update_data(a_type=t)
    await state.set_state(AddTx.amount)
    cur = store.currency(cb.message.chat.id)
    await cb.message.edit_text(f"➕ <b>Add {t.lower()}</b>\nSend the <b>amount</b> in {cur}:")


def _cat_roots_kb(roots):
    rows = []
    for r in roots:
        cb = f"acatopen:{r['id']}" if r.get("children") else f"acat:{r['id']}"
        rows.append([(r.get("name", "?"), cb)])
    rows.append([("⏭ Skip category", "acatskip")])
    rows.append([("✖️ Cancel", "tx:cancel")])
    return ikb(rows)


@router.message(StateFilter(AddTx.amount))
async def add_amount(message: Message, state: FSMContext) -> None:
    amt = parse_amount(message.text)
    if amt is None:
        await message.answer("Please send a positive number, e.g. 50000.")
        return
    data = await state.get_data()
    try:
        roots = await api.request(message.chat.id, "GET", "/categories", params={"type": data["a_type"]}) or []
    except api.NeedsLogin:
        await state.clear()
        await message.answer("🔒 Session expired. Send /login to continue.")
        return
    except Exception:  # noqa: BLE001
        roots = []
    await state.update_data(a_amount=amt, a_roots=roots)
    await state.set_state(AddTx.category)
    await message.answer("Pick a <b>category</b>:", reply_markup=_cat_roots_kb(roots))


@router.callback_query(StateFilter(AddTx.category), F.data.startswith("acat"))
async def add_cat(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    data = await state.get_data()
    d = cb.data
    if d == "acatskip":
        await state.update_data(a_categoryId=None)
        await _ask_source(cb, state)
    elif d == "acatback":
        await cb.message.edit_text("Pick a <b>category</b>:", reply_markup=_cat_roots_kb(data.get("a_roots", [])))
    elif d.startswith("acatopen:"):
        rid = int(d.split(":")[1])
        root = next((r for r in data.get("a_roots", []) if r["id"] == rid), {})
        rows = [[(f"▫️ Use “{root.get('name', '?')}”", f"acat:{rid}")]]
        for ch in root.get("children", []):
            rows.append([(ch.get("name", "?"), f"acat:{ch['id']}")])
        rows.append([("⬅️ Back", "acatback"), ("✖️ Cancel", "tx:cancel")])
        await cb.message.edit_text("Pick a sub-category:", reply_markup=ikb(rows))
    elif d.startswith("acat:"):
        await state.update_data(a_categoryId=int(d.split(":")[1]))
        await _ask_source(cb, state)


async def _ask_source(cb: CallbackQuery, state: FSMContext) -> None:
    chat_id = cb.message.chat.id
    cur = store.currency(chat_id)
    try:
        cards = await api.request(chat_id, "GET", "/cards") or []
    except Exception:  # noqa: BLE001
        cards = []
    cards = [c for c in cards if c.get("currency") == cur and c.get("type") != "CASH"]
    await state.update_data(a_cards=cards)
    rows = [[("💵 Cash", "asrc:cash")]]
    for c in cards:
        rows.append([(f"💳 {c.get('name', 'Card')} ···{c.get('lastFourDigits', '')}", f"asrc:card:{c['id']}")])
    rows.append([("✖️ Cancel", "tx:cancel")])
    await state.set_state(AddTx.source)
    await cb.message.edit_text(f"Payment source ({cur}):", reply_markup=ikb(rows))


@router.callback_query(StateFilter(AddTx.source), F.data.startswith("asrc:"))
async def add_src(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    await state.update_data(a_cardId=None if cb.data == "asrc:cash" else int(cb.data.split(":")[2]))
    await state.set_state(AddTx.date)
    await cb.message.edit_text("Date? Tap Today or send <code>YYYY-MM-DD</code>:",
                              reply_markup=ikb([[("📅 Today", "adate:today")], [("✖️ Cancel", "tx:cancel")]]))


@router.callback_query(StateFilter(AddTx.date), F.data == "adate:today")
async def add_date_today(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    await state.update_data(a_date=_today())
    await state.set_state(AddTx.desc)
    await cb.message.edit_text("Add a <b>description</b>, or Skip:",
                              reply_markup=ikb([[("⏭ Skip", "adesc:skip")], [("✖️ Cancel", "tx:cancel")]]))


@router.message(StateFilter(AddTx.date))
async def add_date_typed(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    try:
        dt.date.fromisoformat(text)
    except ValueError:
        await message.answer("Send the date as YYYY-MM-DD, e.g. 2026-05-25.")
        return
    await state.update_data(a_date=text)
    await state.set_state(AddTx.desc)
    await message.answer("Add a <b>description</b>, or Skip:",
                         reply_markup=ikb([[("⏭ Skip", "adesc:skip")], [("✖️ Cancel", "tx:cancel")]]))


@router.callback_query(StateFilter(AddTx.desc), F.data == "adesc:skip")
async def add_desc_skip(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    await state.update_data(a_desc=None)
    await _confirm_add(cb, state)


@router.message(StateFilter(AddTx.desc))
async def add_desc_typed(message: Message, state: FSMContext) -> None:
    await state.update_data(a_desc=(message.text or "").strip())
    await _confirm_add(message, state)


def _cat_label(roots, cat_id) -> str:
    if cat_id is None:
        return "—"
    for r in roots:
        if r.get("id") == cat_id:
            return r.get("name", "?")
        for ch in r.get("children", []):
            if ch.get("id") == cat_id:
                return f"{r.get('name', '?')} → {ch.get('name', '?')}"
    return "selected"


async def _confirm_add(event, state: FSMContext) -> None:
    chat_id = common.chat_id_of(event)
    cur = store.currency(chat_id)
    d = await state.get_data()
    src = "Cash" if d.get("a_cardId") is None else next(
        (c.get("name", "Card") for c in d.get("a_cards", []) if c["id"] == d["a_cardId"]), "Card")
    text = (
        "Please confirm:\n\n"
        f"Type: <b>{d['a_type'].title()}</b>\n"
        f"Amount: <b>{fmt_money(d['a_amount'], cur)}</b>\n"
        f"Category: {esc(_cat_label(d.get('a_roots', []), d.get('a_categoryId')))}\n"
        f"Source: {esc(src)}\n"
        f"Date: {d['a_date']}\n"
        f"Description: {esc(d.get('a_desc') or '—')}"
    )
    await state.set_state(AddTx.confirm)
    await common.show(event, text, ikb([[("✅ Confirm", "aok"), ("✖️ Cancel", "tx:cancel")]]))


@router.callback_query(StateFilter(AddTx.confirm), F.data == "aok")
async def add_confirm(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    chat_id = cb.message.chat.id
    cur = store.currency(chat_id)
    d = await state.get_data()
    payload = {
        "type": d["a_type"], "amount": d["a_amount"], "currency": cur, "transactionDate": d["a_date"],
        "subType": "REGULAR_INCOME" if d["a_type"] == "INCOME" else "REGULAR_EXPENSE",
        "cashAmount": d["a_amount"] if d.get("a_cardId") is None else 0,
    }
    if d.get("a_cardId") is not None:
        payload["cardId"] = d["a_cardId"]
    if d.get("a_categoryId") is not None:
        payload["categoryId"] = d["a_categoryId"]
    if d.get("a_desc"):
        payload["description"] = d["a_desc"]
    try:
        await api.request(chat_id, "POST", "/transactions", json=payload)
    except api.NeedsLogin:
        await state.clear()
        await cb.message.edit_text("🔒 Session expired. Please log in.", reply_markup=keyboards.login_kb())
        return
    except api.ApiError as exc:
        await state.clear()
        await cb.message.edit_text(f"❌ {esc(exc.message)}", reply_markup=_menu_kb())
        return
    except Exception:  # noqa: BLE001
        await state.clear()
        await cb.message.edit_text("❌ Couldn't reach the server.", reply_markup=_menu_kb())
        return
    await state.clear()
    await cb.message.edit_text(
        f"✅ {payload['type'].title()} of <b>{fmt_money(payload['amount'], cur)}</b> saved.", reply_markup=_menu_kb())


# ── Recent + view + delete ─────────────────────────────────────────────────
@router.callback_query((F.data == "tx:recent") | (F.data.startswith("txpage:")))
async def show_recent(cb: CallbackQuery) -> None:
    await cb.answer()
    if not await common.gate(cb):
        return
    page = int(cb.data.split(":")[1]) if cb.data.startswith("txpage:") else 0
    chat_id = cb.message.chat.id
    cur = store.currency(chat_id)
    try:
        data = await api.request(chat_id, "GET", "/transactions", params={
            "currency": cur, "page": page, "size": PAGE_SIZE, "sortBy": "transactionDate", "sortDir": "desc"})
    except api.NeedsLogin:
        await cb.message.edit_text("🔒 Session expired. Please log in.", reply_markup=keyboards.login_kb())
        return
    except Exception:  # noqa: BLE001
        await cb.message.edit_text("❌ Couldn't load transactions.", reply_markup=_menu_kb())
        return
    content = (data or {}).get("content", [])
    total_pages = max(1, (data or {}).get("totalPages", 1))
    if not content:
        await cb.message.edit_text("No transactions yet.", reply_markup=_menu_kb())
        return
    rows = []
    for t in content:
        sign = "＋" if t.get("type") == "INCOME" else "－"
        label = f"{t.get('transactionDate', '')} {sign}{fmt_money(t.get('amount'), cur)}"
        if t.get("description"):
            label += f" · {t['description'][:18]}"
        rows.append([(label[:60], f"txview:{t['id']}")])
    nav = []
    if page > 0:
        nav.append(("◀️", f"txpage:{page - 1}"))
    nav.append((f"{page + 1}/{total_pages}", "noop"))
    if page + 1 < total_pages:
        nav.append(("▶️", f"txpage:{page + 1}"))
    rows.append(nav)
    rows.append([("⬅️ Back", "tx:menu")])
    await cb.message.edit_text(f"📋 <b>Recent</b> · {cur}", reply_markup=ikb(rows))


@router.callback_query(F.data == "noop")
async def noop(cb: CallbackQuery) -> None:
    await cb.answer()


@router.callback_query(F.data.startswith("txview:"))
async def show_view(cb: CallbackQuery) -> None:
    await cb.answer()
    if not await common.gate(cb):
        return
    tid = int(cb.data.split(":")[1])
    try:
        t = await api.request(cb.message.chat.id, "GET", f"/transactions/{tid}")
    except api.NeedsLogin:
        await cb.message.edit_text("🔒 Session expired. Please log in.", reply_markup=keyboards.login_kb())
        return
    except Exception:  # noqa: BLE001
        await cb.message.edit_text("❌ Couldn't load it.", reply_markup=_menu_kb())
        return
    cur = t.get("currency", "")
    category = (t.get("category") or {}).get("name") or "—"
    card = (t.get("card") or {}).get("name") or "Cash"
    text = (
        f"🧾 <b>Transaction #{tid}</b>\n"
        f"{str(t.get('type', '')).title()} · <b>{fmt_money(t.get('amount'), cur)}</b>\n"
        f"Date: {t.get('transactionDate', '—')}\n"
        f"Category: {esc(category)}\nSource: {esc(card)}\n"
        f"Description: {esc(t.get('description') or '—')}\nNote: {esc(t.get('note') or '—')}"
    )
    await cb.message.edit_text(text, reply_markup=ikb([
        [("🗑 Delete", f"txdel:{tid}")], [("⬅️ Back", "txpage:0")]]))


@router.callback_query(F.data.startswith("txdel:"))
async def ask_delete(cb: CallbackQuery) -> None:
    await cb.answer()
    tid = int(cb.data.split(":")[1])
    await cb.message.edit_text(f"Delete transaction #{tid}? This can't be undone.", reply_markup=ikb([
        [("✅ Yes, delete", f"txdelok:{tid}"), ("✖️ No", f"txview:{tid}")]]))


@router.callback_query(F.data.startswith("txdelok:"))
async def do_delete(cb: CallbackQuery) -> None:
    await cb.answer()
    if not await common.gate(cb):
        return
    tid = int(cb.data.split(":")[1])
    try:
        await api.request(cb.message.chat.id, "DELETE", f"/transactions/{tid}")
    except api.NeedsLogin:
        await cb.message.edit_text("🔒 Session expired. Please log in.", reply_markup=keyboards.login_kb())
        return
    except api.ApiError as exc:
        await cb.message.edit_text(f"❌ {esc(exc.message)}", reply_markup=_menu_kb())
        return
    except Exception:  # noqa: BLE001
        await cb.message.edit_text("❌ Couldn't reach the server.", reply_markup=_menu_kb())
        return
    await show_recent(cb)


# ── Exchange ─────────────────────────────────────────────────────────────
def _wallet_kb(cards, prefix: str):
    rows = [[("💵 Cash", f"{prefix}:cash")]]
    for c in cards:
        rows.append([(f"💳 {c.get('name', 'Card')} ···{c.get('lastFourDigits', '')} ({c.get('currency')})",
                     f"{prefix}:card:{c['id']}")])
    rows.append([("✖️ Cancel", "tx:cancel")])
    return ikb(rows)


@router.callback_query(F.data == "tx:exchange")
async def ex_entry(cb: CallbackQuery, state: FSMContext) -> None:
    if not await common.gate(cb):
        return
    await cb.answer()
    try:
        cards = await api.request(cb.message.chat.id, "GET", "/cards") or []
    except api.NeedsLogin:
        await cb.message.edit_text("🔒 Session expired. Please log in.", reply_markup=keyboards.login_kb())
        return
    except Exception:  # noqa: BLE001
        cards = []
    cards = [c for c in cards if c.get("type") != "CASH"]
    await state.update_data(x_cards=cards)
    await state.set_state(Exchange.src)
    await cb.message.edit_text("🔁 <b>Exchange</b>\nFrom where?", reply_markup=_wallet_kb(cards, "exfrom"))


@router.callback_query(StateFilter(Exchange.src), F.data.startswith("exfrom:"))
async def ex_from(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    d = await state.get_data()
    if cb.data == "exfrom:cash":
        await state.update_data(x_fromCardId=None, x_fromCurrency=store.currency(cb.message.chat.id))
    else:
        cid = int(cb.data.split(":")[2])
        cur = next((c.get("currency") for c in d.get("x_cards", []) if c["id"] == cid), None)
        await state.update_data(x_fromCardId=cid, x_fromCurrency=cur)
    nd = await state.get_data()
    await state.set_state(Exchange.src_amt)
    await cb.message.edit_text(f"Amount to <b>send</b> ({nd['x_fromCurrency']}):")


@router.message(StateFilter(Exchange.src_amt))
async def ex_from_amt(message: Message, state: FSMContext) -> None:
    amt = parse_amount(message.text)
    if amt is None:
        await message.answer("Send a positive number.")
        return
    await state.update_data(x_fromAmount=amt)
    d = await state.get_data()
    await state.set_state(Exchange.dst)
    await message.answer("To where?", reply_markup=_wallet_kb(d.get("x_cards", []), "exto"))


@router.callback_query(StateFilter(Exchange.dst), F.data.startswith("exto:"))
async def ex_to(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    d = await state.get_data()
    if cb.data == "exto:cash":
        await state.update_data(x_toCardId=None, x_toCurrency=store.currency(cb.message.chat.id))
    else:
        cid = int(cb.data.split(":")[2])
        cur = next((c.get("currency") for c in d.get("x_cards", []) if c["id"] == cid), None)
        await state.update_data(x_toCardId=cid, x_toCurrency=cur)
    nd = await state.get_data()
    await state.set_state(Exchange.dst_amt)
    await cb.message.edit_text(f"Amount to <b>receive</b> ({nd['x_toCurrency']}):")


@router.message(StateFilter(Exchange.dst_amt))
async def ex_to_amt(message: Message, state: FSMContext) -> None:
    amt = parse_amount(message.text)
    if amt is None:
        await message.answer("Send a positive number.")
        return
    await state.update_data(x_toAmount=amt)
    d = await state.get_data()
    fr = "Cash" if d.get("x_fromCardId") is None else next(
        (c.get("name", "Card") for c in d.get("x_cards", []) if c["id"] == d["x_fromCardId"]), "Card")
    to = "Cash" if d.get("x_toCardId") is None else next(
        (c.get("name", "Card") for c in d.get("x_cards", []) if c["id"] == d["x_toCardId"]), "Card")
    await state.set_state(Exchange.confirm)
    await message.answer(
        "🔁 Confirm exchange:\n\n"
        f"Send: <b>{fmt_money(d['x_fromAmount'], d['x_fromCurrency'])}</b> from {esc(fr)}\n"
        f"Receive: <b>{fmt_money(d['x_toAmount'], d['x_toCurrency'])}</b> to {esc(to)}",
        reply_markup=ikb([[("✅ Confirm", "exok"), ("✖️ Cancel", "tx:cancel")]]))


@router.callback_query(StateFilter(Exchange.confirm), F.data == "exok")
async def ex_confirm(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    d = await state.get_data()
    payload = {
        "fromCardId": d.get("x_fromCardId"), "toCardId": d.get("x_toCardId"),
        "fromAmount": d["x_fromAmount"], "toAmount": d["x_toAmount"],
        "fromCurrency": d["x_fromCurrency"], "toCurrency": d["x_toCurrency"],
        "transactionDate": _today(),
    }
    try:
        await api.request(cb.message.chat.id, "POST", "/transactions/exchange", json=payload)
    except api.NeedsLogin:
        await state.clear()
        await cb.message.edit_text("🔒 Session expired. Please log in.", reply_markup=keyboards.login_kb())
        return
    except api.ApiError as exc:
        await state.clear()
        await cb.message.edit_text(f"❌ {esc(exc.message)}", reply_markup=_menu_kb())
        return
    except Exception:  # noqa: BLE001
        await state.clear()
        await cb.message.edit_text("❌ Couldn't reach the server.", reply_markup=_menu_kb())
        return
    await state.clear()
    await cb.message.edit_text("✅ Exchange recorded.", reply_markup=_menu_kb())


# ── Bulk add ─────────────────────────────────────────────────────────────
@router.callback_query(F.data == "tx:bulk")
async def bulk_entry(cb: CallbackQuery, state: FSMContext) -> None:
    if not await common.gate(cb):
        return
    await cb.answer()
    await state.set_state(Bulk.type)
    await cb.message.edit_text("📥 <b>Bulk add</b>\nAll of one type — income or expense?", reply_markup=ikb([
        [("📈 Income", "btype:INCOME"), ("📉 Expense", "btype:EXPENSE")],
        [("✖️ Cancel", "tx:cancel")],
    ]))


@router.callback_query(StateFilter(Bulk.type), F.data.startswith("btype:"))
async def bulk_type(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    await state.update_data(b_type=cb.data.split(":", 1)[1])
    chat_id = cb.message.chat.id
    cur = store.currency(chat_id)
    try:
        cards = await api.request(chat_id, "GET", "/cards") or []
    except Exception:  # noqa: BLE001
        cards = []
    cards = [c for c in cards if c.get("currency") == cur and c.get("type") != "CASH"]
    rows = [[("💵 Cash", "bsrc:cash")]]
    for c in cards:
        rows.append([(f"💳 {c.get('name', 'Card')} ···{c.get('lastFourDigits', '')}", f"bsrc:card:{c['id']}")])
    rows.append([("✖️ Cancel", "tx:cancel")])
    await state.set_state(Bulk.source)
    await cb.message.edit_text(f"Payment source for all ({cur}):", reply_markup=ikb(rows))


@router.callback_query(StateFilter(Bulk.source), F.data.startswith("bsrc:"))
async def bulk_src(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    await state.update_data(b_cardId=None if cb.data == "bsrc:cash" else int(cb.data.split(":")[2]))
    await state.set_state(Bulk.lines)
    await cb.message.edit_text(
        "Send the lines — one per line: <code>amount description</code>\n\n"
        "Example:\n<code>50000 lunch\n12000 bus\n300000 rent</code>")


@router.message(StateFilter(Bulk.lines))
async def bulk_lines(message: Message, state: FSMContext) -> None:
    chat_id = message.chat.id
    cur = store.currency(chat_id)
    d = await state.get_data()
    sub = "REGULAR_INCOME" if d["b_type"] == "INCOME" else "REGULAR_EXPENSE"
    card_id = d.get("b_cardId")
    items, skipped = [], 0
    for line in (message.text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        amt = parse_amount(parts[0])
        if amt is None:
            skipped += 1
            continue
        tx = {"type": d["b_type"], "amount": amt, "currency": cur, "transactionDate": _today(),
              "subType": sub, "cashAmount": amt if card_id is None else 0}
        if card_id is not None:
            tx["cardId"] = card_id
        if len(parts) > 1 and parts[1].strip():
            tx["description"] = parts[1].strip()
        items.append(tx)
    if not items:
        await message.answer("No valid lines found. Each line must start with an amount.")
        return
    try:
        await api.request(chat_id, "POST", "/transactions/bulk", json={"cardId": card_id, "transactions": items})
    except api.NeedsLogin:
        await state.clear()
        await message.answer("🔒 Session expired. Please log in.", reply_markup=keyboards.login_kb())
        return
    except api.ApiError as exc:
        await state.clear()
        await message.answer(f"❌ {esc(exc.message)}", reply_markup=_menu_kb())
        return
    except Exception:  # noqa: BLE001
        await state.clear()
        await message.answer("❌ Couldn't reach the server.", reply_markup=_menu_kb())
        return
    await state.clear()
    note = f" (skipped {skipped} invalid)" if skipped else ""
    await message.answer(f"✅ Added {len(items)} transaction(s){note}.", reply_markup=_menu_kb())
