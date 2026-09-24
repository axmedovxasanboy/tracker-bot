"""🧾 History — the web's History page in the bot.

One month at a time (‹ Aug 2026 · Oct 2026 ›, never past this month), built the web's way: every
transaction dated in the month comes down (`GET /transactions`, all pages of 100) and every figure
is added up from exactly those rows.

* **In · Out · Saved** with the web's `flowOf` rules: borrowed money, money taken out of savings
  and money lent are their own lines; moves between wallets and loans paid back to the owner are
  skipped; a wallet check's surplus comes back off Out.
* **Where it went** — Out by top-level category, the six largest, the rest as "Other".
* **The list** — 10 a page, newest first, grouped by day. A number button opens one transaction:
  Edit (amount, category, wallet, date, description — plain income and expenses only, as the web
  keeps a special entry's kind) and Delete (asks first).
* **🔎 Search** — asks for a word and filters the month, as the web's search box does.

The list block and the transaction screens are shared with 👛 Wallets (a wallet's recent
transactions), so a detail opened from there comes back there. Where a screen came from rides in
the callback as an "origin": `2026-09.0` (History, page 0), `2026-09.0.s` (with the search on),
`c7.0` (card 7, page 0), `k.0` (cash, page 0).

Callbacks owned here: `hist`, `hist:*`.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
import math
import re
from typing import Any, Callable

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from .. import api, clock, common, keyboards, ui
from ..config import CURRENCY
from ..i18n import cat_name, t
from ..keyboards import esc, ikb
from ..money import fmt_money, fmt_num, parse_amount
from . import home

router = Router(name="history")
log = logging.getLogger(__name__)

PAGE = 10             # rows per page, the owner's ask
_FETCH_SIZE = 100     # the server's own cap on a page (app.pagination.max-page-size)
_MAX_PAGES = 20       # 2 000 rows in a month: a guard, not a limit anyone meets
TOP_CATEGORIES = 6    # "Where it went" names this many before the rest become "Other"
DESC_LIMIT = 255      # Transaction.description is varchar(255)
_TITLE_LIMIT = 34     # a list row stays one line on a phone
_QUERY_LIMIT = 60
_DATE_CHOICES = 7

_YM = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
REGULAR = ("REGULAR_INCOME", "REGULAR_EXPENSE")
SAVING_SUB_TYPES = frozenset({"DONATION", "EMERGENCY_CONTRIBUTION", "INVESTMENT", "STOCK_PURCHASE"})
_KIND = {
    "LOAN_RECEIVED": "history.kind.loanReceived",
    "LOAN_RETURNED_TO_ME": "history.kind.loanReturned",
    "LOAN_GIVEN": "history.kind.loanGiven",
    "LOAN_REPAYMENT": "history.kind.loanRepayment",
    "BANK_LOAN_PAYMENT": "history.kind.bankLoanPayment",
    "INVESTMENT": "history.kind.investment",
    "STOCK_PURCHASE": "history.kind.investment",
    "DONATION": "history.kind.donation",
    "EMERGENCY_CONTRIBUTION": "history.kind.emergency",
    "INVESTMENT_WITHDRAWAL": "history.kind.investmentWithdrawal",
    "EVERYDAY_SPENDING": "history.kind.everyday",
    "TRANSFER_IN": "history.kind.transfer",
    "TRANSFER_OUT": "history.kind.transfer",
}
# Listed literally so tools/check.py can see every key is used.
_MONTHS_FULL = ("common.monthFull.1", "common.monthFull.2", "common.monthFull.3", "common.monthFull.4",
                "common.monthFull.5", "common.monthFull.6", "common.monthFull.7", "common.monthFull.8",
                "common.monthFull.9", "common.monthFull.10", "common.monthFull.11", "common.monthFull.12")


class HistSearch(StatesGroup):
    """🔎 Search: the one typed word."""
    query = State()


class HistEdit(StatesGroup):
    """Editing one transaction: the edit card, and the three steps that read typed text."""
    card = State()
    amount = State()
    date = State()
    desc = State()


n = home.n


# ── Months ──────────────────────────────────────────────────────────────────
def valid_month(value: str) -> bool:
    return bool(_YM.match(value or ""))


def month_name(chat_id: int | None, month: str) -> str:
    """`2026-09` → "September"."""
    return t(chat_id, _MONTHS_FULL[int(month[5:7]) - 1])


def month_label(chat_id: int | None, month: str) -> str:
    """`2026-09` → "September 2026" (the web's formatMonth)."""
    return t(chat_id, "common.monthYear", month=month_name(chat_id, month), year=month[:4])


def shift_month(month: str, delta: int) -> str:
    y, m = int(month[:4]), int(month[5:7]) - 1 + delta
    return f"{y + m // 12:04d}-{m % 12 + 1:02d}"


def month_bounds(month: str) -> tuple[str, str]:
    y, m = int(month[:4]), int(month[5:7])
    nxt = dt.date(y + (m == 12), m % 12 + 1, 1)
    return f"{month}-01", (nxt - dt.timedelta(days=1)).isoformat()


# ── Loading ─────────────────────────────────────────────────────────────────
async def fetch_month(chat_id: int, month: str) -> list[dict]:
    """Every transaction dated in `month`, all pages of it, newest first."""
    start, end = month_bounds(month)

    def page(i: int):
        return api.request(chat_id, "GET", "/transactions", params={
            "page": i, "size": _FETCH_SIZE, "sortBy": "transactionDate", "sortDir": "desc",
            "startDate": start, "endDate": end})

    first = await page(0) or {}
    pages = min(int(first.get("totalPages") or 1), _MAX_PAGES)
    rest = await asyncio.gather(*(page(i) for i in range(1, pages))) if pages > 1 else []
    seen: set = set()
    rows: list[dict] = []
    for res in (first, *rest):
        for tx in (res or {}).get("content") or []:
            # A row added between two page requests shifts the pages; never count one twice.
            if isinstance(tx, dict) and tx.get("id") not in seen:
                seen.add(tx.get("id"))
                rows.append(tx)
    return rows


async def _categories(chat_id: int, **params) -> list[dict]:
    """The category tree; an empty list when it cannot be read (the figures do not need it)."""
    try:
        cats = await api.request(chat_id, "GET", "/categories", params=params or None) or []
    except api.NeedsLogin:
        raise
    except Exception:  # noqa: BLE001
        log.warning("category list failed for chat %s", chat_id, exc_info=True)
        cats = []
    return [c for c in cats if isinstance(c, dict)]


# ── What each row counts as (the web's flowOf) ──────────────────────────────
def flow_of(tx: dict) -> str:
    sub = tx.get("subType")
    if tx.get("transferPairId") is not None or sub in ("TRANSFER_IN", "TRANSFER_OUT"):
        return "skip"
    if tx.get("type") == "INCOME":
        if sub == "LOAN_RECEIVED":
            return "borrowed"
        if sub == "INVESTMENT_WITHDRAWAL":
            return "fromSavings"
        if sub == "EVERYDAY_SPENDING":
            return "surplus"
        if sub == "LOAN_RETURNED_TO_ME":
            return "skip"
        return "in"
    if sub == "LOAN_GIVEN":
        return "lent"
    if sub in SAVING_SUB_TYPES:
        return "saved"
    return "out"


def totals(rows: list[dict]) -> dict[str, float]:
    out = dict.fromkeys(("in", "out", "saved", "borrowed", "lent", "fromSavings"), 0.0)
    for tx in rows:
        if tx.get("currency", CURRENCY) != CURRENCY:
            continue  # a dormant foreign cash pot never enters a total
        flow, amount = flow_of(tx), n(tx.get("amount"))
        if flow == "surplus":
            out["out"] -= amount
        elif flow in out:
            out[flow] += amount
    return {k: round(v, 2) for k, v in out.items()}


def spending(rows: list[dict], roots: list[dict]) -> tuple[list[tuple[dict, float]], float]:
    """Out by top-level category — (the top six, everything else) — netted as Out is."""
    root_of: dict[Any, dict] = {}
    everyday_root = None
    for root in roots:
        root_of[root.get("id")] = root
        for child in root.get("children") or []:
            root_of[child.get("id")] = root
        if root.get("applicableSubType") == "EVERYDAY_SPENDING":
            everyday_root = root.get("id")
    by_root: dict[Any, list] = {}
    uncategorised = surplus = everyday_uncategorised = 0.0
    for tx in rows:
        if tx.get("currency", CURRENCY) != CURRENCY:
            continue
        flow, amount = flow_of(tx), n(tx.get("amount"))
        if flow == "surplus":
            surplus += amount
            continue
        if flow != "out":
            continue
        c = tx.get("category")
        if not isinstance(c, dict):
            uncategorised += amount
            if tx.get("subType") == "EVERYDAY_SPENDING":
                everyday_uncategorised += amount
            continue
        root = root_of.get(c.get("id")) or root_of.get(c.get("parentId")) or c
        if tx.get("subType") == "EVERYDAY_SPENDING":
            everyday_root = root.get("id")
        entry = by_root.setdefault(root.get("id"), [root, 0.0])
        entry[1] += amount
    left = surplus
    everyday = by_root.get(everyday_root) if everyday_root is not None else None
    if everyday is not None and left > 0:
        take = min(left, everyday[1])
        everyday[1] -= take
        left -= take
        if round(everyday[1], 2) <= 0:
            by_root.pop(everyday_root, None)
    uncategorised -= min(left, everyday_uncategorised)
    ranked = sorted(by_root.values(), key=lambda e: -e[1])
    top = [(e[0], round(e[1], 2)) for e in ranked[:TOP_CATEGORIES]]
    other = round(sum(e[1] for e in ranked[TOP_CATEGORIES:]) + uncategorised, 2)
    return top, other


def matches(tx: dict, query: str) -> bool:
    """The web's search: description, note, category (both names) and card."""
    cat, card = tx.get("category") or {}, tx.get("card") or {}
    hay = " ".join(str(x) for x in (tx.get("description"), tx.get("note"), cat.get("name"),
                                    cat.get("nameUz"), card.get("name")) if x)
    return query.casefold() in hay.casefold()


# ── Rows, shared with 👛 Wallets ────────────────────────────────────────────
def _is_income(tx: dict) -> bool:
    return tx.get("type") == "INCOME"


def signed(tx: dict, amount: float | None = None, unit: bool = False) -> str:
    value = n(tx.get("amount")) if amount is None else amount
    return ("+" if _is_income(tx) else "−") + (fmt_money(value) if unit else fmt_num(value))


def _title(chat_id: int | None, tx: dict) -> str:
    desc = str(tx.get("description") or "").strip()
    if not desc and isinstance(tx.get("category"), dict):
        desc = cat_name(chat_id, tx["category"])
    return home.clip(desc or "—", _TITLE_LIMIT)


def day_header(chat_id: int | None, iso: str) -> str:
    try:
        d = dt.date.fromisoformat(str(iso)[:10])
    except ValueError:
        return f"<i>{esc(iso)}</i>"
    today = clock.today()
    if d == today:
        text = t(chat_id, "history.dayToday", date=ui.day(chat_id, d))
    elif d == today - dt.timedelta(days=1):
        text = t(chat_id, "history.dayYesterday", date=ui.day(chat_id, d))
    else:
        text = ui.day(chat_id, d, weekday=True)
    return f"<i>{text}</i>"


def list_block(chat_id: int | None, rows: list[dict], start: int, origin: str,
               portion: Callable[[dict], float] | None = None) -> tuple[list[str], list[list[tuple[str, str]]]]:
    """Numbered rows grouped by day, and the number buttons that open each one."""
    lines: list[str] = []
    buttons: list[tuple[str, str]] = []
    day = None
    for i, tx in enumerate(rows, start=start + 1):
        date = str(tx.get("transactionDate") or "")[:10]
        if date != day:
            day = date
            lines.append(day_header(chat_id, date))
        line = t(chat_id, "history.row", n=i, amount=signed(tx, portion(tx) if portion else None),
                 title=esc(_title(chat_id, tx)))
        cat = tx.get("category")
        if isinstance(cat, dict) and str(tx.get("description") or "").strip():
            line += f" · <i>{esc(home.clip(cat_name(chat_id, cat), 20))}</i>"
        lines.append(line)
        buttons.append((str(i), f"hist:t:{tx.get('id')}:{origin}"))
    return lines, ui.grid(buttons, 5)


def back_callback(origin: str) -> str:
    """Where a transaction screen's Back goes."""
    parts = (origin or "").split(".")
    page = parts[1] if len(parts) > 1 and parts[1].isdigit() else "0"
    head = parts[0]
    if head[:1] == "c" and head[1:].isdigit():
        return f"wal:c:{head[1:]}:{page}"
    if head == "k":
        return f"wal:k:{page}"
    if valid_month(head):
        return f"hist:m:{head}:{page}" + (":s" if "s" in parts[2:] else "")
    return "hist"


# ── The month screen ────────────────────────────────────────────────────────
async def show_month(event, state: FSMContext, month: str, page: int = 0, search: bool = False,
                     notice: str | None = None) -> None:
    chat_id = common.chat_id_of(event)
    this_month = clock.month()
    if not valid_month(month) or month > this_month:
        month = this_month
    d = await state.get_data()
    query = str(d.get("hist_q") or "").strip() if search else ""
    if not query and d.get("hist_q"):
        await state.update_data(hist_q=None)
    try:
        rows, roots = await asyncio.gather(fetch_month(chat_id, month), _categories(chat_id))
    except Exception as exc:  # noqa: BLE001
        await home.report(event, exc)
        return

    label = month_label(chat_id, month)
    lines = [notice, ""] if notice else []
    lines.append(t(chat_id, "history.title", month=label))
    kb: list[list[tuple[str, str]]] = []
    if not rows:
        lines += ["", t(chat_id, "history.empty", month=label)]
    else:
        tot = totals(rows)
        lines += ["", t(chat_id, "history.in", amount=fmt_money(tot["in"])),
                  t(chat_id, "history.out", amount=fmt_money(max(0.0, tot["out"]))),
                  t(chat_id, "history.saved", amount=fmt_money(tot["saved"]))]
        for key, flow in (("history.borrowed", "borrowed"), ("history.lent", "lent"),
                          ("history.fromSavings", "fromSavings")):
            if tot[flow] > 0:
                lines.append(t(chat_id, key, amount=fmt_money(tot[flow])))
        top, other = spending(rows, roots)
        lines += ["", t(chat_id, "history.whereItWent")]
        if not top and other <= 0:
            lines.append(t(chat_id, "history.nothingSpent", month=label))
        for cat, amount in top:
            lines.append(t(chat_id, "history.spendRow", name=esc(cat_name(chat_id, cat)), amount=fmt_num(amount)))
        if other > 0:
            lines.append(t(chat_id, "history.spendRow", name=t(chat_id, "history.other"), amount=fmt_num(other)))

        visible = [tx for tx in rows if matches(tx, query)] if query else rows
        pages = max(1, math.ceil(len(visible) / PAGE))
        page = min(max(page, 0), pages - 1)
        chunk = visible[page * PAGE:(page + 1) * PAGE]
        lines.append("")
        if query:
            lines.append(t(chat_id, "history.searchTitle", query=esc(query), count=len(visible)))
        elif chunk:
            lines.append(t(chat_id, "history.listTitle", first=page * PAGE + 1,
                           last=page * PAGE + len(chunk), total=len(visible)))
        if not chunk:
            lines.append(t(chat_id, "history.noneFound"))
        origin = f"{month}.{page}" + (".s" if query else "")
        block, buttons = list_block(chat_id, chunk, page * PAGE, origin)
        lines += block
        kb += buttons
        flag = ":s" if query else ""
        pager = []
        if page > 0:
            pager.append((t(chat_id, "common.prev"), f"hist:m:{month}:{page - 1}{flag}"))
        if page < pages - 1:
            pager.append((t(chat_id, "common.next"), f"hist:m:{month}:{page + 1}{flag}"))
        kb.append(pager)

    months = [("‹ " + month_label(chat_id, shift_month(month, -1)), f"hist:m:{shift_month(month, -1)}:0")]
    if month < this_month:  # nothing is recorded ahead of today's month
        months.append((month_label(chat_id, shift_month(month, 1)) + " ›", f"hist:m:{shift_month(month, 1)}:0"))
    kb.append(months)
    if query:
        kb.append([(t(chat_id, "history.clearSearchBtn"), f"hist:m:{month}:0")])
    elif rows:
        kb.append([(t(chat_id, "history.searchBtn"), f"hist:s:{month}")])
    kb.append(ui.nav(chat_id, back="more", home=True))
    await common.show(event, "\n".join(lines), ikb(kb))


@router.callback_query(F.data == "hist")
async def on_history(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    await state.clear()
    if not await common.gate(cb):
        return
    await show_month(cb, state, clock.month())


@router.callback_query(F.data.startswith("hist:m:"))
async def on_month(cb: CallbackQuery, state: FSMContext) -> None:
    """`hist:m:{YYYY-MM}:{page}[:s]` — a month, a page, and whether the search stays on."""
    await common.ack(cb)
    if not await common.gate(cb):
        return
    await state.set_state(None)
    parts = cb.data.split(":")
    month = parts[2] if len(parts) > 2 else clock.month()
    page = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0
    await show_month(cb, state, month, page, search=len(parts) > 4 and parts[4] == "s")


# ── 🔎 Search ──────────────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("hist:s:"))
async def on_search(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    if not await common.gate(cb):
        return
    chat_id = common.chat_id_of(cb)
    month = cb.data.split(":")[2]
    if not valid_month(month):
        month = clock.month()
    await state.set_state(HistSearch.query)
    await state.update_data(hist_month=month)
    await common.show(cb, t(chat_id, "history.searchAsk", month=month_label(chat_id, month)),
                      ikb([ui.nav(chat_id, back=f"hist:m:{month}:0", home=True)]))


@router.message(StateFilter(HistSearch.query))
async def on_search_typed(message: Message, state: FSMContext) -> None:
    chat_id = common.chat_id_of(message)
    query = " ".join((message.text or "").split())[:_QUERY_LIMIT]
    if not query:
        await message.answer(t(chat_id, "history.searchEmpty"))
        return
    if not await common.gate(message):
        await state.clear()
        return
    month = (await state.get_data()).get("hist_month") or clock.month()
    await state.set_state(None)
    await state.update_data(hist_q=query)
    await show_month(message, state, month, 0, search=True)


# ── One transaction ─────────────────────────────────────────────────────────
def locked(tx: dict) -> bool:
    """A special entry keeps its kind: only plain income and expenses are edited from here."""
    return tx.get("transferPairId") is not None or tx.get("subType") not in (None, *REGULAR)


def kind_label(chat_id: int | None, tx: dict) -> str | None:
    key = _KIND.get(tx.get("subType"))
    return t(chat_id, key) if key else None


def _card_label(card: dict) -> str:
    last4 = card.get("lastFourDigits")
    return f"{card.get('name') or '—'} •••• {last4}" if last4 else str(card.get("name") or "—")


def _long_date(chat_id: int | None, iso: str) -> str:
    text = ui.day(chat_id, iso, weekday=True)
    return text if str(iso)[:4] == str(clock.today().year) else f"{text} {str(iso)[:4]}"


async def _load_tx(event, tx_id: str) -> dict | None:
    """`GET /transactions/{id}`; None after saying why (gone, logged out, unreachable)."""
    chat_id = common.chat_id_of(event)
    try:
        tx = await api.request(chat_id, "GET", f"/transactions/{tx_id}")
    except api.ApiError as exc:
        if exc.status == 404:
            await common.show(event, t(chat_id, "history.gone"), keyboards.back_home_kb(chat_id))
            return None
        await home.report(event, exc)
        return None
    except Exception as exc:  # noqa: BLE001
        await home.report(event, exc)
        return None
    return tx if isinstance(tx, dict) else None


def detail_text(chat_id: int | None, tx: dict) -> str:
    lines = [t(chat_id, "history.detailTitle"), "",
             t(chat_id, "history.detailAmount", amount=signed(tx, unit=True),
               type=t(chat_id, "history.typeIncome" if _is_income(tx) else "history.typeExpense")),
             esc(tx.get("description") or "—"), "",
             t(chat_id, "history.detailDate", date=_long_date(chat_id, tx.get("transactionDate")))]
    cat = tx.get("category")
    if isinstance(cat, dict):
        lines.append(t(chat_id, "history.detailCategory", name=esc(cat_name(chat_id, cat))))
    kind = kind_label(chat_id, tx)
    if kind:
        lines.append(t(chat_id, "history.detailKind", kind=kind))
    card = tx.get("card") if isinstance(tx.get("card"), dict) else None
    cash = n(tx.get("cashAmount"))
    if card and cash > 0 and n(tx.get("cardAmount")) > 0:
        lines.append(t(chat_id, "history.detailSplit", cash=fmt_money(cash), card=fmt_money(n(tx.get("cardAmount")))))
        lines.append(t(chat_id, "history.detailCard", name=esc(_card_label(card))))
    elif card and card.get("type") != "CASH":
        lines.append(t(chat_id, "history.detailCard", name=esc(_card_label(card))))
    else:
        lines.append(t(chat_id, "history.detailCash"))
    if tx.get("note"):
        lines.append(t(chat_id, "history.detailNote", note=esc(tx["note"])))
    return "\n".join(lines)


async def show_detail(event, state: FSMContext, tx_id: str, origin: str, notice: str | None = None) -> None:
    chat_id = common.chat_id_of(event)
    tx = await _load_tx(event, tx_id)
    if tx is None:
        return
    text = detail_text(chat_id, tx)
    if locked(tx):
        text += "\n\n" + t(chat_id, "history.locked", kind=kind_label(chat_id, tx) or "—")
    if notice:
        text = f"{notice}\n\n{text}"

    def b(key: str, data: str) -> InlineKeyboardButton:
        return InlineKeyboardButton(text=t(chat_id, key), callback_data=data)

    rows: list[list[InlineKeyboardButton]] = []
    if locked(tx):
        rows.append([b("common.delete", f"hist:d:{tx_id}:{origin}")])
        app = keyboards.web_app_button(chat_id)
        if app is not None:
            rows.append([app])
    else:
        rows.append([b("common.edit", f"hist:e:{tx_id}:{origin}"), b("common.delete", f"hist:d:{tx_id}:{origin}")])
    rows.append([b("common.back", back_callback(origin)), b("common.home", "home")])
    await common.show(event, text, InlineKeyboardMarkup(inline_keyboard=rows))


def _split_ref(data: str) -> tuple[str, str] | None:
    """`hist:x:{id}:{origin}` → (id, origin)."""
    parts = data.split(":", 3)
    if len(parts) < 3 or not parts[2].isdigit():
        return None
    return parts[2], parts[3] if len(parts) > 3 else ""


@router.callback_query(F.data.startswith("hist:t:"))
async def on_detail(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    if not await common.gate(cb):
        return
    ref = _split_ref(cb.data)
    if ref is None:
        await show_month(cb, state, clock.month())
        return
    await state.set_state(None)
    await state.update_data(he=None)
    await show_detail(cb, state, *ref)


# ── Delete ──────────────────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("hist:d:"))
async def on_delete(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    if not await common.gate(cb):
        return
    ref = _split_ref(cb.data)
    if ref is None:
        await show_month(cb, state, clock.month())
        return
    chat_id = common.chat_id_of(cb)
    tx = await _load_tx(cb, ref[0])
    if tx is None:
        return
    lines = [t(chat_id, "history.deleteAsk"), "",
             f"<b>{signed(tx, unit=True)}</b> · {esc(_title(chat_id, tx))}",
             t(chat_id, "history.detailDate", date=_long_date(chat_id, tx.get("transactionDate")))]
    if tx.get("transferPairId") is not None:
        lines += ["", t(chat_id, "history.deleteTransfer")]
    await common.show(cb, "\n".join(lines), ikb([
        [(t(chat_id, "common.delete"), f"hist:x:{ref[0]}:{ref[1]}")],
        ui.nav(chat_id, cancel=f"hist:t:{ref[0]}:{ref[1]}"),
    ]))


@router.callback_query(F.data.startswith("hist:x:"))
async def on_delete_confirmed(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    if not await common.gate(cb):
        return
    ref = _split_ref(cb.data)
    if ref is None:
        await show_month(cb, state, clock.month())
        return
    chat_id = common.chat_id_of(cb)
    await common.begin_write(cb, chat_id)
    try:
        await api.request(chat_id, "DELETE", f"/transactions/{ref[0]}")
    except api.NeedsLogin:
        await state.clear()
        await common.show(cb, t(chat_id, "common.sessionExpired"), keyboards.login_kb(chat_id))
        return
    except api.ApiError as exc:
        if exc.status != 404:  # already gone is what was asked for
            reason = (t(chat_id, "common.serverUnreachable") if isinstance(exc, api.Unreachable)
                      else f"❌ {esc(exc.message)}")
            await common.show(cb, reason, ikb([ui.nav(chat_id, back=f"hist:t:{ref[0]}:{ref[1]}", home=True)]))
            return
    await return_to(cb, state, ref[1], t(chat_id, "history.deleted"))


async def return_to(event, state: FSMContext, origin: str, notice: str | None = None) -> None:
    """Back to the list a transaction was opened from, with a one-line outcome above it."""
    back = back_callback(origin).split(":")
    if back[0] == "wal":
        from . import wallets  # wallets imports this module; importing it back at call time is safe
        page = int(back[-1]) if back[-1].isdigit() else 0
        if back[1] == "c":
            await wallets.show_card(event, int(back[2]), page, notice)
        else:
            await wallets.show_cash(event, page, notice)
        return
    if back[0] == "hist" and len(back) > 3:
        await show_month(event, state, back[2], int(back[3]) if back[3].isdigit() else 0,
                         search=len(back) > 4, notice=notice)
        return
    await show_month(event, state, clock.month(), notice=notice)


# ── Edit ────────────────────────────────────────────────────────────────────
def _regular(tx_type: str) -> str:
    return "REGULAR_INCOME" if tx_type == "INCOME" else "REGULAR_EXPENSE"


def _cat_label(chat_id: int | None, cat: dict, parent: dict | None) -> str:
    return f"{cat_name(chat_id, parent)} → {cat_name(chat_id, cat)}" if parent else cat_name(chat_id, cat)


def draft_of(chat_id: int | None, tx: dict, origin: str) -> dict:
    """The edit draft — the web's walletOf: a card row with a cash part is a split."""
    amount = n(tx.get("amount"))
    cash = n(tx.get("cashAmount"))
    card = tx.get("card") if isinstance(tx.get("card"), dict) else None
    on_card = bool(card) and card.get("type") != "CASH" and amount - cash > 0
    cat = tx.get("category") if isinstance(tx.get("category"), dict) else None
    return {
        "id": tx.get("id"), "origin": origin, "type": tx.get("type") or "EXPENSE",
        "subType": tx.get("subType") or _regular(tx.get("type") or "EXPENSE"), "amount": amount,
        "card": card.get("id") if on_card else None, "wallet": card.get("name") if on_card else None,
        "split": on_card and cash > 0, "cash": cash if on_card else 0.0,
        "cat": cat.get("id") if cat else None, "catName": cat_name(chat_id, cat) if cat else None,
        "origCat": cat.get("id") if cat else None,
        "date": str(tx.get("transactionDate") or clock.today_iso())[:10],
        "desc": str(tx.get("description") or ""), "note": tx.get("note") or "",
        "investmentId": tx.get("investmentId"),
    }


async def edit_screen(event, state: FSMContext, error: str = "") -> None:
    chat_id = common.chat_id_of(event)
    he = (await state.get_data()).get("he") or {}
    type_word = t(chat_id, "history.typeIncome" if he.get("type") == "INCOME" else "history.typeExpense")
    lines = [t(chat_id, "history.editTitle", type=type_word), "",
             t(chat_id, "history.editAmount", amount=fmt_money(he.get("amount")))]
    if he.get("split"):
        lines.append(t(chat_id, "history.editSplit", cash=fmt_money(he.get("cash"))))
    lines.append("🏷 " + esc(he["catName"]) if he.get("cat") is not None else t(chat_id, "history.editNoCategory"))
    lines.append("💳 " + esc(he.get("wallet") or "—") if he.get("card") is not None
                 else "💵 " + t(chat_id, "common.cash"))
    lines.append("📅 " + _long_date(chat_id, he.get("date")))
    lines.append("📝 " + esc(he["desc"]) if he.get("desc") else t(chat_id, "history.editDescNone"))
    if error:
        lines += ["", error, t(chat_id, "history.notSaved")]
    await state.set_state(HistEdit.card)
    await common.show(event, "\n".join(lines), ikb([
        [(t(chat_id, "history.btnAmount"), "hist:ea"), (t(chat_id, "history.btnCategory"), "hist:ec")],
        [(t(chat_id, "history.btnWallet"), "hist:ew"), (t(chat_id, "history.btnDate"), "hist:ed")],
        [(t(chat_id, "history.btnDesc"), "hist:en")],
        [(t(chat_id, "history.btnSave"), "hist:es")],
        ui.nav(chat_id, back=f"hist:t:{he.get('id')}:{he.get('origin', '')}", home=True),
    ]))


async def _draft(cb: CallbackQuery, state: FSMContext) -> dict | None:
    """Gate the tap and hand back the edit draft. None: already answered (e.g. after a restart)."""
    chat_id = common.chat_id_of(cb)
    if not await common.gate(cb):
        return None
    he = (await state.get_data()).get("he")
    if not isinstance(he, dict) or he.get("id") is None:
        await common.ack(cb, t(chat_id, "common.oldButton"), alert=True)
        await state.set_state(None)
        await show_month(cb, state, clock.month())
        return None
    await common.ack(cb)
    return he


@router.callback_query(F.data.startswith("hist:e:"))
async def on_edit(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    if not await common.gate(cb):
        return
    ref = _split_ref(cb.data)
    if ref is None:
        await show_month(cb, state, clock.month())
        return
    chat_id = common.chat_id_of(cb)
    tx = await _load_tx(cb, ref[0])
    if tx is None:
        return
    if locked(tx):
        await show_detail(cb, state, *ref)
        return
    await state.update_data(he=draft_of(chat_id, tx, ref[1]), he_roots=None, he_cards=None)
    await edit_screen(cb, state)


@router.callback_query(F.data == "hist:eb")
async def on_edit_back(cb: CallbackQuery, state: FSMContext) -> None:
    if await _draft(cb, state) is None:
        return
    await edit_screen(cb, state)


@router.message(StateFilter(HistEdit.card))
async def on_edit_typed(message: Message) -> None:
    await message.answer(t(common.chat_id_of(message), "common.tapButton"))


# Amount
@router.callback_query(F.data == "hist:ea")
async def on_edit_amount(cb: CallbackQuery, state: FSMContext) -> None:
    if await _draft(cb, state) is None:
        return
    chat_id = common.chat_id_of(cb)
    await state.set_state(HistEdit.amount)
    await common.show(cb, t(chat_id, "history.amountAsk"), ikb([ui.nav(chat_id, back="hist:eb")]))


@router.message(StateFilter(HistEdit.amount))
async def on_edit_amount_typed(message: Message, state: FSMContext) -> None:
    chat_id = common.chat_id_of(message)
    he = (await state.get_data()).get("he")
    if not isinstance(he, dict):
        await state.set_state(None)
        await show_month(message, state, clock.month())
        return
    amount = parse_amount(message.text)
    if amount is None:
        await message.answer(t(chat_id, "history.amountAsk"))
        return
    await state.update_data(he=dict(he, amount=amount))
    await edit_screen(message, state)


# Category
async def _roots(chat_id: int, state: FSMContext, he: dict) -> list[dict]:
    d = await state.get_data()
    roots = d.get("he_roots")
    if roots is None:
        sub = he.get("subType") if he.get("subType") in REGULAR else _regular(he.get("type"))
        roots = await _categories(chat_id, type=he.get("type"), subType=sub)
        await state.update_data(he_roots=roots)
    return roots


@router.callback_query(F.data == "hist:ec")
async def on_edit_categories(cb: CallbackQuery, state: FSMContext) -> None:
    he = await _draft(cb, state)
    if he is None:
        return
    chat_id = common.chat_id_of(cb)
    roots = await _roots(chat_id, state, he)
    items = [(home.clip(cat_name(chat_id, r)), f"hist:eco:{r['id']}" if r.get("children") else f"hist:ecp:{r['id']}")
             for r in roots if r.get("id") is not None]
    text = t(chat_id, "history.categoryAsk") if roots else t(chat_id, "history.noCategories")
    await common.show(cb, text, ikb([*ui.grid(items, 2), ui.nav(chat_id, back="hist:eb")]))


@router.callback_query(F.data.startswith("hist:eco:"))
async def on_edit_category_open(cb: CallbackQuery, state: FSMContext) -> None:
    """A category's sub-categories. The category itself only when the row already sits on it —
    the web's rule: an edit does not have to pick a sub-category it never had."""
    he = await _draft(cb, state)
    if he is None:
        return
    chat_id = common.chat_id_of(cb)
    raw = cb.data.split(":")[2]
    root = next((r for r in await _roots(chat_id, state, he) if str(r.get("id")) == raw), None)
    if root is None:
        await edit_screen(cb, state)
        return
    items = []
    if he.get("origCat") == root.get("id"):
        items.append((home.clip(t(chat_id, "history.useCategory", name=cat_name(chat_id, root))),
                      f"hist:ecp:{root['id']}"))
    items += [(home.clip(cat_name(chat_id, c)), f"hist:ecp:{c['id']}") for c in root.get("children") or []]
    await common.show(cb, t(chat_id, "history.subCategoryAsk", name=esc(cat_name(chat_id, root))),
                      ikb([*ui.grid(items, 2), ui.nav(chat_id, back="hist:ec")]))


@router.callback_query(F.data.startswith("hist:ecp:"))
async def on_edit_category_pick(cb: CallbackQuery, state: FSMContext) -> None:
    he = await _draft(cb, state)
    if he is None:
        return
    chat_id = common.chat_id_of(cb)
    raw = cb.data.split(":")[2]
    for root in await _roots(chat_id, state, he):
        for cat, parent in [(root, None), *((c, root) for c in root.get("children") or [])]:
            if str(cat.get("id")) == raw:
                he = dict(he, cat=cat["id"], catName=_cat_label(chat_id, cat, parent))
    await state.update_data(he=he)
    await edit_screen(cb, state)


# Wallet
@router.callback_query(F.data == "hist:ew")
async def on_edit_wallets(cb: CallbackQuery, state: FSMContext) -> None:
    he = await _draft(cb, state)
    if he is None:
        return
    chat_id = common.chat_id_of(cb)
    try:
        cards = await api.request(chat_id, "GET", "/cards") or []
    except Exception as exc:  # noqa: BLE001
        await home.report(cb, exc)
        return
    cards = [c for c in cards if isinstance(c, dict) and c.get("type") != "CASH"
             and c.get("currency", CURRENCY) == CURRENCY]
    await state.update_data(he_cards=cards)
    rows = [[(home.clip("💳 " + str(c.get("name") or "—")) + f" · {fmt_money(n(c.get('currentBalance')))}",
              f"hist:ewp:{c['id']}")] for c in cards]
    rows.append([(t(chat_id, "common.cashBtn"), "hist:ewp:cash")])
    rows.append(ui.nav(chat_id, back="hist:eb"))
    ask = "history.walletAskIn" if he.get("type") == "INCOME" else "history.walletAskOut"
    await common.show(cb, t(chat_id, ask), ikb(rows))


@router.callback_query(F.data.startswith("hist:ewp:"))
async def on_edit_wallet_pick(cb: CallbackQuery, state: FSMContext) -> None:
    he = await _draft(cb, state)
    if he is None:
        return
    raw = cb.data.split(":")[2]
    if raw == "cash":
        he = dict(he, card=None, wallet=None, split=False, cash=0.0)
    else:
        card = next((c for c in (await state.get_data()).get("he_cards") or [] if str(c.get("id")) == raw), None)
        if card is not None:
            he = dict(he, card=card["id"], wallet=card.get("name"), split=False, cash=0.0)
    await state.update_data(he=he)
    await edit_screen(cb, state)


# Date
def parse_date(text: str | None, year: int) -> str | None:
    """`2026-09-12`, `12.09.2026`, `12/09/26` or `12.09` (this year) → ISO; None when unreadable."""
    raw = (text or "").strip()
    try:
        return dt.date.fromisoformat(raw).isoformat()
    except ValueError:
        pass
    m = re.fullmatch(r"(\d{1,2})[./-](\d{1,2})(?:[./-](\d{2}|\d{4}))?", raw)
    if not m:
        return None
    y = int(m.group(3)) if m.group(3) else year
    if y < 100:
        y += 2000
    try:
        return dt.date(y, int(m.group(2)), int(m.group(1))).isoformat()
    except ValueError:
        return None


@router.callback_query(F.data == "hist:ed")
async def on_edit_dates(cb: CallbackQuery, state: FSMContext) -> None:
    he = await _draft(cb, state)
    if he is None:
        return
    chat_id = common.chat_id_of(cb)
    base = clock.today()
    days = [base - dt.timedelta(days=i) for i in range(_DATE_CHOICES)]
    items = [(ui.day(chat_id, d, relative=True), f"hist:edp:{d.isoformat()}") for d in days]
    await common.show(cb, t(chat_id, "history.dateAsk"), ikb([
        *ui.grid(items, 3), [(t(chat_id, "history.btnTypeDate"), "hist:edt")], ui.nav(chat_id, back="hist:eb")]))


@router.callback_query(F.data.startswith("hist:edp:"))
async def on_edit_date_pick(cb: CallbackQuery, state: FSMContext) -> None:
    he = await _draft(cb, state)
    if he is None:
        return
    iso = parse_date(cb.data.split(":", 2)[2], clock.today().year)
    if iso:
        await state.update_data(he=dict(he, date=iso))
    await edit_screen(cb, state)


@router.callback_query(F.data == "hist:edt")
async def on_edit_date_type(cb: CallbackQuery, state: FSMContext) -> None:
    if await _draft(cb, state) is None:
        return
    chat_id = common.chat_id_of(cb)
    await state.set_state(HistEdit.date)
    await common.show(cb, t(chat_id, "history.dateTypeAsk"), ikb([ui.nav(chat_id, back="hist:ed")]))


@router.message(StateFilter(HistEdit.date))
async def on_edit_date_typed(message: Message, state: FSMContext) -> None:
    chat_id = common.chat_id_of(message)
    he = (await state.get_data()).get("he")
    if not isinstance(he, dict):
        await state.set_state(None)
        await show_month(message, state, clock.month())
        return
    iso = parse_date(message.text, int(str(he.get("date") or clock.today_iso())[:4]))
    if iso is None:
        await message.answer(t(chat_id, "history.badDate"))
        return
    await state.update_data(he=dict(he, date=iso))
    await edit_screen(message, state)


# Description
@router.callback_query(F.data == "hist:en")
async def on_edit_desc(cb: CallbackQuery, state: FSMContext) -> None:
    if await _draft(cb, state) is None:
        return
    chat_id = common.chat_id_of(cb)
    await state.set_state(HistEdit.desc)
    await common.show(cb, t(chat_id, "history.descAsk"), ikb([
        [(t(chat_id, "history.btnNoDesc"), "hist:enx")], ui.nav(chat_id, back="hist:eb")]))


@router.callback_query(F.data == "hist:enx")
async def on_edit_desc_clear(cb: CallbackQuery, state: FSMContext) -> None:
    he = await _draft(cb, state)
    if he is None:
        return
    await state.update_data(he=dict(he, desc=""))
    await edit_screen(cb, state)


@router.message(StateFilter(HistEdit.desc))
async def on_edit_desc_typed(message: Message, state: FSMContext) -> None:
    he = (await state.get_data()).get("he")
    if not isinstance(he, dict):
        await state.set_state(None)
        await show_month(message, state, clock.month())
        return
    await state.update_data(he=dict(he, desc=(message.text or "").strip()[:DESC_LIMIT]))
    await edit_screen(message, state)


# Save
def edit_payload(he: dict) -> dict:
    """The web's edit request: the kind, the stored links and the note ride along unchanged."""
    amount = float(he["amount"])
    card = he.get("card")
    body: dict = {
        "type": he["type"], "amount": amount, "currency": CURRENCY,
        "description": he.get("desc") or "", "transactionDate": he["date"],
        "subType": he.get("subType") or _regular(he["type"]), "note": he.get("note") or "",
        # The cash part of the amount: all of it for cash, none for a card, the stored part for a split.
        "cashAmount": float(he.get("cash") or 0) if he.get("split") else (0 if card is not None else amount),
    }
    if card is not None:
        body["cardId"] = card
    if he.get("cat") is not None:
        body["categoryId"] = he["cat"]
    if he.get("investmentId") is not None:
        body["investmentId"] = he["investmentId"]
    return body


@router.callback_query(F.data == "hist:es")
async def on_edit_save(cb: CallbackQuery, state: FSMContext) -> None:
    he = await _draft(cb, state)
    if he is None:
        return
    chat_id = common.chat_id_of(cb)
    if he.get("cat") is None:
        await edit_screen(cb, state, error="❌ " + t(chat_id, "history.errCategory"))
        return
    if he.get("split") and float(he.get("cash") or 0) >= float(he.get("amount") or 0):
        await edit_screen(cb, state, error="❌ " + t(chat_id, "history.errSplit", cash=fmt_money(he.get("cash"))))
        return
    await common.begin_write(cb, chat_id)
    try:
        await api.request(chat_id, "PUT", f"/transactions/{he['id']}", json=edit_payload(he))
    except api.NeedsLogin:
        await state.clear()
        await common.show(cb, t(chat_id, "common.sessionExpired"), keyboards.login_kb(chat_id))
        return
    except api.ApiError as exc:
        await edit_screen(cb, state, error=(t(chat_id, "common.serverUnreachable")
                                            if isinstance(exc, api.Unreachable) else f"❌ {esc(exc.message)}"))
        return
    await state.set_state(None)
    await state.update_data(he=None, he_roots=None, he_cards=None)
    await show_detail(cb, state, str(he["id"]), he.get("origin") or "", notice=t(chat_id, "history.updated"))
