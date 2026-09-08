"""The owner guard: this bot moves one real person's money and Telegram is a public door.

Anyone who finds the bot can start it. Authorisation today is `store.is_active(chat_id)` and
nothing else, so a stranger gets the login screen — and after a factory reset the backend
answers `needsSignup`, which means the FIRST person to type a username and password OWNS the
account and everything the owner types into it afterwards.

Two modes, per FIX-CONTRACT §2:

* `OWNER_CHAT_ID` set — only that chat is served. This is the configuration to run in.
* not set — **trust on first login**: every private chat is served until one of them
  authenticates, and from that moment only that chat is. The bound id is logged at INFO so
  it can be pinned in `.env`, after which the window closes permanently.

Registered as an OUTER middleware on the update observer, so it runs before any filter, any
router and any FSM lookup — a refused chat never reaches a handler and never touches state.
aiogram installs its own `ErrorsMiddleware` on that observer first, so anything raised in
here still lands in `bot/errors.py` rather than in the void.
"""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import Bot, Dispatcher
from aiogram.dispatcher.middlewares.base import BaseMiddleware
from aiogram.enums import ChatType
from aiogram.types import Chat, TelegramObject, Update

from . import config
from .i18n import t
from .session import store

logger = logging.getLogger("tracker-bot.guard")

# One refusal per chat, and a ceiling on how many chats we remember. Both are anti-amplifier
# measures: with the webhook secret unset (see main.py's boot warning) a stranger can post
# forged updates as fast as they like, and a bot that answers every one of them is a way to
# spend the owner's rate limit for them.
_REFUSAL_MEMORY = 512
_refused: set[int] = set()


def setup(dp: Dispatcher) -> None:
    """Install the guard ahead of every router."""
    dp.update.outer_middleware(OwnerGuard())


class OwnerGuard(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Update):  # defensive: this observer only ever carries Update
            return await handler(event, data)

        chat = _chat_of(event)
        if chat is None:
            # Nothing this bot registers arrives without a chat. Anything that does is
            # dropped rather than guessed at, because there is no id to compare.
            logger.debug("Dropped update id=%s: no chat on it", event.update_id)
            return None

        reason = _refusal_reason(chat)
        if reason is None:
            return await handler(event, data)  # the owner's updates pass through untouched

        await _refuse(event, data, chat, reason)
        return None


def _refusal_reason(chat: Chat) -> str | None:
    """None when this chat may be served; otherwise why it may not, for the log."""
    if config.OWNER_CHAT_ID is not None:
        if chat.id == config.OWNER_CHAT_ID:
            return None
        return f"OWNER_CHAT_ID is {config.OWNER_CHAT_ID}"

    if chat.type != ChatType.PRIVATE:
        # A group can never be the owner's private chat, and these screens print balances.
        return f"{chat.type} chats are never served"

    # `SessionStore.start` binds the first chat that authenticates, so `owner_id()` is None
    # only while nobody has logged in yet. That window has to stay open or a fresh deployment
    # could never be set up from the phone; it closes on the first successful login and the
    # bound id is logged there for pinning in .env.
    owner = store.owner_id()
    if owner is None or chat.id == owner:
        return None
    return f"chat {owner} claimed this bot first"


async def _refuse(event: Update, data: dict[str, Any], chat: Chat, reason: str) -> None:
    """Say no once per chat, then stay silent. Every refused chat is logged either way."""
    if chat.id in _refused:
        logger.debug("Refused update id=%s from chat=%s again", event.update_id, chat.id)
        return
    logger.warning("Refused chat_id=%s (%s): %s", chat.id, chat.type, reason)
    if len(_refused) >= _REFUSAL_MEMORY:
        # Past the ceiling the guard can no longer tell a first refusal from a repeat, so it
        # stops replying rather than risk answering the same flood forever. The line above
        # still records who was turned away.
        return
    _refused.add(chat.id)

    bot: Bot | None = data.get("bot")
    if bot is None:
        return
    text = t(chat.id, "common.notForYou")
    try:
        if event.callback_query is not None:
            # An unanswered callback spins on the stranger's screen; an alert also means the
            # refusal is seen when the tap came from a message they cannot see any more.
            await bot.answer_callback_query(event.callback_query.id, text=text, show_alert=True)
        else:
            await bot.send_message(chat.id, text)
    except Exception:  # noqa: BLE001
        logger.debug("Couldn't deliver the refusal to chat=%s", chat.id, exc_info=True)


def _chat_of(update: Update) -> Chat | None:
    if update.message is not None:
        return update.message.chat
    if update.callback_query is not None:
        message = update.callback_query.message
        return message.chat if message is not None else None
    if update.edited_message is not None:
        return update.edited_message.chat
    return None
