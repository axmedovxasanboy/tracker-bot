"""⚙️ Settings — one small screen: language, the monthly income, help, lock.

Everything else (categories, loans, goals, the danger zone) lives in the web app.

The income is here because the backend refuses every money write until it is set, and the guard
that says so (on recording) needs a way through that works from the phone.

Callbacks owned here: `set`, `set:income`, `lang:*`.
"""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from .. import api, common, keyboards, ui
from ..i18n import get_lang, set_lang, t
from ..keyboards import esc, ikb
from ..money import fmt_money, parse_amount
from ..session import store
from ..states import Settings
from . import home

router = Router(name="settings")


async def show_settings(event) -> None:
    chat_id = common.chat_id_of(event)
    try:
        s = await api.request(chat_id, "GET", "/settings") or {}
    except Exception as exc:  # noqa: BLE001
        await home.report(event, exc)
        return
    income = home.n(s.get("monthlyStableIncome"))
    other = "uz" if get_lang(chat_id) == "en" else "en"
    lines = [t(chat_id, "settings.title"), "",
             t(chat_id, "settings.income", amount=fmt_money(income) if income else t(chat_id, "settings.notSet")),
             "", t(chat_id, "settings.hint")]
    await common.show(event, "\n".join(lines), ikb([
        [(t(chat_id, "settings.langBtn"), f"lang:{other}"), (t(chat_id, "settings.incomeBtn"), "set:income")],
        [(t(chat_id, "settings.helpBtn"), "sys:help"), (t(chat_id, "settings.lockBtn"), "lock")],
        ui.nav(chat_id, home=True),
    ]))


@router.message(Command("settings"))
async def settings_cmd(message: Message, state: FSMContext) -> None:
    await state.clear()
    if not await common.gate(message):
        return
    await show_settings(message)


@router.callback_query(F.data == "set")
async def on_settings(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    await state.clear()
    if not await common.gate(cb):
        return
    await show_settings(cb)


# Ungated: a logged-out owner who cannot read the login prompt is exactly who needs to switch.
@router.callback_query(F.data.startswith("lang:"))
async def on_lang(cb: CallbackQuery) -> None:
    chat_id = common.chat_id_of(cb)
    choice = cb.data.split(":", 1)[1]
    if choice not in ("en", "uz"):
        await common.ack(cb)
        return
    set_lang(chat_id, choice)
    await common.ack(cb, t(chat_id, "lang.changed"))
    if store.is_active(chat_id):
        await show_settings(cb)
    else:
        await common.show(cb, t(chat_id, "auth.welcome"), keyboards.login_kb(chat_id))


@router.callback_query(F.data == "set:income")
async def on_income(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    if not await common.gate(cb):
        return
    chat_id = common.chat_id_of(cb)
    await state.set_state(Settings.income)
    await common.show(cb, f"{t(chat_id, 'settings.incomeTitle')}\n\n{t(chat_id, 'settings.incomeAsk')}",
                      ikb([ui.nav(chat_id, back="set", cancel="home")]))


@router.message(StateFilter(Settings.income))
async def on_income_typed(message: Message, state: FSMContext) -> None:
    chat_id = message.chat.id
    amount = parse_amount(message.text)
    if amount is None:
        await message.answer(t(chat_id, "settings.incomeAsk"))
        return
    if not await common.gate(message):
        await state.clear()
        return
    try:
        # Only the one field: SettingsService.update writes solely what the request carries.
        await api.request(chat_id, "PUT", "/settings", json={"monthlyStableIncome": amount})
    except api.NeedsLogin:
        await state.clear()
        await common.show(message, t(chat_id, "common.sessionExpired"), keyboards.login_kb(chat_id))
        return
    except api.ApiError as exc:
        # Still in the state, so the next number typed is another attempt.
        await message.answer(t(chat_id, "common.serverUnreachable") if isinstance(exc, api.Unreachable)
                             else f"❌ {esc(exc.message)}")
        return
    await state.clear()
    await home.show_home(message, t(chat_id, "settings.incomeSaved", amount=fmt_money(amount)))
