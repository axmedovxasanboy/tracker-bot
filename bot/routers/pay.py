"""Pay from a Home button: tap Pay, tap the wallet — done.

The same endpoints as the web's pay dialogs:

* a bill            — POST /finance/monthly-payments/{id}/pay           (Coming up, kind BILL)
* a bank installment — POST /transactions, sub-type BANK_LOAN_PAYMENT     (kind BANK)
* borrowed money    — POST /finance/loans-taken/{id}/repay               (kind LOAN, monthly or ASAP)
* a debt            — POST /finance/debts/{id}/repay                     (kind DEBT)
* the donation      — POST /finance/donations
* investments / the emergency fund — one of the owner's own accounts from GET /finance/investments
  (opening balances included, goals left out, emergency-flagged ones for the emergency fund) via
  POST /finance/investments/{id}/contribute, or the plain fund record POST /emergencies
* a goal            — POST /finance/investments/{id}/contribute on that goal

Every Pay button re-reads the advisor first and pays the CURRENT amount, so a screen scrolled up
from yesterday cannot pay yesterday's figure, and a bill paid from the web in the meantime says
"already taken care of" instead of being paid twice. The wallet list puts the one used last first.

Callbacks owned here: `pay:*` (from Home), `pw:*` (wallet), `pk:*` (account), `pa` (other amount).
"""
from __future__ import annotations

from typing import Any

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from .. import api, clock, common, keyboards, storage, ui
from ..config import CURRENCY
from ..i18n import t
from ..keyboards import esc, ikb
from ..money import fmt_money, parse_amount
from ..states import Pay
from . import home

router = Router(name="pay")

_ICON = {"BILL": "💳", "BANK": "🏦", "LOAN": "🤝", "DEBT": "🤝", "DONATION": "🤲",
         "EMERGENCY": "🛟", "INVESTMENTS": "📈", "GOAL": "🎯"}
_FUND = "fund"  # the emergency fund without an account behind it


# ── Wallets, last used first ────────────────────────────────────────────────
# Paying and recording each remember their own last wallet: a donation paid in cash once must
# not turn the next "50000 lunch" into a cash expense. Paying falls back to recording's.
def last_wallet(kind: str = "record") -> Any:
    """The wallet used last: a card id, "cash", or None."""
    if kind == "pay":
        return storage.pref("payWallet", storage.pref("wallet"))
    return storage.pref("wallet")


def remember_wallet(card_id: int | None, kind: str = "record") -> None:
    storage.set_pref("payWallet" if kind == "pay" else "wallet", "cash" if card_id is None else card_id)


def ordered_wallets(data: dict, kind: str = "pay") -> list[dict]:
    """The advisor's wallets: the one used last first, then cards by balance, then cash."""
    wallets = [w for w in data.get("wallets") or [] if isinstance(w, dict)]
    if not any(w.get("type") == "CASH" for w in wallets):
        wallets.append({"type": "CASH", "cardId": None, "label": "Cash", "balance": 0})
    last = last_wallet(kind)

    def rank(w: dict) -> tuple:
        key = "cash" if w.get("type") == "CASH" else w.get("cardId")
        return (key != last, w.get("type") == "CASH", -home.n(w.get("balance")))

    return sorted(wallets, key=rank)


def wallet_name(chat_id: int | None, w: dict) -> str:
    return t(chat_id, "common.cash") if w.get("type") == "CASH" else str(w.get("label") or "—")


# ── Finding what the button is for ──────────────────────────────────────────
def _target(chat_id: int, data: dict, kind: str, ref: int | None) -> dict | None:
    """What this button pays now: {kind, ref, name, amount}, or None when nothing is due."""
    month = str(data.get("date") or clock.today_iso())[:7]
    if kind in home.UPCOMING_KINDS:
        daily = data.get("daily") if isinstance(data.get("daily"), dict) else {}
        for u in daily.get("upcoming") or []:
            if (home.payable_upcoming(u, month) and u.get("kind") == kind
                    and (u.get("refId") or 0) == (ref or 0)):
                return {"kind": kind, "ref": u.get("refId"), "name": str(u.get("name") or "—"),
                        "amount": home.n(u.get("amount"))}
        return None
    for r in home.savings_rows(data):
        if home.n(r.get("remaining")) <= 0:
            continue
        if (kind == "GOAL" and r.get("bucket") == "GOAL" and r.get("refId") == ref) or \
                (kind in home.BUCKETS and r.get("bucket") == kind):
            return {"kind": kind, "ref": r.get("refId"), "name": home.savings_name(chat_id, r),
                    "amount": home.n(r.get("remaining"))}
    return None


async def _bank_description(chat_id: int, ref: int | None) -> str:
    """"Bank installment — Kapitalbank (Car loan)", as the web writes it."""
    try:
        loans = [b for b in await api.request(chat_id, "GET", "/finance/bank-loans") or []
                 if isinstance(b, dict)]
    except Exception:  # noqa: BLE001 — a plain description is fine; the payment is what matters
        loans = []
    loan = next((b for b in loans if b.get("id") == ref), None)
    if loan is None and len(loans) == 1:
        loan = loans[0]
    if loan is None:
        return "Bank installment"
    return f"Bank installment — {loan.get('bankName') or ''} ({loan.get('loanName') or ''})"


def _accounts(bucket: str, holdings: list[dict]) -> list[dict]:
    """The owner's accounts for this money, the one used last first, then by value."""
    emergency = bucket == "EMERGENCY"
    mine = [i for i in holdings if isinstance(i, dict) and i.get("currency", CURRENCY) == CURRENCY
            and not i.get("savingsGoal") and bool(i.get("emergencyFund")) == emergency]
    last = storage.pref(f"account.{bucket}")
    return sorted(mine, key=lambda i: (i.get("id") != last,
                                       -home.n(i.get("value") or i.get("currentValue") or i.get("investedAmount"))))


# ── Screens ─────────────────────────────────────────────────────────────────
async def _wallet_screen(event, state: FSMContext) -> None:
    chat_id = common.chat_id_of(event)
    d = await state.get_data()
    flow = d.get("pay") or {}
    lines = [t(chat_id, "pay.header", icon=_ICON.get(flow.get("kind"), "💳"), name=esc(flow.get("name") or ""),
               amount=fmt_money(flow.get("amount")))]
    if flow.get("account"):
        lines.append(t(chat_id, "pay.into", name=esc(flow["account"])))
    lines += ["", t(chat_id, "pay.fromWhich")]
    rows = [[(("💵 " if w.get("type") == "CASH" else "💳 ")
              + t(chat_id, "pay.wallet", name=wallet_name(chat_id, w), amount=fmt_money(home.n(w.get("balance")))),
              f"pw:{i}")] for i, w in enumerate(d.get("pay_wallets") or [])]
    rows.append([(t(chat_id, "pay.otherAmount"), "pa"), (t(chat_id, "common.cancel"), "home")])
    await state.set_state(Pay.pick)
    await common.show(event, "\n".join(lines), ikb(rows))


async def _start(cb: CallbackQuery, state: FSMContext, data: dict, flow: dict) -> None:
    await state.set_state(Pay.pick)
    await state.set_data({"pay": flow, "pay_wallets": ordered_wallets(data)})
    await _wallet_screen(cb, state)


@router.callback_query(F.data.startswith("pay:"))
async def on_pay(cb: CallbackQuery, state: FSMContext) -> None:
    chat_id = common.chat_id_of(cb)
    await common.ack(cb)
    if not await common.gate(cb):
        return
    parts = cb.data.split(":")
    kind = parts[1] if len(parts) > 1 else ""
    ref = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None
    try:
        data = await home.fetch(chat_id)
    except Exception as exc:  # noqa: BLE001
        await home.report(cb, exc)
        return
    target = _target(chat_id, data, kind, ref)
    if target is None:
        await state.clear()
        await home.show_home(cb, t(chat_id, "pay.gone"))
        return

    flow: dict[str, Any] = {**target}
    if kind == "BANK":
        flow["desc"] = await _bank_description(chat_id, target.get("ref"))
    if kind in ("EMERGENCY", "INVESTMENTS"):
        try:
            holdings = await api.request(chat_id, "GET", "/finance/investments") or []
        except Exception as exc:  # noqa: BLE001
            await home.report(cb, exc)
            return
        accounts = _accounts(kind, holdings)
        options = [{"id": i["id"], "name": str(i.get("name") or "—")} for i in accounts]
        if kind == "EMERGENCY":
            fund = {"id": _FUND, "name": t(chat_id, "pay.fundOption")}
            last = storage.pref("account.EMERGENCY")
            options = [fund, *options] if last == _FUND else [*options, fund]
        if not options:
            await state.clear()
            await common.show(cb, t(chat_id, "pay.noAccount"), keyboards.app_home_kb(chat_id))
            return
        if len(options) > 1:
            await state.set_state(Pay.pick)
            await state.set_data({"pay": flow, "pay_accounts": options,
                                  "pay_wallets": ordered_wallets(data)})
            rows = [[(home.clip(_ICON[kind] + " " + o["name"], 40), f"pk:{i}")]
                    for i, o in enumerate(options)]
            rows.append(ui.nav(chat_id, cancel="home"))
            await common.show(cb, t(chat_id, "pay.header", icon=_ICON[kind], name=esc(flow["name"]),
                                    amount=fmt_money(flow["amount"])) + "\n\n" + t(chat_id, "pay.payInto"),
                              ikb(rows))
            return
        _choose(flow, options[0])
    await _start(cb, state, data, flow)


def _choose(flow: dict, option: dict) -> None:
    """Pay into this account. The plain fund is named by the flow itself ("Emergency fund")."""
    flow["accountId"] = option["id"]
    flow["account"] = None if option["id"] == _FUND else option["name"]


def _stale_data(d: dict, key: str, raw: str) -> bool:
    items = d.get(key) or []
    return not d.get("pay") or not raw.isdigit() or int(raw) >= len(items)


async def _stale(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb, t(common.chat_id_of(cb), "common.oldButton"), alert=True)
    await state.clear()
    await home.show_home(cb)


@router.callback_query(F.data.startswith("pk:"))
async def on_account(cb: CallbackQuery, state: FSMContext) -> None:
    d = await state.get_data()
    raw = cb.data.split(":", 1)[1]
    if _stale_data(d, "pay_accounts", raw):
        await _stale(cb, state)
        return
    await common.ack(cb)
    option = d["pay_accounts"][int(raw)]
    flow = dict(d["pay"])
    _choose(flow, option)
    await state.update_data(pay=flow, pay_accounts=None)
    await _wallet_screen(cb, state)


@router.callback_query(F.data == "pa")
async def on_other_amount(cb: CallbackQuery, state: FSMContext) -> None:
    chat_id = common.chat_id_of(cb)
    d = await state.get_data()
    if not d.get("pay"):
        await _stale(cb, state)
        return
    await common.ack(cb)
    await state.set_state(Pay.amount)
    await common.show(cb, t(chat_id, "pay.sendAmount", name=esc(d["pay"].get("name") or "")),
                      ikb([ui.nav(chat_id, cancel="home")]))


@router.message(StateFilter(Pay.amount))
async def on_amount_typed(message: Message, state: FSMContext) -> None:
    chat_id = common.chat_id_of(message)
    amount = parse_amount(message.text)
    if amount is None:
        await message.answer(t(chat_id, "common.positiveNumber"))
        return
    d = await state.get_data()
    flow = dict(d.get("pay") or {})
    if not flow:
        await state.clear()
        await home.show_home(message)
        return
    flow["amount"] = amount
    await state.update_data(pay=flow)
    await _wallet_screen(message, state)


@router.message(StateFilter(Pay.pick))
async def on_typed_while_picking(message: Message, state: FSMContext) -> None:
    """Typing at the bot always records: "50000 lunch" here leaves the payment for a new draft."""
    from . import record  # record imports this module
    await state.clear()
    await record.on_text(message, state)


# ── Recording ───────────────────────────────────────────────────────────────
def _request(flow: dict, card_id: int | None) -> tuple[str, dict]:
    """The endpoint and body for this payment, from `card_id` (None = cash), dated today."""
    amount, today, kind, ref = flow["amount"], clock.today_iso(), flow["kind"], flow.get("ref")
    card = {"cardId": card_id} if card_id is not None else {}
    if kind == "BILL":
        return f"/finance/monthly-payments/{ref}/pay", {
            "amount": amount, "paymentDate": today, "mode": "CASH" if card_id is None else "CARD", **card}
    if kind == "BANK":
        return "/transactions", {
            "type": "EXPENSE", "subType": "BANK_LOAN_PAYMENT", "amount": amount, "currency": CURRENCY,
            "description": flow.get("desc") or "Bank installment", "transactionDate": today,
            "cashAmount": amount if card_id is None else 0, **card}
    if kind in ("LOAN", "DEBT"):
        path = "loans-taken" if kind == "LOAN" else "debts"
        return f"/finance/{path}/{ref}/repay", {"amount": amount, "paymentDate": today, **card}
    if kind == "DONATION":
        # No recipient asked: saved without one, as the web does.
        return "/finance/donations", {"recipientName": "Anonymous", "anonymous": True, "amount": amount,
                                      "currency": CURRENCY, "donationDate": today, **card}
    if kind == "EMERGENCY" and flow.get("accountId") == _FUND:
        return "/emergencies", {"amount": amount, "currency": CURRENCY, "date": today, **card}
    target = ref if kind == "GOAL" else flow.get("accountId")
    return f"/finance/investments/{target}/contribute", {
        "amount": amount, "currency": CURRENCY, "date": today, **card}


@router.callback_query(F.data.startswith("pw:"))
async def on_wallet(cb: CallbackQuery, state: FSMContext) -> None:
    """The last tap: record it from this wallet, then show Home again."""
    chat_id = common.chat_id_of(cb)
    d = await state.get_data()
    raw = cb.data.split(":", 1)[1]
    if _stale_data(d, "pay_wallets", raw) or d.get("pay_accounts"):
        await _stale(cb, state)
        return
    await common.ack(cb)
    if not await common.gate(cb):
        return
    flow = d["pay"]
    wallet = d["pay_wallets"][int(raw)]
    card_id = wallet.get("cardId") if wallet.get("type") != "CASH" else None
    path, body = _request(flow, card_id)
    await common.begin_write(cb, chat_id)
    try:
        await api.request(chat_id, "POST", path, json=body)
    except Exception as exc:  # noqa: BLE001
        await state.clear()
        await home.report(cb, exc)
        return
    await state.clear()
    remember_wallet(card_id, "pay")
    if flow.get("accountId") is not None:
        storage.set_pref(f"account.{flow['kind']}", flow["accountId"])
    name = flow["name"] + (f" · {flow['account']}" if flow.get("account") else "")
    await home.show_home(cb, t(chat_id, "pay.done", amount=fmt_money(flow["amount"]), name=esc(name)))
