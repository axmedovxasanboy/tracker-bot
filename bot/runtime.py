"""Runtime config fetched from the backend at startup (not from env).

The web-view URL is set in the web app's Developer page, stored in the backend, and read
once when the bot boots. Keyboards read it from here to add the "Open App" Web App button.
"""
from dataclasses import dataclass


@dataclass
class Runtime:
    web_view_url: str | None = None


# Shared singleton, populated in main.py during startup.
runtime = Runtime()
