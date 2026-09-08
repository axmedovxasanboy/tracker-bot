"""Build the Dispatcher, wire routers, and run in WEBHOOK mode.

Telegram pushes updates to a public HTTPS URL (no polling). That URL and the web-view URL
are configured in the web app's Developer page, stored in the backend, and fetched here at
startup via GET /settings/telegram. The bot runs a small aiohttp server (bind host/port from
env) and registers the webhook on boot. To stop all Telegram traffic, stop the process.

This module also owns the things that are true of the bot as a whole rather than of any one
screen: who is allowed to talk to it (`middlewares`), what happens when a handler throws
(`errors`), the /help screen that makes the command surface discoverable at all, and the two
commands that have to outrank every open form — /help and /add — which is a property of the
router ORDER and so cannot live in the router that draws their screens.
"""
import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlparse

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import SimpleEventIsolation
from aiogram.types import BotCommand, CallbackQuery, MenuButtonCommands, Message
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

from . import api, common, errors, keyboards, middlewares, runtime
from .config import (BOT_TOKEN, OWNER_CHAT_ID, REMINDERS_ENABLED, WEBHOOK_HOST, WEBHOOK_PATH,
                     WEBHOOK_PORT, WEBHOOK_SECRET)
from .i18n import system as system_strings
from .i18n import t
from .routers import (auth, cards, categories, finance, menu, months, quickadd, transactions,
                      wizard)
from .states import QuickAdd

# The reminder loop is optional by construction: it is the one part of the bot that sends
# messages nobody asked for, and a scheduler that fails to import must not be the reason the
# owner cannot record an expense.
try:
    from . import reminders
except Exception as exc:  # noqa: BLE001
    reminders = None
    _reminders_import_error: Exception | None = exc
else:
    _reminders_import_error = None

logger = logging.getLogger("tracker-bot")

# The blue command menu, in the order Telegram lists it. Each name also indexes
# `system.cmd.<name>` in bot/i18n/system.py, which is what /help prints, so the menu and the
# help screen cannot describe the same command differently.
COMMANDS = ("start", "add", "menu", "help", "lock", "cancel")

# How long shutdown waits for updates that are already running. Long enough for a month-close
# to finish its POST and tell the owner what it did; short enough that `docker stop` does not
# reach its own 10 s grace and SIGKILL the process mid-write.
SHUTDOWN_GRACE = 8.0

# The two commands that have to work when the owner is stuck: /help and /add. Included FIRST
# (see main) so neither can be swallowed by a state-filtered text handler the way /lock was
# swallowed by the login prompt.
router = Router(name="system")

# The states quick add runs in, as the dispatcher spells them ("QuickAdd:confirm", …). Read
# from the group rather than written out, so renaming a state cannot silently turn the check
# below into "always clear".
_QUICKADD_STATES = frozenset(member.state for member in QuickAdd.__all_states__)


def _help_text(chat_id: int | None) -> str:
    """The /help screen: what the bot does, what each command is for, and how to get out.

    Section names come from `menu.page.*` rather than being written out here, so a screen the
    web app renamed (Dashboard→Home, Overview→Plan, Cards→Wallets) cannot be described in
    /help by a word that is no longer on its button.
    """
    sections = (
        ("system.help.home", "menu.page.dashboard"),
        ("system.help.plan", "menu.page.overview"),
        ("system.help.months", "menu.page.months"),
        ("system.help.transactions", "menu.page.transactions"),
        ("system.help.wallets", "menu.page.cards"),
        ("system.help.finance", "menu.page.finance"),
        ("system.help.categories", "menu.page.categories"),
        ("system.help.settings", "menu.page.settings"),
    )
    lines = [t(chat_id, "system.help.title"), "", t(chat_id, "system.help.intro"), "",
             t(chat_id, "system.help.sectionsTitle")]
    lines += [t(chat_id, key, name=t(chat_id, page)) for key, page in sections]
    lines += ["", t(chat_id, "system.help.commandsTitle")]
    lines += [t(chat_id, "system.help.cmdLine", cmd=name, desc=t(chat_id, f"system.cmd.{name}"))
              for name in COMMANDS]
    lines += ["", t(chat_id, "system.help.quickTitle"), t(chat_id, "system.help.quick"),
              "", t(chat_id, "system.help.stuck")]
    return "\n".join(lines)


# No auth gate and no state clearing on either handler: /help is the screen a stuck user
# reaches for, and it would be a poor rescue if it demanded a login or threw away the form
# they are halfway through.
@router.message(Command("help"))
async def help_cmd(message: Message) -> None:
    chat_id = common.chat_id_of(message)
    await common.show(message, _help_text(chat_id), keyboards.back_menu_kb(chat_id))


@router.callback_query(F.data == "sys:help")
async def help_cb(cb: CallbackQuery) -> None:
    chat_id = common.chat_id_of(cb)
    await common.ack(cb)
    await common.show(cb, _help_text(chat_id), keyboards.back_menu_kb(chat_id))


# ── /add ────────────────────────────────────────────────────────────────────
# The screens live in `quickadd`, which is included LAST because it ends in a bare-text
# catch-all — right for the catch-all, and fatal for the command. By the time the dispatcher
# reaches the last router it has already offered the update to twenty-odd state-filtered
# `@router.message` handlers, and only auth.py checks whether what it is about to store is a
# command (its `_DOWNSTREAM_COMMANDS` whitelists "add" precisely so it falls through). So
# `/add` tapped from the blue menu at "Send the category name" was saved as a category called
# "/add"; at a description step it became a transaction's description; at the reset prompt it
# was POSTed to /settings/reset as the password. Every other published command works from
# anywhere for one reason only — it is registered on a router included before those handlers.
#
# So the ENTRY POINT moves here, to the router included first, and delegates. The two do not
# have to share a router: `quickadd.add_cmd` is an ordinary coroutine, and its own
# registration stays where it is as a harmless second line of defence. The argument form is
# preserved because the same coroutine parses it: bare `/add` opens the quick-add screen,
# `/add 50000 lunch` goes straight to a filled draft.
@router.message(Command("add"))
async def add_cmd(message: Message, state: FSMContext, command: CommandObject) -> None:
    """Quick add, reachable from every state.

    Gate first, clear second. Someone who types /add at the login prompt should be told to log
    in and still have the half-finished login they were in the middle of; `gate` renders that
    screen and returns False before anything is thrown away.

    Then a flow left open elsewhere is ended, because quick add is an escape from it and not a
    step inside it: without this, `/add` typed halfway through the month close would draw the
    draft card over a flow whose next typed message is still read as a wallet balance. Quick
    add's own states are the exception — replacing one draft with another is exactly what
    `_new_draft` does, and clearing here would throw away the `qa_ui` message id it uses to
    take the buttons off the card it is superseding.
    """
    if not await common.gate(message):
        return
    current = await state.get_state()
    if current is not None and current not in _QUICKADD_STATES:
        await state.clear()
    await quickadd.add_cmd(message, state, command)


def _commands(table: dict[str, str]) -> list[BotCommand]:
    """One language's command list. Descriptions are plain text — Telegram parses no HTML."""
    return [BotCommand(command=name, description=table[f"system.cmd.{name}"])
            for name in COMMANDS]


async def _register_commands(bot: Bot) -> None:
    """Publish the command list and make the ☰ button show it.

    `language_code="uz"` is matched against the *Telegram client's* language, not the bot's
    own per-chat toggle; there is no per-chat scope for a command list short of one API call
    per chat on every language switch, so the blue menu follows the phone and the screens
    follow the toggle.

    The menu button is set unconditionally, and to `MenuButtonCommands` rather than the Web
    App button this used to install. Two reasons. A Web App menu button REPLACES the command
    list in the UI, and the commands are the only rescue for someone stranded mid-flow — the
    web app is still one tap away as the "Open App" button at the top of the main menu. And
    `setChatMenuButton` stores state on Telegram's side that outlives the process: skipping
    the call when no web-view URL is configured is not the same as clearing it, which is how
    a stale "Open App" ends up pointing at a URL that died months ago.
    """
    await bot.set_my_commands(_commands(system_strings.EN))
    await bot.set_my_commands(_commands(system_strings.UZ), language_code="uz")
    await bot.set_chat_menu_button(menu_button=MenuButtonCommands())


def _load_config() -> tuple[str, str | None]:
    """Fetch the webhook + web-view URLs from the backend (one-shot, before the server starts)."""
    try:
        cfg = asyncio.run(api.telegram_config())
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(
            f"Couldn't read Telegram config from the backend ({exc}). "
            "Is the backend running, and is API_BASE_URL correct?"
        ) from exc
    webhook_url = (cfg.get("webhookUrl") or "").strip()
    web_view_url = (cfg.get("webViewUrl") or "").strip() or None
    if not webhook_url:
        raise SystemExit(
            "No webhook URL configured. Open the web app → Developer → set the Webhook URL "
            "(a public HTTPS URL Telegram can reach), then restart the bot."
        )
    return webhook_url, web_view_url


def _announce_security(webhook_url: str) -> None:
    """Say plainly, at every boot, which of the two doors is standing open."""
    if not WEBHOOK_SECRET:
        bar = "!" * 78
        logger.warning(bar)
        logger.warning("WEBHOOK_SECRET is empty. aiogram's verify_secret() then returns True "
                       "for every request without looking at the header, so %s is an "
                       "unauthenticated endpoint into the dispatcher: anyone who learns it can "
                       "post updates that this bot will act on as if they were yours.",
                       webhook_url)
        logger.warning("Generate one:  python -c \"import secrets; print(secrets.token_urlsafe(32))\"")
        logger.warning("Put it in .env as WEBHOOK_SECRET and restart — Telegram echoes it back "
                       "in the X-Telegram-Bot-Api-Secret-Token header and the server checks it.")
        logger.warning(bar)

    if OWNER_CHAT_ID is not None:
        logger.info("Owner guard: serving chat_id=%s and refusing everyone else.", OWNER_CHAT_ID)
    else:
        logger.warning("OWNER_CHAT_ID is not set — the first chat that logs in claims this bot "
                       "for the life of the process, and every other chat is refused from then "
                       "on. Pin your own id in .env to close that window across restarts.")


async def _quietly(what: str, action: Callable[..., Awaitable[Any]], *args: Any) -> None:
    """Run one shutdown step. A cleanup that raises must not skip the cleanups after it."""
    try:
        await action(*args)
    except Exception:  # noqa: BLE001
        logger.warning("Shutdown: couldn't %s", what, exc_info=True)


def main() -> None:
    if not BOT_TOKEN:
        raise SystemExit("BOT_TOKEN is required (get one from @BotFather). Set it in .env.")

    webhook_url, web_view_url = _load_config()
    runtime.runtime.web_view_url = web_view_url
    # Listen on the path of the configured public URL so the two can't drift; fall back to env.
    path = urlparse(webhook_url).path or WEBHOOK_PATH
    secret = WEBHOOK_SECRET or None
    _announce_security(webhook_url)

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    # SimpleEventIsolation takes a per-chat lock around each update, so a second tap cannot
    # start until the first has finished. Without it the dispatcher's default is
    # DisabledEventIsolation and every update runs in its own detached task
    # (SimpleRequestHandler defaults to handle_in_background=True), so a double tap on Confirm
    # ran two handlers concurrently: both read the same FSM state, both passed the same
    # StateFilter, and both POSTed. Removing the keyboard is not a guard — the edit that
    # removes it is a round trip that lands well after the second tap. This closes the race
    # for every confirm button in the bot at once rather than one handler at a time.
    dp = Dispatcher(events_isolation=SimpleEventIsolation())
    # Before any router: refuse chats that are not the owner's, and make sure a handler that
    # throws still reaches the person who tapped the button.
    middlewares.setup(dp)
    errors.setup(dp)

    # Order matters at both ends. `system` first, because /help and /add must outrank the
    # state-filtered text handlers that would otherwise eat them — a command that only works
    # when you are not stuck is no use to someone who is, and a swallowed /add is written into
    # whatever field was open. `quickadd` LAST, because it ends in a bare text handler that
    # answers anything typed at the menu; a router after it would never see a typed message
    # again. That pair is why /add is entered from `system` and delegated (see add_cmd): the
    # command needs to be first and the catch-all needs to be last, and one router cannot be
    # both. In between, the original order — auth (start/login/lock/cancel) → menu
    # (navigation) → wizard (shared create steps) → the section routers — which state filters
    # keep unambiguous anyway.
    for r in (router, auth.router, menu.router, wizard.router,
              transactions.router, finance.router, cards.router, categories.router,
              months.router, quickadd.router):
        dp.include_router(r)

    handler = SimpleRequestHandler(dispatcher=dp, bot=bot, secret_token=secret)
    reminders_task: asyncio.Task[Any] | None = None

    async def on_startup() -> None:
        nonlocal reminders_task
        await bot.set_webhook(
            url=webhook_url,
            secret_token=secret,
            # Not dropped. Telegram queues updates while the container is down, and throwing
            # that queue away is what makes a tap sent during a redeploy vanish without trace.
            # The FSM lives in memory and is empty after a restart, so a replayed multi-step
            # confirm cannot complete; a replayed navigation tap just redraws a screen.
            drop_pending_updates=False,
            allowed_updates=dp.resolve_used_update_types(),
        )
        # Cosmetic next to the webhook, and allowed to fail as such: a flood-limited command
        # list is not a reason to refuse to serve.
        await _quietly("register the command menu", _register_commands, bot)
        if reminders is not None:
            try:
                # Held for the life of the process: asyncio keeps only a weak reference to a
                # task, so a loop nobody holds can be collected mid-sleep and simply stop.
                reminders_task = await reminders.start(bot)
            except Exception:  # noqa: BLE001
                logger.exception("Reminders failed to start — the bot carries on without them.")
            else:
                logger.info("Reminders: %s", "running" if reminders_task else "disabled")
        elif REMINDERS_ENABLED:
            # Only worth a warning when the owner actually asked for reminders and is not
            # going to get any; with the feature off, a missing module is not news.
            logger.warning("REMINDERS_ENABLED is set but bot/reminders.py did not import (%s) "
                           "— nothing will be sent.", _reminders_import_error)
        logger.info("Webhook registered: %s", webhook_url)

    async def on_shutdown() -> None:
        # 1. Stop the inflow first, so nothing new starts while we are draining. Telegram then
        #    holds updates instead of hammering a dying upstream, and delivers them on boot.
        await _quietly("delete the webhook", bot.delete_webhook)
        if reminders is not None:
            await _quietly("stop the reminder loop", reminders.stop)

        # 2. Let the updates already in flight finish. They are detached background tasks, not
        #    open HTTP requests — aiohttp's own shutdown does not know about them and closes
        #    the Bot session out from under them. That is how a month-close commits at the
        #    backend and then never gets to tell the owner it did.
        pending = [task for task in getattr(handler, "_background_feed_update_tasks", ())
                   if not task.done()]
        if pending:
            logger.info("Waiting up to %.0fs for %d update(s) still running…",
                        SHUTDOWN_GRACE, len(pending))
            _, still_running = await asyncio.wait(pending, timeout=SHUTDOWN_GRACE)
            if still_running:
                logger.warning("%d update(s) did not finish in time and will be cancelled.",
                               len(still_running))

        # 3. Only now let the connection pool go; step 2 was still using it.
        await _quietly("close the API client", api.aclose)

    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    app = web.Application()
    # setup_application BEFORE handler.register: aiohttp fires on_shutdown callbacks in
    # registration order, and `register` appends the one that closes the Bot session. Putting
    # the dispatcher's hooks in first is what lets the drain above run while the session is
    # still open.
    setup_application(app, dp, bot=bot)
    handler.register(app, path=path)

    logger.info("Tracker bot starting (webhook) — listening on %s:%s%s", WEBHOOK_HOST, WEBHOOK_PORT, path)
    web.run_app(app, host=WEBHOOK_HOST, port=WEBHOOK_PORT)
