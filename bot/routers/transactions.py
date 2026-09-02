"""Transactions: add (guided), recent + delete."""
import datetime as dt

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from .. import api, common, keyboards
from ..config import CURRENCY
from ..i18n import cat_name, t
from ..keyboards import esc, fmt_money, ikb
from ..states import AddTx

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


def _menu_kb(chat_id: int):
    return ikb([
        [(t(chat_id, "common.add"), "tx:add"), (t(chat_id, "tx.recentBtn"), "tx:recent")],
        [(t(chat_id, "common.menu"), "menu:home")],
    ])


async def show_menu(cb: CallbackQuery) -> None:
    chat_id = cb.message.chat.id
    await cb.message.edit_text(t(chat_id, "tx.menuTitle"), reply_markup=_menu_kb(chat_id))


@router.callback_query(F.data == "tx:menu")
async def tx_menu(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    await state.clear()
    await show_menu(cb)


@router.callback_query(F.data == "tx:cancel")
async def tx_cancel(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    chat_id = cb.message.chat.id
    await state.clear()
    await cb.message.edit_text(t(chat_id, "common.cancelled"), reply_markup=_menu_kb(chat_id))


# ── Add ──────────────────────────────────────────────────────────────────
@router.callback_query(F.data == "tx:add")
async def add_entry(cb: CallbackQuery, state: FSMContext) -> None:
    if not await common.gate(cb):
        return
    await cb.answer()
    if not await common.stable_income_set(cb):
        return
    chat_id = cb.message.chat.id
    await state.set_state(AddTx.type)
    await cb.message.edit_text(
        f"{t(chat_id, 'tx.addTitle')}\n{t(chat_id, 'tx.incomeOrExpense')}", reply_markup=ikb([
        [(t(chat_id, "tx.income"), "atype:INCOME"), (t(chat_id, "tx.expense"), "atype:EXPENSE")],
        [(t(chat_id, "common.cancel"), "tx:cancel")],
    ]))


@router.callback_query(StateFilter(AddTx.type), F.data.startswith("atype:"))
async def add_type(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    chat_id = cb.message.chat.id
    a_type = cb.data.split(":", 1)[1]
    await state.update_data(a_type=a_type)
    await state.set_state(AddTx.amount)
    type_key = "common.typeIncome" if a_type == "INCOME" else "common.typeExpense"
    await cb.message.edit_text(t(chat_id, "tx.addHeader", type=t(chat_id, type_key).lower(), currency=CURRENCY))


def _cat_roots_kb(chat_id: int, roots):
    rows = []
    for r in roots:
        cb = f"acatopen:{r['id']}" if r.get("children") else f"acat:{r['id']}"
        rows.append([(cat_name(chat_id, r), cb)])
    rows.append([(t(chat_id, "tx.skipCategory"), "acatskip")])
    rows.append([(t(chat_id, "common.cancel"), "tx:cancel")])
    return ikb(rows)


@router.message(StateFilter(AddTx.amount))
async def add_amount(message: Message, state: FSMContext) -> None:
    chat_id = message.chat.id
    amt = parse_amount(message.text)
    if amt is None:
        await message.answer(t(chat_id, "tx.positiveNumber"))
        return
    data = await state.get_data()
    try:
        roots = await api.request(chat_id, "GET", "/categories", params={"type": data["a_type"]}) or []
    except api.NeedsLogin:
        await state.clear()
        await message.answer(t(chat_id, "tx.sessionExpiredShort"))
        return
    except Exception:  # noqa: BLE001
        roots = []
    await state.update_data(a_amount=amt, a_roots=roots)
    await state.set_state(AddTx.category)
    await message.answer(t(chat_id, "tx.pickCategory"), reply_markup=_cat_roots_kb(chat_id, roots))


@router.callback_query(StateFilter(AddTx.category), F.data.startswith("acat"))
async def add_cat(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    chat_id = cb.message.chat.id
    data = await state.get_data()
    d = cb.data
    if d == "acatskip":
        await state.update_data(a_categoryId=None)
        await _ask_subtype(cb, state)
    elif d == "acatback":
        await cb.message.edit_text(t(chat_id, "tx.pickCategory"), reply_markup=_cat_roots_kb(chat_id, data.get("a_roots", [])))
    elif d.startswith("acatopen:"):
        rid = int(d.split(":")[1])
        root = next((r for r in data.get("a_roots", []) if r["id"] == rid), {})
        rows = [[(t(chat_id, "tx.useCategory", name=cat_name(chat_id, root)), f"acat:{rid}")]]
        for ch in root.get("children", []):
            rows.append([(cat_name(chat_id, ch), f"acat:{ch['id']}")])
        rows.append([(t(chat_id, "common.back"), "acatback"), (t(chat_id, "common.cancel"), "tx:cancel")])
        await cb.message.edit_text(t(chat_id, "tx.pickSubCategory"), reply_markup=ikb(rows))
    elif d.startswith("acat:"):
        await state.update_data(a_categoryId=int(d.split(":")[1]))
        await _ask_subtype(cb, state)


# Only EXPENSE sub-types are offered: the four that fund an allocation bucket, plus a plain
# expense. Loan sub-types are deliberately absent — they auto-create finance records that need
# a counterparty the add flow never asks for; the Finance section has dedicated flows for those.
EXPENSE_SUBTYPES = [
    ("REGULAR_EXPENSE", "tx.kindRegular"),
    ("DONATION", "tx.kindDonation"),
    ("EMERGENCY_CONTRIBUTION", "tx.kindEmergency"),
    ("INVESTMENT", "tx.kindInvestment"),
    ("STOCK_PURCHASE", "tx.kindStocks"),
]
SUBTYPE_KEY = {code: key for code, key in EXPENSE_SUBTYPES}


def _subtype_kb(chat_id: int):
    rows = [[(t(chat_id, key), f"asub:{code}")] for code, key in EXPENSE_SUBTYPES]
    rows.append([(t(chat_id, "common.cancel"), "tx:cancel")])
    return ikb(rows)


async def _ask_subtype(event, state: FSMContext) -> None:
    """Income has no allocation bucket, so it skips straight to the source step."""
    d = await state.get_data()
    if d.get("a_type") != "EXPENSE":
        await state.update_data(a_subType="REGULAR_INCOME")
        await _ask_source(event, state)
        return
    chat_id = common.chat_id_of(event)
    await state.set_state(AddTx.subtype)
    await common.show(event, t(chat_id, "tx.whatKind"), reply_markup=_subtype_kb(chat_id))


@router.callback_query(StateFilter(AddTx.subtype), F.data.startswith("asub:"))
async def add_subtype(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    await state.update_data(a_subType=cb.data.split(":", 1)[1])
    await _ask_source(cb, state)


async def _ask_source(cb: CallbackQuery, state: FSMContext) -> None:
    chat_id = cb.message.chat.id
    try:
        cards = await api.request(chat_id, "GET", "/cards") or []
    except Exception:  # noqa: BLE001
        cards = []
    cards = [c for c in cards if c.get("currency") == CURRENCY and c.get("type") != "CASH"]
    await state.update_data(a_cards=cards)
    rows = [[(t(chat_id, "common.cashBtn"), "asrc:cash")]]
    for c in cards:
        rows.append([(f"💳 {c.get('name', 'Card')} ···{c.get('lastFourDigits', '')}", f"asrc:card:{c['id']}")])
    rows.append([(t(chat_id, "common.cancel"), "tx:cancel")])
    await state.set_state(AddTx.source)
    await cb.message.edit_text(t(chat_id, "tx.paymentSource", currency=CURRENCY), reply_markup=ikb(rows))


@router.callback_query(StateFilter(AddTx.source), F.data.startswith("asrc:"))
async def add_src(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    chat_id = cb.message.chat.id
    await state.update_data(a_cardId=None if cb.data == "asrc:cash" else int(cb.data.split(":")[2]))
    await state.set_state(AddTx.date)
    await cb.message.edit_text(t(chat_id, "tx.dateHeader"),
                              reply_markup=ikb([[(t(chat_id, "common.today"), "adate:today")], [(t(chat_id, "common.cancel"), "tx:cancel")]]))


@router.callback_query(StateFilter(AddTx.date), F.data == "adate:today")
async def add_date_today(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    chat_id = cb.message.chat.id
    await state.update_data(a_date=_today())
    await state.set_state(AddTx.desc)
    await cb.message.edit_text(t(chat_id, "tx.addDescription"),
                              reply_markup=ikb([[(t(chat_id, "common.skip"), "adesc:skip")], [(t(chat_id, "common.cancel"), "tx:cancel")]]))


@router.message(StateFilter(AddTx.date))
async def add_date_typed(message: Message, state: FSMContext) -> None:
    chat_id = message.chat.id
    text = (message.text or "").strip()
    try:
        dt.date.fromisoformat(text)
    except ValueError:
        await message.answer(t(chat_id, "tx.sendDateFormat"))
        return
    await state.update_data(a_date=text)
    await state.set_state(AddTx.desc)
    await message.answer(t(chat_id, "tx.addDescription"),
                         reply_markup=ikb([[(t(chat_id, "common.skip"), "adesc:skip")], [(t(chat_id, "common.cancel"), "tx:cancel")]]))


@router.callback_query(StateFilter(AddTx.desc), F.data == "adesc:skip")
async def add_desc_skip(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    await state.update_data(a_desc=None)
    await _confirm_add(cb, state)


@router.message(StateFilter(AddTx.desc))
async def add_desc_typed(message: Message, state: FSMContext) -> None:
    await state.update_data(a_desc=(message.text or "").strip())
    await _confirm_add(message, state)


async def _allocation_preview(chat_id: int, sub_type, amount, date):
    """Ask the backend what this draft transaction would do to the allocation.

    The sub-type to bucket routing lives server-side, so the bot can't promise a bucket the
    accounting wouldn't credit. Returns None on any failure — the preview is a nicety and
    must never block recording a transaction.
    """
    if not sub_type:
        return None
    try:
        return await api.request(
            chat_id, "POST", f"/overview/allocation-preview?currency={CURRENCY}",
            json={"subType": sub_type, "amount": amount, "transactionDate": date})
    except Exception:  # noqa: BLE001
        return None


def _format_preview(chat_id: int, p) -> str:
    """Render a preview payload as a confirm-screen block. Empty string when not applicable."""
    if not p or not p.get("applicable"):
        return ""
    label = esc(str(p.get("label") or ""))
    if p.get("bucketNotRecommended"):
        return f"\n\n{t(chat_id, 'alloc.countsToward', label=label)}\n{t(chat_id, 'alloc.notRequired')}"
    return (
        f"\n\n{t(chat_id, 'alloc.countsToward', label=label)}\n"
        f"{t(chat_id, 'alloc.target')}: {fmt_money(p.get('recommended'))}\n"
        f"{t(chat_id, 'alloc.paidSoFar')}: {fmt_money(p.get('paidBefore'))}\n"
        f"{t(chat_id, 'alloc.afterThis')}: <b>{fmt_money(p.get('paidAfter'))}</b>\n"
        f"<i>{esc(str(p.get('message') or ''))}</i>"
    )


def _cat_label(chat_id: int, roots, cat_id) -> str:
    if cat_id is None:
        return t(chat_id, "common.none")
    for r in roots:
        if r.get("id") == cat_id:
            return cat_name(chat_id, r)
        for ch in r.get("children", []):
            if ch.get("id") == cat_id:
                return f"{cat_name(chat_id, r)} → {cat_name(chat_id, ch)}"
    return t(chat_id, "tx.selected")


async def _confirm_add(event, state: FSMContext) -> None:
    chat_id = common.chat_id_of(event)
    d = await state.get_data()
    src = t(chat_id, "common.cash") if d.get("a_cardId") is None else next(
        (c.get("name", "Card") for c in d.get("a_cards", []) if c["id"] == d["a_cardId"]), "Card")
    sub = d.get("a_subType")
    type_key = "common.typeIncome" if d["a_type"] == "INCOME" else "common.typeExpense"
    sub_line = ""
    if d.get("a_type") == "EXPENSE":
        kind_label = t(chat_id, SUBTYPE_KEY[sub]) if sub in SUBTYPE_KEY else t(chat_id, "common.none")
        sub_line = f"{t(chat_id, 'tx.fieldKind')}: {esc(kind_label)}\n"
    text = (
        f"{t(chat_id, 'tx.confirmPlease')}\n\n"
        f"{t(chat_id, 'tx.fieldType')}: <b>{t(chat_id, type_key)}</b>\n"
        f"{t(chat_id, 'tx.fieldAmount')}: <b>{fmt_money(d['a_amount'])}</b>\n"
        f"{t(chat_id, 'tx.fieldCategory')}: {esc(_cat_label(chat_id, d.get('a_roots', []), d.get('a_categoryId')))}\n"
        f"{sub_line}"
        f"{t(chat_id, 'tx.fieldSource')}: {esc(src)}\n"
        f"{t(chat_id, 'tx.fieldDate')}: {d['a_date']}\n"
        f"{t(chat_id, 'tx.fieldDescription')}: {esc(d.get('a_desc') or t(chat_id, 'common.none'))}"
    )
    text += _format_preview(chat_id, await _allocation_preview(chat_id, sub, d["a_amount"], d["a_date"]))
    await state.set_state(AddTx.confirm)
    await common.show(event, text, ikb([[(t(chat_id, "common.confirm"), "aok"), (t(chat_id, "common.cancel"), "tx:cancel")]]))


@router.callback_query(StateFilter(AddTx.confirm), F.data == "aok")
async def add_confirm(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    chat_id = cb.message.chat.id
    d = await state.get_data()
    payload = {
        "type": d["a_type"], "amount": d["a_amount"], "currency": CURRENCY, "transactionDate": d["a_date"],
        "subType": d.get("a_subType") or ("REGULAR_INCOME" if d["a_type"] == "INCOME" else "REGULAR_EXPENSE"),
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
        await cb.message.edit_text(t(chat_id, "common.sessionExpired"), reply_markup=keyboards.login_kb(chat_id))
        return
    except api.ApiError as exc:
        await state.clear()
        await cb.message.edit_text(f"❌ {esc(exc.message)}", reply_markup=_menu_kb(chat_id))
        return
    except Exception:  # noqa: BLE001
        await state.clear()
        await cb.message.edit_text(t(chat_id, "common.serverUnreachable"), reply_markup=_menu_kb(chat_id))
        return
    await state.clear()
    summary = ""
    after = await _allocation_preview(chat_id, payload["subType"], 0, payload["transactionDate"])
    if after and after.get("applicable") and not after.get("bucketNotRecommended"):
        remaining = after.get("remainingAfter") or 0
        summary = (
            "\n\n" + t(chat_id, "tx.savedProgressHeader", label=esc(str(after.get('label'))),
                       paid=fmt_money(after.get('paidBefore')), target=fmt_money(after.get('recommended')))
            + ("\n" + t(chat_id, "alloc.stillToGo", amount=fmt_money(remaining)) if float(remaining) > 0
               else "\n" + t(chat_id, "alloc.fullyCovered"))
        )
    type_key = "common.typeIncome" if payload["type"] == "INCOME" else "common.typeExpense"
    await cb.message.edit_text(
        t(chat_id, "tx.savedOk", type=t(chat_id, type_key), amount=fmt_money(payload['amount'])) + summary,
        reply_markup=_menu_kb(chat_id))


# ── Recent + view + delete ─────────────────────────────────────────────────
@router.callback_query((F.data == "tx:recent") | (F.data.startswith("txpage:")))
async def show_recent(cb: CallbackQuery) -> None:
    await cb.answer()
    if not await common.gate(cb):
        return
    chat_id = cb.message.chat.id
    page = int(cb.data.split(":")[1]) if cb.data.startswith("txpage:") else 0
    try:
        data = await api.request(chat_id, "GET", "/transactions", params={
            "currency": CURRENCY, "page": page, "size": PAGE_SIZE, "sortBy": "transactionDate", "sortDir": "desc"})
    except api.NeedsLogin:
        await cb.message.edit_text(t(chat_id, "common.sessionExpired"), reply_markup=keyboards.login_kb(chat_id))
        return
    except Exception:  # noqa: BLE001
        await cb.message.edit_text(t(chat_id, "tx.loadError"), reply_markup=_menu_kb(chat_id))
        return
    content = (data or {}).get("content", [])
    total_pages = max(1, (data or {}).get("totalPages", 1))
    if not content:
        await cb.message.edit_text(t(chat_id, "tx.noTransactionsYet"), reply_markup=_menu_kb(chat_id))
        return
    rows = []
    for tx in content:
        sign = "＋" if tx.get("type") == "INCOME" else "－"
        label = f"{tx.get('transactionDate', '')} {sign}{fmt_money(tx.get('amount'))}"
        if tx.get("description"):
            label += f" · {tx['description'][:18]}"
        rows.append([(label[:60], f"txview:{tx['id']}")])
    nav = []
    if page > 0:
        nav.append(("◀️", f"txpage:{page - 1}"))
    nav.append((f"{page + 1}/{total_pages}", "noop"))
    if page + 1 < total_pages:
        nav.append(("▶️", f"txpage:{page + 1}"))
    rows.append(nav)
    rows.append([(t(chat_id, "common.back"), "tx:menu")])
    await cb.message.edit_text(t(chat_id, "tx.recentTitle", currency=CURRENCY), reply_markup=ikb(rows))


@router.callback_query(F.data == "noop")
async def noop(cb: CallbackQuery) -> None:
    await cb.answer()


@router.callback_query(F.data.startswith("txview:"))
async def show_view(cb: CallbackQuery) -> None:
    await cb.answer()
    if not await common.gate(cb):
        return
    chat_id = cb.message.chat.id
    tid = int(cb.data.split(":")[1])
    try:
        tx = await api.request(chat_id, "GET", f"/transactions/{tid}")
    except api.NeedsLogin:
        await cb.message.edit_text(t(chat_id, "common.sessionExpired"), reply_markup=keyboards.login_kb(chat_id))
        return
    except Exception:  # noqa: BLE001
        await cb.message.edit_text(t(chat_id, "tx.viewLoadError"), reply_markup=_menu_kb(chat_id))
        return
    category = cat_name(chat_id, tx.get("category"))
    card = (tx.get("card") or {}).get("name") or t(chat_id, "common.cash")
    type_key = "common.typeIncome" if tx.get("type") == "INCOME" else "common.typeExpense"
    text = (
        f"{t(chat_id, 'tx.txHeader', id=tid)}\n"
        f"{t(chat_id, type_key)} · <b>{fmt_money(tx.get('amount'))}</b>\n"
        f"{t(chat_id, 'tx.fieldDate')}: {tx.get('transactionDate', '—')}\n"
        f"{t(chat_id, 'tx.fieldCategory')}: {esc(category)}\n{t(chat_id, 'tx.fieldSource')}: {esc(card)}\n"
        f"{t(chat_id, 'tx.fieldDescription')}: {esc(tx.get('description') or t(chat_id, 'common.none'))}\n"
        f"{t(chat_id, 'tx.fieldNote')}: {esc(tx.get('note') or t(chat_id, 'common.none'))}"
    )
    await cb.message.edit_text(text, reply_markup=ikb([
        [(t(chat_id, "common.delete"), f"txdel:{tid}")], [(t(chat_id, "common.back"), "txpage:0")]]))


@router.callback_query(F.data.startswith("txdel:"))
async def ask_delete(cb: CallbackQuery) -> None:
    await cb.answer()
    chat_id = cb.message.chat.id
    tid = int(cb.data.split(":")[1])
    await cb.message.edit_text(t(chat_id, "tx.deleteConfirm", id=tid), reply_markup=ikb([
        [(t(chat_id, "common.deleteYes"), f"txdelok:{tid}"), (t(chat_id, "common.no"), f"txview:{tid}")]]))


@router.callback_query(F.data.startswith("txdelok:"))
async def do_delete(cb: CallbackQuery) -> None:
    await cb.answer()
    if not await common.gate(cb):
        return
    chat_id = cb.message.chat.id
    tid = int(cb.data.split(":")[1])
    try:
        await api.request(chat_id, "DELETE", f"/transactions/{tid}")
    except api.NeedsLogin:
        await cb.message.edit_text(t(chat_id, "common.sessionExpired"), reply_markup=keyboards.login_kb(chat_id))
        return
    except api.ApiError as exc:
        await cb.message.edit_text(f"❌ {esc(exc.message)}", reply_markup=_menu_kb(chat_id))
        return
    except Exception:  # noqa: BLE001
        await cb.message.edit_text(t(chat_id, "common.serverUnreachable"), reply_markup=_menu_kb(chat_id))
        return
    await show_recent(cb)
