"""Quick add: one typed message becomes a draft, one tap books it.

Recording a single expense through the guided flow costs nine taps, a typed number and six
blocking round-trips — for the one action this bot exists to make cheap. Worse, the shortcut
every person tries first, typing "50000 lunch" straight into the chat, produced *nothing*:
every message handler in the bot is gated by `Command()` or `StateFilter`, so an out-of-state
text update matched nothing and aiogram dropped it silently. The owner watched their message
sit there unanswered and concluded the bot was broken.

This module is the answer to both, and it is deliberately shaped as a **draft, not a wizard**:

* Typing `50000 lunch` (or `50k taxi`, `1.5m rent`, `250 ming coffee`, `+2000000 salary`,
  `-50000 taxi`) renders a card with everything already filled in — today's date, the wallet
  used last time, no category, the description you typed — and a Save button. The common case
  is one message and one tap, with exactly one blocking call before the card appears (the
  stable-income guard the backend enforces on every write anyway).
* Every field on the card has a button that changes just that field and comes straight back.
  Nothing is a linear step, so there is no "start over" and no Back that unwinds five screens.
* `/add` opens the same card from the blue command menu; `/add 50000 lunch` skips the prompt.
* "Repeat last" copies the newest transaction and dates it today, which is how a daily
  commute or a recurring top-up gets recorded in two taps.

Two structural rules, both load-bearing:

**This router is included LAST** (see `bot/main.py`) because it ends in a bare-text handler.
That handler answers a message only when there is no FSM state *and* the text really begins
with an amount; anything else falls through to a friendly "I didn't understand that" with a
way into the menu, which is the fix for the silence described above. A router registered
after this one would never see typed input again.

**Every `qa:` callback is registered without a `StateFilter`** and reads the draft out of FSM
data instead. MemoryStorage dies with the process, and a state-gated confirm button on a
screen that outlived a restart matches nothing at all: the tap spins for fifteen seconds and
then does nothing, forever, with the screen still looking live. Checking for the draft by hand
means a stale card can say so and offer a way forward.
"""
from __future__ import annotations

import datetime as dt
import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message, TelegramObject

from .. import api, common, keyboards, ui
from ..clock import today, today_iso
from ..config import CURRENCY
from ..i18n import cat_name, t
from ..keyboards import esc
from ..money import fmt_money, parse_amount
from ..states import QuickAdd

router = Router(name="quickadd")
log = logging.getLogger(__name__)

# `Transaction.description` is a plain @Column, i.e. varchar(255). A 4000-character message
# that happens to start with a digit would be rejected by Postgres as a 500 rather than by
# validation, so the clip happens here where it can be silent and harmless.
DESC_LIMIT = 255

# How many days the date picker offers. Quick add is for something that just happened; a
# genuinely old entry belongs in the full flow, which takes a typed date.
DATE_CHOICES = 5

# The wallet the owner used last, per chat. In memory on purpose: it is a convenience, not a
# setting — a wrong guess costs one tap to correct, and persisting it would mean a schema for
# something that is only ever "probably still the same card as five minutes ago". The bot is
# single-owner (see the owner guard in bot/middlewares.py) so this dict holds one entry in
# practice; it is bounded anyway because nothing else would ever prune it.
_LAST_SOURCE: dict[int, tuple[int | None, str | None]] = {}
_LAST_SOURCE_LIMIT = 32

# Sub-types a copied transaction may keep as-is: they create no finance record of their own,
# so repeating one cannot spawn a duplicate holding or a junk donation row.
_REPEAT_KEEP = ("REGULAR_INCOME", "REGULAR_EXPENSE", "STOCK_PURCHASE")

# Sub-types that are safe to keep ONLY when the original carried an investmentId. With an id
# the backend tops up that exact holding (`addFundsToInvestment`); without one it CREATES a
# new holding from the transaction, which is how a monthly gold top-up grew a fresh junk row
# every month. Quick add never picks these itself — it only ever carries an existing link.
_REPEAT_LINKED = ("INVESTMENT", "EMERGENCY_CONTRIBUTION")

# Rows that are not a thing a person "records" and so cannot be repeated: the two legs of a
# wallet-to-wallet move (written as a pair by POST /transactions/transfer) and the month-close
# reconciliation plug.
_REPEAT_TRANSFER = ("TRANSFER_IN", "TRANSFER_OUT")

# The only sub-types that fund an allocation bucket (OverviewService.bucketForSubType). The
# preview is skipped entirely for anything else, because the answer is known in advance —
# "not applicable" — and a round trip to be told so would cost the draft its whole point.
_BUCKET_SUBTYPES = ("DONATION", "EMERGENCY_CONTRIBUTION", "INVESTMENT")

# Sub-type -> the label shown on the card. Only the kinds a repeat can carry appear here; a
# regular income/expense shows no Kind line at all, because "Kind: Regular expense" is a row
# of text that never varies.
_KIND_KEYS = {
    "EMERGENCY_CONTRIBUTION": "quickadd.kind.emergency",
    "INVESTMENT": "quickadd.kind.investment",
    "STOCK_PURCHASE": "quickadd.kind.stocks",
}

# Bucket code -> our own label. The API also sends `label`, but it is English prose composed
# server-side, and printing it is how the most-walked screen in the bot ended up with an
# English sentence glued to an Uzbek postposition.
_BUCKET_KEYS = {
    "DONATION": "quickadd.bucket.donation",
    "EMERGENCY": "quickadd.bucket.emergency",
    "INVESTMENTS": "quickadd.bucket.investments",
    "SAVINGS": "quickadd.bucket.savings",
    "STOCKS": "quickadd.bucket.stocks",
}


# ── Parsing a typed entry ───────────────────────────────────────────────────

def parse_entry(text: str | None) -> tuple[str, float, str] | None:
    """`"50k taxi"` -> `("EXPENSE", 50000.0, "taxi")`. None when it is not an entry at all.

    The amount is matched greedily from the front, longest first, because the way this region
    writes money puts spaces inside the number: "1 500 000 rent" and "250 ming coffee" both
    have to survive `str.split()`. Longest-first is what makes "250 ming" beat "250".

    A leading `+` books income and a leading `-` an expense; with neither, an expense, because
    that is what the overwhelming majority of entries are. After the sign the text must begin
    with a digit — that single check is what stops this from being a catch-all that swallows
    every sentence typed at the menu.
    """
    raw = (text or "").strip()
    if not raw:
        return None
    tx_type = "EXPENSE"
    if raw[0] in "+-":
        tx_type = "INCOME" if raw[0] == "+" else "EXPENSE"
        raw = raw[1:].lstrip()
    if not raw[:1].isdigit():
        return None
    tokens = raw.split()
    for cut in range(len(tokens), 0, -1):
        amount = parse_amount(" ".join(tokens[:cut]))
        if amount is not None:
            return tx_type, amount, " ".join(tokens[cut:]).strip()[:DESC_LIMIT]
    return None


# ── The draft in FSM data ───────────────────────────────────────────────────

def _has_draft(data: dict) -> bool:
    return data.get("qa_amount") is not None and bool(data.get("qa_type"))


def _regular(tx_type: str) -> str:
    return "REGULAR_INCOME" if tx_type == "INCOME" else "REGULAR_EXPENSE"


def _remember_source(chat_id: int, card_id: int | None, card_name: str | None) -> None:
    _LAST_SOURCE[chat_id] = (card_id, card_name)
    while len(_LAST_SOURCE) > _LAST_SOURCE_LIMIT:
        _LAST_SOURCE.pop(next(iter(_LAST_SOURCE)), None)


async def _new_draft(event: TelegramObject, state: FSMContext, tx_type: str, amount: float,
                     desc: str, *, card_id: int | None = None, card_name: str | None = None,
                     category_id: int | None = None, category_name: str | None = None,
                     sub_type: str | None = None, investment_id: int | None = None,
                     notes: tuple[str, ...] = ()) -> None:
    """Replace whatever draft was open with this one and put it on screen.

    The screen id survives (`qa_ui`) so that the card being replaced can have its buttons
    stripped rather than left live above the new one.
    """
    chat_id = common.chat_id_of(event)
    if card_id is None and card_name is None:
        card_id, card_name = _LAST_SOURCE.get(chat_id, (None, None))
    previous = await state.get_data()
    draft = {
        "qa_type": tx_type,
        "qa_amount": amount,
        "qa_date": today_iso(),
        "qa_cardId": card_id,
        "qa_cardName": card_name,
        "qa_categoryId": category_id,
        "qa_categoryName": category_name,
        "qa_desc": desc or None,
        "qa_subType": sub_type,
        "qa_investmentId": investment_id,
        "qa_notes": list(notes),
    }
    if previous.get("qa_ui"):
        draft["qa_ui"] = previous["qa_ui"]
    await state.set_state(QuickAdd.confirm)
    await state.set_data(draft)
    await show_draft(event, state)


# ── Rendering ───────────────────────────────────────────────────────────────

async def _render(event: TelegramObject, state: FSMContext, text: str,
                  kb: InlineKeyboardMarkup | None) -> None:
    """Draw the flow's screen, keeping exactly ONE live keyboard per draft.

    A callback edits the message it came from, which is already the single screen. A typed
    step cannot: the owner's own message has pushed the card up the chat and Telegram has no
    way to answer in place, so a new one is sent — and the previous card's buttons are taken
    away first. Leaving them is what makes a Save button sit there looking live above a
    screen it no longer describes.

    `Message.answer` is used directly on that path rather than `common.show` for one reason:
    the id of the message it returns is what lets the NEXT typed step strip this one. Every
    screen this module draws is a short card, well inside the 4096-character limit that
    `common.show` exists to handle.
    """
    if isinstance(event, CallbackQuery):
        await common.show(event, text, kb)
        if event.message is not None:
            await state.update_data(qa_ui=event.message.message_id)
        return
    data = await state.get_data()
    previous = data.get("qa_ui")
    if previous and isinstance(event, Message) and event.bot is not None:
        try:
            await event.bot.edit_message_reply_markup(
                chat_id=event.chat.id, message_id=previous, reply_markup=None)
        except TelegramBadRequest:
            # Already stripped, deleted, or older than Telegram lets us touch. Nothing here
            # is worth failing the render the owner is waiting for.
            log.debug("couldn't strip the previous quick-add keyboard", exc_info=True)
    sent = await event.answer(text, reply_markup=kb)
    await state.update_data(qa_ui=sent.message_id)


def _date_label(chat_id: int, iso: str) -> str:
    """`2026-09-07 (today)` — the date is data, the suffix is the reassurance."""
    if iso == today_iso():
        return f"{iso} {t(chat_id, 'quickadd.suffixToday')}"
    if iso == (today() - dt.timedelta(days=1)).isoformat():
        return f"{iso} {t(chat_id, 'quickadd.suffixYesterday')}"
    return iso


def _card_text(chat_id: int, d: dict, *, alloc: str = "", error: str = "") -> str:
    """The draft card. Everything that came from the owner or the API is escaped."""
    head = "quickadd.headIncome" if d["qa_type"] == "INCOME" else "quickadd.headExpense"
    # "Cash" is claimed only when there really is no card. A card whose name could not be
    # resolved is shown by its id instead: printing "Cash" over a payload that carries a
    # cardId would be the card-timeout-becomes-cash defect written into the confirmation.
    wallet = (t(chat_id, "common.cash") if d.get("qa_cardId") is None
              else d.get("qa_cardName") or f"💳 #{d['qa_cardId']}")
    lines = [
        t(chat_id, "quickadd.draftTitle"),
        "",
        t(chat_id, head, amount=fmt_money(d["qa_amount"])),
        f"{t(chat_id, 'quickadd.field.date')}: {_date_label(chat_id, d['qa_date'])}",
        f"{t(chat_id, 'quickadd.field.wallet')}: {esc(wallet)}",
    ]
    kind_key = _KIND_KEYS.get(d.get("qa_subType") or "")
    if kind_key:
        # A translated label, not an API string: escaping it would print &amp; on screen.
        lines.append(f"{t(chat_id, 'quickadd.field.kind')}: {t(chat_id, kind_key)}")
    category = d.get("qa_categoryName") or t(chat_id, "common.none")
    lines.append(f"{t(chat_id, 'quickadd.field.category')}: {esc(category)}")
    description = d.get("qa_desc") or t(chat_id, "common.none")
    lines.append(f"{t(chat_id, 'quickadd.field.description')}: {esc(description)}")
    if alloc:
        lines += ["", alloc]
    elif d.get("qa_subType") == "STOCK_PURCHASE":
        lines += ["", t(chat_id, "quickadd.stocksNote")]
    for note in d.get("qa_notes") or []:
        lines += ["", t(chat_id, note)]
    if error:
        lines += ["", error, t(chat_id, "quickadd.notSaved")]
    lines += ["", t(chat_id, "quickadd.draftFoot")]
    return "\n".join(lines)


def _draft_kb(chat_id: int, d: dict) -> InlineKeyboardMarkup:
    """Every field on the card has its own button, and Save sits where Confirm always sits."""
    flip = "quickadd.btnToExpense" if d["qa_type"] == "INCOME" else "quickadd.btnToIncome"
    return ui.ikb([
        [(t(chat_id, "quickadd.btnAmount"), "qa:amount"),
         (t(chat_id, "quickadd.btnDate"), "qa:date")],
        [(t(chat_id, "quickadd.btnWallet"), "qa:src"),
         (t(chat_id, "quickadd.btnCategory"), "qa:cat")],
        [(t(chat_id, "quickadd.btnDesc"), "qa:desc"),
         (t(chat_id, flip), "qa:flip")],
        ui.confirm_row(chat_id, "qa:save", "qa:cancel", ok_key="quickadd.save"),
    ])


def _start_kb(chat_id: int) -> InlineKeyboardMarkup:
    return ui.ikb([
        [(t(chat_id, "quickadd.repeat"), "qa:repeat")],
        ui.nav(chat_id, menu=True),
    ])


def _lost_kb(chat_id: int) -> InlineKeyboardMarkup:
    """For a message the bot could not read as anything: a way on, never a dead end."""
    return ui.ikb([
        [(t(chat_id, "quickadd.repeat"), "qa:repeat"),
         (t(chat_id, "quickadd.help"), "sys:help")],
        ui.nav(chat_id, menu=True),
    ])


def _back_kb(chat_id: int) -> InlineKeyboardMarkup:
    return ui.ikb([ui.nav(chat_id, back="qa:back")])


async def show_draft(event: TelegramObject, state: FSMContext, *, error: str = "") -> None:
    """Put the current draft on screen, allocation block and all."""
    chat_id = common.chat_id_of(event)
    d = await state.get_data()
    alloc = _format_preview(chat_id, await _preview(chat_id, d, d["qa_amount"]))
    await _render(event, state, _card_text(chat_id, d, alloc=alloc, error=error),
                  _draft_kb(chat_id, d))


async def _expired(event: TelegramObject, state: FSMContext) -> None:
    """The draft is gone (the process restarted). Say so; never leave a live-looking card."""
    chat_id = common.chat_id_of(event)
    await state.clear()
    await common.show(event, t(chat_id, "quickadd.expired"), ui.ikb([
        [(t(chat_id, "quickadd.another"), "qa:new")],
        ui.nav(chat_id, menu=True),
    ]))


async def _open(cb: CallbackQuery, state: FSMContext) -> dict | None:
    """Gate the tap and hand back the draft. None means the screen is already answered."""
    if not await common.gate(cb):
        return None
    data = await state.get_data()
    if not _has_draft(data):
        chat_id = common.chat_id_of(cb)
        await common.ack(cb, t(chat_id, "quickadd.expiredToast"))
        await _expired(cb, state)
        return None
    await common.ack(cb)
    return data


# ── Allocation preview ──────────────────────────────────────────────────────

async def _preview(chat_id: int, d: dict, amount: float) -> dict | None:
    """What this draft does to its allocation bucket, or None when there is nothing to say.

    Skipped without a request for a plain income or expense: `bucketForSubType` returns null
    for those, so the answer is a guaranteed "not applicable" and the round trip would be
    pure latency on the one screen whose whole purpose is to appear instantly. Any failure is
    swallowed — this block is a nicety and must never be the reason an entry cannot be saved.
    """
    sub = d.get("qa_subType")
    if sub not in _BUCKET_SUBTYPES:
        return None
    body: dict = {"subType": sub, "amount": amount, "transactionDate": d["qa_date"]}
    if d.get("qa_investmentId") is not None:
        body["investmentId"] = d["qa_investmentId"]
    try:
        return await api.request(chat_id, "POST", "/overview/allocation-preview",
                                 params={"currency": CURRENCY}, json=body)
    except Exception:  # noqa: BLE001
        log.debug("allocation preview failed for chat %s", chat_id, exc_info=True)
        return None


def _bucket_label(chat_id: int, p: dict) -> str:
    key = _BUCKET_KEYS.get(str(p.get("bucket") or ""))
    if key:
        return t(chat_id, key)
    return esc(str(p.get("label") or ""))  # an enum we don't know yet, straight from the API


def _format_preview(chat_id: int, p: dict | None) -> str:
    """Rebuild the preview locally. The response's own `message` is never printed.

    `OverviewService` composes that sentence as English prose with an ungrouped BigDecimal in
    it ("Leaves 300000.00 still to put aside for Donation."), so it is both untranslated and
    unformatted. Every figure it quotes is in the payload beside it.
    """
    if not p or not p.get("applicable"):
        return ""
    label = _bucket_label(chat_id, p)
    header = t(chat_id, "quickadd.countsToward", label=label)
    if p.get("bucketNotRecommended"):
        return f"{header}\n{t(chat_id, 'quickadd.allocNotRequired')}"
    try:
        remaining = float(p.get("remainingAfter") or 0)
    except (TypeError, ValueError):
        remaining = 0.0
    tail = (t(chat_id, "quickadd.allocStillToGo", amount=fmt_money(remaining))
            if remaining > 0 else t(chat_id, "quickadd.allocCovered"))
    return (
        f"{header}\n"
        f"{t(chat_id, 'quickadd.allocTarget')}: {fmt_money(p.get('recommended'))}\n"
        f"{t(chat_id, 'quickadd.allocPaid')}: {fmt_money(p.get('paidBefore'))}\n"
        f"{t(chat_id, 'quickadd.allocAfter')}: <b>{fmt_money(p.get('paidAfter'))}</b>\n"
        f"<i>{tail}</i>"
    )


# ── /add ────────────────────────────────────────────────────────────────────
# Registered before every message handler in this module so that the bare-text catch-all at
# the bottom can never eat the command that opens this very screen.

@router.message(Command("add"))
async def add_cmd(message: Message, state: FSMContext, command: CommandObject) -> None:
    """`/add` opens the prompt; `/add 50000 lunch` skips it and goes straight to the draft."""
    chat_id = common.chat_id_of(message)
    if not await common.gate(message):
        return
    parsed = parse_entry(command.args)
    if parsed is None:
        await state.clear()
        await common.show(
            message,
            f"{t(chat_id, 'quickadd.startTitle')}\n\n{t(chat_id, 'quickadd.startBody')}",
            _start_kb(chat_id))
        return
    if not await common.stable_income_set(message):
        return
    await _new_draft(message, state, *parsed)


@router.callback_query(F.data == "qa:new")
async def new_cb(cb: CallbackQuery, state: FSMContext) -> None:
    chat_id = common.chat_id_of(cb)
    await common.ack(cb)
    if not await common.gate(cb):
        return
    # Cleared, not kept: the next thing typed has to reach the bare-text handler, and that
    # handler only fires when there is no state.
    await state.clear()
    await common.show(
        cb, f"{t(chat_id, 'quickadd.startTitle')}\n\n{t(chat_id, 'quickadd.startBody')}",
        _start_kb(chat_id))


# ── Repeat last ─────────────────────────────────────────────────────────────

@router.callback_query(F.data == "qa:repeat")
async def repeat_cb(cb: CallbackQuery, state: FSMContext) -> None:
    """Copy the newest transaction into a fresh draft, dated today.

    Nothing is written here — the copy lands on the same card as everything else, so a wrong
    guess costs a Cancel rather than a delete.
    """
    chat_id = common.chat_id_of(cb)
    await common.ack(cb)
    if not await common.gate(cb):
        return
    if not await common.stable_income_set(cb):
        return
    try:
        page = await api.request(chat_id, "GET", "/transactions", params={
            "currency": CURRENCY, "page": 0, "size": 1,
            "sortBy": "transactionDate", "sortDir": "desc"})
    except api.NeedsLogin:
        await state.clear()
        await common.show(cb, t(chat_id, "common.sessionExpired"), keyboards.login_kb(chat_id))
        return
    except api.Unreachable:
        await common.show(cb, t(chat_id, "common.serverUnreachable"), _start_kb(chat_id))
        return
    except api.ApiError as exc:
        await common.show(cb, f"❌ {esc(exc.message)}", _start_kb(chat_id))
        return
    except Exception:  # noqa: BLE001
        log.warning("repeat-last lookup failed for chat %s", chat_id, exc_info=True)
        await common.show(cb, t(chat_id, "quickadd.repeatError"), _start_kb(chat_id))
        return

    content = (page or {}).get("content") or []
    if not content:
        await common.show(cb, t(chat_id, "quickadd.repeatNone"), _start_kb(chat_id))
        return
    last = content[0]
    sub = last.get("subType")
    if last.get("transferPairId") is not None or sub in _REPEAT_TRANSFER:
        await common.show(cb, t(chat_id, "quickadd.repeatTransfer"), _start_kb(chat_id))
        return
    if sub == "EVERYDAY_SPENDING":
        await common.show(cb, t(chat_id, "quickadd.repeatPlug"), _start_kb(chat_id))
        return

    tx_type = "INCOME" if last.get("type") == "INCOME" else "EXPENSE"
    investment_id = last.get("investmentId")
    notes = ["quickadd.repeatNote"]
    if sub in _REPEAT_KEEP:
        kept, kept_investment = sub, None
    elif sub in _REPEAT_LINKED and investment_id is not None:
        # A top-up of a named holding: the backend adds funds to that record and creates
        # nothing, so the copy is the same operation rather than a new junk row.
        kept, kept_investment = sub, investment_id
    else:
        kept, kept_investment = None, None
        if sub not in (None, _regular(tx_type)):
            notes.append("quickadd.repeatKindReset")

    card = last.get("card") or {}
    category = last.get("category")
    try:
        amount = float(last.get("amount") or 0)
    except (TypeError, ValueError):
        amount = 0.0
    if amount <= 0:
        await common.show(cb, t(chat_id, "quickadd.repeatError"), _start_kb(chat_id))
        return
    await _new_draft(
        cb, state, tx_type, amount, (last.get("description") or "")[:DESC_LIMIT],
        card_id=card.get("id"), card_name=card.get("name"),
        category_id=(category or {}).get("id"),
        category_name=cat_name(chat_id, category) if category else None,
        sub_type=kept, investment_id=kept_investment, notes=tuple(notes))


# ── Draft navigation ────────────────────────────────────────────────────────

@router.callback_query(F.data == "qa:back")
async def back_cb(cb: CallbackQuery, state: FSMContext) -> None:
    d = await _open(cb, state)
    if d is None:
        return
    # Back always lands on the card, from any sub-screen — there is no chain to unwind.
    await state.set_state(QuickAdd.confirm)
    await show_draft(cb, state)


@router.callback_query(F.data == "qa:cancel")
async def cancel_cb(cb: CallbackQuery, state: FSMContext) -> None:
    """No gate: throwing away an unsaved draft must work even after the session has died."""
    chat_id = common.chat_id_of(cb)
    await common.ack(cb)
    await state.clear()
    await common.show(cb, t(chat_id, "common.cancelled"), ui.ikb([
        [(t(chat_id, "quickadd.another"), "qa:new")],
        ui.nav(chat_id, menu=True),
    ]))


@router.callback_query(F.data == "qa:flip")
async def flip_cb(cb: CallbackQuery, state: FSMContext) -> None:
    """Turn an expense into income or back — the one field a typed `+` most often gets wrong.

    The kind and the category go with it: an expense category is not offered for income, and
    a sub-type carried in from a repeat describes a direction that no longer applies.
    """
    d = await _open(cb, state)
    if d is None:
        return
    flipped = "EXPENSE" if d["qa_type"] == "INCOME" else "INCOME"
    await state.update_data(qa_type=flipped, qa_subType=None, qa_investmentId=None,
                            qa_categoryId=None, qa_categoryName=None, qa_roots=None)
    await show_draft(cb, state)


# ── Amount ──────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "qa:amount")
async def amount_cb(cb: CallbackQuery, state: FSMContext) -> None:
    d = await _open(cb, state)
    if d is None:
        return
    chat_id = common.chat_id_of(cb)
    await state.set_state(QuickAdd.amount)
    await _render(cb, state, t(chat_id, "quickadd.amountAsk", currency=CURRENCY),
                  _back_kb(chat_id))


@router.message(StateFilter(QuickAdd.amount))
async def amount_typed(message: Message, state: FSMContext) -> None:
    chat_id = common.chat_id_of(message)
    data = await state.get_data()
    if not _has_draft(data):
        await _expired(message, state)
        return
    amount = parse_amount(message.text)
    if amount is None:
        await common.show(message, t(chat_id, "quickadd.badAmount"), _back_kb(chat_id))
        return
    await state.update_data(qa_amount=amount)
    await state.set_state(QuickAdd.confirm)
    await show_draft(message, state)


# ── Description ─────────────────────────────────────────────────────────────

@router.callback_query(F.data == "qa:desc")
async def desc_cb(cb: CallbackQuery, state: FSMContext) -> None:
    d = await _open(cb, state)
    if d is None:
        return
    chat_id = common.chat_id_of(cb)
    await state.set_state(QuickAdd.desc)
    await _render(cb, state, t(chat_id, "quickadd.descAsk"), ui.ikb([
        [(t(chat_id, "quickadd.noDesc"), "qa:desc:clear")],
        ui.nav(chat_id, back="qa:back"),
    ]))


@router.callback_query(F.data == "qa:desc:clear")
async def desc_clear_cb(cb: CallbackQuery, state: FSMContext) -> None:
    d = await _open(cb, state)
    if d is None:
        return
    await state.update_data(qa_desc=None)
    await state.set_state(QuickAdd.confirm)
    await show_draft(cb, state)


@router.message(StateFilter(QuickAdd.desc))
async def desc_typed(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    if not _has_draft(data):
        await _expired(message, state)
        return
    text = (message.text or "").strip()[:DESC_LIMIT]
    await state.update_data(qa_desc=text or None)
    await state.set_state(QuickAdd.confirm)
    await show_draft(message, state)


# ── Date ────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "qa:date")
async def date_cb(cb: CallbackQuery, state: FSMContext) -> None:
    """A short list of recent days rather than a typed date.

    The days are counted in the owner's timezone, not the container's UTC — between midnight
    and 05:00 in Tashkent a UTC "today" is yesterday, and in the monthly-envelope model that
    files the money into the wrong day and, on the 1st, into a month that may already be
    closed and locked.
    """
    d = await _open(cb, state)
    if d is None:
        return
    chat_id = common.chat_id_of(cb)
    base = today()
    choices: list[tuple[str, str]] = []
    for offset in range(DATE_CHOICES):
        day = base - dt.timedelta(days=offset)
        iso = day.isoformat()
        if offset == 0:
            label = t(chat_id, "common.today")
        elif offset == 1:
            label = t(chat_id, "quickadd.yesterday")
        else:
            label = iso
        choices.append((label, f"qa:date:{iso}"))
    await _render(cb, state, t(chat_id, "quickadd.dateAsk"),
                  ui.ikb([*ui.grid(choices, 2), ui.nav(chat_id, back="qa:back")]))


@router.callback_query(F.data.startswith("qa:date:"))
async def date_pick_cb(cb: CallbackQuery, state: FSMContext) -> None:
    d = await _open(cb, state)
    if d is None:
        return
    iso = cb.data.split(":", 2)[2]
    try:
        dt.date.fromisoformat(iso)
    except ValueError:
        # Only our own buttons produce this callback, so a malformed one means a replayed or
        # forged update. Redraw rather than write a date nobody chose.
        await show_draft(cb, state)
        return
    await state.update_data(qa_date=iso)
    await show_draft(cb, state)


# ── Wallet ──────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "qa:src")
async def source_cb(cb: CallbackQuery, state: FSMContext) -> None:
    """Pick cash or a card.

    A failed card lookup shows the failure. Collapsing it into an empty list — which is what
    the guided flow did — leaves a keyboard that offers Cash and nothing else, identical to
    the screen a brand-new account sees, so the owner records a card payment as cash and both
    wallets are wrong at month-close.
    """
    d = await _open(cb, state)
    if d is None:
        return
    chat_id = common.chat_id_of(cb)
    try:
        cards = await api.request(chat_id, "GET", "/cards") or []
    except api.NeedsLogin:
        await state.clear()
        await common.show(cb, t(chat_id, "common.sessionExpired"), keyboards.login_kb(chat_id))
        return
    except Exception:  # noqa: BLE001
        log.warning("card list failed for chat %s", chat_id, exc_info=True)
        await _render(cb, state, t(chat_id, "quickadd.walletError"), ui.ikb([
            [(t(chat_id, "common.retry"), "qa:src")],
            ui.nav(chat_id, back="qa:back"),
        ]))
        return
    cards = [c for c in cards if c.get("currency") == CURRENCY and c.get("type") != "CASH"]
    # Kept so that picking one costs no second request: 64 bytes of callback data has room
    # for an id and nothing else, and the name is what the confirmation has to show.
    await state.update_data(qa_cards=cards)
    rows: list[list[tuple[str, str]]] = [[(t(chat_id, "common.cashBtn"), "qa:src:cash")]]
    short = False
    for card in cards:
        # A card that cannot cover this expense is marked rather than hidden: the backend
        # refuses the write outright, and finding that out on the Save tap wastes the entry.
        warn = _card_is_short(card, d)
        short = short or warn
        name = str(card.get("name") or "Card")
        tail = str(card.get("lastFourDigits") or "")
        label = f"{'⚠️ ' if warn else ''}💳 {name}{f' ···{tail}' if tail else ''}"
        rows.append([(label[:48], f"qa:src:{card['id']}")])
    rows.append(ui.nav(chat_id, back="qa:back"))
    ask = "quickadd.walletAskIn" if d["qa_type"] == "INCOME" else "quickadd.walletAskOut"
    text = t(chat_id, ask)
    if short:
        text += f"\n\n{t(chat_id, 'quickadd.cardShort', amount=fmt_money(d['qa_amount']))}"
    await _render(cb, state, text, ui.ikb(rows))


def _card_is_short(card: dict, d: dict) -> bool:
    """True when this card's balance cannot cover the draft. False whenever we can't tell."""
    if d["qa_type"] != "EXPENSE":
        return False
    try:
        return float(card.get("currentBalance")) < float(d["qa_amount"])
    except (TypeError, ValueError):
        return False


@router.callback_query(F.data.startswith("qa:src:"))
async def source_pick_cb(cb: CallbackQuery, state: FSMContext) -> None:
    d = await _open(cb, state)
    if d is None:
        return
    chat_id = common.chat_id_of(cb)
    choice = cb.data.split(":", 2)[2]
    if choice == "cash":
        await state.update_data(qa_cardId=None, qa_cardName=None)
        await show_draft(cb, state)
        return
    try:
        card_id = int(choice)
    except ValueError:
        await show_draft(cb, state)
        return
    name = next((c.get("name") for c in (d.get("qa_cards") or [])
                 if c.get("id") == card_id), None)
    if name is None:
        # The list this button was drawn from is gone (a replayed tap after a restart), and
        # the card line has to name the card rather than fall back to "Cash".
        try:
            name = (await api.request(chat_id, "GET", f"/cards/{card_id}") or {}).get("name")
        except Exception:  # noqa: BLE001
            log.debug("card %s lookup failed", card_id, exc_info=True)
    await state.update_data(qa_cardId=card_id, qa_cardName=name)
    await show_draft(cb, state)


# ── Category ────────────────────────────────────────────────────────────────

def _roots_kb(chat_id: int, roots: list[dict]) -> InlineKeyboardMarkup:
    items = [(cat_name(chat_id, r)[:32],
              f"qa:catopen:{r['id']}" if r.get("children") else f"qa:cat:{r['id']}")
             for r in roots]
    return ui.ikb([
        *ui.grid(items, 2),
        [(t(chat_id, "quickadd.noCategory"), "qa:cat:none")],
        ui.nav(chat_id, back="qa:back"),
    ])


@router.callback_query(F.data == "qa:cat")
async def category_cb(cb: CallbackQuery, state: FSMContext) -> None:
    d = await _open(cb, state)
    if d is None:
        return
    chat_id = common.chat_id_of(cb)
    try:
        roots = await api.request(chat_id, "GET", "/categories", params={
            "type": d["qa_type"],
            "subType": d.get("qa_subType") or _regular(d["qa_type"]),
        }) or []
    except api.NeedsLogin:
        await state.clear()
        await common.show(cb, t(chat_id, "common.sessionExpired"), keyboards.login_kb(chat_id))
        return
    except Exception:  # noqa: BLE001
        log.warning("category list failed for chat %s", chat_id, exc_info=True)
        await _render(cb, state, t(chat_id, "quickadd.categoryError"), ui.ikb([
            [(t(chat_id, "common.retry"), "qa:cat")],
            ui.nav(chat_id, back="qa:back"),
        ]))
        return
    await state.update_data(qa_roots=roots)
    if not roots:
        await _render(cb, state, t(chat_id, "quickadd.categoryNone"), ui.ikb([
            [(t(chat_id, "quickadd.noCategory"), "qa:cat:none")],
            ui.nav(chat_id, back="qa:back"),
        ]))
        return
    await _render(cb, state, t(chat_id, "quickadd.categoryAsk"), _roots_kb(chat_id, roots))


@router.callback_query(F.data.startswith("qa:catopen:"))
async def category_open_cb(cb: CallbackQuery, state: FSMContext) -> None:
    """Open one root's children, with the root itself still choosable at the top."""
    d = await _open(cb, state)
    if d is None:
        return
    chat_id = common.chat_id_of(cb)
    try:
        root_id = int(cb.data.split(":", 2)[2])
    except ValueError:
        await show_draft(cb, state)
        return
    root = next((r for r in (d.get("qa_roots") or []) if r.get("id") == root_id), None)
    if root is None:
        await category_cb(cb, state)  # the cache is gone with the process; refetch and redraw
        return
    items = [(t(chat_id, "quickadd.useCategory", name=cat_name(chat_id, root))[:40],
              f"qa:cat:{root_id}")]
    items += [(cat_name(chat_id, child)[:32], f"qa:cat:{child['id']}")
              for child in root.get("children") or []]
    await _render(cb, state, t(chat_id, "quickadd.subCategoryAsk"), ui.ikb([
        *ui.grid(items, 2),
        ui.nav(chat_id, back="qa:cat"),
    ]))


@router.callback_query(F.data.startswith("qa:cat:"))
async def category_pick_cb(cb: CallbackQuery, state: FSMContext) -> None:
    d = await _open(cb, state)
    if d is None:
        return
    chat_id = common.chat_id_of(cb)
    choice = cb.data.split(":", 2)[2]
    if choice == "none":
        await state.update_data(qa_categoryId=None, qa_categoryName=None)
        await show_draft(cb, state)
        return
    try:
        category_id = int(choice)
    except ValueError:
        await show_draft(cb, state)
        return
    name = None
    for root in d.get("qa_roots") or []:
        if root.get("id") == category_id:
            name = cat_name(chat_id, root)
            break
        for child in root.get("children") or []:
            if child.get("id") == category_id:
                name = f"{cat_name(chat_id, root)} → {cat_name(chat_id, child)}"
                break
        if name:
            break
    await state.update_data(qa_categoryId=category_id, qa_categoryName=name)
    await show_draft(cb, state)


# ── Save ────────────────────────────────────────────────────────────────────

def _payload(d: dict) -> dict:
    sub = d.get("qa_subType") or _regular(d["qa_type"])
    card_id = d.get("qa_cardId")
    payload: dict = {
        "type": d["qa_type"],
        "amount": d["qa_amount"],
        "currency": CURRENCY,
        "transactionDate": d["qa_date"],
        "subType": sub,
        # No card means the whole amount is physical cash; that is what lets the cash-balance
        # query attribute it. With a card, 0 marks it as a pure card payment.
        "cashAmount": d["qa_amount"] if card_id is None else 0,
    }
    if card_id is not None:
        payload["cardId"] = card_id
    if d.get("qa_categoryId") is not None:
        payload["categoryId"] = d["qa_categoryId"]
    if d.get("qa_desc"):
        payload["description"] = d["qa_desc"]
    if d.get("qa_investmentId") is not None:
        payload["investmentId"] = d["qa_investmentId"]
    return payload


@router.callback_query(F.data == "qa:save")
async def save_cb(cb: CallbackQuery, state: FSMContext) -> None:
    """Write the draft. A rejection keeps the draft; only a success clears it."""
    d = await _open(cb, state)
    if d is None:
        return
    chat_id = common.chat_id_of(cb)
    payload = _payload(d)
    # Before the request, not after: the screen becomes "Saving…" with no keyboard, so an
    # impatient second tap has no button to hit. The backend books a duplicate transaction
    # quite happily, and this is the only thing standing in the way of one.
    await common.begin_write(cb, chat_id)
    try:
        await api.request(chat_id, "POST", "/transactions", json=payload)
    except api.NeedsLogin:
        await state.clear()
        await common.show(cb, t(chat_id, "common.sessionExpired"), keyboards.login_kb(chat_id))
        return
    except api.Unreachable:
        await show_draft(cb, state, error=t(chat_id, "common.serverUnreachable"))
        return
    except api.ApiError as exc:
        # A closed month, an over-drawn card, a category that has since been deleted: the
        # backend's sentence names the problem, and the draft is redrawn under it so the fix
        # is one tap away instead of a whole re-entry.
        await show_draft(cb, state, error=f"❌ {esc(exc.message)}")
        return
    except Exception:  # noqa: BLE001
        log.warning("quick-add save failed for chat %s", chat_id, exc_info=True)
        await show_draft(cb, state, error=t(chat_id, "common.serverUnreachable"))
        return

    _remember_source(chat_id, d.get("qa_cardId"), d.get("qa_cardName"))
    saved_key = ("quickadd.saved.income" if d["qa_type"] == "INCOME"
                 else "quickadd.saved.expense")
    lines = [t(chat_id, saved_key, amount=fmt_money(d["qa_amount"]))]
    if d.get("qa_desc"):
        lines.append(esc(d["qa_desc"]))
    # Asked with amount 0, so the figures describe the bucket AFTER this write rather than
    # forecasting it again.
    after = await _preview(chat_id, d, 0)
    if after and after.get("applicable") and not after.get("bucketNotRecommended"):
        try:
            remaining = float(after.get("remainingAfter") or 0)
        except (TypeError, ValueError):
            remaining = 0.0
        lines += ["", t(chat_id, "quickadd.savedProgress",
                        label=_bucket_label(chat_id, after),
                        paid=fmt_money(after.get("paidBefore")),
                        target=fmt_money(after.get("recommended"))),
                  (t(chat_id, "quickadd.allocStillToGo", amount=fmt_money(remaining))
                   if remaining > 0 else t(chat_id, "quickadd.allocCovered"))]
    await state.clear()
    await common.show(cb, "\n".join(lines), ui.ikb([
        [(t(chat_id, "quickadd.another"), "qa:new")],
        ui.nav(chat_id, menu=True),
    ]))


# ── Typed input while the card is on screen ─────────────────────────────────

@router.message(StateFilter(QuickAdd.confirm))
async def draft_typed(message: Message, state: FSMContext) -> None:
    """Another message while a draft is open corrects it instead of vanishing.

    Typing a number changes the amount (and the description, when one follows it); typing
    anything else becomes the description. That covers both of the corrections a person
    actually makes after seeing the card, without asking them to find a button first — and it
    means no typed message anywhere in this flow is answered with silence.
    """
    chat_id = common.chat_id_of(message)
    data = await state.get_data()
    if not _has_draft(data):
        await _expired(message, state)
        return
    text = (message.text or "").strip()
    if not text or text.startswith("/"):
        # An unknown command. Answering it as a description would file "/stats" as the name
        # of an expense, which is worse than saying plainly that it was not understood.
        await common.show(message, t(chat_id, "quickadd.notUnderstood"), _lost_kb(chat_id))
        return
    parsed = parse_entry(text)
    if parsed is None:
        await state.update_data(qa_desc=text[:DESC_LIMIT])
        await show_draft(message, state)
        return
    tx_type, amount, desc = parsed
    updates = {"qa_amount": amount}
    if text[0] in "+-":
        # An explicit sign is a statement about direction, so it re-decides it; a bare number
        # only changes the figure.
        updates["qa_type"] = tx_type
    if desc:
        updates["qa_desc"] = desc
    await state.update_data(**updates)
    await show_draft(message, state)


# ── The bare-text catch-all — LAST handler of the LAST router ───────────────

@router.message(StateFilter(None))
async def bare_message(message: Message, state: FSMContext) -> None:
    """Anything typed with no flow in progress.

    Two outcomes and no third: text that begins with an amount becomes a draft, and
    everything else gets told so, with buttons. Before this handler existed, an out-of-state
    message matched nothing and aiogram dropped the update — the owner's message sat in the
    chat unanswered, which reads as a broken bot rather than as a misunderstanding.

    The `StateFilter(None)` is what makes it safe to register a bare handler at all: every
    flow in the bot holds a state while it is running, so this can never swallow an amount
    meant for the guided add, a wallet balance meant for the month close, or a password.
    """
    chat_id = common.chat_id_of(message)
    if not await common.gate(message):
        return
    parsed = parse_entry(message.text)
    if parsed is None:
        await common.show(message, t(chat_id, "quickadd.notUnderstood"), _lost_kb(chat_id))
        return
    if not await common.stable_income_set(message):
        return
    await _new_draft(message, state, *parsed)
