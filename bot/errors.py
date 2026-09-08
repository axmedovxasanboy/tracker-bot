"""The catch-all error handler — the difference between a bug and a frozen screen.

With nothing registered on `dp.errors`, aiogram's `ErrorsMiddleware` re-raises whatever a
handler threw. In webhook mode `SimpleRequestHandler` runs each update in a detached
background task and has already answered Telegram with 200, so the re-raised exception dies
in a log line inside a task nobody awaits. The owner is left looking at an unchanged screen
with a spinning button, forever, and Telegram never retries. That is the current behaviour
on every expense the bot fails to record.

So this handler has exactly three jobs, in this order:
  1. put the traceback in the log with the update id, so the incident is findable;
  2. stop the spinner by answering the callback query, if there is one;
  3. tell the owner, in their language, that the step failed and give them a way back.

Everything here is written so that it cannot raise: a handler that throws while reporting a
throw would take the whole update down again and lose the log line as well.
"""
from __future__ import annotations

import logging
from typing import Any

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import ErrorEvent, Update

from . import api, common, keyboards
from .i18n import t

logger = logging.getLogger("tracker-bot.errors")


def setup(dp: Dispatcher) -> None:
    """Register the handler on the root error observer."""
    dp.errors.register(on_error)


async def on_error(event: ErrorEvent, **data: Any) -> bool:
    """Report a failed update to its owner. Always returns True — see the module docstring.

    Returning anything other than aiogram's UNHANDLED is what stops `ErrorsMiddleware` from
    re-raising, so this must return even on the paths where it decides to say nothing.
    """
    update = event.update
    exc = event.exception
    cb = update.callback_query
    chat_id = _chat_id(update)

    # The message TEXT is deliberately never logged. Two flows take a password as an
    # ordinary message (login, and the factory-reset confirmation), and this handler fires
    # on exactly the paths where one may be in flight. Callback data is safe and is the
    # single most useful thing for reproducing a tap.
    logger.error(
        "Update id=%s (%s) chat=%s failed%s",
        update.update_id,
        _kind(update),
        chat_id,
        f" on callback_data={cb.data!r}" if cb is not None else "",
        exc_info=exc,
    )

    bot: Bot | None = data.get("bot")
    if bot is None or chat_id is None:
        return True

    # "message is not modified" means the screen already shows what the handler was trying
    # to draw. Nothing failed from where the owner is sitting, so answer the tap and say
    # nothing — an apology here would be the bot inventing a problem.
    quiet = isinstance(exc, TelegramBadRequest) and "message is not modified" in str(exc).lower()

    if cb is not None:
        try:
            await common.ack(cb, None if quiet else t(chat_id, "system.error.toast"))
        except Exception:  # noqa: BLE001
            # A forged or expired query id can't be answered; the spinner is Telegram's
            # problem at that point, and the message below is still worth sending.
            logger.debug("Couldn't answer callback query %s", cb.id, exc_info=True)

    if quiet or isinstance(exc, TelegramForbiddenError):
        # Either there is nothing left to say, or nobody to say it to: a Forbidden means the
        # chat blocked the bot, so the message below would fail for the very same reason.
        return True

    # A session that died mid-flow is an expected outcome, not a crash: say so, and put the
    # log-in button on screen instead of a generic apology that leads nowhere.
    if isinstance(exc, api.NeedsLogin):
        text = t(chat_id, "common.sessionExpired")
        kb = keyboards.login_kb(chat_id)
    else:
        text = f"{t(chat_id, 'system.error.title')}\n\n{t(chat_id, 'system.error.body')}"
        kb = keyboards.back_menu_kb(chat_id)

    try:
        # Sent, not edited. The screen that failed may be inaccessible (a button older than
        # ~48h), already deleted, or the very thing that raised; a new message is the only
        # delivery this handler can rely on. The FSM state is left alone on purpose, so a
        # half-filled form survives a transient backend error and /cancel stays the way out.
        await bot.send_message(chat_id, text, reply_markup=kb)
    except Exception:  # noqa: BLE001
        logger.warning("Couldn't tell chat %s about the failure", chat_id, exc_info=True)
    return True


def _chat_id(update: Update) -> int | None:
    """The chat to apologise to. Only the two update types this bot registers can appear."""
    if update.callback_query is not None:
        message = update.callback_query.message
        # An InaccessibleMessage still carries its chat, which is all that is needed here.
        return message.chat.id if message is not None else update.callback_query.from_user.id
    message = update.message or update.edited_message
    return message.chat.id if message is not None else None


def _kind(update: Update) -> str:
    try:
        return update.event_type
    except Exception:  # noqa: BLE001
        return "unknown"  # event_type raises for an update type this aiogram build predates
