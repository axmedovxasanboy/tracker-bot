"""👛 Wallets — the web's Wallets page: every balance and "You have", a wallet's transactions,
Add card, Add money to a card, Update cash, Move money, and Check wallets.

* **A wallet** (`wal:c:{card}:{page}`, `wal:k:{page}` for cash): its balance and its recent
  transactions, 10 a page — the card's (or the cash) portion of a split payment, as the web shows.
  A number opens the transaction (🧾 History's screens), whose Back comes here.
* **Add card** — nickname → last 4 digits → network → starting balance → Create (`POST /cards`;
  the bank name mirrors the nickname, as the web now does).
* **Add money** to a card / **Move money** — from → to → amount → Transfer
  (`POST /transactions/transfer`; cash is a null card id). The backend refuses a transfer until the
  monthly income is set, so that is asked first.
* **Update cash** — the cash pot's figure (`POST /cash-balances`, the web's inline editor).
* **Check wallets** is the wallet check-in (`GET/POST /months/checkin`): type what is really in each
  wallet now; any gap from the app's figure is saved as everyday spending. One typed balance per
  wallet, then a review where any wallet can be corrected, then Save. A refusal keeps every
  balance already typed.

Callbacks owned here: `wal`, `wal:*`, `ci:*`.
"""
from __future__ import annotations

import asyncio
import re

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from .. import api, clock, common, keyboards, ui
from ..config import CURRENCY
from ..i18n import t
from ..keyboards import esc, ikb
from ..money import fmt_money, parse_amount, parse_number
from ..states import CheckIn
from . import history, home, pay

router = Router(name="wallets")

TX_PAGE = 10
_NAME_LIMIT = 60
NETWORKS = ("UZCARD", "HUMO", "VISA")
NETWORK_LABEL = {"UZCARD": "Uzcard", "HUMO": "Humo", "VISA": "VISA", "CASH": "Cash"}
CARD_COLOR = "#0f172a"  # the web form's first swatch


class WalletFlow(StatesGroup):
    """Add card, Move money / Add money, Update cash. `pick` is every button-only step."""
    card_name = State()
    card_last4 = State()
    card_balance = State()
    pick = State()
    move_amount = State()
    cash_amount = State()


# ── The wallets screen ──────────────────────────────────────────────────────
@router.callback_query(F.data == "wal")
async def on_wallets(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    await state.clear()
    if not await common.gate(cb):
        return
    await show_wallets(cb)


async def show_wallets(event, notice: str | None = None) -> None:
    chat_id = common.chat_id_of(event)
    try:
        data = await home.fetch(chat_id)
    except Exception as exc:  # noqa: BLE001
        await home.report(event, exc)
        return
    lines = [notice, ""] if notice else []
    lines += [t(chat_id, "wallet.title"), ""]
    wallets = pay.ordered_wallets(data, "record")
    buttons = []
    for w in wallets:
        cash = w.get("type") == "CASH"
        icon = "💵" if cash else "💳"
        name = pay.wallet_name(chat_id, w)
        lines.append(t(chat_id, "wallet.row", icon=icon, name=esc(name),
                       amount=fmt_money(home.n(w.get("balance")))))
        if cash:
            buttons.append((t(chat_id, "wallet.walletBtn", icon=icon, name=home.clip(name)), "wal:k:0"))
        elif w.get("cardId") is not None:
            buttons.append((t(chat_id, "wallet.walletBtn", icon=icon, name=home.clip(name)), f"wal:c:{w['cardId']}:0"))
    lines += ["", t(chat_id, "home.have", amount=fmt_money(home.n(data.get("have")))),
              home.checked_text(chat_id, data), "", t(chat_id, "wallet.tapHint")]
    await common.show(event, "\n".join(lines), ikb([
        *ui.grid(buttons, 2),
        [(t(chat_id, "wallet.checkBtn"), "ci:start")],
        [(t(chat_id, "wallet.moveBtn"), "wal:mv"), (t(chat_id, "wallet.addCardBtn"), "wal:add")],
        ui.nav(chat_id, back="more", home=True),
    ]))


# ── Check wallets ───────────────────────────────────────────────────────────
def _label(chat_id: int, w: dict) -> str:
    """Cash is composed server-side as English "Cash"; say it in the owner's language."""
    if str(w.get("walletType") or "").upper() == "CASH":
        return t(chat_id, "common.cash")
    return str(w.get("label") or "—")


def _computed(w: dict) -> float | None:
    try:
        return float(w.get("computedBalance"))
    except (TypeError, ValueError):
        return None


def _index(data: str) -> int | None:
    tail = data.rpartition(":")[2]
    return int(tail) if tail.isdigit() else None


def _first_unset(values: list) -> int | None:
    return next((i for i, v in enumerate(values) if v is None), None)


@router.callback_query(F.data == "ci:start")
async def ci_start(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    if not await common.gate(cb):
        return
    await _intro(cb, state)


async def _intro(event, state: FSMContext) -> None:
    """The first screen — re-reads the status every time rather than trusting an old button."""
    chat_id = common.chat_id_of(event)
    back = ikb([ui.nav(chat_id, back="wal", home=True)])
    try:
        st = await api.request(chat_id, "GET", "/months/checkin", params={"date": clock.today_iso()}) or {}
    except Exception as exc:  # noqa: BLE001
        await home.report(event, exc)
        return
    if not st.get("allowed"):
        await state.clear()
        await common.show(event, f"🔒 {esc(st.get('blockedReason') or t(chat_id, 'wallet.locked'))}", back)
        return
    wallets = st.get("wallets") or []
    if not wallets:
        await common.show(event, t(chat_id, "wallet.none"), back)
        return
    date = str(st.get("date") or clock.today_iso())
    await state.set_state(CheckIn.intro)
    await state.set_data({"ci_date": date, "ci_wallets": wallets, "ci_values": [None] * len(wallets),
                          "ci_index": 0})
    lines = [t(chat_id, "wallet.checkTitle", date=ui.day(chat_id, date)), "", t(chat_id, "wallet.checkIntro")]
    so_far = home.n(st.get("everydaySoFar"))
    if so_far > 0:
        lines += ["", t(chat_id, "wallet.soFar", amount=fmt_money(so_far))]
    await common.show(event, "\n".join(lines), ikb([
        [(t(chat_id, "wallet.startBtn"), "ci:go")],
        ui.nav(chat_id, back="wal", home=True),
    ]))


async def _prompt(event, state: FSMContext) -> None:
    chat_id = common.chat_id_of(event)
    d = await state.get_data()
    wallets = d["ci_wallets"]
    idx = min(max(int(d.get("ci_index") or 0), 0), len(wallets) - 1)
    w, entered = wallets[idx], d["ci_values"][idx]
    computed = _computed(w)
    lines = [t(chat_id, "wallet.step", index=idx + 1, total=len(wallets)), "",
             f"<b>{esc(_label(chat_id, w))}</b>",
             t(chat_id, "wallet.appSays", amount=fmt_money(computed)),
             "", t(chat_id, "wallet.ask", currency=CURRENCY)]
    rows = []
    if entered is not None:
        rows.append([(t(chat_id, "wallet.keep", amount=fmt_money(entered)), f"ci:keep:{idx}")])
    if computed is not None:
        # The backend refuses a negative balance, so an overdrawn wallet is offered as 0.
        rows.append([(t(chat_id, "wallet.matches", amount=fmt_money(max(computed, 0.0))), f"ci:use:{idx}")])
    rows.append(ui.nav(chat_id, back=f"ci:back:{idx}", cancel="ci:x"))
    await state.set_state(CheckIn.balance)
    await state.update_data(ci_index=idx)
    await common.show(event, "\n".join(lines), ikb(rows))


async def _record(event, state: FSMContext, value: float) -> None:
    """Store one wallet's balance, then go wherever there is still work to do."""
    d = await state.get_data()
    values = list(d["ci_values"])
    idx = min(max(int(d.get("ci_index") or 0), 0), len(values) - 1)
    values[idx] = float(value)
    nxt = _first_unset(values)
    await state.update_data(ci_values=values, ci_index=idx if nxt is None else nxt)
    if nxt is None:
        await _review(event, state)
    else:
        await _prompt(event, state)


@router.callback_query(StateFilter(CheckIn.intro), F.data == "ci:go")
async def ci_go(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    await _prompt(cb, state)


@router.callback_query(StateFilter(CheckIn.balance), F.data.startswith("ci:use:"))
async def ci_use(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    d = await state.get_data()
    idx = _index(cb.data)
    if idx != d.get("ci_index"):
        # Every wallet shares one state: a stale "matches" from the previous wallet must not
        # write its figure into the wallet being asked for now.
        await _prompt(cb, state)
        return
    await _record(cb, state, max(_computed(d["ci_wallets"][idx]) or 0.0, 0.0))


@router.callback_query(StateFilter(CheckIn.balance), F.data.startswith("ci:keep:"))
async def ci_keep(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    d = await state.get_data()
    idx = _index(cb.data)
    if idx != d.get("ci_index") or d["ci_values"][idx] is None:
        await _prompt(cb, state)
        return
    await _record(cb, state, d["ci_values"][idx])


@router.callback_query(StateFilter(CheckIn.balance), F.data.startswith("ci:back:"))
async def ci_back(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    d = await state.get_data()
    idx = int(d.get("ci_index") or 0)
    if idx <= 0:
        await _intro(cb, state)
        return
    await state.update_data(ci_index=idx - 1)
    await _prompt(cb, state)


@router.message(StateFilter(CheckIn.balance))
async def ci_typed(message: Message, state: FSMContext) -> None:
    chat_id = common.chat_id_of(message)
    value = parse_number(message.text)
    if value is None:
        await message.answer(t(chat_id, "common.sendNumberExample"))
        return
    if value < 0:
        await message.answer(t(chat_id, "wallet.negative"))
        return
    await _record(message, state, value)


@router.message(StateFilter(CheckIn.intro, CheckIn.review))
async def ci_typed_elsewhere(message: Message) -> None:
    await message.answer(t(common.chat_id_of(message), "wallet.tapButton"))


async def _review(event, state: FSMContext, notice: str | None = None) -> None:
    chat_id = common.chat_id_of(event)
    d = await state.get_data()
    wallets, values = d["ci_wallets"], d["ci_values"]
    lines = [notice, ""] if notice else []
    lines += [t(chat_id, "wallet.reviewTitle", date=ui.day(chat_id, d.get("ci_date"))), ""]
    lines += [t(chat_id, "wallet.reviewRow", name=esc(_label(chat_id, w)), amount=fmt_money(v))
              for w, v in zip(wallets, values)]
    # The same arithmetic the server runs: app figure − typed figure, netted over the wallets.
    gap = sum((_computed(w) or 0.0) - v for w, v in zip(wallets, values) if v is not None)
    lines += ["", (t(chat_id, "wallet.willSpend", amount=fmt_money(gap)) if gap > 0
                   else t(chat_id, "wallet.willSurplus", amount=fmt_money(-gap)) if gap < 0
                   else t(chat_id, "wallet.willMatch"))]
    rows = ui.grid([(t(chat_id, "wallet.fixBtn", name=_label(chat_id, w)), f"ci:edit:{i}")
                    for i, w in enumerate(wallets)], 2)
    rows.append([(t(chat_id, "wallet.saveBtn"), "ci:ok")])
    rows.append(ui.nav(chat_id, cancel="ci:x"))
    await state.set_state(CheckIn.review)
    await common.show(event, "\n".join(lines), ikb(rows))


@router.callback_query(StateFilter(CheckIn.review, CheckIn.balance), F.data.startswith("ci:edit:"))
async def ci_edit(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    d = await state.get_data()
    idx = _index(cb.data)
    if idx is None or not 0 <= idx < len(d.get("ci_wallets") or []):
        await _review(cb, state)
        return
    await state.update_data(ci_index=idx)
    await _prompt(cb, state)


@router.callback_query(StateFilter(CheckIn.review), F.data == "ci:ok")
async def ci_ok(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    chat_id = common.chat_id_of(cb)
    d = await state.get_data()
    missing = _first_unset(d["ci_values"])
    if missing is not None:
        await state.update_data(ci_index=missing)
        await _prompt(cb, state)
        return
    entries = [{"walletType": w.get("walletType"), "cardId": w.get("cardId"),
                "currency": w.get("currency") or CURRENCY, "enteredBalance": v}
               for w, v in zip(d["ci_wallets"], d["ci_values"])]
    await common.begin_write(cb, chat_id)
    try:
        res = await api.request(chat_id, "POST", "/months/checkin",
                                json={"date": d.get("ci_date") or clock.today_iso(), "wallets": entries}) or {}
    except api.NeedsLogin:
        await state.clear()
        await home.report(cb, api.NeedsLogin())
        return
    except api.ApiError as exc:
        # Kept: the owner fixes one figure instead of retyping every wallet.
        await _review(cb, state, t(chat_id, "common.serverUnreachable") if isinstance(exc, api.Unreachable)
                      else f"❌ {esc(exc.message)}")
        return
    await state.clear()
    spent = home.n(res.get("everydayRecorded"))
    notice = (t(chat_id, "wallet.savedSpent", amount=fmt_money(spent)) if spent > 0
              else t(chat_id, "wallet.savedSurplus", amount=fmt_money(-spent)) if spent < 0
              else t(chat_id, "wallet.savedMatch"))
    await home.show_home(cb, notice)


@router.callback_query(F.data == "ci:x")
async def ci_cancel(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    await state.clear()
    if not await common.gate(cb):
        return
    await show_wallets(cb)


@router.callback_query(F.data.startswith("ci:"))
async def ci_stale(cb: CallbackQuery, state: FSMContext) -> None:
    """A check-in tap no step above wanted — an older message's button. Back to where we are."""
    await common.ack(cb)
    if not await common.gate(cb):
        return
    current = await state.get_state()
    d = await state.get_data()
    if d.get("ci_wallets") and current == CheckIn.review.state:
        await _review(cb, state)
    elif d.get("ci_wallets") and current == CheckIn.balance.state:
        await _prompt(cb, state)
    else:
        await _intro(cb, state)


# ── One wallet and its transactions ─────────────────────────────────────────
def _page_of(raw: str) -> int:
    return int(raw) if raw.isdigit() else 0


async def _tx_page(chat_id: int, page: int, **filters) -> dict:
    return await api.request(chat_id, "GET", "/transactions", params={
        "page": page, "size": TX_PAGE, "sortBy": "transactionDate", "sortDir": "desc", **filters}) or {}


def _pager(chat_id: int, res: dict, page: int, prefix: str) -> list[tuple[str, str]]:
    row = []
    if page > 0:
        row.append((t(chat_id, "common.prev"), f"{prefix}{page - 1}"))
    if not res.get("last", True):
        row.append((t(chat_id, "common.next"), f"{prefix}{page + 1}"))
    return row


def _card_portion(tx: dict) -> float:
    if tx.get("cardAmount") is not None:
        return home.n(tx.get("cardAmount"))
    return home.n(tx.get("amount")) - home.n(tx.get("cashAmount"))


async def show_card(event, card_id: int, page: int = 0, notice: str | None = None) -> None:
    chat_id = common.chat_id_of(event)
    try:
        cards, res = await asyncio.gather(api.request(chat_id, "GET", "/cards"),
                                          _tx_page(chat_id, page, cardId=card_id))
    except Exception as exc:  # noqa: BLE001
        await home.report(event, exc)
        return
    card = next((c for c in cards or [] if isinstance(c, dict) and c.get("id") == card_id), None)
    if card is None:
        await common.show(event, t(chat_id, "wallet.cardGone"), ikb([ui.nav(chat_id, back="wal", home=True)]))
        return
    lines = [notice, ""] if notice else []
    lines += [t(chat_id, "wallet.cardTitle", name=esc(card.get("name") or "—"),
                network=NETWORK_LABEL.get(card.get("type"), card.get("type") or "")),
              t(chat_id, "wallet.cardDigits", last4=esc(card.get("lastFourDigits") or "····")),
              t(chat_id, "wallet.balance", amount=fmt_money(home.n(card.get("currentBalance")))),
              "", t(chat_id, "wallet.cardTxSubtitle")]
    rows = [tx for tx in res.get("content") or [] if isinstance(tx, dict)]
    block, buttons = history.list_block(chat_id, rows, page * TX_PAGE, f"c{card_id}.{page}", _card_portion)
    lines += block or [t(chat_id, "wallet.noCardTx")]
    total = int(res.get("totalPages") or 0)
    if total > 1:
        lines += ["", t(chat_id, "wallet.pageOf", page=page + 1, total=total)]
    await common.show(event, "\n".join(lines), ikb([
        *buttons,
        _pager(chat_id, res, page, f"wal:c:{card_id}:"),
        [(t(chat_id, "wallet.topUpBtn"), f"wal:top:{card_id}")],
        ui.nav(chat_id, back="wal", home=True),
    ]))


async def _cash_pot(chat_id: int) -> dict | None:
    pots = await api.request(chat_id, "GET", "/cash-balances") or []
    return next((p for p in pots if isinstance(p, dict) and p.get("currency") == CURRENCY), None)


async def show_cash(event, page: int = 0, notice: str | None = None) -> None:
    chat_id = common.chat_id_of(event)
    try:
        pot = await _cash_pot(chat_id)
        res = await _tx_page(chat_id, page, cashOnly="true", currency=CURRENCY) if pot else {}
    except Exception as exc:  # noqa: BLE001
        await home.report(event, exc)
        return
    lines = [notice, ""] if notice else []
    lines.append(t(chat_id, "wallet.cashTitle"))
    buttons: list = []
    if pot is None:
        lines += ["", t(chat_id, "wallet.cashEmptyHint")]
    else:
        current, initial = home.n(pot.get("currentBalance")), home.n(pot.get("initialBalance"))
        line = t(chat_id, "wallet.balance", amount=fmt_money(current))
        if round(current - initial, 2) != 0:
            line += " · " + t(chat_id, "wallet.startingAmount", amount=fmt_money(initial))
        lines += [line, "", t(chat_id, "wallet.cashTxSubtitle")]
        rows = [tx for tx in res.get("content") or [] if isinstance(tx, dict)]
        block, buttons = history.list_block(chat_id, rows, page * TX_PAGE, f"k.{page}",
                                            lambda tx: home.n(tx.get("cashAmount")))
        lines += block or [t(chat_id, "wallet.noCashTx")]
        total = int(res.get("totalPages") or 0)
        if total > 1:
            lines += ["", t(chat_id, "wallet.pageOf", page=page + 1, total=total)]
    await common.show(event, "\n".join(lines), ikb([
        *buttons,
        _pager(chat_id, res, page, "wal:k:") if pot else [],
        [(t(chat_id, "wallet.updateCashBtn" if pot else "wallet.addCashBtn"), "wal:kx")],
        ui.nav(chat_id, back="wal", home=True),
    ]))


@router.callback_query(F.data.startswith("wal:c:"))
async def on_card(cb: CallbackQuery, state: FSMContext) -> None:
    """`wal:c:{card}:{page}`."""
    await common.ack(cb)
    await state.set_state(None)
    if not await common.gate(cb):
        return
    parts = cb.data.split(":")
    if len(parts) < 3 or not parts[2].isdigit():
        await show_wallets(cb)
        return
    await show_card(cb, int(parts[2]), _page_of(parts[3]) if len(parts) > 3 else 0)


@router.callback_query(F.data.startswith("wal:k:"))
async def on_cash(cb: CallbackQuery, state: FSMContext) -> None:
    """`wal:k:{page}`."""
    await common.ack(cb)
    await state.set_state(None)
    if not await common.gate(cb):
        return
    await show_cash(cb, _page_of(cb.data.split(":")[2]))


# ── Update cash ─────────────────────────────────────────────────────────────
@router.callback_query(F.data == "wal:kx")
async def on_cash_edit(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    if not await common.gate(cb):
        return
    chat_id = common.chat_id_of(cb)
    try:
        pot = await _cash_pot(chat_id)
    except Exception as exc:  # noqa: BLE001
        await home.report(cb, exc)
        return
    lines = [t(chat_id, "wallet.cashModalTitle"), "", t(chat_id, "wallet.cashHoldLabel", currency=CURRENCY),
             t(chat_id, "wallet.cashHoldHint")]
    if pot is not None:
        lines += ["", t(chat_id, "wallet.cashNow", current=fmt_money(home.n(pot.get("currentBalance"))),
                        initial=fmt_money(home.n(pot.get("initialBalance"))))]
    lines += ["", t(chat_id, "wallet.cashAsk")]
    await state.set_state(WalletFlow.cash_amount)
    await common.show(cb, "\n".join(lines), ikb([ui.nav(chat_id, back="wal:k:0", home=True)]))


@router.message(StateFilter(WalletFlow.cash_amount))
async def on_cash_typed(message: Message, state: FSMContext) -> None:
    chat_id = common.chat_id_of(message)
    value = parse_number(message.text)
    if value is None:
        await message.answer(t(chat_id, "common.sendNumberExample"))
        return
    if value < 0:
        await message.answer(t(chat_id, "wallet.negative"))
        return
    if not await common.gate(message):
        await state.clear()
        return
    try:
        await api.request(chat_id, "POST", "/cash-balances", json={"currency": CURRENCY, "initialBalance": value})
    except api.NeedsLogin:
        await state.clear()
        await common.show(message, t(chat_id, "common.sessionExpired"), keyboards.login_kb(chat_id))
        return
    except api.ApiError as exc:
        # Still in the state, so the next number typed is another attempt.
        await message.answer(t(chat_id, "common.serverUnreachable") if isinstance(exc, api.Unreachable)
                             else f"❌ {esc(exc.message)}")
        return
    await state.clear()
    await show_cash(message, 0, t(chat_id, "wallet.cashSaved"))


# ── Add card ────────────────────────────────────────────────────────────────
def _card_nav(chat_id: int) -> list[tuple[str, str]]:
    return ui.nav(chat_id, cancel="wal")


@router.callback_query(F.data == "wal:add")
async def on_add_card(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    if not await common.gate(cb):
        return
    chat_id = common.chat_id_of(cb)
    await state.set_state(WalletFlow.card_name)
    await state.update_data(wc={})
    await common.show(cb, f"{t(chat_id, 'wallet.newCardTitle')}\n\n{t(chat_id, 'wallet.askName')}",
                      ikb([_card_nav(chat_id)]))


@router.message(StateFilter(WalletFlow.card_name))
async def on_card_name(message: Message, state: FSMContext) -> None:
    chat_id = common.chat_id_of(message)
    name = " ".join((message.text or "").split())
    if not name:
        await message.answer(t(chat_id, "wallet.askName"))
        return
    if len(name) > _NAME_LIMIT:
        await message.answer(t(chat_id, "wallet.nameTooLong", limit=_NAME_LIMIT))
        return
    await state.update_data(wc={"name": name})
    await state.set_state(WalletFlow.card_last4)
    await common.show(message, f"{t(chat_id, 'wallet.newCardTitle')}\n\n{t(chat_id, 'wallet.askLast4', name=esc(name))}",
                      ikb([_card_nav(chat_id)]))


@router.message(StateFilter(WalletFlow.card_last4))
async def on_card_last4(message: Message, state: FSMContext) -> None:
    chat_id = common.chat_id_of(message)
    digits = (message.text or "").strip()
    if not re.fullmatch(r"\d{4}", digits):
        await message.answer(t(chat_id, "wallet.badLast4"))
        return
    wc = dict((await state.get_data()).get("wc") or {}, last4=digits)
    await state.update_data(wc=wc)
    await state.set_state(WalletFlow.pick)
    await common.show(message, f"{t(chat_id, 'wallet.newCardTitle')}\n\n{t(chat_id, 'wallet.askNetwork')}", ikb([
        [(NETWORK_LABEL[k], f"wal:net:{k}") for k in NETWORKS], _card_nav(chat_id)]))


@router.callback_query(F.data.startswith("wal:net:"))
async def on_card_network(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    if not await common.gate(cb):
        return
    chat_id = common.chat_id_of(cb)
    wc = (await state.get_data()).get("wc") or {}
    network = cb.data.split(":")[2]
    if not wc.get("last4") or network not in NETWORKS:
        await common.ack(cb, t(chat_id, "common.oldButton"), alert=True)
        await show_wallets(cb)
        return
    await state.update_data(wc=dict(wc, type=network))
    await state.set_state(WalletFlow.card_balance)
    await common.show(cb, f"{t(chat_id, 'wallet.newCardTitle')}\n\n"
                          f"{t(chat_id, 'wallet.askStart', name=esc(wc['name']), currency=CURRENCY)}",
                      ikb([_card_nav(chat_id)]))


@router.message(StateFilter(WalletFlow.card_balance))
async def on_card_balance(message: Message, state: FSMContext) -> None:
    chat_id = common.chat_id_of(message)
    value = parse_number(message.text)
    if value is None:
        await message.answer(t(chat_id, "common.sendNumberExample"))
        return
    if value < 0:
        await message.answer(t(chat_id, "wallet.negative"))
        return
    wc = dict((await state.get_data()).get("wc") or {}, balance=value)
    await state.update_data(wc=wc)
    await state.set_state(WalletFlow.pick)
    await common.show(message, "\n".join([
        t(chat_id, "wallet.newCardTitle"), "",
        t(chat_id, "wallet.reviewCard", name=esc(wc.get("name")), network=NETWORK_LABEL.get(wc.get("type"), ""),
          last4=wc.get("last4"), amount=fmt_money(value))]),
        ikb([[(t(chat_id, "wallet.createBtn"), "wal:addok")], _card_nav(chat_id)]))


@router.callback_query(F.data == "wal:addok")
async def on_card_create(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    if not await common.gate(cb):
        return
    chat_id = common.chat_id_of(cb)
    wc = (await state.get_data()).get("wc") or {}
    if not all(k in wc for k in ("name", "last4", "type", "balance")):
        await common.ack(cb, t(chat_id, "common.oldButton"), alert=True)
        await state.clear()
        await show_wallets(cb)
        return
    await common.begin_write(cb, chat_id)
    try:
        # bankName is required by the API but no longer asked for: it mirrors the nickname.
        await api.request(chat_id, "POST", "/cards", json={
            "name": wc["name"], "bankName": wc["name"], "type": wc["type"], "lastFourDigits": wc["last4"],
            "initialBalance": wc["balance"], "currency": CURRENCY, "color": CARD_COLOR})
    except api.NeedsLogin:
        await state.clear()
        await common.show(cb, t(chat_id, "common.sessionExpired"), keyboards.login_kb(chat_id))
        return
    except api.ApiError as exc:
        reason = t(chat_id, "common.serverUnreachable") if isinstance(exc, api.Unreachable) else f"❌ {esc(exc.message)}"
        await common.show(cb, reason, ikb([[(t(chat_id, "wallet.createBtn"), "wal:addok")], _card_nav(chat_id)]))
        return
    await state.clear()
    await show_wallets(cb, t(chat_id, "wallet.cardCreated"))


# ── Move money / Add money ──────────────────────────────────────────────────
def _key(value) -> str:
    return "cash" if value in (None, "cash") else str(value)


def _wallet_label(chat_id: int, wm: dict, key: str) -> str:
    if key == "cash":
        return t(chat_id, "common.cash")
    card = next((c for c in wm.get("cards") or [] if str(c.get("id")) == key), None)
    return str(card.get("name") or "—") if card else "—"


def _wallet_balance(wm: dict, key: str) -> float:
    if key == "cash":
        return home.n(wm.get("cash"))
    card = next((c for c in wm.get("cards") or [] if str(c.get("id")) == key), None)
    return home.n(card.get("currentBalance")) if card else 0.0


def _options(wm: dict, other: str | None) -> list[str]:
    """Every wallet but the one on the other side; cash only once a pot exists, and never twice."""
    keys = [str(c.get("id")) for c in wm.get("cards") or []]
    if wm.get("hasCash"):
        keys.append("cash")
    return [k for k in keys if k != other]


async def _move_start(cb: CallbackQuery, state: FSMContext, to: str | None) -> None:
    chat_id = common.chat_id_of(cb)
    try:
        settings, cards, pot = await asyncio.gather(
            api.request(chat_id, "GET", "/settings"), api.request(chat_id, "GET", "/cards"), _cash_pot(chat_id))
    except Exception as exc:  # noqa: BLE001
        await home.report(cb, exc)
        return
    if home.n((settings or {}).get("monthlyStableIncome")) <= 0:
        # The backend refuses every transfer until the income is set; say so before the form.
        await common.show(cb, f"{t(chat_id, 'guard.incomeTitle')}\n\n{t(chat_id, 'guard.incomeBody')}",
                          keyboards.income_guard_kb(chat_id))
        return
    cards = [c for c in cards or [] if isinstance(c, dict) and c.get("type") != "CASH"
             and c.get("currency", CURRENCY) == CURRENCY]
    wm = {"cards": cards, "hasCash": pot is not None, "cash": home.n((pot or {}).get("currentBalance")),
          "from": None, "to": to, "top": to is not None, "amount": None}
    if to is not None and to not in _options(wm, None):
        await show_wallets(cb)
        return
    if len(_options(wm, None)) < 2:
        await common.show(cb, t(chat_id, "wallet.needTwo"), ikb([
            [(t(chat_id, "wallet.addCardBtn"), "wal:add")], ui.nav(chat_id, back="wal", home=True)]))
        return
    await state.update_data(wm=wm)
    await _move_next(cb, state)


def _move_head(chat_id: int, wm: dict) -> list[str]:
    head = (t(chat_id, "wallet.topUpTitle", name=esc(_wallet_label(chat_id, wm, wm["to"]))) if wm.get("top")
            else t(chat_id, "wallet.moveTitle"))
    lines = [head]
    if wm.get("from") and wm.get("to"):
        lines.append(t(chat_id, "wallet.moveFromTo", source=esc(_wallet_label(chat_id, wm, wm["from"])),
                       target=esc(_wallet_label(chat_id, wm, wm["to"]))))
    return lines + [""]


async def _move_next(event, state: FSMContext, error: str = "") -> None:
    """Whatever the move still needs: the source, the destination, the amount, then the review."""
    chat_id = common.chat_id_of(event)
    wm = (await state.get_data()).get("wm") or {}
    lines = _move_head(chat_id, wm)
    cancel = ui.nav(chat_id, cancel="wal")
    if wm.get("from") is None or wm.get("to") is None:
        picking_from = wm.get("from") is None
        other = wm.get("to") if picking_from else wm.get("from")
        keys = [k for k in _options(wm, other) if not (other == "cash" and k == "cash")]
        rows = [[(t(chat_id, "wallet.pickRow", icon="💵" if k == "cash" else "💳",
                    name=home.clip(_wallet_label(chat_id, wm, k)), amount=fmt_money(_wallet_balance(wm, k))),
                  f"wal:{'mf' if picking_from else 'mt'}:{k}")] for k in keys]
        lines.append(t(chat_id, "wallet.askFrom" if picking_from else "wallet.askTo"))
        await state.set_state(WalletFlow.pick)
        await common.show(event, "\n".join(lines), ikb([*rows, cancel]))
        return
    if wm.get("amount") is None:
        lines.append(t(chat_id, "wallet.askAmount"))
        await state.set_state(WalletFlow.move_amount)
        await common.show(event, "\n".join(lines), ikb([cancel]))
        return
    amount = float(wm["amount"])
    lines = [lines[0], "", t(chat_id, "wallet.reviewMove", amount=fmt_money(amount),
                             source=esc(_wallet_label(chat_id, wm, wm["from"])),
                             target=esc(_wallet_label(chat_id, wm, wm["to"])))]
    have = _wallet_balance(wm, wm["from"])
    if amount > have:
        lines += ["", t(chat_id, "wallet.overBalance", name=esc(_wallet_label(chat_id, wm, wm["from"])),
                        amount=fmt_money(have))]
    if error:
        lines += ["", error]
    await state.set_state(WalletFlow.pick)
    await common.show(event, "\n".join(lines), ikb([[(t(chat_id, "wallet.transferBtn"), "wal:mok")], cancel]))


async def _move_data(cb: CallbackQuery, state: FSMContext) -> dict | None:
    chat_id = common.chat_id_of(cb)
    if not await common.gate(cb):
        return None
    wm = (await state.get_data()).get("wm")
    if not isinstance(wm, dict) or "cards" not in wm:
        await common.ack(cb, t(chat_id, "common.oldButton"), alert=True)
        await state.clear()
        await show_wallets(cb)
        return None
    await common.ack(cb)
    return wm


@router.callback_query(F.data == "wal:mv")
async def on_move(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    if not await common.gate(cb):
        return
    await _move_start(cb, state, None)


@router.callback_query(F.data.startswith("wal:top:"))
async def on_top_up(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    if not await common.gate(cb):
        return
    raw = cb.data.split(":")[2]
    if not raw.isdigit():
        await show_wallets(cb)
        return
    await _move_start(cb, state, raw)


@router.callback_query(F.data.startswith("wal:mf:"))
async def on_move_from(cb: CallbackQuery, state: FSMContext) -> None:
    wm = await _move_data(cb, state)
    if wm is None:
        return
    key = _key(cb.data.split(":")[2])
    if key in _options(wm, wm.get("to")) and not (key == "cash" and wm.get("to") == "cash"):
        await state.update_data(wm=dict(wm, **{"from": key}))
    await _move_next(cb, state)


@router.callback_query(F.data.startswith("wal:mt:"))
async def on_move_to(cb: CallbackQuery, state: FSMContext) -> None:
    wm = await _move_data(cb, state)
    if wm is None:
        return
    key = _key(cb.data.split(":")[2])
    if key in _options(wm, wm.get("from")) and not (key == "cash" and wm.get("from") == "cash"):
        await state.update_data(wm=dict(wm, to=key))
    await _move_next(cb, state)


@router.message(StateFilter(WalletFlow.move_amount))
async def on_move_amount(message: Message, state: FSMContext) -> None:
    chat_id = common.chat_id_of(message)
    wm = (await state.get_data()).get("wm")
    if not isinstance(wm, dict):
        await state.clear()
        await show_wallets(message)
        return
    amount = parse_amount(message.text)
    if amount is None:
        await message.answer(t(chat_id, "common.positiveNumber"))
        return
    await state.update_data(wm=dict(wm, amount=amount))
    await _move_next(message, state)


@router.callback_query(F.data == "wal:mok")
async def on_move_confirm(cb: CallbackQuery, state: FSMContext) -> None:
    wm = await _move_data(cb, state)
    if wm is None:
        return
    chat_id = common.chat_id_of(cb)
    if wm.get("amount") is None or not wm.get("from") or not wm.get("to"):
        await _move_next(cb, state)
        return
    if wm["from"] == "cash" and wm["to"] == "cash":
        await _move_next(cb, state, t(chat_id, "wallet.cashToCash"))
        return
    body = {"fromCardId": None if wm["from"] == "cash" else int(wm["from"]),
            "toCardId": None if wm["to"] == "cash" else int(wm["to"]),
            "amount": float(wm["amount"]), "transactionDate": clock.today_iso()}
    await common.begin_write(cb, chat_id)
    try:
        await api.request(chat_id, "POST", "/transactions/transfer", json=body)
    except api.NeedsLogin:
        await state.clear()
        await common.show(cb, t(chat_id, "common.sessionExpired"), keyboards.login_kb(chat_id))
        return
    except api.ApiError as exc:
        await _move_next(cb, state, t(chat_id, "common.serverUnreachable") if isinstance(exc, api.Unreachable)
                         else f"❌ {esc(exc.message)}")
        return
    await state.clear()
    notice = t(chat_id, "wallet.moved", amount=fmt_money(float(wm["amount"])))
    if wm.get("top") and str(wm["to"]).isdigit():
        await show_card(cb, int(wm["to"]), 0, notice)
    else:
        await show_wallets(cb, notice)


@router.message(StateFilter(WalletFlow.pick))
async def on_pick_typed(message: Message) -> None:
    await message.answer(t(common.chat_id_of(message), "common.tapButton"))
