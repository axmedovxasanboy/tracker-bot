"""Inline keyboards shared by several screens, plus `esc` and `ikb` (HTML is the parse mode).

The reusable shapes (grids, nav rows) live in `bot/ui.py`; this module owns the product's own
buttons: Home's bottom rows, the ☰ More menu, log in, the income guard, Settings.
"""
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from .runtime import runtime

__all__ = ["esc", "ikb", "web_app_button", "home_rows", "more_kb", "login_kb", "back_home_kb",
           "app_home_kb", "income_guard_kb"]


def esc(value) -> str:
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def ikb(rows: list[list[tuple[str, str]]]) -> InlineKeyboardMarkup:
    """Build an inline keyboard from rows of (text, callback_data) tuples. Empty rows are dropped."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=text, callback_data=data) for (text, data) in row]
        for row in rows if row
    ])


def web_app_button(chat_id: int | None) -> InlineKeyboardButton | None:
    """The "Open app" button, or None when no usable web-view URL is configured.

    The URL comes from the web app's Developer page (read at boot) or WEB_VIEW_URL. Telegram
    rejects a non-HTTPS web_app URL outright, so a local http:// deployment gets no button.
    """
    from .i18n import t
    url = runtime.web_view_url
    if url and url.startswith("https://"):
        return InlineKeyboardButton(text=t(chat_id, "home.btn.app"), web_app=WebAppInfo(url=url))
    return None


def home_rows(chat_id: int | None) -> list[list[InlineKeyboardButton]]:
    """Home's two bottom rows: Add · Wallets · More, then Open app · Settings · Refresh."""
    from .i18n import t

    def b(key: str, data: str) -> InlineKeyboardButton:
        return InlineKeyboardButton(text=t(chat_id, key), callback_data=data)

    second = [b("home.btn.settings", "set"), b("home.btn.refresh", "home")]
    app = web_app_button(chat_id)
    if app is not None:
        second.insert(0, app)
    return [[b("home.btn.add", "add"), b("home.btn.wallets", "wal"), b("home.btn.more", "more")], second]


def more_kb(chat_id: int | None) -> InlineKeyboardMarkup:
    """☰ More: every other screen the web app has, two to a row, Open app and Home last.

    `sav` and `loan` are the entry points of the Savings and Loans & bills routers — the callback
    data is the contract between the two, so it is spelled exactly once, here.
    """
    from .i18n import t

    def b(key: str, data: str) -> InlineKeyboardButton:
        return InlineKeyboardButton(text=t(chat_id, key), callback_data=data)

    keyboard = [
        [b("home.more.history", "hist"), b("home.btn.wallets", "wal")],
        [b("home.more.savings", "sav"), b("home.more.loans", "loan")],
        [b("home.more.profile", "prof"), b("home.more.settings", "set")],
    ]
    last = [b("common.home", "home")]
    app = web_app_button(chat_id)
    if app is not None:
        last.insert(0, app)
    keyboard.append(last)
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def login_kb(chat_id: int | None = None) -> InlineKeyboardMarkup:
    """Log in — and the other language, for an owner who cannot read this one."""
    from .i18n import get_lang, t
    other = "uz" if get_lang(chat_id) == "en" else "en"
    return ikb([[(t(chat_id, "auth.loginButton"), "auth:login"), (t(chat_id, "settings.langBtn"), f"lang:{other}")]])


def back_home_kb(chat_id: int | None = None) -> InlineKeyboardMarkup:
    from .i18n import t
    return ikb([[(t(chat_id, "common.home"), "home")]])


def app_home_kb(chat_id: int | None = None) -> InlineKeyboardMarkup:
    """For "do that in the web app": Open app (when there is one) and Home."""
    from .i18n import t
    keyboard = []
    app = web_app_button(chat_id)
    if app is not None:
        keyboard.append([app])
    keyboard.append([InlineKeyboardButton(text=t(chat_id, "common.home"), callback_data="home")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def income_guard_kb(chat_id: int | None = None) -> InlineKeyboardMarkup:
    """Under "set your monthly income first": the fix itself, the web app, and Home."""
    from .i18n import t
    keyboard = [[InlineKeyboardButton(text=t(chat_id, "settings.incomeBtn"), callback_data="set:income")]]
    app = web_app_button(chat_id)
    if app is not None:
        keyboard.append([app])
    keyboard.append([InlineKeyboardButton(text=t(chat_id, "common.home"), callback_data="home")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)
