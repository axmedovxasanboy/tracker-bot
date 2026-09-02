"""Cards: list, view + delete, add card, and per-currency cash balances. Create via wizard."""
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from . import wizard
from .. import api, common, keyboards
from ..i18n import t
from ..keyboards import esc, fmt_money, ikb

router = Router()

CARD_SPEC = {
    "title": "cards.new.title", "endpoint": "/cards", "back": "cards:list", "success": "cards.new.success",
    "auto_currency": True, "fields": [
        {"key": "name", "label": "cards.new.name", "kind": "text", "required": True},
        {"key": "bankName", "label": "cards.new.bankName", "kind": "text", "required": True},
        # Card network brand names — proper nouns, identical in every language, so they're
        # passed straight through as literal text (t() returns an unknown key as-is).
        {"key": "type", "label": "cards.new.type", "kind": "choice", "required": True,
         "choices": [("UZCARD", "UzCard"), ("HUMO", "Humo"), ("VISA", "Visa")]},
        {"key": "lastFourDigits", "label": "cards.new.last4", "kind": "text", "required": True,
         "regex": r"^\d{4}$", "regex_msg": "cards.new.last4Msg"},
        {"key": "initialBalance", "label": "cards.new.initialBalance", "kind": "number", "required": True},
    ],
}

CASH_SPEC = {
    "title": "cards.cashSpec.title", "endpoint": "/cash-balances", "back": "cards:cash",
    "success": "cards.cashSpec.success", "auto_currency": True, "fields": [
        {"key": "initialBalance", "label": "cards.cashSpec.field", "kind": "number", "required": True},
    ],
}


def _back_kb(chat_id: int):
    return ikb([[(t(chat_id, "common.back"), "cards:list")]])


async def show_menu(cb: CallbackQuery) -> None:
    await _render_cards(cb)


@router.callback_query(F.data == "cards:list")
async def cards_list(cb: CallbackQuery) -> None:
    await cb.answer()
    if not await common.gate(cb):
        return
    await _render_cards(cb)


async def _render_cards(cb: CallbackQuery) -> None:
    chat_id = cb.message.chat.id
    try:
        cards = await api.request(chat_id, "GET", "/cards") or []
    except api.NeedsLogin:
        await cb.message.edit_text(t(chat_id, "common.sessionExpired"), reply_markup=keyboards.login_kb(chat_id))
        return
    except Exception:  # noqa: BLE001
        await cb.message.edit_text(t(chat_id, "cards.loadError"), reply_markup=keyboards.back_menu_kb(chat_id))
        return
    cards = [c for c in cards if c.get("type") != "CASH"]
    lines, rows = [t(chat_id, "cards.title")], []
    if not cards:
        lines.append(t(chat_id, "cards.noneYet"))
    for c in cards:
        lines.append("• " + t(
            chat_id, "cards.line", name=esc(c.get('name')), bank=esc(c.get('bankName')), type=c.get('type'),
            last4=c.get('lastFourDigits', ''), balance=fmt_money(c.get('currentBalance'))))
        rows.append([(f"💳 {str(c.get('name'))[:24]}", f"card:view:{c['id']}")])
    rows.append([(t(chat_id, "cards.addCard"), "cards:add"), (t(chat_id, "cards.cashBalancesBtn"), "cards:cash")])
    rows.append([(t(chat_id, "common.menu"), "menu:home")])
    await cb.message.edit_text("\n".join(lines), reply_markup=ikb(rows))


@router.callback_query(F.data.startswith("card:view:"))
async def card_view(cb: CallbackQuery) -> None:
    await cb.answer()
    if not await common.gate(cb):
        return
    chat_id = cb.message.chat.id
    cid = int(cb.data.split(":")[2])
    try:
        c = await api.request(chat_id, "GET", f"/cards/{cid}")
    except api.NeedsLogin:
        await cb.message.edit_text(t(chat_id, "common.sessionExpired"), reply_markup=keyboards.login_kb(chat_id))
        return
    except Exception:  # noqa: BLE001
        await cb.message.edit_text(t(chat_id, "cards.viewLoadError"), reply_markup=_back_kb(chat_id))
        return
    text = (
        f"{t(chat_id, 'cards.viewHeader', name=esc(c.get('name')), bank=esc(c.get('bankName')), type=c.get('type'), last4=c.get('lastFourDigits', ''))}\n"
        f"{t(chat_id, 'cards.currency', currency=c.get('currency'))}\n"
        f"{t(chat_id, 'cards.initial', amount=fmt_money(c.get('initialBalance')))}\n"
        f"{t(chat_id, 'cards.current', amount=fmt_money(c.get('currentBalance')))}"
    )
    await cb.message.edit_text(text, reply_markup=ikb([
        [(t(chat_id, "common.delete"), f"card:del:{cid}")], [(t(chat_id, "common.back"), "cards:list")]]))


@router.callback_query(F.data.startswith("card:del:"))
async def card_del(cb: CallbackQuery) -> None:
    await cb.answer()
    chat_id = cb.message.chat.id
    cid = int(cb.data.split(":")[2])
    await cb.message.edit_text(
        t(chat_id, "cards.deleteConfirm"),
        reply_markup=ikb([[(t(chat_id, "common.deleteYes"), f"card:delok:{cid}"), (t(chat_id, "common.no"), f"card:view:{cid}")]]))


@router.callback_query(F.data.startswith("card:delok:"))
async def card_delok(cb: CallbackQuery) -> None:
    await cb.answer()
    if not await common.gate(cb):
        return
    chat_id = cb.message.chat.id
    cid = int(cb.data.split(":")[2])
    try:
        await api.request(chat_id, "DELETE", f"/cards/{cid}")
    except api.NeedsLogin:
        await cb.message.edit_text(t(chat_id, "common.sessionExpired"), reply_markup=keyboards.login_kb(chat_id))
        return
    except api.ApiError as exc:
        await cb.message.edit_text(f"❌ {esc(exc.message)}", reply_markup=_back_kb(chat_id))
        return
    except Exception:  # noqa: BLE001
        await cb.message.edit_text(t(chat_id, "common.serverUnreachable"), reply_markup=_back_kb(chat_id))
        return
    await _render_cards(cb)


@router.callback_query(F.data == "cards:cash")
async def show_cash(cb: CallbackQuery) -> None:
    await cb.answer()
    if not await common.gate(cb):
        return
    chat_id = cb.message.chat.id
    try:
        rows = await api.request(chat_id, "GET", "/cash-balances") or []
    except api.NeedsLogin:
        await cb.message.edit_text(t(chat_id, "common.sessionExpired"), reply_markup=keyboards.login_kb(chat_id))
        return
    except Exception:  # noqa: BLE001
        await cb.message.edit_text(t(chat_id, "cards.cashLoadError"), reply_markup=_back_kb(chat_id))
        return
    lines = [t(chat_id, "cards.cashTitle")]
    if not rows:
        lines.append(t(chat_id, "cards.noCashSet"))
    for cb_row in rows:
        cur = cb_row.get("currency")
        lines.append("• " + t(
            chat_id, "cards.cashLine", currency=cur, current=fmt_money(cb_row.get('currentBalance')),
            initial=fmt_money(cb_row.get('initialBalance'))))
    await cb.message.edit_text("\n".join(lines), reply_markup=ikb([
        [(t(chat_id, "cards.setCashBalance"), "cash:add")], [(t(chat_id, "common.back"), "cards:list")]]))


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
