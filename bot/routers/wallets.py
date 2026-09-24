"""👛 Wallets: every balance, the total ("You have"), and Check wallets.

Check wallets is the wallet check-in (`GET/POST /months/checkin`): type what is really in each
wallet now; any gap from the app's figure is saved as everyday spending. One typed balance per
wallet, then a review where any wallet can be corrected, then Save. A refusal keeps every
balance already typed.

Callbacks owned here: `wal`, `ci:*`.
"""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from .. import api, clock, common, ui
from ..config import CURRENCY
from ..i18n import t
from ..keyboards import esc, ikb
from ..money import fmt_money, parse_number
from ..states import CheckIn
from . import home, pay

router = Router(name="wallets")


# ── The wallets screen ──────────────────────────────────────────────────────
@router.callback_query(F.data == "wal")
async def on_wallets(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    await state.clear()
    if not await common.gate(cb):
        return
    await show_wallets(cb)


async def show_wallets(event) -> None:
    chat_id = common.chat_id_of(event)
    try:
        data = await home.fetch(chat_id)
    except Exception as exc:  # noqa: BLE001
        await home.report(event, exc)
        return
    lines = [t(chat_id, "wallet.title"), ""]
    wallets = pay.ordered_wallets(data, "record")
    for w in wallets:
        icon = "💵" if w.get("type") == "CASH" else "💳"
        lines.append(t(chat_id, "wallet.row", icon=icon, name=esc(pay.wallet_name(chat_id, w)),
                       amount=fmt_money(home.n(w.get("balance")))))
    lines += ["", t(chat_id, "home.have", amount=fmt_money(home.n(data.get("have")))),
              home.checked_text(chat_id, data)]
    await common.show(event, "\n".join(lines), ikb([
        [(t(chat_id, "wallet.checkBtn"), "ci:start")],
        ui.nav(chat_id, home=True),
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
