"""Cards: list, view + delete, add card, and per-currency cash balances. Create via wizard."""
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from . import wizard
from .. import api, common, keyboards
from ..keyboards import esc, fmt_money, ikb
from ..session import store

router = Router()

CURRENCY_CHOICES = [("UZS", "UZS"), ("USD", "USD"), ("EUR", "EUR")]

CARD_SPEC = {
    "title": "New card", "endpoint": "/cards", "back": "cards:list", "success": "Card added.",
    "auto_currency": False, "fields": [
        {"key": "name", "label": "Card name", "kind": "text", "required": True},
        {"key": "bankName", "label": "Bank name", "kind": "text", "required": True},
        {"key": "type", "label": "Card type", "kind": "choice", "required": True,
         "choices": [("UZCARD", "UzCard"), ("HUMO", "Humo"), ("VISA", "Visa")]},
        {"key": "currency", "label": "Currency", "kind": "choice", "required": True, "choices": CURRENCY_CHOICES},
        {"key": "lastFourDigits", "label": "Last 4 digits", "kind": "text", "required": True,
         "regex": r"^\d{4}$", "regex_msg": "Enter exactly 4 digits."},
        {"key": "initialBalance", "label": "Initial balance", "kind": "number", "required": True},
    ],
}

CASH_SPEC = {
    "title": "Set cash balance", "endpoint": "/cash-balances", "back": "cards:cash",
    "success": "Cash balance saved.", "auto_currency": False, "fields": [
        {"key": "currency", "label": "Currency", "kind": "choice", "required": True, "choices": CURRENCY_CHOICES},
        {"key": "initialBalance", "label": "Starting balance", "kind": "number", "required": True},
    ],
}


def _back_kb():
    return ikb([[("⬅️ Back", "cards:list")]])


async def show_menu(cb: CallbackQuery) -> None:
    await _render_cards(cb)


@router.callback_query(F.data == "cards:list")
async def cards_list(cb: CallbackQuery) -> None:
    await cb.answer()
    if not await common.gate(cb):
        return
    await _render_cards(cb)


async def _render_cards(cb: CallbackQuery) -> None:
    try:
        cards = await api.request(cb.message.chat.id, "GET", "/cards") or []
    except api.NeedsLogin:
        await cb.message.edit_text("🔒 Session expired. Please log in.", reply_markup=keyboards.login_kb())
        return
    except Exception:  # noqa: BLE001
        await cb.message.edit_text("❌ Couldn't load cards.", reply_markup=keyboards.back_menu_kb())
        return
    cards = [c for c in cards if c.get("type") != "CASH"]
    lines, rows = ["💳 <b>Cards</b>\n"], []
    if not cards:
        lines.append("No cards yet.")
    for c in cards:
        cur = c.get("currency")
        lines.append(f"• {esc(c.get('name'))} — {esc(c.get('bankName'))} {c.get('type')} "
                     f"···{c.get('lastFourDigits', '')}: {fmt_money(c.get('currentBalance'), cur)}")
        rows.append([(f"💳 {str(c.get('name'))[:24]}", f"card:view:{c['id']}")])
    rows.append([("➕ Add card", "cards:add"), ("💵 Cash balances", "cards:cash")])
    rows.append([("⬅️ Menu", "menu:home")])
    await cb.message.edit_text("\n".join(lines), reply_markup=ikb(rows))


@router.callback_query(F.data.startswith("card:view:"))
async def card_view(cb: CallbackQuery) -> None:
    await cb.answer()
    if not await common.gate(cb):
        return
    cid = int(cb.data.split(":")[2])
    try:
        c = await api.request(cb.message.chat.id, "GET", f"/cards/{cid}")
    except api.NeedsLogin:
        await cb.message.edit_text("🔒 Session expired. Please log in.", reply_markup=keyboards.login_kb())
        return
    except Exception:  # noqa: BLE001
        await cb.message.edit_text("❌ Couldn't load that card.", reply_markup=_back_kb())
        return
    cur = c.get("currency")
    text = (
        f"💳 <b>{esc(c.get('name'))}</b>\n"
        f"{esc(c.get('bankName'))} · {c.get('type')} · ···{c.get('lastFourDigits', '')}\n"
        f"Currency: {cur}\n"
        f"Initial: {fmt_money(c.get('initialBalance'), cur)}\n"
        f"Current: <b>{fmt_money(c.get('currentBalance'), cur)}</b>"
    )
    await cb.message.edit_text(text, reply_markup=ikb([
        [("🗑 Delete", f"card:del:{cid}")], [("⬅️ Back", "cards:list")]]))


@router.callback_query(F.data.startswith("card:del:"))
async def card_del(cb: CallbackQuery) -> None:
    await cb.answer()
    cid = int(cb.data.split(":")[2])
    await cb.message.edit_text(
        "Delete this card? Its transactions stay in history but lose the card link.",
        reply_markup=ikb([[("✅ Yes, delete", f"card:delok:{cid}"), ("✖️ No", f"card:view:{cid}")]]))


@router.callback_query(F.data.startswith("card:delok:"))
async def card_delok(cb: CallbackQuery) -> None:
    await cb.answer()
    if not await common.gate(cb):
        return
    cid = int(cb.data.split(":")[2])
    try:
        await api.request(cb.message.chat.id, "DELETE", f"/cards/{cid}")
    except api.NeedsLogin:
        await cb.message.edit_text("🔒 Session expired. Please log in.", reply_markup=keyboards.login_kb())
        return
    except api.ApiError as exc:
        await cb.message.edit_text(f"❌ {esc(exc.message)}", reply_markup=_back_kb())
        return
    except Exception:  # noqa: BLE001
        await cb.message.edit_text("❌ Couldn't reach the server.", reply_markup=_back_kb())
        return
    await _render_cards(cb)


@router.callback_query(F.data == "cards:cash")
async def show_cash(cb: CallbackQuery) -> None:
    await cb.answer()
    if not await common.gate(cb):
        return
    try:
        rows = await api.request(cb.message.chat.id, "GET", "/cash-balances") or []
    except api.NeedsLogin:
        await cb.message.edit_text("🔒 Session expired. Please log in.", reply_markup=keyboards.login_kb())
        return
    except Exception:  # noqa: BLE001
        await cb.message.edit_text("❌ Couldn't load cash balances.", reply_markup=_back_kb())
        return
    lines = ["💵 <b>Cash balances</b>\n"]
    if not rows:
        lines.append("No cash balances set.")
    for cb_row in rows:
        cur = cb_row.get("currency")
        lines.append(f"• {cur}: <b>{fmt_money(cb_row.get('currentBalance'), cur)}</b> "
                     f"(start {fmt_money(cb_row.get('initialBalance'), cur)})")
    await cb.message.edit_text("\n".join(lines), reply_markup=ikb([
        [("➕ Set cash balance", "cash:add")], [("⬅️ Back", "cards:list")]]))


@router.callback_query(F.data == "cards:add")
async def add_card(cb: CallbackQuery, state: FSMContext) -> None:
    if not await common.gate(cb):
        return
    await cb.answer()
    await wizard.start(cb, state, CARD_SPEC)


@router.callback_query(F.data == "cash:add")
async def add_cash(cb: CallbackQuery, state: FSMContext) -> None:
    if not await common.gate(cb):
        return
    await cb.answer()
    await wizard.start(cb, state, CASH_SPEC)
