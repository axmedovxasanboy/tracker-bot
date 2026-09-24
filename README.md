# Tracker — Telegram Bot (aiogram)

A small **pocket advisor** for the Tracker API, built with **aiogram v3**. The owner uses it for
three things: **record quickly, pay from a button, check wallets**. Everything else lives in the
web app (the 🌐 Open app button). UZS-only, and bilingual (English / Oʻzbek, in ⚙️ Settings).

Tracker is a **single-user** app, and so is this bot: see [Who the bot answers to](#who-the-bot-answers-to).

## Structure

```
tracker-telegram-bot/
├── run.py                # launcher: logging, signal handling, exit status
├── requirements.txt
├── Dockerfile            # webhook container (deployment: DEPLOY.md)
├── .env.example
└── bot/
    ├── config.py         # env settings, parsed and validated at import
    ├── clock.py          # "today" in Tashkent time — the container runs on UTC
    ├── session.py        # sessions (until /lock) and the owner binding
    ├── storage.py        # the owner's saved login, binding, language, preferences (one JSON file)
    ├── keepalive.py      # refreshes the login before the 7-day refresh token runs out
    ├── reminders.py      # the optional evening message (off by default)
    ├── api.py            # httpx API client: auth + request() with token refresh
    ├── money.py          # the one amount parser + the money formatter
    ├── keyboards.py      # Home's buttons, log in, the income guard
    ├── ui.py             # grid, nav row, short dates
    ├── common.py         # show() (edit-or-send), ack(), begin_write(), gate()
    ├── states.py         # FSM StatesGroups
    ├── runtime.py        # startup-fetched config (web-view URL)
    ├── i18n/             # EN + Oʻzbek strings, one module per area, merged at import
    ├── main.py           # Dispatcher + router wiring + webhook (aiohttp) server, /help, /add
    └── routers/
        ├── auth.py       # /start, typed login/signup, /lock, /menu, /cancel
        ├── settings.py   # ⚙️ language, monthly income, help, log out
        ├── home.py       # Home, from GET /advisor
        ├── pay.py        # Pay buttons: bills, bank, loans, debts, savings, goals
        ├── wallets.py    # 👛 balances + Check wallets
        └── record.py     # quick add, ➕ Add, the draft card (included last: catch-alls)
```

## Features

- **Home** (`GET /advisor`, the same answer the web Home shows): how much you can spend a day
  and until when, the pace or "short" warning, Coming up, Savings this month, You have. Pay
  buttons sit only where the web has them (this month, still to pay; at most six).
- **Quick add**: type `50000 lunch` → a draft with the category guessed from keywords (EN, UZ,
  transliterations) or from the word last time, the last-used wallet (else the card with the
  most on it — never cash by default) and today; one tap on Save. `+2000000 salary` is income.
- **➕ Add**: Expense / Income → amount → category → wallet → the same draft card.
- **Pay**: tap Pay, tap the wallet (last used first) — bills, bank installments, borrowed money,
  debts, donation, investments / emergency fund (your own accounts), goals.
- **👛 Wallets**: every balance, "You have", and Check wallets (type each wallet's real balance).
- A login lasts **until /lock**, across restarts and deploys (`bot/storage.py`, `bot/keepalive.py`).

### Commands

`/start` Home · `/add` record · `/settings` · `/help` · `/lock` log out · `/cancel` abort the
current step · `/login` · `/menu` (= Home).

### Known gaps

- Transactions can't be edited or deleted from the bot — use the web app.
- Every money-writing endpoint stays refused by the backend until **Monthly income** is set.

## Setup & run

```bash
cd tracker-telegram-bot
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # set BOT_TOKEN; adjust API_BASE_URL if backend isn't on localhost:8080
python run.py               # backend must be running, with a Webhook URL set (see below)
```

In Telegram: open the bot → `/start` → **Log in** (first run creates the single account) → use
the menu.

A fatal boot problem — an unreadable `.env` value, a backend that is not answering, no webhook
URL configured — is logged as one actionable line and the process exits non-zero. If the
container is restarting, `docker logs bot` says why.

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
`WEBHOOK_PATH`), so the two can't drift. **To stop all Telegram traffic, stop the process.**

## Security

Two settings carry the whole perimeter. Both are blank by default, which is fine on a laptop
and not fine on a public URL.

### `WEBHOOK_SECRET` — required in production

Telegram echoes this secret back in the `X-Telegram-Bot-Api-Secret-Token` header of every
update, and the server rejects mismatches. **Left blank, the check does not happen at all** —
aiogram's `verify_secret` returns `True` when there is no secret to compare — so anyone who
discovers the public webhook URL can POST forged updates and drive the bot as if they were you.
Generate one and put it in `.env` before the URL is reachable from the internet:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

### Who the bot answers to

Tracker holds one person's money. Set `OWNER_CHAT_ID` to your own numeric chat id
(`@userinfobot` will tell you) and every other chat is refused outright — no login screen, no
menu. Leave it blank and the bot falls back to trust-on-first-login: the first chat that
authenticates successfully claims it for the life of the process, and the bound id is logged at
INFO, so you can start the bot, log in, then copy that id into `.env` and restart.

## Environment

Every variable the bot reads. Anything not listed here is not read. A malformed value stops the
boot with a line naming the variable, rather than a traceback or a silent wrong default.

| Var                 | Default                        | Purpose                                                        |
| ------------------- | ------------------------------ | -------------------------------------------------------------- |
| `BOT_TOKEN`         | —                              | Bot token from @BotFather (**required**)                        |
| `API_BASE_URL`      | `http://localhost:8080/api/v1` | Tracker backend base URL; must include `http://` or `https://`  |
| `API_TIMEOUT`       | `10`                           | Seconds to wait on one API call                                 |
| `STAY_LOGGED_IN`    | `true`                         | Keep the owner's login across restarts; a login lasts until /lock |
| `SESSION_FILE`      | `data/session.json`            | Where that login, the owner binding and preferences are kept      |
| `OWNER_CHAT_ID`     | —                              | The only chat served; blank = trust the first chat that logs in |
| `TZ_OFFSET_HOURS`   | `5`                            | Hours ahead of UTC the owner lives in (Tashkent, no DST)        |
| `LOG_LEVEL`         | `INFO`                         | `DEBUG` / `INFO` / `WARNING` / `ERROR`                          |
| `REMINDERS_ENABLED` | `false`                        | The optional evening message (needs an owner chat to write to)  |
| `REMINDER_HOUR`     | `21`                           | Local hour (0–23) it is delivered at                            |
| `WEBHOOK_HOST`      | `0.0.0.0`                      | Local aiohttp bind host                                         |
| `WEBHOOK_PORT`      | `8081`                         | Local aiohttp bind port                                         |
| `WEBHOOK_PATH`      | `/webhook`                     | Fallback path if the public URL has none                        |
| `WEBHOOK_SECRET`    | —                              | Shared secret Telegram echoes back (**required in production**) |

> The public **Webhook URL** and **Web-view URL** are set in the web app (Developer page), not here.

## Notes

- **Dates come from `bot/clock.py`, not from the container's clock.** "Today" and "this month"
  are computed at `TZ_OFFSET_HOURS` ahead of UTC, so a UTC container cannot file a 01:00
  expense into yesterday — or, on the 1st, into last month's envelope, which for a closed month
  the backend refuses outright. The Dockerfile also sets `TZ=Asia/Tashkent`, but only so that
  OS-level local time reads sensibly; nothing the bot writes depends on it.
- `.env` is git-ignored — never commit the token.
- Deployment (image, compose entry, Caddy route, rollback) is in [DEPLOY.md](DEPLOY.md).
