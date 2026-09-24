"""The front door: /start, the typed login/signup, /lock, /menu and the global /cancel.

A login lasts until /lock — see `bot/session.py` and `bot/keepalive.py`.

Four things happen here that are not obvious from the handlers themselves.

**The owner is bound.** `SessionStore.start()` claims the process for the first chat that
authenticates, and `bot/middlewares.py` refuses every other chat from that moment on. This
module is the only place a successful authentication lands, so it is also where the binding is
*checked*: the guard reads `owner_id()` at the top of an update, and two chats can therefore
both be inside `got_password` while the door is still open. The loser of that race gets its
session dropped again rather than left in memory.

**A command must never become a credential.** Handlers inside one router are tried in
registration order and the first match wins, so a bare `StateFilter(Auth.username)` text
handler swallows anything typed at it — `/lock` included, which is the escape hatch the login
success message itself advertises. Every command handler in this router is registered above
the two state handlers, and the state handlers additionally refuse command-shaped text, so a
command that belongs to another router (`/add`, `/help`, `/settings`) still reaches it.

**A factory reset (web app) takes the bot's own configuration with it.** `ResetService`
truncates `settings`, which is where `telegram_webhook_url` lives — the value `main.py` reads
at boot. So the signup that follows a reset writes both URLs back.

**The password is deleted from the chat, and that can fail.** Deleting an incoming message
needs the right and a message younger than 48h; when it does not work the password is sitting
in the chat history and the owner is told so, rather than the failure being swallowed.
"""
import logging
import re

from aiogram import F, Router
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message, TelegramObject

from .. import api, common, keyboards, runtime, ui
from ..i18n import t
from ..keyboards import esc
from ..session import store
from ..states import Auth
from . import home

log = logging.getLogger(__name__)

router = Router()

# Telegram's own command syntax: a leading slash, up to 32 word characters, optionally
# addressed to a bot. Matching this rather than a bare "starts with /" keeps a password like
# "/2xTashkent!" usable — only text Telegram itself would render as a command is intercepted.
_COMMAND = re.compile(r"^/([A-Za-z0-9_]{1,32})(?:@[A-Za-z0-9_]+)?(?:\s|$)")

# Commands this router deliberately lets fall through to the router that owns them. `/help`
# and `/add` live in main.py's `system` router, which is included FIRST and therefore already
# outranks everything here; `/settings` lives in the settings router. Anything else that is
# command-shaped is unknown to the bot, and dropping it silently mid-login would be worse than
# the swallowing this whole arrangement exists to fix — `command_during_login` answers it.
_DOWNSTREAM_COMMANDS = frozenset({"add", "help", "settings"})

# The backend answers authentication failures with English prose and no machine-readable code,
# so these four sentences are matched verbatim (AuthService.java:38-55, and the "already
# exists" guard at :31). A wording change on the Java side costs us the translation and
# nothing else: `_api_error` falls back to printing the server's own sentence, which is what
# the bot did for all four of them before.
_BACKEND_ERRORS = {
    "Invalid username or password.": "auth.err.invalidCredentials",
    "Password must be at least 6 characters.": "auth.err.passwordTooShort",
    "Username is required.": "auth.err.usernameRequired",
    "An account already exists — please log in.": "auth.err.accountExists",
}


# ── Small helpers ───────────────────────────────────────────────────────────
async def _home_or_login(event: TelegramObject, notice: str | None = None) -> None:
    """Home when logged in; otherwise the notice (or the welcome) with the log-in button."""
    chat_id = common.chat_id_of(event)
    if store.is_active(chat_id):
        await home.show_home(event, notice)
        return
    await common.show(event, notice or t(chat_id, "auth.pleaseLoginFirst"), keyboards.login_kb(chat_id))


def _command_name(text: str | None) -> str | None:
    """The command in this message text, without its slash or @botname — None if it is not one."""
    if not text:
        return None
    match = _COMMAND.match(text.strip())
    return match.group(1).lower() if match else None


async def _not_a_command(message: Message) -> bool:
    """Filter: this message is safe to read as a username or a password.

    Async on purpose. aiogram runs a *synchronous* filter through `asyncio.to_thread`
    (dispatcher/event/handler.py:70), which would spend a thread hop on every message typed
    during the login flow to answer a regex.
    """
    return _command_name(message.text) is None


async def _unknown_command(message: Message) -> bool:
    """Filter: command-shaped, and no later router is going to handle it."""
    name = _command_name(message.text)
    return name is not None and name not in _DOWNSTREAM_COMMANDS


async def _needs_signup() -> bool | None:
    """True when the backend has no account yet. None when we could not find out.

    Token-less and cheap, but it is a network call on the path of `/start`, so a failure has
    to be survivable: the caller falls back to the ordinary "log in" copy, which is wrong only
    in its emphasis.
    """
    try:
        status = await api.auth_status()
    except Exception:  # noqa: BLE001
        log.debug("Couldn't read /auth/status for the welcome screen", exc_info=True)
        return None
    return bool(status.get("needsSignup"))


def _api_error(chat_id: int, exc: api.ApiError) -> str:
    key = _BACKEND_ERRORS.get((exc.message or "").strip())
    return t(chat_id, key) if key else f"❌ {esc(exc.message)}"


def _joined(body: str, extra: list[str]) -> str:
    """The result plus whatever the flow has to warn about, as separate paragraphs."""
    return "\n\n".join([body, *extra]) if extra else body


async def _delete_quietly(message: Message) -> bool:
    """Delete the message the password was typed into. False when it is still in the history.

    Deleting an incoming message needs the permission and a message younger than 48 hours, and
    the API can simply refuse. Swallowing that leaves a plaintext password in the chat with
    nobody aware of it, so the caller turns a False into a line the owner can act on.
    """
    try:
        await message.delete()
    except Exception:  # noqa: BLE001
        # Never log the message itself: it is the password.
        log.warning("Couldn't delete the password message in chat %s — it stays in the history.",
                    message.chat.id, exc_info=True)
        return False
    return True


async def _webhook_url(bot) -> str | None:
    """The public URL Telegram is delivering updates to.

    main.py reads it from the backend at boot but has no reason to publish it, so the value is
    recovered from Telegram itself and cached on `runtime`. `getWebhookInfo` is authoritative
    in a way the stored setting is not: it is where updates are *actually* arriving.
    """
    cached = runtime.runtime.webhook_url
    if cached:
        return cached
    try:
        info = await bot.get_webhook_info()
    except Exception:  # noqa: BLE001
        log.warning("Couldn't read the webhook URL back from Telegram", exc_info=True)
        return None
    url = (info.url or "").strip() or None
    runtime.runtime.webhook_url = url
    return url


async def _restore_telegram_config(chat_id: int, bot) -> str | None:
    """Put the bot's own settings back after the reset that wiped them. Returns a line to show.

    Only the fields that are actually empty are written. `SettingsService.update` treats a
    null field as "leave it alone" and an empty string as "clear it", so a PUT carrying just
    these two keys cannot disturb the income or the tracking-start month — but reading first
    also means a URL the owner changed in the web app between the reset and this signup is not
    overwritten by the one this process booted with.
    """
    web_view = runtime.runtime.web_view_url
    webhook = await _webhook_url(bot)

    try:
        settings = await api.request(chat_id, "GET", "/settings") or {}
    except Exception:  # noqa: BLE001
        # The rescue matters more than the read: assume both are missing and write what we have.
        log.warning("Couldn't read /settings before restoring the Telegram config", exc_info=True)
        settings = {}

    stored_hook = (settings.get("telegramWebhookUrl") or "").strip()
    stored_view = (settings.get("telegramWebViewUrl") or "").strip()

    payload: dict[str, str] = {}
    if webhook and not stored_hook:
        payload["telegramWebhookUrl"] = webhook
    if web_view and not stored_view:
        payload["telegramWebViewUrl"] = web_view

    if not payload:
        # Nothing to write. The one case worth shouting about is the crash-loop: no stored
        # webhook URL and no way to work out what it should be.
        if not stored_hook and not webhook:
            return t(chat_id, "auth.webhookUnknown")
        return None

    try:
        await api.request(chat_id, "PUT", "/settings", json=payload)
    except Exception:  # noqa: BLE001
        log.exception("Couldn't restore the Telegram config after signup")
        return t(chat_id, "auth.configRestoreFailed", url=esc(webhook or stored_hook or "—"))
    log.info("Restored the Telegram config wiped by the reset: %s", ", ".join(sorted(payload)))
    return t(chat_id, "auth.configRestored")


def _login_nav(chat_id: int, *, back: bool) -> InlineKeyboardMarkup:
    """Cancel on every step of the typed flow, Back once there is a step to go back to."""
    return ui.ikb([ui.nav(chat_id, back="auth:back" if back else None, cancel="auth:cancel")])


async def _ask_username(event: TelegramObject, state: FSMContext) -> None:
    """Step one of the typed flow, and the target of the password step's Back button."""
    chat_id = common.chat_id_of(event)
    first_run = await _needs_signup()
    await state.set_state(Auth.username)
    # Remembered so the password prompt can say "pick" rather than "enter"; the branch that
    # actually decides signup-vs-login is re-checked against the backend in `got_password`.
    await state.update_data(signup=bool(first_run))
    key = "auth.chooseUsername" if first_run else "auth.enterUsername"
    await common.show(event, t(chat_id, key), _login_nav(chat_id, back=False))


# ── Commands ────────────────────────────────────────────────────────────────
# All of them above the two state handlers: registration order is what decides, and /lock was
# the one that lost that lottery — typed at the "send your username" prompt it was stored as
# the username, and the next thing typed became the password of an account named "/lock".
@router.message(CommandStart())
async def start(message: Message, state: FSMContext) -> None:
    await state.clear()
    chat_id = message.chat.id
    if store.is_active(chat_id):
        await home.show_home(message)
        return
    if await _needs_signup():
        # First run — the account does not exist yet, so this screen is not an invitation to
        # log in, it is a warning that the next two messages create the owner of the account.
        await common.show(message, t(chat_id, "auth.welcomeFirstRun"),
                          ui.ikb([[(t(chat_id, "auth.setupButton"), "auth:login")]]))
        return
    await common.show(message, t(chat_id, "auth.welcome"), keyboards.login_kb(chat_id))


@router.message(Command("menu"))
async def menu_cmd(message: Message, state: FSMContext) -> None:
    await state.clear()
    await _home_or_login(message)


@router.message(Command("cancel"))
async def cancel_cmd(message: Message, state: FSMContext) -> None:
    await state.clear()
    await _home_or_login(message, t(message.chat.id, "common.cancelled"))


@router.message(Command("lock"))
async def lock_cmd(message: Message, state: FSMContext) -> None:
    chat_id = message.chat.id
    store.lock(chat_id)
    await state.clear()
    await common.show(message, t(chat_id, "auth.locked"), keyboards.login_kb(chat_id))


@router.message(Command("login"))
async def login_cmd(message: Message, state: FSMContext) -> None:
    await _ask_username(message, state)


# ── The typed flow ──────────────────────────────────────────────────────────
@router.message(StateFilter(Auth.username), _not_a_command)
async def got_username(message: Message, state: FSMContext) -> None:
    chat_id = message.chat.id
    username = (message.text or "").strip()
    if not username:
        # A sticker, a photo, a forwarded contact. Re-ask rather than storing "" and letting
        # the backend answer "Username is required." two messages later.
        await common.show(message, t(chat_id, "auth.usernameNeeded"), _login_nav(chat_id, back=False))
        return
    data = await state.get_data()
    await state.update_data(username=username)
    await state.set_state(Auth.password)
    key = "auth.choosePassword" if data.get("signup") else "auth.enterPassword"
    await common.show(message, t(chat_id, key), _login_nav(chat_id, back=True))


@router.message(StateFilter(Auth.password), _not_a_command)
async def got_password(message: Message, state: FSMContext) -> None:
    chat_id = message.chat.id
    data = await state.get_data()
    username = data.get("username", "")
    password = message.text or ""
    if not password:
        await common.show(message, t(chat_id, "auth.passwordNeeded"), _login_nav(chat_id, back=True))
        return

    # Delete first, and only once we know there is a password in it — deleting a photo the
    # owner sent by mistake would be its own small betrayal.
    kept = not await _delete_quietly(message)
    warnings: list[str] = [t(chat_id, "auth.passwordNotDeleted")] if kept else []

    # The password message has just vanished from the chat; without this the screen would sit
    # empty for as long as the server spends on bcrypt.
    await common.begin_write(message, chat_id)
    try:
        created = bool((await api.auth_status()).get("needsSignup"))
        tokens = await api.signup(username, password) if created else await api.login(username, password)
    except api.Unreachable:
        await state.clear()
        await common.show(message, _joined(t(chat_id, "common.serverUnreachable"), warnings),
                          keyboards.login_kb(chat_id))
        return
    except api.ApiError as exc:
        await state.clear()
        body = f"{_api_error(chat_id, exc)}\n\n{t(chat_id, 'auth.tryAgain')}"
        await common.show(message, _joined(body, warnings), keyboards.login_kb(chat_id))
        return
    except Exception:  # noqa: BLE001
        log.exception("Login failed for chat %s", chat_id)
        await state.clear()
        await common.show(message, _joined(t(chat_id, "auth.serverUnreachable"), warnings),
                          keyboards.login_kb(chat_id))
        return

    store.start(chat_id, username, tokens["accessToken"], tokens["refreshToken"])
    await state.clear()

    # `start()` binds the owner, and the return value here is the owner it ended up with —
    # not necessarily this chat. Only one arrangement produces a difference: nobody was bound
    # when the guard let this update in, and another chat finished authenticating while we
    # were awaiting the backend. That chat owns the bot now, so drop the session this one just
    # got rather than leaving a live token pair in memory.
    owner = store.bind_owner(chat_id)
    if owner != chat_id:
        store.lock(chat_id)
        log.warning("Chat %s authenticated, but chat %s had already claimed this bot — "
                    "session dropped.", chat_id, owner)
        await common.show(message, t(chat_id, "common.notForYou"))
        return
    log.info("Login OK for chat %s — this bot is owned by chat %s. Pin it with "
             "OWNER_CHAT_ID=%s in .env so a restart cannot reopen the window.",
             chat_id, owner, owner)

    if created:
        # This signup either founded the install or followed a factory reset. Either way the
        # settings row is empty, which is why the config rescue and the income prompt both
        # hang off this branch and not off an ordinary login.
        note = await _restore_telegram_config(chat_id, message.bot)
        if note:
            warnings.append(note)
        warnings.append(t(chat_id, "auth.setIncomeNext"))
        kb = keyboards.income_guard_kb(chat_id)
    else:
        kb = None

    body = t(chat_id, "auth.loginSuccess",
             verb=t(chat_id, "auth.accountCreated" if created else "auth.loggedIn"),
             username=esc(username))
    if kb is None:
        # An ordinary login lands on Home, with the greeting above it.
        await home.show_home(message, _joined(body, warnings))
        return
    await common.show(message, _joined(body, warnings), kb)


@router.message(StateFilter(Auth.username, Auth.password), _unknown_command)
async def command_during_login(message: Message, state: FSMContext) -> None:
    """A command nothing in the bot handles, typed mid-login.

    Registered after the two state handlers, which it can never collide with (they refuse
    command-shaped text and this one requires it). Without it an unknown command would fall
    past every router — `record`'s catch-all is `StateFilter(None)` — and vanish, which is a
    worse failure than the swallowing this filter arrangement exists to fix.
    """
    chat_id = message.chat.id
    current = await state.get_state()
    await common.show(
        message,
        t(chat_id, "auth.commandDuringLogin", cmd=esc(_command_name(message.text) or "")),
        _login_nav(chat_id, back=current == Auth.password.state))


# ── Callbacks ───────────────────────────────────────────────────────────────
@router.callback_query(F.data == "auth:login")
async def login_cb(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    await _ask_username(cb, state)


@router.callback_query(F.data == "auth:back")
async def back_cb(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    await _ask_username(cb, state)


@router.callback_query(F.data == "auth:cancel")
async def cancel_cb(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    await state.clear()
    await _home_or_login(cb, t(common.chat_id_of(cb), "common.cancelled"))


@router.callback_query(F.data == "lock")
async def lock_cb(cb: CallbackQuery, state: FSMContext) -> None:
    chat_id = common.chat_id_of(cb)
    store.lock(chat_id)
    await state.clear()
    await common.ack(cb, t(chat_id, "auth.lockedToast"))
    await common.show(cb, t(chat_id, "auth.locked"), keyboards.login_kb(chat_id))
