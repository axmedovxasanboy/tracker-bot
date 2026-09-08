"""Runtime config fetched from the backend at startup (not from env).

The web-view URL is set in the web app's Developer page, stored in the backend, and read
once when the bot boots. Keyboards read it from here to add the "Open App" Web App button.

The webhook URL lives here for a less obvious reason: a factory reset TRUNCATEs the settings
table (ResetService.TRUNCATE_ALL names it explicitly), and `telegram_webhook_url` is the value
main.py reads at boot. Once it is gone the next start raises SystemExit and the container
crash-loops, recoverable only from the web app. `bot/routers/auth.py` writes both URLs back
after the signup that follows a reset, and this is where it looks for them.
"""
from dataclasses import dataclass


@dataclass
class Runtime:
    web_view_url: str | None = None
    #: The public URL Telegram posts updates to. main.py knows it at boot but has no reason to
    #: publish it, so this is filled in lazily by the first caller that needs it, from
    #: `getWebhookInfo` — Telegram is the authority on where it is actually delivering.
    webhook_url: str | None = None


# Shared singleton, populated in main.py during startup.
runtime = Runtime()
