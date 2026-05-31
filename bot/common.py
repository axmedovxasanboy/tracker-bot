"""Shared handler helpers: render (edit-or-send) and the auth gate."""
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message, TelegramObject

from . import keyboards
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
    if store.is_active(chat_id_of(event)):
        return True
    if isinstance(event, CallbackQuery):
        await event.answer()
    await show(event, "🔒 Session expired. Please log in.", keyboards.login_kb())
    return False
