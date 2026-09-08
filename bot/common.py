"""Shared handler primitives: acknowledge, render, gate, guard.

Everything here exists because the same three mistakes were being made independently in every
router, and each of them is invisible to the person making it — the bot keeps running, the log
line scrolls past, and the owner is left holding a phone with a spinning button on it.

* A callback query may be answered exactly once. Two `cb.answer()` calls for one tap raise
  TelegramBadRequest from the second, which aborts the handler mid-render. `ack()` makes the
  second call free.
* `cb.message` is not always a `Message`. Since Bot API 7.0 it can be an `InaccessibleMessage`
  stub with no `edit_text` at all, so the render raises AttributeError after the query has been
  answered and the FSM state cleared. `show()`/`edit()` know the difference.
* A write with a live Confirm button under it can be submitted twice by an impatient thumb.
  `begin_write()` takes the button away before the request leaves the process.

Routers should reach for `show`, `ack`, `begin_write`, `gate` and `stable_income_set` and never
touch `cb.message.edit_text` directly — that is the call that has no idea what it is holding.
"""
import logging

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message, TelegramObject

from . import keyboards
from .i18n import t
from .session import store

log = logging.getLogger(__name__)

# Telegram's hard ceiling for message text. Anything longer is rejected outright, so long
# screens (a month history, a full allocation ledger) are split rather than truncated.
TEXT_LIMIT = 4096

# The one TelegramBadRequest that means "your render was a no-op" rather than "your render
# failed". Re-pressing the button that is already on screen produces it constantly.
_NOT_MODIFIED = "message is not modified"

# The ones that mean "that message is gone or was never ours" — recoverable by sending a new
# message. Anything else is a real bug (unbalanced HTML, a bad markup) and must not be hidden.
_UNEDITABLE = (
    "message to edit not found",
    "message can't be edited",
    "message identifier is not specified",
    "message_id_invalid",
)

# Answered callback-query ids. Bounded: this is a long-lived process and the ids are never
# reused, so an unbounded set would be a slow leak for no benefit.
_ACK_LIMIT = 1024
_acked: dict[str, None] = {}


def chat_id_of(event: TelegramObject) -> int:
    """The chat this event belongs to — the key for the session, the language and the API."""
    if isinstance(event, CallbackQuery):
        # `message` is None for an inline-mode query and an InaccessibleMessage stub for a
        # deleted one. Both still identify the person, and this is a private-chat bot, where
        # the user id and the chat id are the same number.
        if event.message is not None:
            return event.message.chat.id
        return event.from_user.id
    chat = getattr(event, "chat", None)
    if chat is not None:
        return chat.id
    user = getattr(event, "from_user", None)
    if user is not None:
        return user.id
    raise TypeError(f"chat_id_of: no chat on a {type(event).__name__}")


async def ack(event: TelegramObject, text: str | None = None, alert: bool = False) -> None:
    """Answer a callback query at most once, whatever the call order upstream.

    Telegram accepts one answerCallbackQuery per query id; the second is a 400. That used to
    fire whenever `gate()` ran after a handler had already answered, and because the exception
    was raised *before* the handler rendered anything, the tap simply vanished — no session
    prompt, no error, no screen change. Making the acknowledgement idempotent retires that
    whole class of bug, and lets any helper clear the spinner defensively without having to
    know whether its caller did so first.

    A `text`/`alert` passed on a repeat call is dropped rather than sent: Telegram would not
    display it anyway, because the query it belongs to has already been answered.
    """
    if not isinstance(event, CallbackQuery):
        return
    if event.id in _acked:
        return
    # Marked before the await, so a re-entrant call during the round trip is also a no-op.
    _acked[event.id] = None
    while len(_acked) > _ACK_LIMIT:
        _acked.pop(next(iter(_acked)), None)  # dicts keep insertion order: oldest id first
    try:
        await event.answer(text, show_alert=alert)
    except TelegramBadRequest:
        # "query is too old and response timeout expired or query ID is invalid" — the
        # spinner cleared itself minutes ago and there is nothing left to acknowledge.
        log.debug("callback %s could not be answered", event.id, exc_info=True)


def _split(text: str, limit: int = TEXT_LIMIT) -> list[str]:
    """Cut text into ≤limit pieces on line boundaries.

    Line boundaries specifically, because every long screen in this bot is a list of one-line
    rows with their own <b>…</b> on each: cutting between lines keeps the HTML balanced, while
    cutting at an arbitrary offset would leave an open tag and Telegram would reject the send.
    """
    if len(text) <= limit:
        return [text]
    parts: list[str] = []
    buf = ""
    for line in text.split("\n"):
        while len(line) > limit:  # one line longer than a whole message: no boundary to use
            if buf:
                parts.append(buf)
                buf = ""
            parts.append(line[:limit])
            line = line[limit:]
        candidate = f"{buf}\n{line}" if buf else line
        if len(candidate) > limit:
            parts.append(buf)
            buf = line
        else:
            buf = candidate
    if buf:
        parts.append(buf)
    return parts


async def _edit_message(event: CallbackQuery, text: str,
                        kb: InlineKeyboardMarkup | None) -> bool:
    """Try to edit the message a callback came from. False means 'send a new one instead'."""
    msg = event.message
    try:
        if isinstance(msg, Message):
            await msg.edit_text(text, reply_markup=kb)
        elif msg is not None and event.bot is not None:
            # An InaccessibleMessage still carries chat + message_id, so the edit is worth one
            # attempt through the raw method — it just has no `edit_text` shortcut of its own.
            await event.bot.edit_message_text(text, chat_id=msg.chat.id,
                                              message_id=msg.message_id, reply_markup=kb)
        else:
            return False
    except TelegramBadRequest as exc:
        detail = (exc.message or "").lower()
        if _NOT_MODIFIED in detail:
            return True  # the screen already says exactly this; the render succeeded
        if any(reason in detail for reason in _UNEDITABLE):
            return False
        raise  # a real render bug — let the error handler log it and tell the user
    return True


async def _send(event: TelegramObject, text: str, kb: InlineKeyboardMarkup | None) -> None:
    if isinstance(event, Message):
        await event.answer(text, reply_markup=kb)
        return
    msg = getattr(event, "message", None)
    if msg is not None:
        await msg.answer(text, reply_markup=kb)  # InaccessibleMessage does carry `answer`
        return
    bot = getattr(event, "bot", None)
    if bot is not None:
        await bot.send_message(chat_id_of(event), text, reply_markup=kb)


async def show(event: TelegramObject, text: str, kb: InlineKeyboardMarkup | None = None, *,
               reply_markup: InlineKeyboardMarkup | None = None) -> None:
    """Render a screen: edit in place for a callback, send for a typed command or answer.

    `reply_markup` is a real alias for `kb`, not a rename. Every aiogram send/edit method
    spells the parameter `reply_markup`, so callers reach for that name by muscle memory —
    one already did, and the TypeError it raised took every expense the owner tried to record
    with it. Accepting both names is cheaper than finding the next one in production.
    """
    kb = kb if kb is not None else reply_markup
    chunks = _split(text)
    last = len(chunks) - 1
    if isinstance(event, CallbackQuery):
        # The keyboard belongs on the final chunk, so it sits at the bottom of the screen the
        # user is actually looking at.
        if not await _edit_message(event, chunks[0], kb if last == 0 else None):
            await _send(event, chunks[0], kb if last == 0 else None)
        for i, part in enumerate(chunks[1:], start=1):
            await _send(event, part, kb if i == last else None)
        return
    for i, part in enumerate(chunks):
        await _send(event, part, kb if i == last else None)


async def edit(event: TelegramObject, text: str,
               kb: InlineKeyboardMarkup | None = None) -> None:
    """Update the screen in place, never posting a new message.

    Use this where a second message would be wrong — replacing a confirmation with its result,
    for instance. A Message event has nothing of ours to edit (the bot cannot edit the user's
    own message), so this does nothing there; reach for `show` whenever the event might be a
    typed one. Long text is still split, but only the first chunk can be an edit.
    """
    if not isinstance(event, CallbackQuery):
        log.debug("edit() on a %s: nothing of ours to edit", type(event).__name__)
        return
    chunks = _split(text)
    last = len(chunks) - 1
    if not await _edit_message(event, chunks[0], kb if last == 0 else None):
        log.debug("edit() could not reach the message for callback %s", event.id)
        return
    for i, part in enumerate(chunks[1:], start=1):
        await _send(event, part, kb if i == last else None)


async def begin_write(event: TelegramObject, chat_id: int | None = None) -> None:
    """Show "Saving…" and take the keyboard away, BEFORE the write leaves the process.

    Two jobs in one call. It is the in-flight feedback — several of these writes take seconds
    against a cold backend, and until now the screen sat there unchanged as if the tap had
    been ignored. And it is the double-submit guard: the second tap of an impatient thumb has
    no button left to hit, which is the only defence the bot has, because the backend happily
    books the same transaction, the same repayment or the same month-close twice.

    On a typed step there is no button to remove, so this posts the notice instead of editing:
    the feedback still matters, and a text answer cannot be double-tapped anyway.
    """
    if chat_id is None:
        chat_id = chat_id_of(event)
    saving = t(chat_id, "common.saving")
    if isinstance(event, CallbackQuery):
        if await _edit_message(event, saving, None):
            return
    await _send(event, saving, None)


async def gate(event: TelegramObject) -> bool:
    """True if the chat has a live session; otherwise render the log-in prompt and False."""
    chat_id = chat_id_of(event)
    if store.is_active(chat_id):
        return True
    # `ack` rather than `event.answer()`: most callers have already answered by the time they
    # get here and the duplicate used to abort this handler before it could render anything.
    await ack(event)
    await show(event, t(chat_id, "common.sessionExpired"), keyboards.login_kb(chat_id))
    return False


async def stable_income_set(event: TelegramObject) -> bool:
    """False (and shows the guard) when Settings has no monthly stable income.

    The backend refuses every money-writing call until it is set, so each write flow checks up
    front rather than walking the owner through a whole form only to reject it at the end.
    On any lookup failure this returns True and lets the backend be the authority.

    The guard screen carries the fix, not directions to another application: a fresh phone-only
    owner who signs up in the bot hits this wall on their very first tap, and "open the web app"
    is not an answer they can act on from where they are standing.
    """
    from . import api
    chat_id = chat_id_of(event)
    try:
        settings = await api.request(chat_id, "GET", "/settings") or {}
    except api.NeedsLogin:
        await ack(event)
        await show(event, t(chat_id, "common.sessionExpired"), keyboards.login_kb(chat_id))
        return False
    except Exception:  # noqa: BLE001
        return True
    income = settings.get("monthlyStableIncome")
    try:
        if income is not None and float(income) > 0:
            return True
    except (TypeError, ValueError):
        pass  # the field is there but is not a number — treat it as unset
    await ack(event)
    await show(
        event,
        f"{t(chat_id, 'guard.incomeTitle')}\n\n{t(chat_id, 'guard.incomeBody')}",
        keyboards.income_guard_kb(chat_id))
    return False
