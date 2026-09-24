"""Home — the pocket advisor, built from `GET /advisor` (the same answer the web Home renders).

Top to bottom, mirroring the web: the date; how much can be spent a day and until when; the pace
warning or the "short" warning; what is coming up; this month's savings; what the owner has.
Pay buttons sit only where the web puts a Pay button — this month's rows that are still to pay —
and at most `_MAX_PAY` of them; everything else is for the web app. The bottom rows are the
three things the bot is for: record (➕ Add, or just type "50000 lunch"), pay, check wallets.

`compose()` is shared with the optional evening message (`bot/reminders.py`).

☰ More (`more`) is the door to every other screen: History, Wallets, Savings, Loans & bills,
Profile, Settings and the web app. Home itself only gains the one button.

Callbacks owned here: `home`, `more`.
"""
from __future__ import annotations

import logging
from typing import Any

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from .. import api, clock, common, keyboards, ui
from ..i18n import t
from ..keyboards import esc
from ..money import fmt_money, fmt_num

router = Router(name="home")
log = logging.getLogger(__name__)

# More Pay buttons than this and Home is a menu again; the rest are one tap away in the web app.
_MAX_PAY = 6
# Coming-up rows printed before "+N more in the app".
_MAX_UPCOMING = 6
# A button label is plain text and a phone shows ~25 characters of it.
_LABEL_LIMIT = 24

UPCOMING_KINDS = ("BILL", "BANK", "LOAN", "DEBT")
BUCKETS = ("DONATION", "EMERGENCY", "INVESTMENTS")
BUCKET_KEY = {"DONATION": "home.bucket.donation", "EMERGENCY": "home.bucket.emergency",
              "INVESTMENTS": "home.bucket.investments"}


def n(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def clip(label: str, limit: int = _LABEL_LIMIT) -> str:
    return label if len(label) <= limit else label[:limit - 1] + "…"


async def fetch(chat_id: int) -> dict[str, Any]:
    """`GET /advisor` for the owner's today. Raises what `api.request` raises."""
    data = await api.request(chat_id, "GET", "/advisor", params={"date": clock.today_iso()})
    return data if isinstance(data, dict) else {}


# ── Which rows can be paid from here (the web's rules) ──────────────────────
def payable_upcoming(u: dict, month: str) -> bool:
    """Still to pay, this month, with the id the pay endpoint needs (a bank loan can do without)."""
    if not isinstance(u, dict) or u.get("recorded") or n(u.get("amount")) <= 0:
        return False
    if str(u.get("date") or "")[:7] != month or u.get("kind") not in UPCOMING_KINDS:
        return False
    return u.get("kind") == "BANK" or u.get("refId") is not None


def savings_rows(data: dict) -> list[dict]:
    """The three buckets, then each goal with an id — what the web's list shows."""
    rows = data.get("savingsThisMonth")
    if rows is None:
        rows = data.get("setAside") or []  # an older backend: the unmet rows stand in
    rows = [r for r in rows if isinstance(r, dict)]
    return ([r for r in rows if r.get("bucket") in BUCKETS]
            + [r for r in rows if r.get("bucket") == "GOAL" and r.get("refId") is not None])


def savings_name(chat_id: int | None, row: dict) -> str:
    key = BUCKET_KEY.get(row.get("bucket"))
    if key:
        return t(chat_id, key)
    return str(row.get("name") or "").strip() or t(chat_id, "home.bucket.goal")


def checked_text(chat_id: int | None, data: dict) -> str:
    """"checked 3 days ago" — when the wallets were last checked."""
    ago = data.get("balanceCheckedDaysAgo")
    if ago is None:
        return t(chat_id, "home.have.notChecked")
    return t(chat_id, "home.have.checkedToday") if int(ago) == 0 else t(chat_id, "home.have.checkedAgo", days=int(ago))


def pay_callback(kind: str, ref: Any = None) -> str:
    return f"pay:{kind}:{ref}" if ref is not None else f"pay:{kind}"


# ── The screen ──────────────────────────────────────────────────────────────
def compose(chat_id: int | None, data: dict, header: str | None = None,
            notice: str | None = None) -> tuple[str, InlineKeyboardMarkup]:
    lines: list[str] = []
    if header:
        lines += [header, ""]
    if notice:
        lines += [notice, ""]
    today = str(data.get("date") or clock.today_iso())
    month = today[:7]
    lines.append("📅 " + ui.day(chat_id, today, weekday=True))

    pays: list[tuple[str, str]] = []
    daily = data.get("daily") if isinstance(data.get("daily"), dict) else None
    if daily is not None:
        short = daily.get("shortBy") if isinstance(daily.get("shortBy"), dict) else None
        if short:
            lines.append(t(chat_id, "home.short", amount=fmt_money(n(short.get("amount"))),
                           date=ui.day(chat_id, short.get("date"))))
        else:
            safe = n(daily.get("safePerDay"))
            lines.append(t(chat_id, "home.perDay", amount=fmt_money(safe),
                           date=ui.day(chat_id, daily.get("until"))))
            pace = daily.get("paceDaily")
            if daily.get("runsOutOn") and pace is not None:
                lines.append(t(chat_id, "home.paceRunsOut", pace=fmt_money(n(pace)),
                               date=ui.day(chat_id, daily.get("runsOutOn"))))
            elif pace is not None and n(pace) <= safe:
                lines.append(t(chat_id, "home.paceOk", pace=fmt_money(n(pace))))

        upcoming = [u for u in daily.get("upcoming") or [] if isinstance(u, dict)]
        lines += ["", t(chat_id, "home.upcoming.title")]
        if not upcoming:
            lines.append(t(chat_id, "home.upcoming.empty"))
        for u in upcoming[:_MAX_UPCOMING]:
            tags = ""
            if u.get("overdue"):
                tags += " · " + t(chat_id, "home.upcoming.overdue")
            if u.get("asap"):
                tags += " · " + t(chat_id, "home.upcoming.repayFast")
            if u.get("recorded"):
                tags += " · " + t(chat_id, "home.upcoming.recorded")
            lines.append(t(chat_id, "home.upcoming.row", date=ui.day(chat_id, u.get("date"), relative=True),
                           name=esc(u.get("name") or "—"), amount=fmt_num(n(u.get("amount")))) + tags)
        if len(upcoming) > _MAX_UPCOMING:
            lines.append(t(chat_id, "home.upcoming.more", count=len(upcoming) - _MAX_UPCOMING))
        for u in upcoming:
            if payable_upcoming(u, month):
                pays.append((clip("💳 " + str(u.get("name") or "—")),
                             pay_callback(u["kind"], u.get("refId") if u.get("refId") is not None else 0)))
    elif data.get("missingStableIncome"):
        lines.append(t(chat_id, "home.noIncome"))

    rows = savings_rows(data)
    if rows:
        lines += ["", t(chat_id, "home.savings.title")]
        for r in rows:
            name = esc(savings_name(chat_id, r))
            if n(r.get("remaining")) <= 0:
                lines.append(t(chat_id, "home.savings.done", name=name, amount=fmt_money(n(r.get("paid")))))
                continue
            lines.append(t(chat_id, "home.savings.row", name=name, paid=fmt_num(n(r.get("paid"))),
                           target=fmt_money(n(r.get("target")))))
            cb = pay_callback("GOAL", r["refId"]) if r.get("bucket") == "GOAL" else pay_callback(r["bucket"])
            pays.append((clip("💳 " + savings_name(chat_id, r)), cb))

    checked = checked_text(chat_id, data)
    due = any(isinstance(s, dict) and s.get("action") in ("CHECK_IN", "CLOSE_MONTH")
              for s in data.get("suggestions") or [])
    lines += ["", t(chat_id, "home.have", amount=fmt_money(n(data.get("have"))))
              + f" · {'⚠️ ' if due else ''}{checked}"]
    lines += ["", t(chat_id, "home.typeHint")]

    seen: set[str] = set()
    buttons = [b for b in pays if not (b[1] in seen or seen.add(b[1]))][:_MAX_PAY]
    kb: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text=text, callback_data=cb) for text, cb in row]
        for row in ui.grid(buttons, 2)]
    if data.get("missingStableIncome"):
        kb.append([InlineKeyboardButton(text=t(chat_id, "settings.incomeBtn"), callback_data="set:income")])
    kb += keyboards.home_rows(chat_id)
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=kb)


async def report(event, exc: BaseException) -> None:
    """Show why Home (or a pay step) could not load, with a way back."""
    chat_id = common.chat_id_of(event)
    retry = keyboards.ikb([[(t(chat_id, "common.retry"), "home")]])
    if isinstance(exc, api.NeedsLogin):
        await common.show(event, t(chat_id, "common.sessionExpired"), keyboards.login_kb(chat_id))
    elif isinstance(exc, api.Unreachable):
        await common.show(event, t(chat_id, "common.serverUnreachable"), retry)
    elif isinstance(exc, api.ApiError):
        await common.show(event, f"❌ {esc(exc.message)}", retry)
    else:
        log.warning("Home failed to load", exc_info=exc)
        await common.show(event, t(chat_id, "home.loadError"), retry)


async def show_home(event, notice: str | None = None) -> None:
    """Render Home, with an optional one-line outcome ("✅ Saved …") above it."""
    chat_id = common.chat_id_of(event)
    try:
        data = await fetch(chat_id)
    except Exception as exc:  # noqa: BLE001 — dispatched by type in report()
        if notice:
            await common.show(event, notice, keyboards.back_home_kb(chat_id))
            return
        await report(event, exc)
        return
    text, kb = compose(chat_id, data, notice=notice)
    await common.show(event, text, kb)


@router.callback_query(F.data == "home")
async def on_home(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    await state.clear()
    if not await common.gate(cb):
        return
    await show_home(cb)


@router.callback_query(F.data == "more")
async def on_more(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    await state.clear()
    if not await common.gate(cb):
        return
    chat_id = common.chat_id_of(cb)
    await common.show(cb, t(chat_id, "home.more.title"), keyboards.more_kb(chat_id))
