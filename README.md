# Tracker — Telegram Bot (aiogram)

A native Telegram client for the Tracker API, built with **aiogram v3**. The bot logs into the
Spring Boot backend with your account and drives everything through inline-button menus
mirroring the web app's eight pages: Home, Plan, Months, Transactions, Wallets, Finance,
Categories, Settings. It is UZS-only — every amount is entered and displayed in UZS, with no
currency selection — and fully bilingual (English / Oʻzbek, switched in Settings).

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
    ├── session.py        # in-memory sessions (TTL + /lock) + store singleton
    ├── api.py            # httpx API client: auth + request() with 401→refresh
    ├── money.py          # the one amount parser + the one money formatter
    ├── keyboards.py      # the bot's own menus (main menu, login, settings, language)
    ├── ui.py             # reusable keyboard shapes: grid, nav row, pager, confirm row
    ├── common.py         # show()/edit() (edit-or-send), ack(), begin_write(), gate()
    ├── states.py         # FSM StatesGroups
    ├── runtime.py        # startup-fetched config (web-view URL) shared with keyboards
    ├── i18n/             # EN + Oʻzbek strings, one module per area, merged at import
    ├── main.py           # Dispatcher + router wiring + webhook (aiohttp) server
    └── routers/
        ├── auth.py       # /start, typed login/signup, /lock, /menu, /cancel
        ├── menu.py       # main menu, Home, Plan, Settings, language, factory reset
        ├── wizard.py     # generic field-stepper create flow (shared)
        ├── transactions.py
        ├── finance.py
        ├── cards.py      # Wallets: cards + cash balances
        ├── categories.py
        └── months.py     # month summary, permanent close, history
```

## Features

- Typed **login / signup** (auto-detects first-run signup vs login), a session with a TTL, `/lock`.
- **Home** (dashboard summary), **Plan** (tier + allocation), **Settings** (language, factory
  reset — password-confirmed, and it wipes the account).
- **Transactions**: add (guided: type → amount → category → subtype → source → date → note →
  confirm), quick add ("50000 lunch", `/add`), move money between wallets, recent (paged),
  view, delete.
- **Finance**: 9 sections — debts, loans given, loans taken, bank loans, subscriptions,
  donations, investments, savings goals, emergency fund — each with create (shared wizard),
  edit and delete, plus repay / mark returned / pay / contribute / update goal value and
  "already paid" marks.
- **Wallets**: cards list, view, add, edit, delete; cash balances (set/upsert).
- **Categories**: two-level list, add (root/sub + bonus-income flag), edit, delete.
- **Months**: current-month summary, **permanent close** (you enter the real end-of-month
  balance of every wallet), and history.

### Commands

`/start` open the bot · `/menu` reopen the main menu · `/login` log in · `/lock` end the
session now · `/cancel` abort the current flow.

### Known gaps

Documented so the next reader stops looking for them:

- **Transactions can't be edited from the bot** — add, view and delete only. Edit one in the
  web app. (Cards, categories, finance records and the stable income can be edited here.)
- **Sessions are in memory**, so a restart means logging in again (fine for a personal bot).
- Every money-writing endpoint stays refused by the backend until **Monthly stable income**
  is set — that is the product rule, not a bot limitation.

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
| `SESSION_TTL_HOURS` | `24`                           | Hours before re-login is required                               |
| `OWNER_CHAT_ID`     | —                              | The only chat served; blank = trust the first chat that logs in |
| `TZ_OFFSET_HOURS`   | `5`                            | Hours ahead of UTC the owner lives in (Tashkent, no DST)        |
| `LOG_LEVEL`         | `INFO`                         | `DEBUG` / `INFO` / `WARNING` / `ERROR`                          |
| `REMINDERS_ENABLED` | `false`                        | Opt-in switch for the bot's scheduled reminders                 |
| `REMINDER_HOUR`     | `21`                           | Local hour (0–23) reminders are delivered at                    |
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
