"""Wallets — the bank cards, the one cash pot, and everything the owner can do to them.

Four decisions shape this file.

**The screen is Wallets.** The web app calls cards-plus-cash "Wallets / Hamyonlar", and it is
the same section, for the same person, over the same two endpoints. The bot used to call it
Cards and hide the cash behind a second screen, so the two clients disagreed about the name of
a thing the owner switches between on one phone. `cards.*` remains the key prefix and the
callback namespace because that is what the endpoint is called; the words on screen follow the
web app.

**A card can be edited, and that is not a nicety.** `CardService.delete` runs
`TransactionRepository.detachFromCard`, which sets `card = NULL` on every transaction that ever
used it. Until now, fixing a mistyped bank name or a wrong starting balance meant deleting the
card and adding it again — which silently cut every past expense loose from the card it was
paid with, and quietly moved money on the Wallets screen. `PUT /cards/{id}` has existed all
along; nothing called it.

**A one-field edit still sends the whole card.** `CardRequest` is validated as a complete
object (`name`, `bankName`, `type`, `lastFourDigits`, `initialBalance` and `currency` are all
@NotNull), so an edit reads the card back and re-sends every field with one value replaced.
`color` is echoed for the same reason — a null one would be overwritten with the server's
default indigo. (The card-number / PIN vault those two fields belonged to was removed on
2026-09-22; a card is a name, its last four digits and a balance now.)

**Cash is one pot, not a list.** `GET /cash-balances` returns an array because the table is
keyed by currency, but the product has been UZS-only since the currency pivot and
`CashBalanceService.upsert` keeps exactly one row per currency — so the old "cash balances"
screen could only ever render a list of one, with the currency printed next to it. It is now
the cash pot: what is in hand, what it started from, and one button to set it.

**The cash prompt asks what is in hand; the endpoint stores the opening figure.** Those are
two different numbers, and the gap between them is every cash transaction ever recorded.
`CashBalanceResponse.currentBalance` is `initialBalance + CashBalanceRepository
.sumCashlessTransactions(currency)`, and `POST /cash-balances` writes `initialBalance` alone.
Sending the answer to "how much do you hold right now?" straight into that field is therefore
wrong by the whole transaction net — the balance the bot then printed back was not the number
the owner had just typed. The pot reports BOTH readings, so the net is their difference and the
opening figure that yields a wanted balance is `held - net`; `_save_cash` computes it, and the
screen names all three figures so the two readings cannot be confused for one. The one case the
subtraction cannot see in advance is the first run, where no pot row exists yet but cardless
transactions may: the POST's own response carries both figures, so a single correction settles
it. Card balances need none of this — `cards.new.initialBalance` says "Starting balance",
which is exactly the field `CardRequest.initialBalance` is.

Callback namespaces owned here: `cards:*`, `card:*`, `cardf:*`, `cardt:*`, `cash:*`.
"""
import logging
import re

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from . import wizard
from .. import api, common, keyboards, ui
from ..config import CURRENCY
from ..i18n import t
from ..keyboards import esc, ikb
from ..money import fmt_money, parse_number
from ..states import CardEdit

router = Router()

log = logging.getLogger(__name__)

# The create wizard's spec. `auto_currency` is what satisfies CardRequest.currency, which is
# @NotNull even though UZS is the only value the service accepts.
CARD_SPEC = {
    "title": "cards.new.title", "endpoint": "/cards", "back": "cards:list", "success": "cards.new.success",
    "auto_currency": True, "fields": [
        {"key": "name", "label": "cards.new.name", "kind": "text", "required": True},
        {"key": "bankName", "label": "cards.new.bankName", "kind": "text", "required": True},
        # Card network brand names — proper nouns, identical in every language, so they're
        # passed straight through as literal text (t() returns an unknown key as-is).
        {"key": "type", "label": "cards.new.type", "kind": "choice", "required": True,
         "choices": [("UZCARD", "UzCard"), ("HUMO", "Humo"), ("VISA", "Visa")]},
        {"key": "lastFourDigits", "label": "cards.new.last4", "kind": "text", "required": True,
         "regex": r"^\d{4}$", "regex_msg": "cards.new.last4Msg"},
        {"key": "initialBalance", "label": "cards.new.initialBalance", "kind": "number", "required": True},
    ],
}

# The editable fields, in the order the create wizard asks for them, paired with the label the
# wizard already uses. One vocabulary for both screens: whatever the owner was asked for when
# they added the card is what the edit screen calls it.
_EDIT_FIELDS = (
    ("name", "cards.new.name"),
    ("bankName", "cards.new.bankName"),
    ("type", "cards.new.type"),
    ("lastFourDigits", "cards.new.last4"),
    ("initialBalance", "cards.new.initialBalance"),
)
_FIELD_LABEL = dict(_EDIT_FIELDS)

# The networks the form offers. `CardType` also has CASH, but that is the legacy spelling of
# the cash pot from before cash became a row of its own, and neither client offers it.
_NETWORKS = (("UZCARD", "UzCard"), ("HUMO", "Humo"), ("VISA", "Visa"))
_NETWORK_LABEL = dict(_NETWORKS)

_LAST4 = re.compile(r"\d{4}")


def _num(value) -> float:
    """A BigDecimal off the wire as a float — 0.0 for anything unreadable.

    Only ever used to add balances up for the "everything you hold" line, where a missing
    figure must not take the whole total down with it.
    """
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _cash_delta(pot: dict | None) -> float:
    """What the recorded cash transactions have added to, or taken from, the pot.

    `CashBalanceResponse` carries both readings — `initialBalance` as stored and
    `currentBalance` as `initialBalance + sumCashlessTransactions(currency)` — so their
    difference IS that sum. It is the number that turns "what I hold now" into the opening
    figure the endpoint actually takes. No pot yet means nothing is known about the net, and
    0.0 is the only answer available; `_save_cash` corrects for that from the write's reply.
    """
    if not isinstance(pot, dict):
        return 0.0
    return round(_num(pot.get("currentBalance")) - _num(pot.get("initialBalance")), 4)


def _signed(amount: float) -> str:
    """A delta, where the sign is the whole point: "+50 000 UZS" / "-50 000 UZS"."""
    text = fmt_money(abs(amount))
    if amount > 0:
        return f"+{text}"
    if amount < 0:
        return f"-{text}"
    return text


def _network_label(chat_id: int, value) -> str:
    """UZCARD → "UzCard". Brand names, so this is a spelling table, not a translation."""
    if value == "CASH":
        return t(chat_id, "common.cash")
    label = _NETWORK_LABEL.get(value)
    # The fallback goes into message text, so an unknown enum the backend starts sending is
    # escaped rather than trusted.
    return label if label else esc(value or "—")


def _id_at(data: str | None, index: int) -> int | None:
    """The integer at position `index` of a colon-split callback, or None.

    Callback data is the one string in this file that comes from outside it — a button
    scrolled up in the chat, or an update Telegram replayed after a restart — so every id is
    parsed rather than assumed.
    """
    parts = (data or "").split(":")
    if len(parts) <= index:
        return None
    try:
        return int(parts[index])
    except ValueError:
        return None


def _wallets_kb(chat_id: int) -> InlineKeyboardMarkup:
    return ikb([[(t(chat_id, "cards.backToWallets"), "cards:list")]])


# ── the Wallets list ─────────────────────────────────────────────────────────
async def show_menu(cb: CallbackQuery) -> None:
    """Entry point for `menu:cards` — the main menu imports this by name."""
    await _render_wallets(cb)


@router.callback_query(F.data == "cards:list")
async def wallets_list(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    # The section root doubles as the escape hatch from a half-finished edit, so it abandons
    # whatever was in progress rather than leaving a state that would swallow the next
    # message the owner types.
    await state.clear()
    if not await common.gate(cb):
        return
    await _render_wallets(cb)


async def _cash_pot(chat_id: int) -> tuple[dict | None, bool]:
    """The one cash row, and whether we actually managed to ask for it.

    The caller has to tell "you hold no cash" from "the server did not answer", because the
    first is a number that belongs in the total and the second must not be silently counted
    as zero. `NeedsLogin` is re-raised: that is the caller's screen to render.
    """
    try:
        rows = await api.request(chat_id, "GET", "/cash-balances") or []
    except api.NeedsLogin:
        raise
    except Exception:  # noqa: BLE001
        log.debug("cash balance unavailable for chat %s", chat_id, exc_info=True)
        return None, False
    for row in rows:
        if row.get("currency") == CURRENCY:
            return row, True
    # A row left behind by the multi-currency era, or none at all. Either way there is one
    # pot as far as this screen is concerned.
    return (rows[0] if rows else None), True


async def _render_wallets(event, prefix: str = "") -> None:
    chat_id = common.chat_id_of(event)
    try:
        cards = await api.request(chat_id, "GET", "/cards") or []
        pot, cash_known = await _cash_pot(chat_id)
    except api.NeedsLogin:
        await common.show(event, t(chat_id, "common.sessionExpired"), keyboards.login_kb(chat_id))
        return
    except api.Unreachable:
        await common.show(event, t(chat_id, "common.serverUnreachable"),
                          keyboards.back_menu_kb(chat_id))
        return
    except Exception:  # noqa: BLE001
        log.exception("wallets list failed for chat %s", chat_id)
        await common.show(event, t(chat_id, "cards.loadError"), keyboards.back_menu_kb(chat_id))
        return

    # A CASH-typed card is the legacy spelling of the pot; it would otherwise be listed twice.
    cards = [c for c in cards if c.get("type") != "CASH" and c.get("id") is not None]

    lines = [prefix, ""] if prefix else []
    lines += [t(chat_id, "cards.title"), ""]
    if not cards:
        lines.append(t(chat_id, "cards.noneYet"))
    for c in cards:
        lines.append("• " + t(
            chat_id, "cards.line",
            name=esc(c.get("name") or "—"), bank=esc(c.get("bankName") or "—"),
            type=_network_label(chat_id, c.get("type")),
            last4=esc(c.get("lastFourDigits") or "····"),
            balance=fmt_money(c.get("currentBalance"))))

    if not cash_known:
        lines.append(t(chat_id, "cards.cashRowUnavailable"))
    elif pot is None:
        lines.append(t(chat_id, "cards.cashRowUnset"))
    else:
        lines.append(t(chat_id, "cards.cashRow", balance=fmt_money(pot.get("currentBalance"))))

    if cash_known and (cards or pot is not None):
        cards_total = sum(_num(c.get("currentBalance")) for c in cards)
        cash_total = _num(pot.get("currentBalance")) if pot else 0.0
        lines += [
            "",
            t(chat_id, "cards.totalHeld", total=fmt_money(cards_total + cash_total)),
            t(chat_id, "cards.totalSplit", cards=fmt_money(cards_total), cash=fmt_money(cash_total)),
        ]

    # Two per row: a Telegram keyboard scrolls with the message, so a one-per-row list of
    # cards pushes Add and Cash off the bottom of the screen they belong to.
    rows = ui.grid([(f"💳 {str(c.get('name') or '—')[:22]}", f"card:view:{c['id']}") for c in cards], 2)
    rows.append([(t(chat_id, "cards.addCard"), "cards:add"),
                 (t(chat_id, "common.cashBtn"), "cards:cash")])
    rows.append(ui.nav(chat_id, menu=True))
    await common.show(event, "\n".join(lines), ikb(rows))


# ── one card ─────────────────────────────────────────────────────────────────
def _card_screen(chat_id: int, card: dict) -> tuple[str, InlineKeyboardMarkup]:
    """The card's own screen, built from a CardResponse — a GET's or a PUT's, identically."""
    cid = card.get("id")
    text = "\n".join([
        t(chat_id, "cards.viewHeader",
          name=esc(card.get("name") or "—"), bank=esc(card.get("bankName") or "—"),
          type=_network_label(chat_id, card.get("type")),
          last4=esc(card.get("lastFourDigits") or "····")),
        "",
        t(chat_id, "cards.initial", amount=fmt_money(card.get("initialBalance"))),
        t(chat_id, "cards.current", amount=fmt_money(card.get("currentBalance"))),
    ])
    kb = ikb([
        [(t(chat_id, "common.edit"), f"card:edit:{cid}"),
         (t(chat_id, "common.delete"), f"card:del:{cid}")],
        ui.nav(chat_id, back="cards:list", menu=True),
    ])
    return text, kb


async def _load_card(event, chat_id: int, cid: int) -> dict | None:
    """One card, or None with the failure already on screen."""
    try:
        card = await api.request(chat_id, "GET", f"/cards/{cid}")
    except api.NeedsLogin:
        await common.show(event, t(chat_id, "common.sessionExpired"), keyboards.login_kb(chat_id))
        return None
    except api.Unreachable:
        await common.show(event, t(chat_id, "common.serverUnreachable"), _wallets_kb(chat_id))
        return None
    except api.ApiError as exc:
        # 404 is the ordinary case here, not an error: a card deleted from the web app, or a
        # button tapped from a message older than the card itself.
        if exc.status == 404:
            await common.show(event, t(chat_id, "cards.gone"), _wallets_kb(chat_id))
        else:
            await common.show(event, f"❌ {esc(exc.message)}", _wallets_kb(chat_id))
        return None
    except Exception:  # noqa: BLE001
        log.exception("GET /cards/%s failed for chat %s", cid, chat_id)
        await common.show(event, t(chat_id, "cards.viewLoadError"), _wallets_kb(chat_id))
        return None
    if not isinstance(card, dict):
        await common.show(event, t(chat_id, "cards.gone"), _wallets_kb(chat_id))
        return None
    return card


@router.callback_query(F.data.startswith("card:view:"))
async def card_view(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    if not await common.gate(cb):
        return
    chat_id = common.chat_id_of(cb)
    cid = _id_at(cb.data, 2)
    if cid is None:
        await common.show(cb, t(chat_id, "cards.gone"), _wallets_kb(chat_id))
        return
    # Arriving at a card's own screen ends any edit that was open on another one.
    await state.clear()
    card = await _load_card(cb, chat_id, cid)
    if card is None:
        return
    text, kb = _card_screen(chat_id, card)
    await common.show(cb, text, kb)


# ── editing a card ───────────────────────────────────────────────────────────
def _card_payload(card: dict) -> dict:
    """Every field `PUT /cards/{id}` needs, read back off the card being edited.

    See the module docstring: CardRequest is a whole-object write, so a one-field edit has to
    re-send the other five.
    """
    return {
        "name": card.get("name"),
        "bankName": card.get("bankName"),
        "type": card.get("type"),
        "lastFourDigits": card.get("lastFourDigits"),
        "initialBalance": card.get("initialBalance"),
        "currency": CURRENCY,
        "color": card.get("color"),
    }


@router.callback_query(F.data.startswith("card:edit:"))
async def card_edit_menu(cb: CallbackQuery, state: FSMContext) -> None:
    """Which part is wrong? — the field chooser."""
    await common.ack(cb)
    if not await common.gate(cb):
        return
    chat_id = common.chat_id_of(cb)
    cid = _id_at(cb.data, 2)
    if cid is None:
        await common.show(cb, t(chat_id, "cards.gone"), _wallets_kb(chat_id))
        return
    card = await _load_card(cb, chat_id, cid)
    if card is None:
        return
    # Stash the card so the prompt after this one does not have to fetch it again. The
    # prompt re-fetches anyway if the stash is for a different card or has been lost to a
    # restart, so this is an optimisation and never a source of truth.
    await state.clear()
    await state.set_state(CardEdit.field)
    await state.update_data(cd_id=cid, cd_card=card)
    rows = ui.grid([(t(chat_id, key), f"cardf:{cid}:{field}") for field, key in _EDIT_FIELDS], 2)
    rows.append(ui.nav(chat_id, back=f"card:view:{cid}", menu=True))
    await common.show(cb, t(chat_id, "cards.editTitle"), ikb(rows))


@router.callback_query(F.data.startswith("cardf:"))
async def card_field_prompt(cb: CallbackQuery, state: FSMContext) -> None:
    """Ask for one field's new value. `cardf:<id>:<field>`."""
    await common.ack(cb)
    if not await common.gate(cb):
        return
    chat_id = common.chat_id_of(cb)
    parts = (cb.data or "").split(":")
    cid = _id_at(cb.data, 1)
    field = parts[2] if len(parts) > 2 else ""
    if cid is None or field not in _FIELD_LABEL:
        await common.show(cb, t(chat_id, "cards.expired"), _wallets_kb(chat_id))
        return

    data = await state.get_data()
    card = data.get("cd_card")
    if not isinstance(card, dict) or card.get("id") != cid:
        card = await _load_card(cb, chat_id, cid)
        if card is None:
            return

    label = t(chat_id, _FIELD_LABEL[field])
    back = ui.nav(chat_id, back=f"card:edit:{cid}", cancel=f"card:view:{cid}")
    if field == "type":
        # A closed set of three brands: buttons, not typing. Stateless on purpose — the pick
        # carries the card id and the value, so it still works after a restart.
        await state.set_state(CardEdit.field)
        await state.update_data(cd_id=cid, cd_card=card)
        rows = ui.grid([(name, f"cardt:{cid}:{value}") for value, name in _NETWORKS], 3)
        rows.append(back)
        await common.show(cb, t(chat_id, "cards.editPickType", field=label,
                                current=_network_label(chat_id, card.get("type"))), ikb(rows))
        return

    current = (fmt_money(card.get(field)) if field == "initialBalance"
               else esc(card.get(field) or "—"))
    await state.set_state(CardEdit.value)
    await state.update_data(cd_kind="card", cd_id=cid, cd_field=field, cd_card=card)
    if field == "initialBalance":
        # The one card field a hurried reader could take for "the balance now". Unlike cash,
        # the label is honest — `CardRequest.initialBalance` IS the starting balance — so the
        # fix is to print the other reading beside it rather than to convert the answer.
        text = t(chat_id, "cards.editBalancePrompt", field=label, current=current,
                 balance=fmt_money(card.get("currentBalance")))
    else:
        text = t(chat_id, "cards.editPrompt", field=label, current=current)
    await common.show(cb, text, ikb([back]))


@router.callback_query(F.data.startswith("cardt:"))
async def card_network_pick(cb: CallbackQuery, state: FSMContext) -> None:
    """`cardt:<id>:<NETWORK>` — the one field that is picked rather than typed."""
    await common.ack(cb)
    if not await common.gate(cb):
        return
    chat_id = common.chat_id_of(cb)
    parts = (cb.data or "").split(":")
    cid = _id_at(cb.data, 1)
    value = parts[2] if len(parts) > 2 else ""
    if cid is None or value not in _NETWORK_LABEL:
        await common.show(cb, t(chat_id, "cards.expired"), _wallets_kb(chat_id))
        return
    card = await _load_card(cb, chat_id, cid)
    if card is None:
        return
    await _save_card(cb, state, chat_id, cid, card, "type", value)


async def _save_card(event, state: FSMContext, chat_id: int, cid: int,
                     card: dict, field: str, value) -> None:
    """PUT the card with one field replaced, then show the card as it now stands."""
    payload = _card_payload(card)
    payload[field] = value
    await common.begin_write(event, chat_id)
    try:
        updated = await api.request(chat_id, "PUT", f"/cards/{cid}", json=payload)
    except api.NeedsLogin:
        await state.clear()
        await common.show(event, t(chat_id, "common.sessionExpired"), keyboards.login_kb(chat_id))
        return
    except api.Unreachable:
        await common.show(event, t(chat_id, "common.serverUnreachable"), _wallets_kb(chat_id))
        return
    except api.ApiError as exc:
        if exc.status == 404:
            await state.clear()
            await common.show(event, t(chat_id, "cards.gone"), _wallets_kb(chat_id))
            return
        # A validation message names its own field ("lastFourDigits: Must be exactly 4
        # digits"), which is more use than a generic failure — but the keyboard is gone by
        # now, so the way back has to come with it.
        await common.show(event, f"❌ {esc(exc.message)}",
                          ikb([[(t(chat_id, "common.back"), f"card:edit:{cid}")]]))
        return
    except Exception:  # noqa: BLE001
        log.exception("PUT /cards/%s failed for chat %s", cid, chat_id)
        await common.show(event, t(chat_id, "cards.saveError"),
                          ikb([[(t(chat_id, "common.back"), f"card:edit:{cid}")]]))
        return
    await state.clear()
    saved = t(chat_id, "cards.saved")
    if isinstance(updated, dict) and updated.get("id") is not None:
        text, kb = _card_screen(chat_id, updated)
        await common.show(event, f"{saved}\n\n{text}", kb)
    else:
        await common.show(event, saved, _wallets_kb(chat_id))


@router.message(StateFilter(CardEdit.value))
async def value_typed(message: Message, state: FSMContext) -> None:
    """The one typed step in this file — a card field, or the cash amount.

    Both flows land here because both are "send me one value"; `cd_kind` says which, and the
    validation is the only thing that differs. A failed validation stays in the state: the
    owner is one keystroke from a valid answer, and dropping them back to the card would mean
    re-opening two screens to try again.
    """
    chat_id = message.chat.id
    data = await state.get_data()
    raw = (message.text or "").strip()

    if data.get("cd_kind") == "cash":
        amount = parse_number(raw)
        if amount is None:
            await message.answer(t(chat_id, "common.sendNumberExample"))
            return
        if not await common.gate(message):
            await state.clear()
            return
        await _save_cash(message, state, chat_id, amount)
        return

    cid, field = data.get("cd_id"), data.get("cd_field")
    card = data.get("cd_card")
    if not isinstance(cid, int) or field not in _FIELD_LABEL or not isinstance(card, dict):
        # Only reachable if the bag was emptied under us; the state itself cannot survive a
        # restart. Saying so beats writing a card with half a payload.
        await state.clear()
        await message.answer(t(chat_id, "cards.expired"), reply_markup=_wallets_kb(chat_id))
        return

    if field == "lastFourDigits":
        if not _LAST4.fullmatch(raw):
            await message.answer(t(chat_id, "cards.new.last4Msg"))
            return
        value = raw
    elif field == "initialBalance":
        # parse_number, not parse_amount: a card can legitimately start at zero, and a credit
        # card can start below it.
        value = parse_number(raw)
        if value is None:
            await message.answer(t(chat_id, "common.sendNumberExample"))
            return
    else:
        if not raw:
            await message.answer(t(chat_id, "cards.emptyValue"))
            return
        value = raw

    if not await common.gate(message):
        await state.clear()
        return
    await _save_card(message, state, chat_id, cid, card, field, value)


# ── deleting a card ──────────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("card:del:"))
async def card_del_confirm(cb: CallbackQuery) -> None:
    await common.ack(cb)
    if not await common.gate(cb):
        return
    chat_id = common.chat_id_of(cb)
    cid = _id_at(cb.data, 2)
    if cid is None:
        await common.show(cb, t(chat_id, "cards.gone"), _wallets_kb(chat_id))
        return
    # The card is fetched so the confirmation can name it. A "Delete this card?" with no name
    # on it is the one screen where the owner cannot check what they are about to lose.
    card = await _load_card(cb, chat_id, cid)
    if card is None:
        return
    await common.show(cb, t(chat_id, "cards.deleteConfirm", name=esc(card.get("name") or "—")),
                      ikb([ui.confirm_row(chat_id, f"card:delok:{cid}", f"card:view:{cid}",
                                          destructive=True)]))


@router.callback_query(F.data.startswith("card:delok:"))
async def card_delete(cb: CallbackQuery) -> None:
    await common.ack(cb)
    if not await common.gate(cb):
        return
    chat_id = common.chat_id_of(cb)
    cid = _id_at(cb.data, 2)
    if cid is None:
        await common.show(cb, t(chat_id, "cards.gone"), _wallets_kb(chat_id))
        return
    await common.begin_write(cb, chat_id)
    try:
        await api.request(chat_id, "DELETE", f"/cards/{cid}")
    except api.NeedsLogin:
        await common.show(cb, t(chat_id, "common.sessionExpired"), keyboards.login_kb(chat_id))
        return
    except api.Unreachable:
        await common.show(cb, t(chat_id, "common.serverUnreachable"), _wallets_kb(chat_id))
        return
    except api.ApiError as exc:
        # 404 means it is already gone — the second tap of a double-tap, or an update replayed
        # after a restart. The end state is the one the owner asked for, so show it.
        if exc.status != 404:
            await common.show(cb, f"❌ {esc(exc.message)}", _wallets_kb(chat_id))
            return
    except Exception:  # noqa: BLE001
        log.exception("DELETE /cards/%s failed for chat %s", cid, chat_id)
        await common.show(cb, t(chat_id, "cards.deleteError"), _wallets_kb(chat_id))
        return
    await _render_wallets(cb, prefix=t(chat_id, "cards.deleted"))


# ── the cash pot ─────────────────────────────────────────────────────────────
def _cash_screen(chat_id: int, pot: dict | None) -> tuple[str, InlineKeyboardMarkup]:
    lines = [t(chat_id, "cards.cashTitle"), ""]
    if pot is None:
        lines.append(t(chat_id, "cards.noCashSet"))
    else:
        # Three lines, in the order in which they explain each other: what is in hand, what
        # the recorded transactions moved, and the opening figure the backend stores. The
        # owner sets the first and the bot derives the third; printing only the outer two is
        # what made the old screen impossible to reconcile against the number just typed.
        lines += [
            t(chat_id, "cards.cashNow", amount=fmt_money(pot.get("currentBalance"))),
            t(chat_id, "cards.cashDelta", amount=_signed(_cash_delta(pot))),
            t(chat_id, "cards.cashStart", amount=fmt_money(pot.get("initialBalance"))),
        ]
    lines += ["", t(chat_id, "cards.cashNote")]
    kb = ikb([
        [(t(chat_id, "cards.setCashBalance"), "cash:set")],
        ui.nav(chat_id, back="cards:list", menu=True),
    ])
    return "\n".join(lines), kb


@router.callback_query(F.data == "cards:cash")
async def cash_screen(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    if not await common.gate(cb):
        return
    chat_id = common.chat_id_of(cb)
    await state.clear()
    try:
        pot, known = await _cash_pot(chat_id)
    except api.NeedsLogin:
        await common.show(cb, t(chat_id, "common.sessionExpired"), keyboards.login_kb(chat_id))
        return
    if not known:
        await common.show(cb, t(chat_id, "cards.cashLoadError"), _wallets_kb(chat_id))
        return
    text, kb = _cash_screen(chat_id, pot)
    await common.show(cb, text, kb)


# `cash:add` is the button the old build wrote into the chat. It is still out there in
# scrolled-up messages, and Telegram replays updates queued while the container was down.
@router.callback_query(F.data.in_({"cash:set", "cash:add"}))
async def cash_prompt(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    if not await common.gate(cb):
        return
    chat_id = common.chat_id_of(cb)
    try:
        pot, _known = await _cash_pot(chat_id)
    except api.NeedsLogin:
        await common.show(cb, t(chat_id, "common.sessionExpired"), keyboards.login_kb(chat_id))
        return
    await state.clear()
    await state.set_state(CardEdit.value)
    await state.update_data(cd_kind="cash")
    lines = [t(chat_id, "cards.cashTitle"), "", t(chat_id, "cards.cashPrompt")]
    if pot is not None:
        # The reading the question is about. Showing the opening figure here — which is what
        # this screen used to do — invited the owner to answer a question nobody asked.
        lines.append(t(chat_id, "cards.cashNow", amount=fmt_money(pot.get("currentBalance"))))
    # A prompt-specific note: `cards.cashNote` opens by asking for the figure, which is the
    # sentence directly above it here, so on this one screen it would read as a stutter.
    lines += ["", t(chat_id, "cards.cashPromptNote")]
    await common.show(cb, "\n".join(lines),
                      ikb([ui.nav(chat_id, back="cards:cash", cancel="cards:list")]))


async def _save_cash(event, state: FSMContext, chat_id: int, held: float) -> None:
    """Store the opening figure that makes the pot read `held` — the question actually asked.

    `POST /cash-balances` upserts by currency and writes `initialBalance` and nothing else,
    while the balance every screen shows is `initialBalance` plus the net of every cardless
    transaction. The prompt asks what is in hand RIGHT NOW, so the figure to store is that
    answer minus the net — and since the pot reports both readings, the net is their
    difference. See the module docstring for why the two must not be conflated.

    The pot is re-read here instead of being carried over from the prompt: the answer is typed
    by hand, and a cash expense recorded in the web app in between would otherwise land in the
    net twice.
    """
    try:
        pot, known = await _cash_pot(chat_id)
    except api.NeedsLogin:
        await state.clear()
        await common.show(event, t(chat_id, "common.sessionExpired"), keyboards.login_kb(chat_id))
        return
    if not known:
        # With no reading of the pot there is no net to subtract, and putting the typed figure
        # straight into `initialBalance` is the exact error this function exists to prevent.
        # Refusing is honest; storing a number that means something else is not.
        await state.clear()
        await common.show(event, t(chat_id, "cards.cashReadFirst"),
                          ikb([[(t(chat_id, "common.retry"), "cash:set"),
                                (t(chat_id, "common.back"), "cards:cash")]]))
        return

    opening = round(held - _cash_delta(pot), 4)
    await common.begin_write(event, chat_id)
    try:
        pot = await api.request(chat_id, "POST", "/cash-balances",
                                json={"currency": CURRENCY, "initialBalance": opening})
        # First run is the one case the subtraction above cannot see: with no pot row, the GET
        # returns nothing while cardless transactions may already exist, so the net reads as
        # zero. The write's own reply carries both figures, so the net is known now and one
        # correction — never a loop — settles it. The same branch absorbs a transaction
        # recorded between the read and the write. The upsert is idempotent, and the first
        # write is the figure as typed, so a failure here is no worse than the old behaviour.
        if isinstance(pot, dict):
            drift = round(held - _num(pot.get("currentBalance")), 4)
            if abs(drift) >= 0.005:
                opening = round(opening + drift, 4)
                pot = await api.request(chat_id, "POST", "/cash-balances",
                                        json={"currency": CURRENCY, "initialBalance": opening})
    except api.NeedsLogin:
        await state.clear()
        await common.show(event, t(chat_id, "common.sessionExpired"), keyboards.login_kb(chat_id))
        return
    except api.Unreachable:
        await common.show(event, t(chat_id, "common.serverUnreachable"), _wallets_kb(chat_id))
        return
    except api.ApiError as exc:
        await common.show(event, f"❌ {esc(exc.message)}",
                          ikb([[(t(chat_id, "common.back"), "cards:cash")]]))
        return
    except Exception:  # noqa: BLE001
        log.exception("POST /cash-balances failed for chat %s", chat_id)
        await common.show(event, t(chat_id, "cards.saveError"),
                          ikb([[(t(chat_id, "common.back"), "cards:cash")]]))
        return
    await state.clear()
    text, kb = _cash_screen(chat_id, pot if isinstance(pot, dict) else None)
    await common.show(event, f"{t(chat_id, 'cards.cashSaved')}\n\n{text}", kb)


# ── adding a card ────────────────────────────────────────────────────────────
@router.callback_query(F.data == "cards:add")
async def add_card(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    if not await common.gate(cb):
        return
    # Clear before entering. `wizard.start` resets its own `w_data`, but an entry point that
    # inherits whatever the last abandoned flow left in the bag is the shape of bug that put
    # a root category under a parent nobody chose — it costs one line not to have it here.
    await state.clear()
    await wizard.start(cb, state, CARD_SPEC)
