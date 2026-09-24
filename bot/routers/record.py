"""Recording money in or out: quick add ("50000 lunch") and ➕ Add share one draft card.

**Quick add is the main way to record.** A message that starts with an amount becomes a draft
with everything filled in, and one tap on Save books it:

* the type — expense, unless it starts with `+`, or a word says income (salary, maosh, avans,
  bonus…); a leading `-` always means expense;
* the category — from keywords (EN, UZ and common transliterations) mapped onto the owner's own
  categories by name; failing that, the category last saved with one of the words; failing that,
  none, and the card shows a row of category buttons;
* the wallet — the one used last (kept across restarts), else the card with the most on it.
  Never Cash by default;
* the date — today.

Small buttons change the category, wallet or date; a typed number corrects the amount and typed
words the note.

**➕ Add** is the guided version: Expense / Income → amount → category (sub-categories when it has
them) → wallet (last used first) → the same card. The note is optional.

This router is included LAST (see main.py): it ends in the bare-text handler that turns a typed
amount into a draft, and in the catch-all for buttons from older screens. Draft buttons carry no
StateFilter and check the draft by hand, so a card that outlived a restart says so.

Callbacks owned here: `add*`, `qa:*`.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
import re

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandObject, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message, TelegramObject

from .. import api, clock, common, keyboards, storage, ui
from ..config import CURRENCY
from ..i18n import cat_name, t
from ..keyboards import esc, ikb
from ..money import fmt_money, parse_amount
from ..states import Record
from . import home, pay

router = Router(name="record")
log = logging.getLogger(__name__)

DESC_LIMIT = 255      # Transaction.description is varchar(255)
DATE_CHOICES = 5      # today and the four days before it
_CARD_CATEGORIES = 6  # category buttons on a card that has none
_WORD_LIMIT = 300     # remembered word → category pairs

# Keyword → (type it implies, which of the owner's categories). Matched on whole words; words of
# four letters or more also match with an Uzbek suffix ("tushlikka", "taksiga").
_RULES: tuple[tuple[tuple[str, ...], str, str], ...] = (
    (("lunch", "dinner", "breakfast", "food", "meal", "cafe", "coffee", "restaurant", "ovqat",
      "tushlik", "nonushta", "kafe", "kofe", "restoran", "choyxona", "somsa", "lavash", "obed",
      "uzhin", "zavtrak", "обед", "ужин", "завтрак", "еда", "кафе"), "EXPENSE", "food"),
    (("taxi", "taksi", "yandex", "yandeks", "uber", "bus", "avtobus", "metro", "benzin", "petrol",
      "fuel", "propan", "metan", "parking", "parkovka", "такси", "бензин", "автобус", "метро"),
     "EXPENSE", "transport"),
    (("rent", "arenda", "ijara", "kvartira", "kvartplata", "аренда", "квартира"), "EXPENSE", "housing"),
    (("salary", "maosh", "zarplata", "зарплата"), "INCOME", "salary"),
    (("avans", "advance", "аванс"), "INCOME", "avans"),
    (("bonus", "premiya", "mukofot", "бонус", "премия"), "INCOME", "bonus"),
)
# Each target, by the names it goes by (English and the seeded Uzbek), compared lower-case.
_NAMES = {
    "food": ("food & dining", "food", "ovqat va ichimlik", "ovqat"),
    "transport": ("transport",),
    "housing": ("housing", "uy-joy", "rent", "ijara"),
    "salary": ("salary", "oylik maosh", "maosh"),
    "avans": ("avans", "advance"),
    "bonus": ("bonus", "mukofot"),
}
# Short keywords that would catch unrelated words as a prefix ("rentgen", "business").
_EXACT_ONLY = frozenset({"rent", "bus", "uber", "obed"})
_APOSTROPHES = str.maketrans("", "", "ʻʼ’'`")


# ── Reading what was typed ──────────────────────────────────────────────────
def parse_entry(text: str | None) -> tuple[str | None, float, str] | None:
    """`"50k taxi"` → `(None, 50000.0, "taxi")`; the sign, when there is one, is the type.

    The amount is matched greedily from the front, longest first, because this region writes
    money with spaces inside it: "1 500 000 rent" and "250 ming coffee" must both survive.
    After the sign the text must begin with a digit — that is what stops this from swallowing
    every sentence typed at the bot.
    """
    raw = (text or "").strip()
    if not raw:
        return None
    sign = None
    if raw[0] in "+-":
        sign = "INCOME" if raw[0] == "+" else "EXPENSE"
        raw = raw[1:].lstrip()
    if not raw[:1].isdigit():
        return None
    tokens = raw.split()
    for cut in range(len(tokens), 0, -1):
        amount = parse_amount(" ".join(tokens[:cut]))
        if amount is not None:
            return sign, amount, " ".join(tokens[cut:]).strip()[:DESC_LIMIT]
    return None


def words(text: str | None) -> list[str]:
    return re.findall(r"[^\W\d_]+", (text or "").lower().translate(_APOSTROPHES))


def _keyword(word: str) -> tuple[str, str] | None:
    for keys, tx_type, target in _RULES:
        for k in keys:
            if word == k or (len(k) >= 4 and k not in _EXACT_ONLY and word.startswith(k)):
                return tx_type, target
    return None


def guess(note: str, sign: str | None) -> tuple[str, str | None, int | None]:
    """(type, keyword target, remembered category id) for a typed note."""
    found = words(note)
    for w in found:
        hit = _keyword(w)
        if hit and (sign is None or sign == hit[0]):
            return hit[0], hit[1], None
    memory = storage.pref("words") or {}
    for w in found:
        hit = memory.get(w)
        if isinstance(hit, list) and len(hit) == 2 and (sign is None or sign == hit[1]):
            return str(hit[1]), None, hit[0]
    return sign or "EXPENSE", None, None


def _norm(name) -> str:
    return str(name or "").strip().lower().translate(_APOSTROPHES)


def _all(roots: list[dict]):
    """Every category as (category, its parent or None)."""
    for root in roots:
        yield root, None
        for child in root.get("children") or []:
            yield child, root


def _label(chat_id: int, cat: dict, parent: dict | None) -> str:
    return f"{cat_name(chat_id, parent)} → {cat_name(chat_id, cat)}" if parent else cat_name(chat_id, cat)


def find_category(chat_id: int, roots: list[dict], target: str | None,
                  cat_id: int | None) -> tuple[int, str] | None:
    """The owner's category for a keyword target, or the remembered id — (id, label)."""
    if cat_id is not None:
        for cat, parent in _all(roots):
            if cat.get("id") == cat_id:
                return cat_id, _label(chat_id, cat, parent)
        return None
    if target is None:
        return None
    names = _NAMES[target]
    candidates = list(_all(roots))
    if target in ("avans", "bonus"):
        # Under the salary first: that is where the web keeps them.
        salary = [(c, p) for c, p in candidates
                  if p is not None and (_norm(p.get("name")) in _NAMES["salary"]
                                        or _norm(p.get("nameUz")) in _NAMES["salary"])]
        candidates = salary + candidates
    for cat, parent in candidates:
        if _norm(cat.get("name")) in names or _norm(cat.get("nameUz")) in names \
                or (target == "bonus" and cat.get("bonusIncome")):
            return cat["id"], _label(chat_id, cat, parent)
    if target in ("avans", "bonus"):
        return find_category(chat_id, roots, "salary", None)
    return None


def remember_words(rec: dict) -> None:
    """Next time one of these words is typed without a keyword, suggest this category."""
    if rec.get("cat") is None or not rec.get("note"):
        return
    memory = dict(storage.pref("words") or {})
    for w in words(rec["note"]):
        if len(w) >= 3:
            memory.pop(w, None)
            memory[w] = [rec["cat"], rec["type"]]
    while len(memory) > _WORD_LIMIT:
        memory.pop(next(iter(memory)))
    storage.set_pref("words", memory)


# ── Wallets ─────────────────────────────────────────────────────────────────
def _cards(cards: list[dict]) -> list[dict]:
    return [c for c in cards if isinstance(c, dict) and c.get("type") != "CASH"
            and c.get("currency", CURRENCY) == CURRENCY]


def default_wallet(cards: list[dict]) -> tuple[int | None, str | None]:
    """The wallet used last, else the card with the most on it; cash only if there is no card."""
    last = pay.last_wallet()
    if last == "cash":
        return None, None
    for c in cards:
        if c.get("id") == last:
            return c["id"], c.get("name")
    if cards:
        best = max(cards, key=lambda c: home.n(c.get("currentBalance")))
        return best["id"], best.get("name")
    return None, None


def _ordered_cards(cards: list[dict]) -> list[dict]:
    last = pay.last_wallet()
    return sorted(cards, key=lambda c: (c.get("id") != last, -home.n(c.get("currentBalance"))))


# ── The draft ───────────────────────────────────────────────────────────────
async def _load(chat_id: int, tx_type: str) -> tuple[list[dict], list[dict], bool]:
    """The categories for this type, the cards, and whether a stable income is set."""
    cats, cards, settings = await asyncio.gather(
        api.request(chat_id, "GET", "/categories",
                    params={"type": tx_type, "subType": _sub(tx_type)}),
        api.request(chat_id, "GET", "/cards"),
        api.request(chat_id, "GET", "/settings"),
        return_exceptions=True)
    for result in (cards, settings):
        if isinstance(result, BaseException):
            raise result
    if isinstance(cats, BaseException):
        log.warning("category list failed for chat %s", chat_id, exc_info=cats)
        cats = []
    income = home.n((settings or {}).get("monthlyStableIncome"))
    return [c for c in cats or [] if isinstance(c, dict)], _cards(cards or []), income > 0


def _sub(tx_type: str) -> str:
    return "REGULAR_INCOME" if tx_type == "INCOME" else "REGULAR_EXPENSE"


async def _reload_categories(chat_id: int, state: FSMContext, tx_type: str) -> list[dict]:
    try:
        cats = await api.request(chat_id, "GET", "/categories",
                                 params={"type": tx_type, "subType": _sub(tx_type)}) or []
    except api.NeedsLogin:
        raise
    except Exception:  # noqa: BLE001
        cats = []
    cats = [c for c in cats if isinstance(c, dict)]
    await state.update_data(rec_roots=cats)
    return cats


async def new_draft(event: TelegramObject, state: FSMContext, sign: str | None, amount: float,
                    note: str, *, step: str | None = None, cat_id: int | None = None,
                    card_id: int | None = None, tx_type: str | None = None) -> None:
    """Build a draft and put it on screen (or the category step, for ➕ Add)."""
    chat_id = common.chat_id_of(event)
    typ, target, remembered = guess(note, sign)
    typ = tx_type or typ
    try:
        roots, cards, income_set = await _load(chat_id, typ)
    except Exception as exc:  # noqa: BLE001
        await home.report(event, exc)
        return
    if not income_set:
        await common.show(event, f"{t(chat_id, 'guard.incomeTitle')}\n\n{t(chat_id, 'guard.incomeBody')}",
                          keyboards.income_guard_kb(chat_id))
        return
    found = find_category(chat_id, roots, target, cat_id if cat_id is not None else remembered)
    if card_id is not None and any(c.get("id") == card_id for c in cards):
        card = (card_id, next(c.get("name") for c in cards if c.get("id") == card_id))
    else:
        card = default_wallet(cards)
    rec = {"type": typ, "amount": amount, "date": clock.today_iso(), "note": note or None,
           "card": card[0], "wallet": card[1], "cat": found[0] if found else None,
           "catName": found[1] if found else None, "step": step}
    await state.set_state(Record.card)
    await state.update_data(rec=rec, rec_roots=roots, rec_cards=cards)
    if step == "cat":
        await _category_screen(event, state)
    else:
        await show_card(event, state)


async def _render(event: TelegramObject, state: FSMContext, text: str,
                  kb: InlineKeyboardMarkup | None) -> None:
    """Draw the flow's screen, keeping ONE live keyboard: a typed step strips the previous one."""
    if isinstance(event, CallbackQuery):
        await common.show(event, text, kb)
        if event.message is not None:
            await state.update_data(rec_ui=event.message.message_id)
        return
    previous = (await state.get_data()).get("rec_ui")
    if previous and isinstance(event, Message) and event.bot is not None:
        try:
            await event.bot.edit_message_reply_markup(chat_id=event.chat.id, message_id=previous,
                                                      reply_markup=None)
        except TelegramBadRequest:
            log.debug("couldn't strip the previous draft keyboard", exc_info=True)
    sent = await event.answer(text, reply_markup=kb)
    await state.update_data(rec_ui=sent.message_id)


def _card_text(chat_id: int, rec: dict, error: str = "") -> str:
    head = "record.card.income" if rec["type"] == "INCOME" else "record.card.expense"
    wallet = ("💵 " + t(chat_id, "common.cash") if rec.get("card") is None
              else "💳 " + esc(rec.get("wallet") or f"#{rec['card']}"))
    lines = [t(chat_id, head, amount=fmt_money(rec["amount"])),
             "🏷 " + (esc(rec["catName"]) if rec.get("cat") is not None else t(chat_id, "record.card.noCategory")),
             wallet,
             "📅 " + ui.day(chat_id, rec["date"], relative=True)]
    if rec.get("note"):
        lines.append("📝 " + esc(rec["note"]))
    if error:
        lines += ["", error, t(chat_id, "record.notSaved")]
    return "\n".join(lines)


def _card_kb(chat_id: int, rec: dict, roots: list[dict]) -> InlineKeyboardMarkup:
    rows: list[list[tuple[str, str]]] = []
    if rec.get("cat") is None and roots:
        items = [(home.clip(cat_name(chat_id, r)), f"qa:co:{r['id']}" if r.get("children") else f"qa:c:{r['id']}")
                 for r in roots[:_CARD_CATEGORIES]]
        if len(roots) > _CARD_CATEGORIES:
            items.append((t(chat_id, "record.btn.more"), "qa:cats"))
        rows += ui.grid(items, 3)
    rows.append([(t(chat_id, "record.btn.save"), "qa:save")])
    small = [(t(chat_id, "record.btn.wallet"), "qa:ws"), (t(chat_id, "record.btn.date"), "qa:ds")]
    if rec.get("cat") is not None or not roots:
        small.insert(0, (t(chat_id, "record.btn.category"), "qa:cats"))
    rows.append(small)
    flip = "record.btn.toExpense" if rec["type"] == "INCOME" else "record.btn.toIncome"
    rows.append([(t(chat_id, "record.btn.note"), "qa:n"), (t(chat_id, flip), "qa:flip"),
                 (t(chat_id, "common.cancel"), "home")])
    return ikb(rows)


async def show_card(event: TelegramObject, state: FSMContext, *, error: str = "") -> None:
    chat_id = common.chat_id_of(event)
    d = await state.get_data()
    rec = dict(d["rec"], step=None)
    await state.update_data(rec=rec)
    await state.set_state(Record.card)
    await _render(event, state, _card_text(chat_id, rec, error), _card_kb(chat_id, rec, d.get("rec_roots") or []))


async def _draft(cb: CallbackQuery, state: FSMContext) -> dict | None:
    """Gate the tap and hand back the FSM data with its draft. None: already answered."""
    chat_id = common.chat_id_of(cb)
    if not await common.gate(cb):
        return None
    d = await state.get_data()
    rec = d.get("rec")
    if not isinstance(rec, dict) or rec.get("amount") is None:
        await common.ack(cb, t(chat_id, "common.oldButton"), alert=True)
        await state.clear()
        await home.show_home(cb)
        return None
    await common.ack(cb)
    return d


# ── ➕ Add ──────────────────────────────────────────────────────────────────
def _start_kb(chat_id: int) -> InlineKeyboardMarkup:
    return ikb([
        [(t(chat_id, "record.btn.expense"), "add:EXPENSE"), (t(chat_id, "record.btn.income"), "add:INCOME")],
        [(t(chat_id, "record.btn.repeat"), "qa:repeat")],
        ui.nav(chat_id, home=True),
    ])


async def show_start(event: TelegramObject, state: FSMContext) -> None:
    chat_id = common.chat_id_of(event)
    await state.clear()
    await common.show(event, t(chat_id, "record.start"), _start_kb(chat_id))


async def add_cmd(message: Message, state: FSMContext, command: CommandObject) -> None:
    """`/add` opens ➕ Add; `/add 50000 lunch` goes straight to the draft."""
    if not await common.gate(message):
        return
    parsed = parse_entry(command.args)
    if parsed is None:
        await show_start(message, state)
        return
    await new_draft(message, state, *parsed)


@router.callback_query(F.data == "add")
async def on_add(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    if not await common.gate(cb):
        return
    await show_start(cb, state)


@router.callback_query(F.data.startswith("add:"))
async def on_add_type(cb: CallbackQuery, state: FSMContext) -> None:
    chat_id = common.chat_id_of(cb)
    await common.ack(cb)
    if not await common.gate(cb):
        return
    tx_type = "INCOME" if cb.data.endswith("INCOME") else "EXPENSE"
    await state.set_state(Record.amount)
    await state.set_data({"rec_type": tx_type})
    head = "record.card.incomeTitle" if tx_type == "INCOME" else "record.card.expenseTitle"
    await common.show(cb, f"{t(chat_id, head)}\n\n{t(chat_id, 'record.amountAsk')}",
                      ikb([ui.nav(chat_id, back="add", cancel="home")]))


@router.message(StateFilter(Record.amount))
async def on_amount(message: Message, state: FSMContext) -> None:
    chat_id = common.chat_id_of(message)
    parsed = parse_entry(message.text)
    if parsed is None:
        await message.answer(t(chat_id, "record.badAmount"))
        return
    tx_type = (await state.get_data()).get("rec_type") or "EXPENSE"
    await new_draft(message, state, None, parsed[1], parsed[2], step="cat", tx_type=tx_type)


# ── Category ────────────────────────────────────────────────────────────────
async def _category_screen(event: TelegramObject, state: FSMContext) -> None:
    chat_id = common.chat_id_of(event)
    d = await state.get_data()
    rec, roots = d["rec"], d.get("rec_roots") or []
    items = [(home.clip(cat_name(chat_id, r)), f"qa:co:{r['id']}" if r.get("children") else f"qa:c:{r['id']}")
             for r in roots]
    guided = rec.get("step") == "cat"
    rows = ui.grid(items, 2)
    rows.append([(t(chat_id, "common.skip") if guided else t(chat_id, "record.btn.noCategory"), "qa:c:none")])
    rows.append(ui.nav(chat_id, cancel="home") if guided else ui.nav(chat_id, back="qa:back"))
    text = t(chat_id, "record.categoryAsk", amount=fmt_money(rec["amount"]))
    if not roots:
        text += "\n\n" + t(chat_id, "record.noCategories")
    await _render(event, state, text, ikb(rows))


@router.callback_query(F.data == "qa:cats")
async def on_categories(cb: CallbackQuery, state: FSMContext) -> None:
    d = await _draft(cb, state)
    if d is None:
        return
    if not d.get("rec_roots"):
        await _reload_categories(common.chat_id_of(cb), state, d["rec"]["type"])
    await _category_screen(cb, state)


@router.callback_query(F.data.startswith("qa:co:"))
async def on_category_open(cb: CallbackQuery, state: FSMContext) -> None:
    """One category's sub-categories, with the category itself first."""
    d = await _draft(cb, state)
    if d is None:
        return
    chat_id = common.chat_id_of(cb)
    raw = cb.data.split(":")[2]
    root = next((r for r in d.get("rec_roots") or [] if str(r.get("id")) == raw), None)
    if root is None:
        await _category_screen(cb, state)
        return
    items = [(home.clip(t(chat_id, "record.useCategory", name=cat_name(chat_id, root))), f"qa:c:{root['id']}")]
    items += [(home.clip(cat_name(chat_id, c)), f"qa:c:{c['id']}") for c in root.get("children") or []]
    await _render(cb, state, t(chat_id, "record.subCategoryAsk", name=esc(cat_name(chat_id, root))),
                  ikb([*ui.grid(items, 2), ui.nav(chat_id, back="qa:cats")]))


@router.callback_query(F.data.startswith("qa:c:"))
async def on_category(cb: CallbackQuery, state: FSMContext) -> None:
    d = await _draft(cb, state)
    if d is None:
        return
    chat_id = common.chat_id_of(cb)
    raw = cb.data.split(":")[2]
    rec = dict(d["rec"])
    found = find_category(chat_id, d.get("rec_roots") or [], None, int(raw)) if raw.isdigit() else None
    rec["cat"], rec["catName"] = (found if found else (None, None))
    guided = rec.get("step") == "cat"
    rec["step"] = "wallet" if guided else None
    await state.update_data(rec=rec)
    if guided:
        await _wallet_screen(cb, state)
    else:
        await show_card(cb, state)


# ── Wallet ──────────────────────────────────────────────────────────────────
async def _wallet_screen(event: TelegramObject, state: FSMContext) -> None:
    chat_id = common.chat_id_of(event)
    d = await state.get_data()
    rec = d["rec"]
    rows = [[(home.clip("💳 " + str(c.get("name") or "—")) + f" · {fmt_money(home.n(c.get('currentBalance')))}",
              f"qa:w:{c['id']}")] for c in _ordered_cards(d.get("rec_cards") or [])]
    cash = [(t(chat_id, "common.cashBtn"), "qa:w:cash")]
    rows = [cash, *rows] if pay.last_wallet() == "cash" else [*rows, cash]
    guided = rec.get("step") == "wallet"
    rows.append(ui.nav(chat_id, cancel="home") if guided else ui.nav(chat_id, back="qa:back"))
    ask = "record.walletAskIn" if rec["type"] == "INCOME" else "record.walletAskOut"
    await _render(event, state, t(chat_id, ask), ikb(rows))


@router.callback_query(F.data == "qa:ws")
async def on_wallets(cb: CallbackQuery, state: FSMContext) -> None:
    if await _draft(cb, state) is None:
        return
    await _wallet_screen(cb, state)


@router.callback_query(F.data.startswith("qa:w:"))
async def on_wallet(cb: CallbackQuery, state: FSMContext) -> None:
    d = await _draft(cb, state)
    if d is None:
        return
    raw = cb.data.split(":")[2]
    rec = dict(d["rec"])
    if raw == "cash":
        rec["card"], rec["wallet"] = None, None
    elif raw.isdigit():
        card = next((c for c in d.get("rec_cards") or [] if c.get("id") == int(raw)), None)
        if card is not None:
            rec["card"], rec["wallet"] = card["id"], card.get("name")
    await state.update_data(rec=rec)
    await show_card(cb, state)


# ── Date ────────────────────────────────────────────────────────────────────
@router.callback_query(F.data == "qa:ds")
async def on_dates(cb: CallbackQuery, state: FSMContext) -> None:
    if await _draft(cb, state) is None:
        return
    chat_id = common.chat_id_of(cb)
    base = clock.today()
    days = [base - dt.timedelta(days=i) for i in range(DATE_CHOICES)]
    items = [(ui.day(chat_id, d, relative=True), f"qa:d:{d.isoformat()}") for d in days]
    await _render(cb, state, t(chat_id, "record.dateAsk"),
                  ikb([*ui.grid(items, 3), ui.nav(chat_id, back="qa:back")]))


@router.callback_query(F.data.startswith("qa:d:"))
async def on_date(cb: CallbackQuery, state: FSMContext) -> None:
    d = await _draft(cb, state)
    if d is None:
        return
    iso = cb.data.split(":", 2)[2]
    try:
        dt.date.fromisoformat(iso)
    except ValueError:
        iso = d["rec"]["date"]
    await state.update_data(rec=dict(d["rec"], date=iso))
    await show_card(cb, state)


# ── Note, type, back ────────────────────────────────────────────────────────
@router.callback_query(F.data == "qa:n")
async def on_note(cb: CallbackQuery, state: FSMContext) -> None:
    if await _draft(cb, state) is None:
        return
    chat_id = common.chat_id_of(cb)
    await state.set_state(Record.note)
    await _render(cb, state, t(chat_id, "record.noteAsk"),
                  ikb([[(t(chat_id, "common.skip"), "qa:n:-")], ui.nav(chat_id, back="qa:back")]))


@router.callback_query(F.data == "qa:n:-")
async def on_note_skip(cb: CallbackQuery, state: FSMContext) -> None:
    d = await _draft(cb, state)
    if d is None:
        return
    await state.update_data(rec=dict(d["rec"], note=None))
    await show_card(cb, state)


@router.message(StateFilter(Record.note))
async def on_note_typed(message: Message, state: FSMContext) -> None:
    d = await state.get_data()
    if not isinstance(d.get("rec"), dict):
        await state.clear()
        await home.show_home(message)
        return
    note = (message.text or "").strip()[:DESC_LIMIT]
    await state.update_data(rec=dict(d["rec"], note=note or None))
    await show_card(message, state)


@router.callback_query(F.data == "qa:flip")
async def on_flip(cb: CallbackQuery, state: FSMContext) -> None:
    """Expense ↔ income. The category goes with it: expense categories are not offered for income."""
    d = await _draft(cb, state)
    if d is None:
        return
    rec = dict(d["rec"], cat=None, catName=None)
    rec["type"] = "EXPENSE" if rec["type"] == "INCOME" else "INCOME"
    await state.update_data(rec=rec)
    await _reload_categories(common.chat_id_of(cb), state, rec["type"])
    await show_card(cb, state)


@router.callback_query(F.data == "qa:back")
async def on_back(cb: CallbackQuery, state: FSMContext) -> None:
    if await _draft(cb, state) is None:
        return
    await show_card(cb, state)


# ── Repeat last ─────────────────────────────────────────────────────────────
@router.callback_query(F.data == "qa:repeat")
async def on_repeat(cb: CallbackQuery, state: FSMContext) -> None:
    """Copy the newest income or expense into a fresh draft, dated today."""
    chat_id = common.chat_id_of(cb)
    await common.ack(cb)
    if not await common.gate(cb):
        return
    try:
        page = await api.request(chat_id, "GET", "/transactions", params={
            "currency": CURRENCY, "page": 0, "size": 1, "sortBy": "transactionDate",
            "sortDir": "desc", "excludeTransfers": "true"})
    except Exception as exc:  # noqa: BLE001
        await home.report(cb, exc)
        return
    content = (page or {}).get("content") or []
    last = content[0] if content else None
    if not last or last.get("subType") not in ("REGULAR_INCOME", "REGULAR_EXPENSE") \
            or home.n(last.get("amount")) <= 0:
        key = "record.repeatNone" if not last else "record.repeatCant"
        await common.show(cb, t(chat_id, key), _start_kb(chat_id))
        return
    card = last.get("card") or {}
    category = last.get("category") or {}
    await new_draft(cb, state, "INCOME" if last.get("type") == "INCOME" else "EXPENSE",
                    home.n(last.get("amount")), (last.get("description") or "")[:DESC_LIMIT],
                    cat_id=category.get("id"), card_id=card.get("id"))


# ── Save ────────────────────────────────────────────────────────────────────
def _payload(rec: dict) -> dict:
    card = rec.get("card")
    body: dict = {"type": rec["type"], "amount": rec["amount"], "currency": CURRENCY,
                  "transactionDate": rec["date"], "subType": _sub(rec["type"]),
                  # No card means the whole amount is cash; with a card, 0 marks a card payment.
                  "cashAmount": rec["amount"] if card is None else 0}
    if card is not None:
        body["cardId"] = card
    if rec.get("cat") is not None:
        body["categoryId"] = rec["cat"]
    if rec.get("note"):
        body["description"] = rec["note"]
    return body


@router.callback_query(F.data == "qa:save")
async def on_save(cb: CallbackQuery, state: FSMContext) -> None:
    """Write the draft. A refusal keeps the draft on screen with the reason under it."""
    d = await _draft(cb, state)
    if d is None:
        return
    chat_id = common.chat_id_of(cb)
    rec = d["rec"]
    await common.begin_write(cb, chat_id)
    try:
        await api.request(chat_id, "POST", "/transactions", json=_payload(rec))
    except api.NeedsLogin:
        await state.clear()
        await common.show(cb, t(chat_id, "common.sessionExpired"), keyboards.login_kb(chat_id))
        return
    except api.ApiError as exc:
        await show_card(cb, state, error=(t(chat_id, "common.serverUnreachable")
                                          if isinstance(exc, api.Unreachable) else f"❌ {esc(exc.message)}"))
        return
    pay.remember_wallet(rec.get("card"))
    remember_words(rec)
    await state.clear()
    key = "record.saved.income" if rec["type"] == "INCOME" else "record.saved.expense"
    notice = t(chat_id, key, amount=fmt_money(rec["amount"]))
    if rec.get("note"):
        notice += f" — {esc(rec['note'])}"
    await home.show_home(cb, notice)


# ── Typed text ──────────────────────────────────────────────────────────────
@router.message(StateFilter(Record.card))
async def on_card_typed(message: Message, state: FSMContext) -> None:
    """While a card is open: a new entry ("30000 taxi") replaces the draft, a bare number corrects
    the amount, and words become the note."""
    d = await state.get_data()
    rec = d.get("rec")
    text = (message.text or "").strip()
    if not isinstance(rec, dict):
        await state.clear()
        await not_understood(message)
        return
    if not text or text.startswith("/"):
        await not_understood(message)
        return
    parsed = parse_entry(text)
    if parsed is not None and parsed[2]:
        await new_draft(message, state, *parsed)
        return
    if parsed is None:
        rec = dict(rec, note=text[:DESC_LIMIT])
    else:
        sign, amount, _ = parsed
        rec = dict(rec, amount=amount)
        if sign and sign != rec["type"]:
            rec.update(type=sign, cat=None, catName=None)
            await state.update_data(rec=rec)
            await _reload_categories(message.chat.id, state, sign)
    await state.update_data(rec=rec)
    await show_card(message, state)


async def not_understood(message: Message) -> None:
    chat_id = common.chat_id_of(message)
    await common.show(message, t(chat_id, "record.notUnderstood"), ikb([
        [(t(chat_id, "home.btn.add"), "add"), (t(chat_id, "common.home"), "home")],
    ]))


@router.message(StateFilter(None))
async def on_text(message: Message, state: FSMContext) -> None:
    """Anything typed with no flow open: an amount becomes a draft, anything else is answered."""
    if not await common.gate(message):
        return
    parsed = parse_entry(message.text)
    if parsed is None:
        await not_understood(message)
        return
    await new_draft(message, state, *parsed)


@router.callback_query()
async def on_old_button(cb: CallbackQuery, state: FSMContext) -> None:
    """A button no handler above wanted — from a screen of an older version, or after a restart."""
    await common.ack(cb, t(common.chat_id_of(cb), "common.oldButton"))
    await state.clear()
    if not await common.gate(cb):
        return
    await home.show_home(cb)
