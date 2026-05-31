# Tracker — Telegram Bot (aiogram)

A native Telegram client for the Tracker API, built with **aiogram v3**. The bot logs into the
Spring Boot backend with your account and drives everything through inline-button menus
mirroring the web app's 7 pages.

## Structure

```
tracker-telegram-bot/
├── run.py                # launcher: python run.py
├── requirements.txt
├── .env.example
└── bot/
    ├── config.py         # env settings
    ├── session.py        # in-memory sessions (24h TTL + /lock) + currency prefs + store singleton
    ├── api.py            # httpx API client: auth + request() with 401→refresh
    ├── keyboards.py      # inline keyboards + money/percent formatting
    ├── common.py         # show() (edit-or-send) + gate() (auth guard)
    ├── states.py         # FSM StatesGroups
    ├── runtime.py        # startup-fetched config (web-view URL) shared with keyboards
    ├── main.py           # Dispatcher + router wiring + webhook (aiohttp) server
    └── routers/
        ├── auth.py       # /start, typed login/signup, /lock, /menu, /cancel
        ├── menu.py       # main menu, Dashboard, Overview, Settings (currency)
        ├── wizard.py     # generic field-stepper create flow (shared)
        ├── transactions.py
        ├── finance.py
        ├── cards.py
        └── categories.py
```

## Features

- Typed **login / signup** (auto-detects first-run signup vs login), **24h session**, `/lock`.
- **Dashboard**, **Overview** (tier + allocation), **Settings** (currency → display + default).
- **Transactions**: add (guided), recent + delete, exchange, bulk add.
- **Finance**: read views for all 7 sections, repay / mark-returned / pay, and create.
- **Cards**: list, view, delete, add; per-currency **cash balances** (set/upsert).
- **Categories**: two-level list, add (root/sub + bonus-income flag), delete.

## Setup & run

```bash
cd tracker-telegram-bot
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # set BOT_TOKEN; adjust API_BASE_URL if backend isn't on localhost:8080
python run.py               # backend must be running, with a Webhook URL set (see below)
```

In Telegram: open the bot → `/start` → **Log in** (first run creates the single account) → use
the menu. `/lock` ends the session; `/menu` reopens the menu; `/cancel` aborts a flow.

## Webhook mode

The bot runs in **webhook mode** (push-based, zero polling): Telegram POSTs each update to a
public HTTPS URL, and the bot runs a small aiohttp server to receive them.

The **public webhook URL** and the **web-view URL** are NOT in `.env` — set them in the web app
under **Developer**. They're stored in the backend and the bot fetches them at startup from the
public `GET /api/v1/settings/telegram` endpoint:

1. Expose the bot's local server (`WEBHOOK_HOST:WEBHOOK_PORT`, default `0.0.0.0:8081`) over
   public HTTPS — e.g. a tunnel like `cloudflared`/`ngrok`, or a reverse proxy with TLS.
2. In the web app → **Developer**, set **Webhook URL** to that public URL ending in the
   `WEBHOOK_PATH` (default `/webhook`), e.g. `https://your-tunnel.example/webhook`. Optionally
   set **Web-view URL** to the public HTTPS URL of the frontend (adds an "Open App" button + the
   ☰ chat menu button).
3. Start the bot. It registers the webhook with Telegram on boot. **After changing either URL,
   restart the bot** so it re-registers.

The path the bot listens on is taken from the configured public URL's path (falling back to
`WEBHOOK_PATH`), so the two can't drift. Set `WEBHOOK_SECRET` to have Telegram echo a shared
secret the server verifies on every update. **To stop all Telegram traffic, stop the process.**

## Environment

| Var                | Default                          | Purpose                                   |
| ------------------ | -------------------------------- | ----------------------------------------- |
| `BOT_TOKEN`        | —                                | Bot token from @BotFather (required)      |
| `API_BASE_URL`     | `http://localhost:8080/api/v1`   | Tracker backend base URL                  |
| `SESSION_TTL_HOURS`| `24`                             | Hours before re-login is required         |
| `DEFAULT_CURRENCY` | `UZS`                            | Starting currency until changed           |
| `WEBHOOK_HOST`     | `0.0.0.0`                        | Local aiohttp bind host                   |
| `WEBHOOK_PORT`     | `8081`                           | Local aiohttp bind port                   |
| `WEBHOOK_PATH`     | `/webhook`                       | Fallback path if the public URL has none  |
| `WEBHOOK_SECRET`   | —                                | Optional shared secret Telegram echoes back |

> The public **Webhook URL** and **Web-view URL** are set in the web app (Developer page), not here.

## Notes

- Sessions are in memory — a restart requires re-login (fine for a personal bot).
- `.env` is git-ignored — never commit the token.
