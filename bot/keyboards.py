"""Inline keyboards + formatting helpers (HTML is the bot's default parse mode)."""
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from .runtime import runtime

# (page key, i18n key) pairs for the main menu grid
PAGES = [
    ("dashboard", "menu.page.dashboard"),
    ("overview", "menu.page.overview"),
    ("months", "menu.page.months"),
    ("transactions", "menu.page.transactions"),
    ("cards", "menu.page.cards"),
    ("finance", "menu.page.finance"),
    ("categories", "menu.page.categories"),
    ("settings", "menu.page.settings"),
]


def esc(value) -> str:
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def fmt_money(amount) -> str:
    if amount is None:
        return "—"
    try:
        n = float(amount)
    except (TypeError, ValueError):
        return esc(amount)
    return f"{n:,.0f} UZS"


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


def menu_text(chat_id: int | None = None) -> str:
    from .i18n import t
    return t(chat_id, "menu.homeText")


def main_menu_kb(chat_id: int | None = None) -> InlineKeyboardMarkup:
    from .i18n import t
    keyboard: list[list[InlineKeyboardButton]] = []
    # A Web App "Open App" button when a valid HTTPS web-view URL is configured. Telegram
    # rejects non-HTTPS web_app URLs, so skip it for http/localhost to avoid send errors.
    url = runtime.web_view_url
    if url and url.startswith("https://"):
        keyboard.append([InlineKeyboardButton(text=t(chat_id, "menu.openApp"), web_app=WebAppInfo(url=url))])
    for i in range(0, len(PAGES), 2):
        keyboard.append([InlineKeyboardButton(text=t(chat_id, key), callback_data=f"menu:{page}")
                         for page, key in PAGES[i:i + 2]])
    keyboard.append([InlineKeyboardButton(text=t(chat_id, "menu.lock"), callback_data="lock")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def login_kb(chat_id: int | None = None) -> InlineKeyboardMarkup:
    from .i18n import t
    return ikb([[(t(chat_id, "auth.loginButton"), "auth:login")]])


def back_menu_kb(chat_id: int | None = None) -> InlineKeyboardMarkup:
    from .i18n import t
    return ikb([[(t(chat_id, "common.menu"), "menu:home")]])


def settings_kb(chat_id: int | None = None) -> InlineKeyboardMarkup:
    from .i18n import t
    return ikb([
        [(t(chat_id, "settings.language"), "lang:open")],
        [(t(chat_id, "menu.clearEverything"), "reset:start")],
        [(t(chat_id, "common.menu"), "menu:home")],
    ])


def language_kb(chat_id: int | None = None) -> InlineKeyboardMarkup:
    """The two language choices, marking the active one."""
    from .i18n import get_lang, t
    cur = get_lang(chat_id)
    mark = lambda code, label: ("✅ " + label) if cur == code else label
    return ikb([
        [(mark("en", "English"), "lang:set:en")],
        [(mark("uz", "Oʻzbek"), "lang:set:uz")],
        [(t(chat_id, "common.menu"), "menu:settings")],
    ])
