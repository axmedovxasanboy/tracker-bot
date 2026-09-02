"""Shared handler helpers: render (edit-or-send) and the auth gate."""
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message, TelegramObject

from . import keyboards
from .i18n import t
from .session import store


def chat_id_of(event: TelegramObject) -> int:
    if isinstance(event, CallbackQuery):
        return event.message.chat.id
    return event.chat.id  # Message


async def show(event: TelegramObject, text: str, kb: InlineKeyboardMarkup | None = None) -> None:
    """Edit the message for a callback; send a new message for a command/text."""
    if isinstance(event, CallbackQuery):
        try:
            await event.message.edit_text(text, reply_markup=kb)
        except TelegramBadRequest:
            pass  # ignore "message is not modified"
    elif isinstance(event, Message):
        await event.answer(text, reply_markup=kb)


async def gate(event: TelegramObject) -> bool:
    """Return True if the chat has an active session; otherwise prompt to log in."""
    chat_id = chat_id_of(event)
    if store.is_active(chat_id):
        return True
    if isinstance(event, CallbackQuery):
        await event.answer()
    await show(event, t(chat_id, "common.sessionExpired"), keyboards.login_kb(chat_id))
    return False


async def stable_income_set(event) -> bool:
    """False (and shows a message) when Settings has no monthly stable income.

    The backend refuses every money-writing call until it is set, so each write flow checks
    up front rather than walking the user through a whole form only to reject it at the end.
    On any lookup failure this returns True and lets the backend be the authority.
    """
    from . import api
    chat_id = chat_id_of(event)
    try:
        s = await api.request(chat_id, "GET", "/settings") or {}
    except api.NeedsLogin:
        await show(event, t(chat_id, "common.sessionExpired"), keyboards.login_kb(chat_id))
        return False
    except Exception:  # noqa: BLE001
        return True
    income = s.get("monthlyStableIncome")
    if income is None or float(income) <= 0:
        await show(
            event,
            f"{t(chat_id, 'guard.incomeTitle')}\n\n{t(chat_id, 'guard.incomeBody')}",
            keyboards.back_menu_kb(chat_id))
        return False
    return True
