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

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/venv/bin:$PATH"

# Non-root user
RUN groupadd -r app && useradd -r -g app -d /home/app -m app

# Bring the venv from the build stage (no pip in the final image)
COPY --from=build /venv /venv

WORKDIR /app
COPY --chown=app:app bot/ ./bot/
COPY --chown=app:app run.py ./

USER app

# Webhook port (matches WEBHOOK_PORT default in bot/config.py)
EXPOSE 8081

CMD ["python", "run.py"]
