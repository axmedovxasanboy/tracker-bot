"""Inline keyboards + formatting helpers (HTML is the bot's default parse mode).

This module holds `esc`, `ikb` and the app-level menus — the keyboards that are about *this*
product's navigation. The reusable shapes every screen needs (grids, pagers, nav rows,
confirm rows) live in `bot/ui.py`, and the money helpers now live in `bot/money.py`; both are
re-exported here so that a router mid-migration keeps compiling either way.
"""
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from .money import fmt_money, fmt_pct
from .runtime import runtime

# Re-exports. `from ..keyboards import esc, fmt_money, ikb` appears in six routers and there is
# no reason to make seven agents rewrite their import lines in the same week; the single
# implementation is in money.py and this name is an alias for it.
__all__ = ["PAGES", "esc", "fmt_money", "fmt_pct", "ikb", "menu_text", "main_menu_kb",
           "login_kb", "back_menu_kb", "income_guard_kb", "settings_kb", "language_kb"]

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


def ikb(rows: list[list[tuple[str, str]]]) -> InlineKeyboardMarkup:
    """Build an inline keyboard from rows of (text, callback_data) tuples.

    Empty rows are dropped rather than sent. The row builders in `ui.py` return `[]` when a
    screen asks for no navigation at all, and Telegram rejects a keyboard containing an empty
    row — filtering here means a caller can append a row unconditionally.
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=text, callback_data=data) for (text, data) in row]
        for row in rows if row
    ])


def _web_app_button(chat_id: int | None) -> InlineKeyboardButton | None:
    """The "Open App" button, or None when no usable web-view URL is configured.

    Telegram rejects a non-HTTPS web_app URL outright, so a local http:// deployment must not
    get one — the send would fail and take the whole screen with it.
    """
    from .i18n import t
    url = runtime.web_view_url
    if url and url.startswith("https://"):
        return InlineKeyboardButton(text=t(chat_id, "menu.openApp"), web_app=WebAppInfo(url=url))
    return None


def menu_text(chat_id: int | None = None) -> str:
    from .i18n import t
    return t(chat_id, "menu.homeText")


def main_menu_kb(chat_id: int | None = None) -> InlineKeyboardMarkup:
    """The main menu: capture first, then the app, then the eight sections, then Lock.

    The capture row is the only addition to this screen that pays for its own height. Every
    other row leads to a *page*; this one is the thing the bot exists for, and without it the
    fast path is invisible — a new owner taps Transactions → Add and walks the nine-step
    guided flow forever, never learning that typing "50000 lunch" does the same job in one
    message. `qa:new` opens the prompt that teaches that syntax and `qa:repeat` copies the
    last transaction; both are stable callbacks in `bot/routers/quickadd.py`.

    The Repeat label is `quickadd.repeat` rather than a menu-namespace copy of the same two
    words: it is the same button as the one on the quick-add screen, and two spellings of one
    action is the drift this rebuild spent a week undoing.
    """
    from .i18n import t
    keyboard: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text=t(chat_id, "menu.quickAddBtn"), callback_data="qa:new"),
         InlineKeyboardButton(text=t(chat_id, "quickadd.repeat"), callback_data="qa:repeat")],
    ]
    web_app = _web_app_button(chat_id)
    if web_app is not None:
        keyboard.append([web_app])
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


def income_guard_kb(chat_id: int | None = None) -> InlineKeyboardMarkup:
    """The keyboard under the "set your monthly income first" guard.

    The guard blocks every transaction, every finance record, every repayment and the month
    close, and it is the first thing a phone-only owner meets after signing up. So the fix has
    to be reachable from the guard itself: `settings:income` starts the one-field flow in the
    bot. The Web App button is offered alongside it when there is one, since the same figure
    can be set there — but it is the second option now, not the only instruction.
    """
    from .i18n import t
    keyboard: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text=t(chat_id, "ui.setIncome"), callback_data="settings:income")],
    ]
    web_app = _web_app_button(chat_id)
    if web_app is not None:
        keyboard.append([web_app])
    keyboard.append([InlineKeyboardButton(text=t(chat_id, "common.menu"), callback_data="menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def settings_kb(chat_id: int | None = None) -> InlineKeyboardMarkup:
    """The Settings screen's keyboard — the single definition of it.

    `bot/routers/menu.py` used to build a second copy carrying one row this one did not
    (the tracking start month), which is how a screen ends up with two different sets of
    entries depending on which file you read. The router now renders this.

    Help sits beside Language because `sys:help` is where the commands and the quick-add
    syntax are written down, and because pairing the two costs no extra row on a screen whose
    last entry deletes the account.
    """
    from .i18n import t
    return ikb([
        [(t(chat_id, "ui.setIncome"), "settings:income")],
        [(t(chat_id, "menu.settings.trackingBtn"), "settings:track")],
        [(t(chat_id, "settings.language"), "lang:open"),
         (t(chat_id, "menu.helpBtn"), "sys:help")],
        [(t(chat_id, "menu.clearEverything"), "reset:start")],
        [(t(chat_id, "common.menu"), "menu:home")],
    ])


def language_kb(chat_id: int | None = None) -> InlineKeyboardMarkup:
    """The two language choices, marking the active one."""
    from .i18n import get_lang, t
    cur = get_lang(chat_id)

    def mark(code: str, label: str) -> str:
        return ("✅ " + label) if cur == code else label

    return ikb([
        [(mark("en", "English"), "lang:set:en")],
        [(mark("uz", "Oʻzbek"), "lang:set:uz")],
        # Labelled for where it actually goes: this returns to Settings, not the main menu.
        [(t(chat_id, "settings.backToSettings"), "menu:settings")],
    ])
