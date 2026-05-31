"""Build the Dispatcher, wire routers, and run in WEBHOOK mode.

Telegram pushes updates to a public HTTPS URL (no polling). That URL and the web-view URL
are configured in the web app's Developer page, stored in the backend, and fetched here at
startup via GET /settings/telegram. The bot runs a small aiohttp server (bind host/port from
env) and registers the webhook on boot. To stop all Telegram traffic, stop the process.
"""
import asyncio
import logging
from urllib.parse import urlparse

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import MenuButtonWebApp, WebAppInfo
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

from . import api, runtime
from .config import (BOT_TOKEN, WEBHOOK_HOST, WEBHOOK_PATH, WEBHOOK_PORT, WEBHOOK_SECRET)
from .routers import auth, cards, categories, finance, menu, transactions, wizard

logger = logging.getLogger("tracker-bot")


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


def main() -> None:
    if not BOT_TOKEN:
        raise SystemExit("BOT_TOKEN is required (get one from @BotFather). Set it in .env.")

    webhook_url, web_view_url = _load_config()
    runtime.runtime.web_view_url = web_view_url
    # Listen on the path of the configured public URL so the two can't drift; fall back to env.
    path = urlparse(webhook_url).path or WEBHOOK_PATH
    secret = WEBHOOK_SECRET or None

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    # Order: auth (start/login/cancel/lock) → menu (navigation) → wizard (shared create steps)
    # → section routers. State filters keep the right handler active anyway.
    for r in (auth.router, menu.router, wizard.router,
              transactions.router, finance.router, cards.router, categories.router):
        dp.include_router(r)

    async def on_startup() -> None:
        await bot.set_webhook(
            url=webhook_url,
            secret_token=secret,
            drop_pending_updates=True,
            allowed_updates=dp.resolve_used_update_types(),
        )
        # Persistent ☰ menu button → opens the web app (HTTPS only; Telegram rejects http).
        if web_view_url and web_view_url.startswith("https://"):
            await bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(text="Open App", web_app=WebAppInfo(url=web_view_url)))
        logger.info("Webhook registered: %s", webhook_url)

    dp.startup.register(on_startup)

    app = web.Application()
    SimpleRequestHandler(dispatcher=dp, bot=bot, secret_token=secret).register(app, path=path)
    setup_application(app, dp, bot=bot)

    logger.info("Tracker bot starting (webhook) — listening on %s:%s%s", WEBHOOK_HOST, WEBHOOK_PORT, path)
    web.run_app(app, host=WEBHOOK_HOST, port=WEBHOOK_PORT)
