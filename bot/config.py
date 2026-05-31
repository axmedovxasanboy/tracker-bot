"""Environment-backed settings."""
import os

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8080/api/v1").strip().rstrip("/")
SESSION_TTL_HOURS = float(os.environ.get("SESSION_TTL_HOURS", "24"))
REQUEST_TIMEOUT = float(os.environ.get("API_TIMEOUT", "10"))
DEFAULT_CURRENCY = os.environ.get("DEFAULT_CURRENCY", "UZS").strip().upper()
CURRENCIES = ("UZS", "USD", "EUR")

# --- Webhook (the bot runs an aiohttp server; Telegram pushes updates to it) ---
# The PUBLIC webhook URL + the web-view URL are NOT set here — they live in the backend
# (Settings → Developer page) and are fetched at startup via GET /settings/telegram.
# These env vars only control the LOCAL aiohttp server bind + the shared secret.
WEBHOOK_HOST = os.environ.get("WEBHOOK_HOST", "0.0.0.0").strip()
WEBHOOK_PORT = int(os.environ.get("WEBHOOK_PORT", "8081"))
# Fallback path the aiohttp server listens on. If the configured public webhook URL has a
# path, that path is used instead (so the two can't drift). Default keeps things working
# when the public URL is just a host.
WEBHOOK_PATH = os.environ.get("WEBHOOK_PATH", "/webhook").strip() or "/webhook"
# Telegram echoes this in the X-Telegram-Bot-Api-Secret-Token header; the server rejects
# mismatches. Leave blank to disable the check (fine for local testing).
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "").strip()
