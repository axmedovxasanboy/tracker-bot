# syntax=docker/dockerfile:1.7

# ─── Build stage ──────────────────────────────────────────────────────────────
# aiogram / aiohttp / httpx / python-dotenv all ship manylinux wheels, so no
# gcc/build-essential is needed at build time.
FROM python:3.12.7-slim AS build

ENV PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN python -m venv /venv
ENV PATH="/venv/bin:$PATH"

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# ─── Runtime stage ────────────────────────────────────────────────────────────
FROM python:3.12.7-slim AS runtime

# TZ makes OS-level local time (log timestamps, `date` in an exec shell) read as Tashkent.
# It is a convenience, not a correctness dependency: slim images may ship no tzdata, in
# which case glibc silently falls back to UTC — so the dates the bot *writes* come from
# bot/clock.py's fixed UTC+5 offset instead, and run.py stamps the log from the same source.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/venv/bin:$PATH" \
    TZ=Asia/Tashkent

# Non-root user
RUN groupadd -r app && useradd -r -g app -d /home/app -m app

# Bring the venv from the build stage (no pip in the final image)
COPY --from=build /venv /venv

WORKDIR /app
COPY --chown=app:app bot/ ./bot/
COPY --chown=app:app run.py ./
# Where the owner's saved login lives (bot/storage.py). Owned by `app` so the bot can write it;
# compose mounts a named volume here, which inherits this ownership on first use.
RUN mkdir -p /app/data && chown app:app /app/data

USER app

# Webhook port (matches WEBHOOK_PORT default in bot/config.py)
EXPOSE 8081

# `docker stop` sends this to PID 1 and waits (10s by default) before SIGKILL.
STOPSIGNAL SIGTERM

# Exec form on purpose: no shell in between, so python is PID 1 and Telegram-facing
# shutdown is graceful. PID 1 is exempt from the kernel's default signal actions — a signal
# with no handler installed is discarded — so a handler has to exist for SIGTERM to do
# anything at all. run.py installs one for the boot window and aiohttp's AppRunner installs
# its own once the server is up; between them, `docker stop` unwinds the app (closing the
# HTTP client and running the dispatcher's shutdown hooks) instead of being killed at the
# end of the grace period.
CMD ["python", "run.py"]
