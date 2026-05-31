"""Inline keyboards + formatting helpers (HTML is the bot's default parse mode)."""
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from .config import CURRENCIES
from .runtime import runtime

PAGES = [
    ("dashboard", "📊 Dashboard"),
    ("overview", "🎯 Overview"),
    ("transactions", "💸 Transactions"),
    ("cards", "💳 Cards"),
    ("finance", "🏦 Finance"),
    ("categories", "🏷 Categories"),
    ("settings", "⚙️ Settings"),
]

MENU_TEXT = "🏠 <b>Tracker</b> — main menu\nPick a section:"


def esc(value) -> str:
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def fmt_money(amount, currency: str = "UZS") -> str:
    if amount is None:
        return "—"
    try:
        n = float(amount)
    except (TypeError, ValueError):
        return esc(amount)
    decimals = 0 if currency == "UZS" else 2
    return f"{n:,.{decimals}f} {currency}"


def fmt_pct(value) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):g}%"
    except (TypeError, ValueError):
        return str(value)


def ikb(rows: list[list[tuple[str, str]]]) -> InlineKeyboardMarkup:
    """Build an inline keyboard from rows of (text, callback_data) tuples."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t, callback_data=d) for (t, d) in row] for row in rows
    ])


def main_menu_kb() -> InlineKeyboardMarkup:
    keyboard: list[list[InlineKeyboardButton]] = []
    # A Web App "Open App" button when a valid HTTPS web-view URL is configured. Telegram
    # rejects non-HTTPS web_app URLs, so skip it for http/localhost to avoid send errors.
    url = runtime.web_view_url
    if url and url.startswith("https://"):
        keyboard.append([InlineKeyboardButton(text="🚀 Open App", web_app=WebAppInfo(url=url))])
    for i in range(0, len(PAGES), 2):
        keyboard.append([InlineKeyboardButton(text=label, callback_data=f"menu:{key}")
                         for key, label in PAGES[i:i + 2]])
    keyboard.append([InlineKeyboardButton(text="🔒 Lock", callback_data="lock")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def login_kb() -> InlineKeyboardMarkup:
    return ikb([[("🔑 Log in", "auth:login")]])


def back_menu_kb() -> InlineKeyboardMarkup:
    return ikb([[("⬅️ Menu", "menu:home")]])


def currency_kb(current: str) -> InlineKeyboardMarkup:
    row = [(("✅ " if c == current else "") + c, f"setcur:{c}") for c in CURRENCIES]
    return ikb([row, [("⬅️ Menu", "menu:home")]])
