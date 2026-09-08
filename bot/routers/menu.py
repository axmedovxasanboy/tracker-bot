"""Main menu, Home, Plan, Settings — the read screens, plus the bot's only settings writer.

Five ideas shape this file.

**Home is about THIS month.** Tracker is a monthly-envelope product: money arrives, the
mandatory outgoings come off the top, and what is left is spent or set aside *within the
month*. A landing screen showing lifetime income and lifetime expenses answers a question
nobody in this product asks, and after a year it answers it in seven digits. So Home now
leads with the current month (`GET /dashboard/monthly`, which returns the whole calendar
year in one call and therefore also pays for the "This year" screen behind it), keeps
spendable and net worth as the two standing balances, and demotes the all-time totals to a
single grey line. "Where it went" (`GET /dashboard/category-breakdown`) is the drill-down
that makes "how much did I spend on food this month" answerable from the phone at all. On an
account with nothing in it yet, all of that is zeroes and two drill-downs into nothing, so
Home shows the one thing that is actually useful there instead: how to record something,
including the typed shortcut (`50000 lunch`) that no screen in the bot used to mention.

**Plan is a summary with drill-downs, not a wall.** The full tier response — three bucket
lines, up to four action items, a pending-subscription list and a variable number of notes —
runs past 4096 characters in the bad cases and past a phone screen in the ordinary ones.
`common.show` would split it, but forty lines of prose is still unreadable. So the top screen
carries the figures a person scans (tier, the three money lines, one line per bucket, the
things they must actually pay) and everything else — the arithmetic behind the left balance,
per-bucket detail, the scenario notes — sits one tap away under Details, with each bucket's
own payment list one tap away under its own button.

**The backend's English is data, not text.** `TierAllocation` hands every sentence over as
`code` + `params` precisely so a client can say it in its own language, and `AllocationLine`
carries a stable `bucket` identifier next to its hard-coded English `label`. This bot has a
full translation table, so it resolves both and keeps `text`/`label` only as the fallback for
something the server starts emitting that this file has not been taught yet. The one
`ActionItem` that deliberately has no code is the owner's own note from the rules editor —
their words, in whichever language they typed them, so it is printed verbatim.

**Nothing can be recorded until the stable income is set, so the bot must be able to set
it.** The backend refuses every money-writing call until `monthlyStableIncome` exists, which
means a phone-only owner who signs up here hits a wall on their first tap. `settings:income`
is the way through it, from Settings and from the guard `common.stable_income_set` renders.
`PUT /settings` carrying only that one field leaves every other setting untouched
(`SettingsService.update` writes each field only when the request supplies it), so this is a
one-key write, not a read-modify-write that could clobber the webhook URLs.

**The factory reset takes the bot's own configuration with it.** `ResetService.TRUNCATE_ALL`
lists `settings`, and that table holds `telegram_webhook_url` / `telegram_web_view_url` — the
values `bot/main.py` reads at boot. The running process keeps working because it captured
them at startup; the NEXT restart finds nulls, exits, and the container crash-loops. The bot
cannot repair that (it has no Developer-settings screen), so the only honest thing it can do
is say so *before* the password is typed. That is what `menu.reset.botWarning` is for.

Callback namespaces owned here: `menu:*`, `home:*`, `plan:*`, `bucket:*`, `settings:*`,
`reset:*`, `lang:*`.
"""
import logging
import re

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from .. import api, clock, common, keyboards, ui
from ..config import CURRENCY
from ..i18n import UZ, get_lang, set_lang, t
from ..keyboards import esc, ikb
from ..money import fmt_money, fmt_pct, parse_amount
from ..session import store
from ..states import Reset, Settings

router = Router()

log = logging.getLogger(__name__)

# `YYYY-MM` and `YYYY`. Both arrive from callback data, which is the one string in this file
# that comes from outside it — a stale button, a replayed update — so both are matched before
# being spent on a query parameter or interpolated into a screen.
_MONTH = re.compile(r"\d{4}-(?:0[1-9]|1[0-2])")
_YEAR = re.compile(r"\d{4}")

# `AllocationLine.bucket` — the stable identifier — to the words this bot uses for the same
# money on the Months screen. The `label` beside it is a hard-coded English string built in
# OverviewService.percentLines ("Donation", "Emergency", "Investments"), which is why the Plan
# screen used to name in English the four buckets the Months screen names in Uzbek.
_BUCKET_KEY = {
    "DONATION": "menu.bucket.donation",
    "EMERGENCY": "menu.bucket.emergency",
    "INVESTMENTS": "menu.bucket.investments",
    "STOCKS": "menu.bucket.stocks",
    "SAVINGS": "menu.bucket.savings",
}

# Buckets the drill-down may ask the server about. `getBucketPayments` throws on anything
# else, and the value reaches us from callback data.
_BUCKETS = frozenset(_BUCKET_KEY)

# `TierAllocation.scenarioKey` — "1.2.1.tight" and friends — to our own description of the
# branch. `scenarioLabel` next to it is an English switch statement (OverviewService:1305).
# The level number is printed by the same line, so none of these repeats it.
_SCENARIO_KEY = {
    "1.1": "menu.overview.scenario11",
    "1.2.1.tight": "menu.overview.scenario121Tight",
    "1.2.1.comfortable": "menu.overview.scenario121Comfort",
    "1.2.2.tight": "menu.overview.scenario122Tight",
    "1.2.2.comfortable": "menu.overview.scenario122Comfort",
    "1.2.3": "menu.overview.scenario123",
    "1.3": "menu.overview.scenario13",
}

# `TierAllocation.ActionItem.code` to our own sentence. Every code OverviewService can emit is
# here EXCEPT three — page.plan.note.setIncome, .trackingStarts and .subscriptionsPending —
# which the server only ever sends together with the matching flag on the tier response
# itself. This screen renders those three states from the flags instead, with more in them
# than the note carries (the pending-subscription list, and a button that sets the income),
# and it does not print the allocation's actions at all while a flag is up, so mapping them
# would add three keys that can never reach a screen.
_ACTION_KEY = {
    "page.plan.actionPayBank": "menu.overview.actPayBank",
    "page.plan.actionPayPersonal": "menu.overview.actPayPersonal",
    "page.plan.action.payDebts34": "menu.overview.actPayDebts34",
    "page.plan.action.setAside": "menu.overview.actSetAside",
    "page.plan.note.tight": "menu.overview.noteTight",
    "page.plan.note.comfortable": "menu.overview.noteComfortable",
    "page.plan.note.loanAndDebt": "menu.overview.noteLoanAndDebt",
    "page.plan.note.heavyDebt": "menu.overview.noteHeavyDebt",
    "page.plan.note.aboveTierCeiling": "menu.overview.noteAboveCeiling",
    "page.plan.note.levelRulesUnset": "menu.overview.noteLevelRulesUnset",
    "page.plan.note.subLevelRulesUnset": "menu.overview.noteSubLevelRulesUnset",
    "page.plan.note.loanPlanNotStarted": "menu.overview.noteLoanPlanNotStarted",
    "page.plan.note.loanChargeNotStarted": "menu.overview.noteLoanChargeNotStarted",
    "page.plan.note.debtChargeNotStarted": "menu.overview.noteDebtChargeNotStarted",
}

# Server labels on a BucketPayment row that only repeat the screen's own title ("Emergency
# fund" under the Emergency fund heading) or are said better by the marked badge. Suppressed
# rather than translated: a row reads "• 03.09 · 250 000 UZS" and the title says the rest.
_GENERIC_ROW_LABELS = frozenset({"Emergency fund", "Stocks", "Marked as already paid"})

# How much of a long list is worth putting on a phone before it stops being scannable. Not a
# Telegram limit — `common.show` splits at 4096 on its own — but a reading limit.
_MAX_CATEGORY_ROWS = 12
_MAX_BUCKET_ROWS = 30
_MAX_LEDGER_MONTHS = 12

# The two TelegramBadRequest families `_finish` has to tell apart when it edits the "Saving…"
# notice, spelled the same way `bot/common.py` spells them: the first means the render was a
# no-op, the second that the message is gone and a new one is the only way through. Anything
# else is a real render bug and is re-raised.
_NOT_MODIFIED = "message is not modified"
_UNEDITABLE = (
    "message to edit not found",
    "message can't be edited",
    "message identifier is not specified",
    "message_id_invalid",
)


# ── small shared pieces ──────────────────────────────────────────────────────
def _month_or_now(raw: str | None) -> str:
    """A validated `YYYY-MM`, or this month in Tashkent. Never trusts the string handed in."""
    return raw if raw and _MONTH.fullmatch(raw) else clock.month()


def _shift(month: str, delta: int) -> str:
    total = int(month[:4]) * 12 + int(month[5:7]) - 1 + delta
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def _num(value) -> float | None:
    """The API sends BigDecimals as JSON numbers, but null is a real answer on most of them."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _plain(amount) -> str:
    """A grouped figure with the currency left off.

    Only for tables that repeat the same unit on every row — the year view prints three money
    figures per line for twelve lines, and "1 500 000 UZS" thirty-six times turns a scannable
    column into wrapped text. The unit is named once, in the heading.
    """
    n = _num(amount)
    return "—" if n is None else f"{n:,.0f}".replace(",", " ")


def _menu_kb(chat_id: int):
    return keyboards.back_menu_kb(chat_id)


async def _saving(event) -> Message | None:
    """In-flight feedback before a write — and, for a typed write, the screen to land on.

    On a tap `common.begin_write` edits the message the button was on: the screen becomes
    "⏳ Saving…", the keyboard goes away, and the impatient second tap has nothing to hit.

    A typed answer has no keyboard to take away, so `begin_write` posts the notice as a NEW
    message. If the outcome is then posted as yet another message, that "⏳ Saving…" stays in
    the chat forever, claiming a write is still running that finished seconds ago — and on a
    phone it is the message the owner scrolls back to. Handing the notice back lets `_finish`
    put the result *onto* it, so a typed write leaves exactly one message behind, the way a
    tapped one does. `transactions.py` solves the same problem with its own `_saving`; this
    file has no tracked flow screen to reuse, so it keeps the notice instead of an id.
    """
    chat_id = common.chat_id_of(event)
    if isinstance(event, CallbackQuery):
        await common.begin_write(event, chat_id)
        return None
    try:
        return await event.answer(t(chat_id, "common.saving"))
    except Exception:  # noqa: BLE001 - the notice is feedback; it must never fail the write
        log.debug("could not post the saving notice for chat %s", chat_id, exc_info=True)
        return None


async def _finish(event, notice: Message | None, text: str, kb=None) -> None:
    """Render the outcome of a write, replacing the "Saving…" notice when there was one.

    The error handling mirrors `common.show` deliberately: "not modified" is a successful
    render, a message that is gone falls back to sending, and anything else — an unbalanced
    tag, a bad markup — is re-raised so F4's error handler reports it rather than this
    swallowing it. `notice` is None for a tap, where `common.show` edits the screen already.
    """
    if notice is not None:
        try:
            await notice.edit_text(text, reply_markup=kb)
            return
        except TelegramBadRequest as exc:
            detail = (exc.message or "").lower()
            if _NOT_MODIFIED in detail:
                return
            if not any(reason in detail for reason in _UNEDITABLE):
                raise
            log.debug("saving notice was gone; sending the outcome instead", exc_info=True)
    await common.show(event, text, kb)


def _sub_kb(chat_id: int, back: str):
    """Back to the screen this one was opened from, plus the way out to the main menu."""
    return ikb([ui.nav(chat_id, back=back, menu=True)])


def _bucket_label(chat_id: int, line: dict) -> str:
    """The bucket's name in the owner's language, falling back to the server's English."""
    key = _BUCKET_KEY.get(str(line.get("bucket") or "").upper())
    return t(chat_id, key) if key else esc(line.get("label") or "—")


def _action_text(chat_id: int, item: dict) -> str:
    """One ActionItem as a sentence in the owner's language.

    `params` values are the server's own formatting (amounts already grouped and carrying
    their unit, months as ISO) plus, on the not-yet-started notes, a lender or creditor NAME
    that came from the owner's own typing — so every value is escaped before it is
    interpolated into what becomes HTML message text.
    """
    key = _ACTION_KEY.get(item.get("code"))
    if key:
        return t(chat_id, key, **{k: esc(v) for k, v in (item.get("params") or {}).items()})
    # No code, or a code this file has not been taught: the DTO keeps `text` as the fallback
    # for exactly this, and for the owner's own note from the rules editor it is the only
    # correct rendering — those are their words, in the language they typed them.
    return esc(item.get("text") or "")


async def _category_names(chat_id: int) -> dict[str, str]:
    """English category name → the owner's language, for the breakdown's bare `c.name`.

    `GET /dashboard/category-breakdown` groups by `categories.name` and returns that one
    string, while every seeded category also carries a `nameUz` that the web app, the
    transaction list and the category picker all show instead. Without this map the one
    screen that answers "where did this month's money go" is the only Uzbek screen in the bot
    printing "Food & Dining". Fetched only for an Uzbek chat, where the map is not an
    identity, and a failure here costs a translation rather than the screen.
    """
    if get_lang(chat_id) != UZ:
        return {}
    try:
        roots = await api.request(chat_id, "GET", "/categories") or []
    except Exception:  # noqa: BLE001
        return {}
    names: dict[str, str] = {}
    for root in roots:
        for c in (root, *(root.get("children") or [])):
            name = c.get("name")
            uz = (c.get("nameUz") or "").strip()
            if name and uz:
                names[name] = uz
    return names


# ── navigation ───────────────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("menu:"))
async def on_menu(cb: CallbackQuery, state: FSMContext) -> None:
    """The main-menu router. Every `menu:*` tap also abandons whatever flow was in progress,
    which is what makes the Menu button a safe escape hatch from any half-finished screen."""
    await common.ack(cb)
    await state.clear()
    if not await common.gate(cb):
        return
    chat_id = common.chat_id_of(cb)
    page = cb.data.split(":", 1)[1]
    if page == "home":
        await common.show(cb, keyboards.menu_text(chat_id), keyboards.main_menu_kb(chat_id))
    elif page == "dashboard":
        await show_home(cb)
    elif page == "overview":
        await show_plan(cb)
    elif page == "settings":
        await show_settings(cb)
    elif page == "months":
        from .months import show_menu
        await show_menu(cb)
    elif page == "transactions":
        from .transactions import show_menu
        await show_menu(cb)
    elif page == "finance":
        from .finance import show_menu
        await show_menu(cb)
    elif page == "cards":
        from .cards import show_menu
        await show_menu(cb)
    elif page == "categories":
        from .categories import show_menu
        await show_menu(cb)
    else:
        # A button from a much older build, or a replayed update. Saying so beats a tap that
        # clears the spinner and changes nothing on screen.
        await common.show(cb, t(chat_id, "common.unknownSection"), _menu_kb(chat_id))


# ── Home ─────────────────────────────────────────────────────────────────────
async def _monthly_series(chat_id: int, year: int) -> list[dict]:
    """`GET /dashboard/monthly` for one calendar year: twelve rows, zero-filled by the server.

    Failure is swallowed on purpose. This is the second call on Home; the first one already
    produced the balances, and losing the month block is a smaller loss than replacing a
    working screen with an error.
    """
    try:
        return await api.request(chat_id, "GET", "/dashboard/monthly",
                                 params={"currency": CURRENCY, "year": year}) or []
    except Exception:  # noqa: BLE001
        log.debug("monthly series for %s unavailable", year, exc_info=True)
        return []


async def show_home(event) -> None:
    chat_id = common.chat_id_of(event)
    try:
        d = await api.request(chat_id, "GET", "/dashboard/summary",
                              params={"currency": CURRENCY}) or {}
    except api.NeedsLogin:
        await common.show(event, t(chat_id, "common.sessionExpired"), keyboards.login_kb(chat_id))
        return
    except api.Unreachable:
        await common.show(event, t(chat_id, "common.serverUnreachable"), _menu_kb(chat_id))
        return
    except Exception:  # noqa: BLE001
        await common.show(event, t(chat_id, "menu.dashboardError"), _menu_kb(chat_id))
        return

    today = clock.today()
    series = await _monthly_series(chat_id, today.year)
    this_month = next((m for m in series if m.get("month") == today.month), {})

    lines = [
        f"{t(chat_id, 'menu.dashboard.title')} · {CURRENCY} · {clock.month()}",
        "",
        f"{t(chat_id, 'menu.dashboard.spendable')}: "
        f"<b>{fmt_money(d.get('spendableBalance', d.get('availableBalance')))}</b>",
        f"{t(chat_id, 'menu.dashboard.netWorth')}: "
        f"<b>{fmt_money(d.get('netWorth', d.get('netBalance')))}</b>",
        t(chat_id, "menu.dashboard.netWorthNote"),
    ]
    # `DashboardSummaryResponse.transactionCount` is a primitive long, so it is always present
    # and 0 really does mean "this account has never recorded anything".
    count = int(_num(d.get("transactionCount")) or 0)
    if not count:
        # The empty state. Six zeroes and two drill-downs into nothing answer no question the
        # owner has on their first day; the question they DO have is how to put something in,
        # and the typed shortcut is the one answer nothing else on any screen gives them.
        lines += ["", t(chat_id, "menu.dashboard.empty")]
        rows = [[(t(chat_id, "menu.quickAddBtn"), "qa:new")]]
    else:
        if this_month:
            lines += [
                "",
                t(chat_id, "menu.dashboard.thisMonth"),
                f"{t(chat_id, 'menu.dashboard.income')}: {fmt_money(this_month.get('income'))}",
                f"{t(chat_id, 'menu.dashboard.expenses')}: "
                f"{fmt_money(this_month.get('expense'))}",
                f"{t(chat_id, 'menu.dashboard.net')}: <b>{fmt_money(this_month.get('net'))}</b>",
            ]
        lines += [
            "",
            t(chat_id, "menu.dashboard.allTime",
              income=fmt_money(d.get("totalIncome")), expense=fmt_money(d.get("totalExpense")),
              count=count),
        ]
        rows = [[(t(chat_id, "menu.dashboard.byCategoryBtn"), "home:cats:EXPENSE"),
                 (t(chat_id, "menu.dashboard.yearBtn"), "home:year")]]

    rows.append([(t(chat_id, "common.menu"), "menu:home")])
    await common.show(event, "\n".join(lines), ikb(rows))


@router.callback_query(F.data.startswith("home:cats"))
async def home_categories(cb: CallbackQuery) -> None:
    """Home → Where it went: this month's spending (or income) by category."""
    await common.ack(cb)
    if not await common.gate(cb):
        return
    chat_id = common.chat_id_of(cb)
    kind = "INCOME" if cb.data.endswith(":INCOME") else "EXPENSE"
    today = clock.today()
    try:
        rows = await api.request(chat_id, "GET", "/dashboard/category-breakdown",
                                 params={"type": kind, "currency": CURRENCY,
                                         "year": today.year, "month": today.month}) or []
    except api.NeedsLogin:
        await common.show(cb, t(chat_id, "common.sessionExpired"), keyboards.login_kb(chat_id))
        return
    except api.Unreachable:
        await common.show(cb, t(chat_id, "common.serverUnreachable"),
                          _sub_kb(chat_id, "menu:dashboard"))
        return
    except Exception:  # noqa: BLE001
        await common.show(cb, t(chat_id, "menu.dashboard.catsError"),
                          _sub_kb(chat_id, "menu:dashboard"))
        return

    names = await _category_names(chat_id)
    sub = ("menu.dashboard.catsSubIncome" if kind == "INCOME"
           else "menu.dashboard.catsSubExpense")
    lines = [
        t(chat_id, "menu.dashboard.catsTitle", month=clock.month()),
        t(chat_id, sub),
        "",
    ]
    if not rows:
        lines.append(t(chat_id, "common.nothingHere"))
    total = 0.0
    for i, row in enumerate(rows):
        # The total counts every category; only the first screenful is listed. A tail of
        # 200-soʻm categories is not worth the scroll, but it is worth the total.
        total += _num(row.get("amount")) or 0.0
        if i >= _MAX_CATEGORY_ROWS:
            continue
        raw = row.get("category") or "—"
        lines.append(t(chat_id, "menu.dashboard.catLine",
                       name=esc(names.get(raw, raw)),
                       amount=fmt_money(row.get("amount")),
                       pct=fmt_pct(row.get("percentage"))))
    if len(rows) > _MAX_CATEGORY_ROWS:
        lines.append(t(chat_id, "menu.dashboard.catsMore", n=len(rows) - _MAX_CATEGORY_ROWS))
    if rows:
        lines += ["", t(chat_id, "menu.dashboard.catsTotal", amount=fmt_money(total))]

    other = "INCOME" if kind == "EXPENSE" else "EXPENSE"
    other_key = ("menu.dashboard.catsIncomeBtn" if other == "INCOME"
                 else "menu.dashboard.catsExpenseBtn")
    kb = ikb([
        [(t(chat_id, other_key), f"home:cats:{other}")],
        ui.nav(chat_id, back="menu:dashboard", menu=True),
    ])
    await common.show(cb, "\n".join(lines), kb)


@router.callback_query(F.data.startswith("home:year"))
async def home_year(cb: CallbackQuery) -> None:
    """Home → This year: one line per month of a calendar year, income / expense / net."""
    await common.ack(cb)
    if not await common.gate(cb):
        return
    chat_id = common.chat_id_of(cb)
    tail = cb.data.rpartition(":")[2]
    year = int(tail) if _YEAR.fullmatch(tail) else clock.today().year
    try:
        rows = await api.request(chat_id, "GET", "/dashboard/monthly",
                                 params={"currency": CURRENCY, "year": year}) or []
    except api.NeedsLogin:
        await common.show(cb, t(chat_id, "common.sessionExpired"), keyboards.login_kb(chat_id))
        return
    except api.Unreachable:
        await common.show(cb, t(chat_id, "common.serverUnreachable"),
                          _sub_kb(chat_id, "menu:dashboard"))
        return
    except Exception:  # noqa: BLE001
        await common.show(cb, t(chat_id, "menu.dashboard.yearError"),
                          _sub_kb(chat_id, "menu:dashboard"))
        return

    lines = [t(chat_id, "menu.dashboard.yearTitle", year=year, currency=CURRENCY), ""]
    income_total = expense_total = 0.0
    printed = 0
    for row in rows:
        income = _num(row.get("income")) or 0.0
        expense = _num(row.get("expense")) or 0.0
        income_total += income
        expense_total += expense
        # The server zero-fills all twelve months, so an untouched month would otherwise take
        # a row to say nothing. Months are printed as YYYY-MM to match the Months screen —
        # `monthName` is the English enum abbreviated to three letters ("SEP").
        if income == 0 and expense == 0:
            continue
        printed += 1
        lines.append(t(chat_id, "menu.dashboard.yearLine",
                       month=f"{year:04d}-{int(row.get('month') or 0):02d}",
                       income=_plain(income), expense=_plain(expense),
                       net=_plain(row.get("net"))))
    if not printed:
        lines.append(t(chat_id, "menu.dashboard.yearEmpty"))
    else:
        lines += ["", t(chat_id, "menu.dashboard.yearTotals",
                        income=_plain(income_total), expense=_plain(expense_total),
                        net=_plain(income_total - expense_total))]

    step = [(f"◀️ {year - 1}", f"home:year:{year - 1}")]
    if year < clock.today().year:
        step.append((f"{year + 1} ▶️", f"home:year:{year + 1}"))
    await common.show(cb, "\n".join(lines),
                      ikb([step, ui.nav(chat_id, back="menu:dashboard", menu=True)]))


# ── Plan ─────────────────────────────────────────────────────────────────────
async def _tier(chat_id: int, month: str) -> dict:
    return await api.request(chat_id, "GET", "/overview/tier",
                             params={"currency": CURRENCY, "month": month}) or {}


def _withheld_lines(chat_id: int, data: dict) -> list[str]:
    """The three states in which the backend deliberately withholds the allocation.

    Each is rendered from the flag rather than from the note the server sends beside it,
    because the flag lets this screen say more: which subscriptions are outstanding and by how
    much, and — for the missing income — a button that fixes it without leaving Telegram.
    """
    lines: list[str] = []
    if data.get("missingStableIncome"):
        lines.append(t(chat_id, "menu.overview.setIncomeWarning"))
    if data.get("beforeTrackingStart"):
        lines.append(t(chat_id, "menu.overview.trackingStarts",
                       month=esc(data.get("trackingStartMonth") or "—")))
    if data.get("subscriptionsPending"):
        lines.append(t(chat_id, "menu.overview.subsPendingWarning"))
        for ps in data.get("pendingSubscriptions") or []:
            lines.append("• " + t(chat_id, "menu.overview.subsPendingLine",
                                  name=esc(ps.get("name") or "—"),
                                  paid=fmt_money(ps.get("paid")),
                                  amount=fmt_money(ps.get("amount"))))
    return lines


def _tier_line(chat_id: int, data: dict, allocation: dict, withheld: bool) -> str:
    """"🏅 <b>Level 1.2</b> · bank loan only · tight (…)".

    `levelLabel` and `scenarioLabel` are both English strings composed server-side; `level` /
    `subLevel` and `scenarioKey` are the identifiers next to them, and those are what this
    renders. While the allocation is withheld there is no scenario to name, so the line stops
    at the level rather than printing "guidance isn't defined yet", which would be a different
    claim entirely.
    """
    if data.get("missingStableIncome"):
        level = t(chat_id, "menu.overview.levelUnknown")
    elif data.get("level") is None:
        level = t(chat_id, "menu.overview.levelAbove")
    else:
        level = t(chat_id, "menu.overview.levelN",
                  n=esc(data.get("subLevel") or data.get("level")))
    if withheld:
        return t(chat_id, "menu.overview.tierLineBare", level=level)
    scenario = t(chat_id, _SCENARIO_KEY.get(allocation.get("scenarioKey"),
                                            "menu.overview.scenarioUnset"))
    return t(chat_id, "menu.overview.tierLine", level=level, scenario=scenario)


def _bucket_line(chat_id: int, line: dict) -> str:
    """One bucket, in the one form that fits a phone: what is still owed to it."""
    label = _bucket_label(chat_id, line)
    if not line.get("recommended"):
        paid = _num(line.get("paidAmount")) or 0.0
        extra = (t(chat_id, "menu.overview.bucketPaidExtra", paid=fmt_money(paid))
                 if paid > 0 else "")
        return "• " + t(chat_id, "menu.overview.bucketNoNeed", label=label, extra=extra)
    if (_num(line.get("remainingAmount")) or 0.0) <= 0:
        return "• " + t(chat_id, "menu.overview.bucketLineDone", label=label,
                        minAmount=fmt_money(line.get("minAmount")))
    return "• " + t(chat_id, "menu.overview.bucketLine", label=label,
                    minPercent=fmt_pct(line.get("minPercent")),
                    minAmount=fmt_money(line.get("minAmount")),
                    left=fmt_money(line.get("remainingAmount")))


async def show_plan(event, month: str | None = None) -> None:
    chat_id = common.chat_id_of(event)
    month = _month_or_now(month)
    try:
        data = await _tier(chat_id, month)
    except api.NeedsLogin:
        await common.show(event, t(chat_id, "common.sessionExpired"), keyboards.login_kb(chat_id))
        return
    except api.Unreachable:
        await common.show(event, t(chat_id, "common.serverUnreachable"), _menu_kb(chat_id))
        return
    except Exception:  # noqa: BLE001
        await common.show(event, t(chat_id, "menu.overviewError"), _menu_kb(chat_id))
        return

    allocation = data.get("allocation") or {}
    withheld = bool(data.get("missingStableIncome") or data.get("beforeTrackingStart")
                    or data.get("subscriptionsPending"))

    lines = [
        f"{t(chat_id, 'menu.overview.title')} · {CURRENCY} · {esc(month)}",
        _tier_line(chat_id, data, allocation, withheld),
        "",
        f"{t(chat_id, 'menu.overview.stableIncome')}: {fmt_money(data.get('income'))}",
        f"{t(chat_id, 'menu.overview.leftMoney')}: {fmt_money(data.get('leftMoney'))}",
        f"{t(chat_id, 'menu.overview.debtPayments')}: {fmt_money(data.get('debtPayments'))}",
    ]
    warnings = _withheld_lines(chat_id, data)
    if warnings:
        lines += ["", *warnings]

    rows: list[list[tuple[str, str]]] = []
    if not withheld:
        if data.get("allocationBase") is not None:
            lines += ["", t(chat_id, "menu.overview.baseNote",
                            base=fmt_money(data.get("allocationBase")))]
        if allocation.get("allocationLocked"):
            lines.append(t(chat_id, "menu.overview.allocationLocked"))

        bucket_lines = allocation.get("lines") or []
        if bucket_lines:
            lines += ["", t(chat_id, "menu.overview.bucketsHeader")]
            lines += [_bucket_line(chat_id, ln) for ln in bucket_lines]
            # Every bucket line is a button: the figure it quotes is a sum of donations,
            # contributions and "already paid" marks, and the owner who disputes it has no
            # other way to see what went into it.
            rows += ui.grid(
                [(t(chat_id, "menu.bucket.btn", label=_bucket_label(chat_id, ln)),
                  f"bucket:{str(ln.get('bucket') or '').upper()}:{month}")
                 for ln in bucket_lines if str(ln.get("bucket") or "").upper() in _BUCKETS],
                2)

        actions = allocation.get("actions") or []
        todo = [a for a in actions if a.get("action")]
        notes = [a for a in actions if not a.get("action")]
        if todo:
            lines += ["", t(chat_id, "menu.overview.actionsHeader")]
            for a in todo:
                sentence = _action_text(chat_id, a)
                if a.get("target") is not None:
                    lines.append("• " + t(chat_id, "menu.overview.actionProgress",
                                          text=sentence, paid=fmt_money(a.get("paid")),
                                          target=fmt_money(a.get("target"))))
                else:
                    lines.append(f"• {sentence}")
        if notes:
            # The notes are the long half of this response and the half nobody re-reads once
            # they know their tier, so they live under Details and are counted here.
            lines += ["", t(chat_id, "menu.overview.notesCount", n=len(notes))]

    if data.get("missingStableIncome"):
        rows.insert(0, [(t(chat_id, "ui.setIncome"), "settings:income")])
    rows.append([(t(chat_id, "menu.overview.detailsBtn"), f"plan:details:{month}"),
                 (t(chat_id, "menu.overview.historyBtn"), f"plan:ledger:{month}")])
    rows.append([(t(chat_id, "common.menu"), "menu:home")])
    await common.show(event, "\n".join(lines), ikb(rows))


@router.callback_query(F.data.startswith("plan:details"))
async def plan_details(cb: CallbackQuery) -> None:
    """Plan → Details: where the left balance comes from, per-bucket detail, the notes."""
    await common.ack(cb)
    if not await common.gate(cb):
        return
    chat_id = common.chat_id_of(cb)
    month = _month_or_now(cb.data.rpartition(":")[2])
    back = _sub_kb(chat_id, "menu:overview")
    try:
        data = await _tier(chat_id, month)
    except api.NeedsLogin:
        await common.show(cb, t(chat_id, "common.sessionExpired"), keyboards.login_kb(chat_id))
        return
    except api.Unreachable:
        await common.show(cb, t(chat_id, "common.serverUnreachable"), back)
        return
    except Exception:  # noqa: BLE001
        await common.show(cb, t(chat_id, "menu.overviewError"), back)
        return

    allocation = data.get("allocation") or {}
    debt = data.get("debtBreakdown") or {}
    ratio = _num(data.get("debtRatio"))
    lines = [
        t(chat_id, "menu.overview.detailsTitle", month=esc(month)),
        "",
        t(chat_id, "menu.overview.mathHeader"),
        f"{t(chat_id, 'menu.overview.stableIncome')}: {fmt_money(data.get('income'))}",
        f"{t(chat_id, 'menu.overview.mandatorySubs')}: "
        f"−{fmt_money(data.get('mandatorySubscriptions'))}",
        f"{t(chat_id, 'menu.overview.leftMoney')}: {fmt_money(data.get('leftMoney'))}",
        f"{t(chat_id, 'menu.overview.debtPayments')}: −{fmt_money(data.get('debtPayments'))}",
        f"{t(chat_id, 'menu.overview.debtBank')}: {fmt_money(debt.get('bankLoans'))}",
        f"{t(chat_id, 'menu.overview.debtLoans')}: {fmt_money(debt.get('loansTaken'))}",
        f"{t(chat_id, 'menu.overview.debtDebts')}: {fmt_money(debt.get('debts'))}",
        f"{t(chat_id, 'menu.overview.leftBalance')}: "
        f"<b>{fmt_money(data.get('allocationBase'))}</b>",
    ]
    if ratio is not None:
        # `debtRatio` is the fraction debtPayments ÷ income, not a percentage.
        lines.append(f"{t(chat_id, 'menu.overview.debtRatio')}: {fmt_pct(ratio * 100)}")

    bucket_lines = allocation.get("lines") or []
    if bucket_lines:
        lines += ["", t(chat_id, "menu.overview.bucketsDetailHeader")]
        for ln in bucket_lines:
            label = _bucket_label(chat_id, ln)
            if ln.get("recommended"):
                lines.append(t(chat_id, "menu.overview.bucketDetailLine", label=label,
                               target=fmt_money(ln.get("minAmount")),
                               paid=fmt_money(ln.get("paidAmount")),
                               left=fmt_money(ln.get("remainingAmount"))))
            else:
                lines.append(t(chat_id, "menu.overview.bucketDetailNoNeed", label=label,
                               paid=fmt_money(ln.get("paidAmount"))))
            # `paidAmount = recorded + markedAmount`, and only the recorded half ever left a
            # wallet — the month-close snapshot counts nothing else. Where the two differ,
            # saying so is the difference between the owner believing money moved and knowing
            # it did not.
            marked = _num(ln.get("markedAmount")) or 0.0
            if marked > 0:
                lines.append(t(chat_id, "menu.overview.bucketMarkedNote",
                               amount=fmt_money(marked)))

    notes = [a for a in (allocation.get("actions") or []) if not a.get("action")]
    if notes:
        lines += ["", t(chat_id, "menu.overview.notesHeader")]
        lines += [f"• {_action_text(chat_id, a)}" for a in notes]
    await common.show(cb, "\n".join(lines), back)


@router.callback_query(F.data.startswith("bucket:"))
async def bucket_payments(cb: CallbackQuery) -> None:
    """Plan → one bucket: the rows that add up to the "paid" figure on the Plan screen."""
    await common.ack(cb)
    if not await common.gate(cb):
        return
    chat_id = common.chat_id_of(cb)
    parts = cb.data.split(":")
    bucket = parts[1].upper() if len(parts) > 1 else ""
    month = _month_or_now(parts[2] if len(parts) > 2 else None)
    back = _sub_kb(chat_id, "menu:overview")
    if bucket not in _BUCKETS:
        await common.show(cb, t(chat_id, "common.unknownSection"), back)
        return

    try:
        data = await _tier(chat_id, month)
        rows = await api.request(chat_id, "GET", f"/overview/bucket/{bucket}/payments",
                                 params={"currency": CURRENCY, "month": month}) or []
    except api.NeedsLogin:
        await common.show(cb, t(chat_id, "common.sessionExpired"), keyboards.login_kb(chat_id))
        return
    except api.Unreachable:
        await common.show(cb, t(chat_id, "common.serverUnreachable"), back)
        return
    except Exception:  # noqa: BLE001
        await common.show(cb, t(chat_id, "menu.bucket.error"), back)
        return

    line = next((ln for ln in ((data.get("allocation") or {}).get("lines") or [])
                 if str(ln.get("bucket") or "").upper() == bucket), {})
    label = _bucket_label(chat_id, line or {"bucket": bucket})
    lines = [t(chat_id, "menu.bucket.title", label=label, month=esc(month)), ""]
    if line.get("recommended"):
        lines.append(t(chat_id, "menu.bucket.recommended",
                       pct=fmt_pct(line.get("minPercent")),
                       amount=fmt_money(line.get("minAmount"))))
    elif line:
        lines.append(t(chat_id, "menu.bucket.notNeeded"))
    # The headline figures come from the allocation line, not from summing the rows below:
    # this screen exists to explain the number the Plan screen quoted, so it has to quote the
    # same one. The rows are the explanation, and where they cannot add up to it — a bucket
    # the tier does not emit a line for — the sum is the only figure there is.
    paid = _num(line.get("paidAmount"))
    if paid is None:
        paid = sum(_num(r.get("amount")) or 0.0 for r in rows)
    lines.append(t(chat_id, "menu.bucket.paid", amount=fmt_money(paid)))
    marked = _num(line.get("markedAmount"))
    if marked is None:
        marked = sum(_num(r.get("amount")) or 0.0 for r in rows if r.get("marked"))
    if marked > 0:
        lines.append(t(chat_id, "menu.bucket.markedPart", amount=fmt_money(marked)))
    if line.get("recommended"):
        lines.append(t(chat_id, "menu.bucket.left",
                       amount=fmt_money(line.get("remainingAmount"))))

    lines += ["", t(chat_id, "menu.bucket.paymentsHeader")]
    if not rows:
        lines.append(t(chat_id, "menu.bucket.noPayments"))
    for r in rows[:_MAX_BUCKET_ROWS]:
        lines.append(t(chat_id, "menu.bucket.row", date=esc(r.get("date") or "—"),
                       amount=fmt_money(r.get("amount")),
                       label=_row_suffix(chat_id, r)))
    if len(rows) > _MAX_BUCKET_ROWS:
        lines.append(t(chat_id, "menu.bucket.more", n=len(rows) - _MAX_BUCKET_ROWS))

    kb_rows: list[list[tuple[str, str]]] = []
    if marked > 0:
        # A mark is the only entry in this list with no transaction behind it, and the reason
        # the owner is on this screen is usually that one of them is wrong. Deleting it lives
        # on Finance's marks screen (`fmarks:<month>`), so this is a link, not a second copy
        # of it — the label is ours so the button does not wait on another module's key.
        kb_rows.append([(t(chat_id, "menu.bucket.marksBtn"), f"fmarks:{month}")])
    kb_rows.append(ui.nav(chat_id, back="menu:overview", menu=True))
    await common.show(cb, "\n".join(lines), ikb(kb_rows))


def _row_suffix(chat_id: int, row: dict) -> str:
    """What to put after the amount on a bucket-payment row, separator included.

    A marked row says so — it is the whole reason the two figures on the screen above can
    disagree with the owner's memory. Otherwise the server's `label` is the counterparty (a
    donation recipient, an investment) and worth printing, unless it is one of the constants
    that only repeat the heading this row already sits under.
    """
    if row.get("marked"):
        return t(chat_id, "menu.bucket.markedBadge")
    label = (row.get("label") or "").strip()
    if not label or label in _GENERIC_ROW_LABELS:
        return ""
    if label == "Anonymous":  # the server's literal for an anonymised donation
        return " · " + t(chat_id, "menu.bucket.anonymous")
    return " · " + esc(label)


@router.callback_query(F.data.startswith("plan:ledger"))
async def plan_ledger(cb: CallbackQuery) -> None:
    """Plan → History: recommended-versus-paid as one running balance across months."""
    await common.ack(cb)
    if not await common.gate(cb):
        return
    chat_id = common.chat_id_of(cb)
    month = _month_or_now(cb.data.rpartition(":")[2])
    back = _sub_kb(chat_id, "menu:overview")
    try:
        data = await api.request(chat_id, "GET", "/overview/allocation-ledger",
                                 params={"currency": CURRENCY, "month": month}) or {}
    except api.NeedsLogin:
        await common.show(cb, t(chat_id, "common.sessionExpired"), keyboards.login_kb(chat_id))
        return
    except api.Unreachable:
        await common.show(cb, t(chat_id, "common.serverUnreachable"), back)
        return
    except Exception:  # noqa: BLE001
        await common.show(cb, t(chat_id, "menu.ledger.error"), back)
        return

    lines = [t(chat_id, "menu.ledger.title", month=esc(month))]
    if data.get("startMonth"):
        lines.append(t(chat_id, "menu.ledger.startMonth", month=esc(data["startMonth"])))
    # The ledger withholds its dues in exactly the states the tier withholds its allocation,
    # and returns empty lists for them — so it says why, in the same words the Plan screen uses.
    warnings = _withheld_lines(chat_id, data)
    if warnings:
        lines += ["", *warnings]
    else:
        lines += [
            "",
            f"{t(chat_id, 'menu.ledger.due')}: {fmt_money(data.get('dueThisMonth'))}",
            f"{t(chat_id, 'menu.ledger.carried')}: "
            f"{fmt_money(data.get('carriedFromPrevious'))}",
        ]
        if data.get("carriedStartMonth") and data.get("carriedEndMonth"):
            lines.append(t(chat_id, "menu.ledger.carriedRange",
                           start=esc(data["carriedStartMonth"]),
                           end=esc(data["carriedEndMonth"])))
        lines.append(f"{t(chat_id, 'menu.ledger.totalDue')}: "
                     f"<b>{fmt_money(data.get('totalDueNow'))}</b>")

        buckets = data.get("buckets") or []
        if buckets:
            lines += ["", t(chat_id, "menu.ledger.bucketsHeader")]
            for b in buckets:
                label = _bucket_label(chat_id, b)
                key = ("menu.ledger.bucketClear" if (_num(b.get("outstanding")) or 0.0) <= 0
                       else "menu.ledger.bucketLine")
                lines.append(t(chat_id, key, label=label, paid=fmt_money(b.get("paid")),
                               recommended=fmt_money(b.get("recommended")),
                               outstanding=fmt_money(b.get("outstanding"))))

        months = list(reversed(data.get("months") or []))
        if months:
            lines += ["", t(chat_id, "menu.ledger.monthsHeader")]
            for m in months[:_MAX_LEDGER_MONTHS]:
                due = sum(_num(ln.get("recommended")) or 0.0 for ln in (m.get("lines") or []))
                paid = sum(_num(ln.get("paid")) or 0.0 for ln in (m.get("lines") or []))
                lines.append(t(chat_id, "menu.ledger.monthLine", month=esc(m.get("month") or "—"),
                               due=_plain(due), paid=_plain(paid)))
            if len(months) > _MAX_LEDGER_MONTHS:
                lines.append(t(chat_id, "menu.ledger.monthsMore",
                               n=len(months) - _MAX_LEDGER_MONTHS))

    step = [(f"◀️ {_shift(month, -1)}", f"plan:ledger:{_shift(month, -1)}")]
    if month < clock.month():
        step.append((f"{_shift(month, 1)} ▶️", f"plan:ledger:{_shift(month, 1)}"))
    await common.show(cb, "\n".join(lines),
                      ikb([step, ui.nav(chat_id, back="menu:overview", menu=True)]))


# ── Settings ─────────────────────────────────────────────────────────────────
async def show_settings(event) -> None:
    chat_id = common.chat_id_of(event)
    try:
        s = await api.request(chat_id, "GET", "/settings") or {}
    except api.NeedsLogin:
        await common.show(event, t(chat_id, "common.sessionExpired"), keyboards.login_kb(chat_id))
        return
    except api.Unreachable:
        await common.show(event, t(chat_id, "common.serverUnreachable"), _menu_kb(chat_id))
        return
    except Exception:  # noqa: BLE001
        await common.show(event, t(chat_id, "menu.settingsError"), _menu_kb(chat_id))
        return

    income = _num(s.get("monthlyStableIncome"))
    tracking = _tracking_month(s)
    lines = [
        t(chat_id, "menu.settings.title"),
        "",
        f"{t(chat_id, 'menu.settings.currency')}: <b>{CURRENCY}</b>",
        f"{t(chat_id, 'menu.settings.stableIncome')}: "
        f"<b>{fmt_money(income) if income else t(chat_id, 'menu.settings.notSet')}</b>",
        f"{t(chat_id, 'menu.settings.trackingMonth')}: "
        + (f"<b>{esc(tracking)}</b> {t(chat_id, 'menu.settings.locked')}" if tracking
           else f"<b>{t(chat_id, 'menu.settings.notSet')}</b>"),
        "",
        t(chat_id, "menu.settings.hint"),
    ]
    # One definition of this keyboard, in keyboards.py. The screen used to build a second copy
    # that was a row short, so what Settings offered depended on which file you were reading.
    await common.show(event, "\n".join(lines), keyboards.settings_kb(chat_id))


def _tracking_month(settings: dict) -> str | None:
    """`allocationTrackingStartMonth` as `YYYY-MM`. The API sends it as a LocalDate."""
    raw = str(settings.get("allocationTrackingStartMonth") or "")
    return raw[:7] if _MONTH.fullmatch(raw[:7]) else None


# ── Settings → monthly stable income ─────────────────────────────────────────
@router.callback_query(F.data == "settings:income")
async def income_open(cb: CallbackQuery, state: FSMContext) -> None:
    """The screen behind the income guard and the Settings row alike.

    Reachable from a wall the owner cannot get past any other way, so it does its own read of
    the current value: arriving here from the guard, "Now: —" is the confirmation that the
    guard was telling the truth, and arriving from Settings it is the value being replaced.
    """
    await common.ack(cb)
    if not await common.gate(cb):
        return
    chat_id = common.chat_id_of(cb)
    try:
        s = await api.request(chat_id, "GET", "/settings") or {}
    except api.NeedsLogin:
        await common.show(cb, t(chat_id, "common.sessionExpired"), keyboards.login_kb(chat_id))
        return
    except Exception:  # noqa: BLE001
        s = {}  # the prompt is still usable without the current figure
    income = _num(s.get("monthlyStableIncome"))
    await state.set_state(Settings.income)
    lines = [
        t(chat_id, "menu.income.title"),
        "",
        t(chat_id, "menu.income.current",
          amount=fmt_money(income) if income else t(chat_id, "menu.settings.notSet")),
        "",
        t(chat_id, "menu.income.prompt"),
        t(chat_id, "menu.income.examples"),
    ]
    await common.show(cb, "\n".join(lines),
                      ikb([ui.nav(chat_id, back="menu:settings", cancel="menu:home")]))


@router.message(StateFilter(Settings.income))
async def income_typed(message: Message, state: FSMContext) -> None:
    chat_id = message.chat.id
    amount = parse_amount(message.text)
    if amount is None:
        # Stay in the state: the owner is one keystroke from a valid answer, and dropping them
        # back to Settings would mean re-opening the screen to try again.
        await message.answer(f"{t(chat_id, 'common.positiveNumber')}\n"
                             f"{t(chat_id, 'menu.income.examples')}")
        return
    if not await common.gate(message):
        await state.clear()
        return
    notice = await _saving(message)
    try:
        # Only the one field. `SettingsService.update` writes each property solely when the
        # request carries it, so the tracking start month and both Telegram URLs survive.
        await api.request(chat_id, "PUT", "/settings", json={"monthlyStableIncome": amount})
    except api.NeedsLogin:
        await state.clear()
        await _finish(message, notice, t(chat_id, "common.sessionExpired"),
                      keyboards.login_kb(chat_id))
        return
    except api.Unreachable:
        # Still in `Settings.income`, so the next thing typed is another attempt.
        await _finish(message, notice, t(chat_id, "common.serverUnreachable"))
        return
    except api.ApiError as exc:
        await _finish(message, notice, f"❌ {esc(exc.message)}")
        return
    except Exception:  # noqa: BLE001
        log.exception("PUT /settings (income) failed for chat %s", chat_id)
        await _finish(message, notice, t(chat_id, "menu.income.saveError"))
        return
    await state.clear()
    await _finish(
        message, notice, t(chat_id, "menu.income.saved", amount=fmt_money(amount)),
        ikb([[(t(chat_id, "menu.page.settings"), "menu:settings"),
              (t(chat_id, "common.menu"), "menu:home")]]))


# ── Settings → allocation tracking start month ───────────────────────────────
@router.callback_query(F.data == "settings:track")
async def track_open(cb: CallbackQuery, state: FSMContext) -> None:
    """Write-once, and the screen says so before anything is typed.

    `SettingsService.update` accepts the value only while the stored one is null; re-sending
    the same month is a no-op and a different one is a 400. Offering the field without that
    sentence would make a permanent decision look like an editable setting.
    """
    await common.ack(cb)
    if not await common.gate(cb):
        return
    chat_id = common.chat_id_of(cb)
    try:
        s = await api.request(chat_id, "GET", "/settings") or {}
    except api.NeedsLogin:
        await common.show(cb, t(chat_id, "common.sessionExpired"), keyboards.login_kb(chat_id))
        return
    except api.Unreachable:
        await common.show(cb, t(chat_id, "common.serverUnreachable"),
                          _sub_kb(chat_id, "menu:settings"))
        return
    except Exception:  # noqa: BLE001
        await common.show(cb, t(chat_id, "menu.settingsError"), _sub_kb(chat_id, "menu:settings"))
        return

    locked = _tracking_month(s)
    if locked:
        await common.show(cb, f"{t(chat_id, 'menu.track.title')}\n\n"
                              f"{t(chat_id, 'menu.track.lockedNow', month=esc(locked))}",
                          _sub_kb(chat_id, "menu:settings"))
        return
    now = clock.month()
    await state.set_state(Settings.tracking_month)
    lines = [
        t(chat_id, "menu.track.title"),
        "",
        t(chat_id, "menu.track.warning"),
        "",
        t(chat_id, "menu.track.prompt", example=now),
    ]
    await common.show(cb, "\n".join(lines), ikb([
        [(t(chat_id, "menu.track.thisMonthBtn", month=now), f"settings:track:{now}")],
        ui.nav(chat_id, back="menu:settings", cancel="menu:home"),
    ]))


@router.callback_query(F.data.startswith("settings:track:"))
async def track_pick(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    if not await common.gate(cb):
        return
    await _save_tracking(cb, state, cb.data.rpartition(":")[2])


@router.message(StateFilter(Settings.tracking_month))
async def track_typed(message: Message, state: FSMContext) -> None:
    chat_id = message.chat.id
    month = (message.text or "").strip()
    if not _MONTH.fullmatch(month):
        await message.answer(t(chat_id, "menu.track.badMonth", example=clock.month()))
        return
    if not await common.gate(message):
        await state.clear()
        return
    await _save_tracking(message, state, month)


async def _save_tracking(event, state: FSMContext, month: str) -> None:
    chat_id = common.chat_id_of(event)
    if not _MONTH.fullmatch(month):
        await common.show(event, t(chat_id, "menu.track.badMonth", example=clock.month()),
                          _sub_kb(chat_id, "menu:settings"))
        return
    notice = await _saving(event)
    try:
        # The column is a date; the server normalises whatever day it gets to the 1st.
        await api.request(chat_id, "PUT", "/settings",
                          json={"allocationTrackingStartMonth": f"{month}-01"})
    except api.NeedsLogin:
        await state.clear()
        await _finish(event, notice, t(chat_id, "common.sessionExpired"),
                      keyboards.login_kb(chat_id))
        return
    except api.Unreachable:
        await _finish(event, notice, t(chat_id, "common.serverUnreachable"),
                      _sub_kb(chat_id, "menu:settings"))
        return
    except api.ApiError as exc:
        # The write-once refusal lands here as a 400 carrying the server's own sentence.
        await state.clear()
        await _finish(event, notice, f"❌ {esc(exc.message)}",
                      _sub_kb(chat_id, "menu:settings"))
        return
    except Exception:  # noqa: BLE001
        log.exception("PUT /settings (tracking month) failed for chat %s", chat_id)
        await _finish(event, notice, t(chat_id, "menu.track.saveError"),
                      _sub_kb(chat_id, "menu:settings"))
        return
    await state.clear()
    await _finish(
        event, notice, t(chat_id, "menu.track.saved", month=esc(month)),
        ikb([[(t(chat_id, "menu.page.settings"), "menu:settings"),
              (t(chat_id, "common.menu"), "menu:home")]]))


# ── Danger Zone: factory reset ───────────────────────────────────────────────
@router.callback_query(F.data == "reset:start")
async def reset_start(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    if not await common.gate(cb):
        return
    chat_id = common.chat_id_of(cb)
    await state.set_state(Reset.password)
    lines = [
        t(chat_id, "menu.reset.title"),
        "",
        t(chat_id, "menu.reset.body"),
        "",
        # The half no other client has to warn about: this bot boots from a row in the table
        # the reset truncates, and it cannot put the row back.
        t(chat_id, "menu.reset.botWarning"),
        "",
        t(chat_id, "menu.reset.prompt"),
    ]
    await common.show(cb, "\n".join(lines),
                      ikb([ui.nav(chat_id, cancel="menu:settings")]))


@router.message(StateFilter(Reset.password))
async def reset_password(message: Message, state: FSMContext) -> None:
    chat_id = message.chat.id
    password = message.text or ""
    try:
        await message.delete()  # don't leave the password in chat history
    except Exception:  # noqa: BLE001
        log.debug("could not delete the reset password message", exc_info=True)
    if not await common.gate(message):
        await state.clear()
        return
    notice = await _saving(message)
    try:
        await api.reset(chat_id, password)
    except api.NeedsLogin:
        # `api.reset` sends `auth_retry=False`, so this is now only a genuinely dead token —
        # a wrong password arrives below as an ApiError and no longer logs the owner out.
        await state.clear()
        await _finish(message, notice, t(chat_id, "common.sessionExpired"),
                      keyboards.login_kb(chat_id))
        return
    except api.Unreachable:
        await state.clear()
        await _finish(message, notice, t(chat_id, "common.serverUnreachable"),
                      keyboards.back_menu_kb(chat_id))
        return
    except api.ApiError as exc:
        if exc.status == 401:
            # ResetService answers a wrong password with 401 "Incorrect password.". Nothing
            # was deleted and the session is intact, so stay in the state and let them retype.
            await _finish(message, notice, t(chat_id, "menu.reset.wrongPassword"),
                          ikb([ui.nav(chat_id, cancel="menu:settings")]))
            return
        await state.clear()
        await _finish(message, notice, f"❌ {esc(exc.message)}",
                      keyboards.back_menu_kb(chat_id))
        return
    except Exception:  # noqa: BLE001
        log.exception("POST /settings/reset failed for chat %s", chat_id)
        await state.clear()
        await _finish(message, notice, t(chat_id, "common.somethingWentWrong"),
                      keyboards.back_menu_kb(chat_id))
        return
    # The account itself is gone: the tokens are dead and the next request would be a 401.
    store.lock(chat_id)
    await state.clear()
    await _finish(message, notice,
                  f"{t(chat_id, 'menu.reset.done')}\n\n{t(chat_id, 'menu.reset.doneNote')}",
                  keyboards.login_kb(chat_id))


# ── Language ─────────────────────────────────────────────────────────────────
# Deliberately ungated: the language is a per-chat preference held in this process, no API
# call is involved, and a locked owner who cannot read the English login prompt is exactly
# the person who needs to switch.
@router.callback_query(F.data == "lang:open")
async def lang_open(cb: CallbackQuery) -> None:
    await common.ack(cb)
    chat_id = common.chat_id_of(cb)
    await common.show(cb, f"{t(chat_id, 'lang.title')}\n\n{t(chat_id, 'lang.pick')}",
                      keyboards.language_kb(chat_id))


@router.callback_query(F.data.startswith("lang:set:"))
async def lang_set(cb: CallbackQuery) -> None:
    chat_id = common.chat_id_of(cb)
    choice = cb.data.rsplit(":", 1)[1]
    if choice not in ("en", "uz"):
        await common.ack(cb)
        return
    if get_lang(chat_id) == choice:
        # Re-tapping the active language: the screen it would render is byte-identical to the
        # one already on it, which Telegram rejects as "message is not modified". `show`
        # swallows that, but a tap that changes nothing at all still has to be answered — so
        # the acknowledgement carries the explanation instead of a silent no-op.
        await common.ack(cb, t(chat_id, "menu.lang.unchanged"))
        return
    await common.ack(cb)
    set_lang(chat_id, choice)
    await common.show(cb, f"{t(chat_id, 'lang.title')}\n\n{t(chat_id, 'lang.changed')}",
                      keyboards.language_kb(chat_id))
