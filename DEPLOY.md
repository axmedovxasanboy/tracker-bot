# Deploy — tracker-telegram-bot

Built and pushed to `ghcr.io/<owner>/tracker-bot` on every push to `main`, then
pulled on the server over SSH.

Service / container name on the server: **`bot`** (used by `docker compose pull/up`).

The container runs an aiohttp webhook server on **port 8081**. Caddy terminates
TLS and reverse-proxies the public webhook path to `bot:8081`.

> **Image name must match.** The workflow pushes `ghcr.io/${GITHUB_REPOSITORY,,}`,
> so the GitHub repo must be named **`tracker-bot`** for the image below to resolve.
> If you rename the repo, update the `image:` line to match exactly or
> `docker compose pull bot` will fail.

---

## GitHub Actions secrets

| Secret           | Purpose                                                |
| ---------------- | ------------------------------------------------------ |
| `SERVER_HOST`    | Hetzner VPS hostname or IP                             |
| `SERVER_USER`    | SSH user — `deploy`                                    |
| `SERVER_SSH_KEY` | Private SSH key (full PEM including header/footer)     |

`GITHUB_TOKEN` is provided automatically and is used to push to ghcr.io.

## Server prerequisites

- Docker + Compose v2 installed.
- The **backend service must be up** before the bot starts — on boot the bot
  calls `GET /api/v1/settings/telegram` against the backend; if that's
  unreachable, or no webhook URL is set, **the bot exits**. With
  `restart: unless-stopped`, Docker just restarts it until the backend responds
  (no healthcheck added, per project policy).
- The **public webhook URL** (and optionally the web-view URL) is set from the
  web app's **Developer** page, *not* from `.env`. The bot reads it at startup
  and registers it with Telegram.
- The server is logged in to ghcr.io if the package is **private**:
  ```bash
  echo "$GHCR_PAT" | docker login ghcr.io -u <github-user> --password-stdin
  ```

## Required `.env` entries on the server (`~/app/.env`)

| Var              | Notes                                                  |
| ---------------- | ------------------------------------------------------ |
| `BOT_TOKEN`      | From @BotFather                                        |
| `WEBHOOK_SECRET` | **Required in production.** Shared secret Telegram echoes back in the `X-Telegram-Bot-Api-Secret-Token` header. Left blank the check is skipped entirely — aiogram's `verify_secret()` returns `True` when there is nothing to compare — so anyone who learns the public URL can POST forged updates. Generate one: `python3 -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `OWNER_CHAT_ID`  | Your numeric Telegram chat id. Set it and the bot refuses every other chat outright. Leave it blank and the first chat that logs in claims the bot until the next restart. Get it from [@userinfobot](https://t.me/userinfobot), or start the bot, log in, and read the `Owner chat bound to …` line in `docker logs bot`. **Needed for the advisor:** with it set, you stay logged in across restarts and deploys and the bot messages you in the evening |

These live in `~/app/.env` on the VPS, **not** in GitHub Actions secrets — the Actions secrets
above are only for building the image and SSH-ing in. Compose reads `~/app/.env` for the
`${...}` values in the block below. After editing it:

```bash
cd ~/app && docker compose up -d bot     # `restart` does NOT re-read .env
```

Everything else is set inline in the compose `environment:` block below.

## Compose entry (server-side, in `~/app/docker-compose.yml`)

```yaml
services:
  bot:
    image: ghcr.io/<owner>/tracker-bot:latest
    container_name: bot
    restart: unless-stopped
    environment:
      BOT_TOKEN: ${BOT_TOKEN}
      API_BASE_URL: http://backend:8080/api/v1
      WEBHOOK_HOST: 0.0.0.0
      WEBHOOK_PORT: 8081
      WEBHOOK_PATH: /webhook
      WEBHOOK_SECRET: ${WEBHOOK_SECRET}
      # The floor under the Developer page. The backend still wins when it has a value; this
      # is what stops a factory reset (which TRUNCATEs the settings row holding the stored
      # copy) from leaving the bot unable to boot. Must match the Caddy route below.
      WEBHOOK_URL: https://bot.tracker.xasanboy.dev/webhook
      WEB_VIEW_URL: ${WEB_VIEW_URL:-}
      SESSION_TTL_HOURS: 24
      # Who the bot answers to. Blank = the first chat to log in claims it (see .env above).
      # Set, it also keeps YOUR login across restarts (in the volume below) — the 24h above
      # then only applies to anyone else.
      OWNER_CHAT_ID: ${OWNER_CHAT_ID:-}
      # What "today" and "this month" mean. The container runs UTC; Tashkent is +5, and
      # without this an expense recorded before 05:00 lands in yesterday — or, on the 1st,
      # in last month's envelope.
      TZ_OFFSET_HOURS: 5
      LOG_LEVEL: INFO
      # The advisor's evening message: at 21:00, only when something needs you (a bill, a
      # wallet check, money to set aside), plus a short look at the month on Sundays.
      REMINDERS_ENABLED: ${REMINDERS_ENABLED:-true}
      REMINDER_HOUR: 21
    volumes:
      # Your saved login, language and which reminders went out (bot/storage.py). Without
      # it every deploy logs you out and the evening message stops until you log in again.
      - bot-data:/app/data
    networks:
      - app-network
    depends_on:
      - backend

volumes:
  bot-data:

networks:
  app-network:
    external: true
```

> The `bot-data` volume holds a refresh token — as good as your password for seven days.
> It is a named volume, so it is never inside the image or the repo; `/lock` in the bot
> deletes the login from it.

> `depends_on` only orders container *start*, not readiness — the bot may still
> boot before the backend is answering and exit; `restart: unless-stopped`
> covers that (see prerequisites).

## Caddyfile

Route the bot's public subdomain to the container. Caddy provisions the
Let's Encrypt cert automatically.

```caddyfile
bot.tracker.xasanboy.dev {
    reverse_proxy /webhook bot:8081
}
```

Then set the public URL **`https://bot.tracker.xasanboy.dev/webhook`** on the web
app's **Developer** page (along with the Web View URL), and restart the bot so it
re-registers the webhook with Telegram:

```bash
cd ~/app && docker compose restart bot
```

## Runtime env vars (reference)

| Var                 | Required | Notes                                                |
| ------------------- | -------- | ---------------------------------------------------- |
| `BOT_TOKEN`         | yes      | From @BotFather                                      |
| `API_BASE_URL`      | yes      | `http://backend:8080/api/v1` for in-network access   |
| `WEBHOOK_SECRET`    | rec.     | Telegram echoes it back; the server rejects mismatches |
| `SESSION_TTL_HOURS` | no       | Default 24. Not applied to the `OWNER_CHAT_ID` login while `STAY_LOGGED_IN` is on |
| `STAY_LOGGED_IN`    | no       | Default `true`: the owner's login is kept in `SESSION_FILE` and never times out |
| `SESSION_FILE`      | no       | Default `data/session.json` (= `/app/data/session.json` in the image) |
| `REMINDERS_ENABLED` | no       | Default `true`: the evening advisor message         |
| `REMINDER_HOUR`     | no       | Default `21` (local time, `TZ_OFFSET_HOURS`)        |
| `API_TIMEOUT`       | no       | Default 10s                                          |
| `WEBHOOK_HOST`      | no       | Default `0.0.0.0`                                    |
| `WEBHOOK_PORT`      | no       | Default `8081` (must match `EXPOSE` + Caddy upstream)|
| `WEBHOOK_PATH`      | no       | Default `/webhook`; overridden by the public URL's path if it has one |

The public webhook URL and Web View URL are **not** env vars — they live in the
backend `Settings` singleton and are configured from the Developer page.

## When `/start` does nothing

The bot answers `/start` even with the backend down, so silence means the update never reached
a handler. Work down this list — each step rules out one layer.

**1. Is the process actually up, or restarting in a loop?**

```bash
docker ps -a --filter name=bot          # look at STATUS: "Restarting (1)" is the tell
docker logs --tail 80 bot
```

**`No webhook URL configured`** means the backend answered but its `settings` row has no
stored URL — a factory reset clears it, and so does a fresh database. Set `WEBHOOK_URL` in the
compose block (it is the floor under the Developer page and survives any database wipe), or set
it on the web app's Developer page, then `docker compose up -d bot`.

A fatal boot error is now one plain sentence at the end of the log — a bad `.env` value names
the variable, and an unreachable backend or a missing webhook URL says so outright. (Before
this rebuild `run.py` swallowed `SystemExit`, so the same failure produced an empty log and
`Exited (0)`, which reads like a clean shutdown. If you see that, you are on an old image.)

The bot reads its public webhook URL from the backend at boot, so **the backend must be up
first**. It exits if `GET /api/v1/settings/telegram` is unreachable or returns no URL.

**2. Is the webhook registered, and is Telegram able to deliver to it?**

This is the single most informative command — Telegram tells you why it is failing:

```bash
curl -s "https://api.telegram.org/bot<BOT_TOKEN>/getWebhookInfo" | python3 -m json.tool
```

- `"url": ""` → the bot never registered. Back to step 1.
- `last_error_message` → Telegram reached your server and got an error. `Wrong response from
  the webhook: 401 Unauthorized` means the secret mismatches (step 3); a TLS or DNS error
  means Caddy or the DNS record; `Connection refused` means the container is not listening.
- `pending_update_count` climbing → delivery is failing, not the handlers.

**3. Did the secret drift?**

The bot registers the webhook with whatever `WEBHOOK_SECRET` it booted with, and checks the
same value on the way in, so the two only diverge if the container was restarted with a
different `.env` than the one it registered under — most often by editing `.env` and running
`docker compose restart`, which does **not** re-read it. Fix:

```bash
cd ~/app && docker compose up -d bot
```

**4. Is Caddy routing the path the bot listens on?**

The bot listens on the *path of the public URL* set in the web app (falling back to
`WEBHOOK_PATH`), so `https://bot.example.dev/webhook` means it serves `/webhook` — and the
Caddy matcher has to agree. From the VPS:

```bash
curl -i https://bot.tracker.xasanboy.dev/webhook       # 405 = reached the bot. 404/502 = routing.
```

`405 Method Not Allowed` is the healthy answer to a GET: aiohttp has the route and wants a POST.

**5. Are you the owner?**

If `OWNER_CHAT_ID` is set to someone else's id, every update from your chat is dropped and the
log says so once:

```bash
docker logs bot 2>&1 | grep -i "Refused chat_id"
```

Clear the variable (or set it to the id that line names) and `docker compose up -d bot`.

## Manual trigger

GitHub UI → **Actions** → **build-and-deploy** → **Run workflow** (branch `main`),
or from the CLI:

```bash
gh workflow run build-and-deploy.yml --ref main
```

## Roll back

Every build pushes `:latest` and `:<short-sha>`. To roll back, pin the image to a
previous short SHA in `~/app/docker-compose.yml`:

```yaml
    image: ghcr.io/<owner>/tracker-bot:a1b2c3d   # ← previous short SHA
```

then:

```bash
cd ~/app
docker compose pull bot
docker compose up -d bot
```

List recent tags:

```bash
gh api /users/<owner>/packages/container/tracker-bot/versions \
  --jq '.[] | {tags: .metadata.container.tags, created: .created_at}'
```
