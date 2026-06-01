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
| `WEBHOOK_SECRET` | Shared secret Telegram echoes back in the `X-Telegram-Bot-Api-Secret-Token` header; the server rejects mismatches |

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
      SESSION_TTL_HOURS: 24
      DEFAULT_CURRENCY: UZS
    networks:
      - app-network
    depends_on:
      - backend

networks:
  app-network:
    external: true
```

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
| `SESSION_TTL_HOURS` | no       | Default 24                                           |
| `API_TIMEOUT`       | no       | Default 10s                                          |
| `DEFAULT_CURRENCY`  | no       | Default `UZS`                                        |
| `WEBHOOK_HOST`      | no       | Default `0.0.0.0`                                    |
| `WEBHOOK_PORT`      | no       | Default `8081` (must match `EXPOSE` + Caddy upstream)|
| `WEBHOOK_PATH`      | no       | Default `/webhook`; overridden by the public URL's path if it has one |

The public webhook URL and Web View URL are **not** env vars — they live in the
backend `Settings` singleton and are configured from the Developer page.

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
