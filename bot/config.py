"""Environment-backed settings, read once at import and validated here.

Parsing lives in this one module on purpose. The bot is deployed by editing a `.env` on a
VPS and running `docker compose up -d`, so a typo goes straight to production; parsed at the
call site it would surface either as a wrong default nobody notices or as a ValueError
inside a handler — and aiogram runs handlers in a detached task, so that traceback dies in
the log with the user staring at a spinning button. A bad value here stops the boot instead,
with one sentence naming the variable and what it wants.

`LOG_LEVEL` is deliberately absent: run.py reads it directly, before this module is
imported, so that the failures above are themselves formatted and logged.
"""
import os

from dotenv import load_dotenv

load_dotenv()


def _raw(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _bad(name: str, raw: str, wants: str) -> SystemExit:
    # SystemExit, not ValueError: run.py logs the message and exits non-zero, so `docker logs`
    # shows one actionable line rather than a traceback through dotenv's internals.
    return SystemExit(f"{name}={raw!r} is invalid — {wants}. Fix it in .env and restart.")


def _number(name: str, default: str, *, low: float, high: float) -> float:
    raw = _raw(name) or default
    try:
        value = float(raw)
    except ValueError:
        raise _bad(name, raw, f"expected a number between {low} and {high}") from None
    if not low <= value <= high:
        raise _bad(name, raw, f"expected a number between {low} and {high}")
    return value


def _int(name: str, default: str, *, low: int, high: int) -> int:
    raw = _raw(name) or default
    try:
        value = int(raw)
    except ValueError:
        raise _bad(name, raw, f"expected a whole number between {low} and {high}") from None
    if not low <= value <= high:
        raise _bad(name, raw, f"expected a whole number between {low} and {high}")
    return value


def _bool(name: str, default: bool) -> bool:
    raw = _raw(name).lower()
    if not raw:
        return default
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    raise _bad(name, raw, "expected true or false")


BOT_TOKEN = _raw("BOT_TOKEN")
API_BASE_URL = _raw("API_BASE_URL", "http://localhost:8080/api/v1").rstrip("/")
# httpx rejects a schemeless base URL with "Request URL is missing an 'http://' or 'https://'
# protocol", which main.py then reports as "Couldn't read Telegram config from the backend" —
# i.e. it sends the owner to check the backend when the fault is one missing word in .env.
if not API_BASE_URL.startswith(("http://", "https://")):
    raise _bad("API_BASE_URL", API_BASE_URL,
               "expected an absolute URL, e.g. http://backend:8080/api/v1")

SESSION_TTL_HOURS = _number("SESSION_TTL_HOURS", "24", low=0.05, high=8760)
REQUEST_TIMEOUT = _number("API_TIMEOUT", "10", low=1, high=300)
# The bot is UZS-only (multi-currency/FX support was removed). The backend's Currency enum
# accepts only "UZS", but request payloads still carry the field, so this constant is stamped
# into every outgoing "currency" key.
CURRENCY = "UZS"

# --- Time (see bot/clock.py) ---
# Hours ahead of UTC the owner lives in. Tashkent is UTC+5 and Uzbekistan abolished DST in
# 1995, so a fixed offset is the whole rule — no zoneinfo lookup, no tzdata in the image.
# This is NOT the container's TZ variable: TZ only decides how the OS renders local time,
# while every date the bot writes to the API comes from this offset.
TZ_OFFSET_HOURS = _number("TZ_OFFSET_HOURS", "5", low=-12, high=14)

# --- Access control ---
# Tracker is single-user. When this is set, only that chat is served; when it is not, the
# first chat to log in successfully claims the bot for the life of the process. Pin it here
# once you know it — the bound id is logged at INFO. 0 reads as unset; no chat has id 0.
_owner = _raw("OWNER_CHAT_ID")
try:
    OWNER_CHAT_ID: int | None = (int(_owner) or None) if _owner else None
except ValueError:
    raise _bad("OWNER_CHAT_ID", _owner,
               "expected a numeric Telegram chat id (@userinfobot will tell you yours)") from None

# --- Staying logged in (see bot/storage.py) ---
# The owner's login, language and reminder history are kept in this file so a restart does not
# log them out — but only when OWNER_CHAT_ID pins who the owner is. In Docker, put it on a
# volume (DEPLOY.md). Set STAY_LOGGED_IN=false to go back to logins that live in memory only
# and expire after SESSION_TTL_HOURS.
STAY_LOGGED_IN = _bool("STAY_LOGGED_IN", True)
SESSION_FILE = _raw("SESSION_FILE", "data/session.json")

# --- The evening advisor message (bot/reminders.py) ---
# On by default: the owner asked the advisor to message them. It still needs to know whose chat
# to write to — OWNER_CHAT_ID, or the chat that logged in — and says nothing until then.
REMINDERS_ENABLED = _bool("REMINDERS_ENABLED", True)
# Local hour (in TZ_OFFSET_HOURS terms, not UTC) reminders are delivered at.
REMINDER_HOUR = _int("REMINDER_HOUR", "21", low=0, high=23)

# --- Webhook (the bot runs an aiohttp server; Telegram pushes updates to it) ---
# The PUBLIC webhook URL + the web-view URL are NOT set here — they live in the backend
# (Settings → Developer page) and are fetched at startup via GET /settings/telegram.
# These env vars only control the LOCAL aiohttp server bind + the shared secret.
WEBHOOK_HOST = _raw("WEBHOOK_HOST", "0.0.0.0")
WEBHOOK_PORT = _int("WEBHOOK_PORT", "8081", low=1, high=65535)
# Fallback path the aiohttp server listens on. If the configured public webhook URL has a
# path, that path is used instead (so the two can't drift). Default keeps things working
# when the public URL is just a host.
WEBHOOK_PATH = _raw("WEBHOOK_PATH", "/webhook") or "/webhook"
if not WEBHOOK_PATH.startswith("/"):
    # aiohttp's UrlDispatcher raises on a relative path; repairing it beats failing the boot
    # over a missing slash the owner cannot see in the error.
    WEBHOOK_PATH = "/" + WEBHOOK_PATH
# The PUBLIC URL Telegram delivers to, and the web-view URL — normally set on the web app's
# Developer page and read from the backend at boot. These env vars are the FLOOR under that:
# the stored copy lives in the `settings` row, which a factory reset TRUNCATEs, and the bot
# reads it before it can serve anything. Without a fallback a wiped database is a bot that
# cannot boot and cannot be reconfigured from Telegram. The backend still wins when it has a
# value, so the Developer page keeps working exactly as before.
WEBHOOK_URL = _raw("WEBHOOK_URL")
if WEBHOOK_URL and not WEBHOOK_URL.startswith("https://"):
    # Telegram refuses a non-HTTPS webhook outright, and set_webhook's failure names the URL
    # rather than the variable it came from.
    raise _bad("WEBHOOK_URL", WEBHOOK_URL,
               "expected a public HTTPS URL, e.g. https://bot.example.dev/webhook")
WEB_VIEW_URL = _raw("WEB_VIEW_URL")
if WEB_VIEW_URL and not WEB_VIEW_URL.startswith("https://"):
    raise _bad("WEB_VIEW_URL", WEB_VIEW_URL,
               "expected a public HTTPS URL (Telegram rejects http for a Web App)")

# Telegram echoes this in the X-Telegram-Bot-Api-Secret-Token header. REQUIRED in production:
# aiogram's verify_secret returns True unconditionally when it is blank, so an empty secret
# means anyone who learns the public URL can POST forged updates to the bot.
WEBHOOK_SECRET = _raw("WEBHOOK_SECRET")
