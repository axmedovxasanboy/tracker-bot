"""Paying — and the small forms Savings and Loans & bills are built from.

**Quick pay** (Home's Pay buttons, and every Pay / Add money / Take money out / Got money back on
Savings and Loans & bills): tap the button, tap the wallet — done, dated today. The endpoints are
the web's own pay dialogs:

* a bill            — POST /finance/monthly-payments/{id}/pay                (kind BILL)
* a bank installment — POST /transactions, sub-type BANK_LOAN_PAYMENT          (kind BANK)
* borrowed money    — POST /finance/loans-taken/{id}/repay                    (kind LOAN)
* a debt            — POST /finance/debts/{id}/repay                          (kind DEBT)
* money paid back to the owner — POST /finance/loans-given/{id}/mark-returned (kind GIVEN)
* the donation      — POST /finance/donations                                 (kind DONATION)
* investments / the emergency fund — one of the owner's own accounts from GET /finance/investments
  (opening balances included, goals left out, emergency-flagged ones for the emergency fund) via
  POST /finance/investments/{id}/contribute, or the plain fund record POST /emergencies
* a goal, or any one account ("Add money") — POST /finance/investments/{id}/contribute
                                                                   (kinds GOAL, HOLDING)
* taking money out of an account — POST /finance/investments/{id}/withdraw     (kind OUT)

Home's buttons re-read the advisor first and pay the CURRENT amount, so a screen scrolled up from
yesterday cannot pay yesterday's figure, and a bill paid from the web in the meantime says
"already taken care of" instead of being paid twice. Savings and Loans re-read their record the
same way before they start (see those routers). A flow carries `ret` — the callback of the screen
it came from — and goes back there when it is done or cancelled.

**Forms** (`Spec`, `open_form`): a few questions in a row, then a card with every answer, a ✏️ per
field and Save. An edit opens straight on the card. Savings and Loans register their forms in
`FORMS`; this module asks the questions and never knows what they are for.

Callbacks owned here: `pay:*`, `pw:*` (wallet), `pk:*` (account), `pa` (other amount).
"""
from __future__ import annotations

import datetime as dt
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message, TelegramObject

from .. import api, clock, common, keyboards, storage, ui
from ..config import CURRENCY
from ..i18n import cat_name, t
from ..keyboards import esc, ikb
from ..money import fmt_money, parse_amount, parse_number
from ..states import Pay
from . import home

router = Router(name="pay")
log = logging.getLogger(__name__)

_ICON = {"BILL": "💳", "BANK": "🏦", "LOAN": "🤝", "DEBT": "🤝", "GIVEN": "🤝", "DONATION": "🤲",
         "EMERGENCY": "🛟", "INVESTMENTS": "📈", "GOAL": "🎯", "HOLDING": "📈", "OUT": "⬇️"}
_FUND = "fund"  # the emergency fund without an account behind it
_NONE = "none"  # "Not from a wallet": the money was already there
# Money into one of the owner's own accounts. "Not from a wallet" exists only for these.
_SAVING = ("EMERGENCY", "INVESTMENTS", "GOAL", "HOLDING")
_EPSILON = 0.001


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


def wallet_button(chat_id: int | None, w: dict) -> str:
    return (("💵 " if w.get("type") == "CASH" else "💳 ")
            + t(chat_id, "pay.wallet", name=wallet_name(chat_id, w), amount=fmt_money(home.n(w.get("balance")))))


# ── Months and dates, shared by the Savings and Loans screens ───────────────
def shift_month(ym: str, n: int) -> str:
    y, m = int(ym[:4]), int(ym[5:7])
    total = y * 12 + (m - 1) + n
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def months_between(a: str, b: str) -> int:
    """Whole months from `a` to `b` (both YYYY-MM); negative when `b` is earlier."""
    return (int(b[:4]) * 12 + int(b[5:7])) - (int(a[:4]) * 12 + int(a[5:7]))


def last_day(ym: str) -> str:
    """The last day of a YYYY-MM month, as YYYY-MM-DD — how a deadline month is stored."""
    nxt = dt.date.fromisoformat(shift_month(ym, 1) + "-01")
    return (nxt - dt.timedelta(days=1)).isoformat()


def month_label(chat_id: int | None, ym: str | None) -> str:
    """`2027-03` → "Mar 2027"."""
    if not ym or not re.fullmatch(r"\d{4}-\d{2}.*", str(ym)):
        return "—"
    return f"{t(chat_id, f'common.mon.{int(str(ym)[5:7])}')} {str(ym)[:4]}"


def date_label(chat_id: int | None, value: Any) -> str:
    """"24 Sep", with the year when it is not this one."""
    if not value:
        return "—"
    text = ui.day(chat_id, value)
    year = str(value)[:4]
    return text if year == str(clock.today().year) or not year.isdigit() else f"{text} {year}"


def plural(chat_id: int | None, count: int, one: str, many: str) -> str:
    return t(chat_id, one if count == 1 else many, count=count)


_DATE_RE = re.compile(r"^(\d{1,2})[./-](\d{1,2})(?:[./-](\d{2}|\d{4}))?$")
_MONTH_RE = re.compile(r"^(?:(\d{4})[./-](\d{1,2})|(\d{1,2})[./-](\d{4}|\d{2}))$")


def parse_date(text: str | None) -> str | None:
    """`2026-09-24`, `24.09.2026`, `24/09/26`, `24.09` (this year) → ISO, or None."""
    raw = (text or "").strip()
    try:
        return dt.date.fromisoformat(raw).isoformat()
    except ValueError:
        pass
    m = _DATE_RE.match(raw)
    if not m:
        return None
    day, month, year = int(m.group(1)), int(m.group(2)), m.group(3)
    y = clock.today().year if year is None else int(year) + (2000 if len(year) == 2 else 0)
    try:
        return dt.date(y, month, day).isoformat()
    except ValueError:
        return None


def parse_month(text: str | None) -> str | None:
    """`2027-03`, `03.2027`, `3/27` → `2027-03`, or None."""
    m = _MONTH_RE.match((text or "").strip())
    if not m:
        return None
    if m.group(1):
        y, mo = int(m.group(1)), int(m.group(2))
    else:
        y, mo = int(m.group(4)), int(m.group(3))
        y += 2000 if y < 100 else 0
    return f"{y:04d}-{mo:02d}" if 1 <= mo <= 12 and 2000 <= y <= 2100 else None


# ── Where a flow goes back to ───────────────────────────────────────────────
# A flow's `ret` is the callback of the screen it started on ("sav:h:12", "loan", "home"). The
# routers that own those screens register a renderer here, so the pay flow can put its "✅ Paid"
# on top of the right screen without importing them (they import this module).
Screen = Callable[[TelegramObject, str | None, str], Awaitable[None]]
_RETURNS: dict[str, Screen] = {}


def register_return(prefix: str, screen: Screen) -> None:
    _RETURNS[prefix] = screen


async def back_to(event: TelegramObject, ret: str | None, notice: str | None = None) -> None:
    ret = ret or "home"
    screen = _RETURNS.get(ret.split(":", 1)[0])
    if screen is None:
        await home.show_home(event, notice)
        return
    await screen(event, notice, ret)


async def report(event: TelegramObject, exc: BaseException, back: str = "home") -> None:
    """Why a screen or a step failed, with a way back to `back`."""
    chat_id = common.chat_id_of(event)
    if isinstance(exc, api.NeedsLogin):
        await common.show(event, t(chat_id, "common.sessionExpired"), keyboards.login_kb(chat_id))
        return
    if isinstance(exc, api.Unreachable):
        text = t(chat_id, "common.serverUnreachable")
    elif isinstance(exc, api.ApiError):
        text = f"❌ {esc(exc.message)}"
    else:
        log.warning("A pay/savings/loans step failed", exc_info=exc)
        text = t(chat_id, "pay.loadError")
    rows = [[(t(chat_id, "common.retry"), back)]]
    if back != "home":
        rows.append(ui.nav(chat_id, home=True))
    await common.show(event, text, ikb(rows))


async def confirm(event: TelegramObject, text: str, yes: str, no: str) -> None:
    """"Delete this …?" — a destructive tap always gets a second one."""
    chat_id = common.chat_id_of(event)
    await common.show(event, text, ikb([[(t(chat_id, "pay.del.yes"), yes)],
                                        ui.nav(chat_id, back=no, home=True)]))


# ── Quick pay: finding what Home's button is for ────────────────────────────
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


async def bank_description(chat_id: int, ref: int | None) -> str:
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


# ── Quick pay: screens ──────────────────────────────────────────────────────
def _none_ok(flow: dict) -> bool:
    """"Not from a wallet" — only where a record can stand without money moving."""
    return flow.get("kind") in _SAVING and flow.get("accountId") != _FUND


def _header(chat_id: int, flow: dict) -> str:
    amount = flow.get("amount")
    return t(chat_id, "pay.header", icon=_ICON.get(flow.get("kind"), "💳"), name=esc(flow.get("name") or ""),
             amount=fmt_money(amount) if amount is not None else "…")


async def _wallet_screen(event, state: FSMContext) -> None:
    chat_id = common.chat_id_of(event)
    d = await state.get_data()
    flow = d.get("pay") or {}
    lines = [_header(chat_id, flow)]
    if flow.get("account"):
        lines.append(t(chat_id, "pay.into", name=esc(flow["account"])))
    if flow.get("note"):
        lines.append(flow["note"])
    lines += ["", t(chat_id, "pay.intoWhich" if flow.get("incoming") else "pay.fromWhich")]
    rows = [[(wallet_button(chat_id, w), f"pw:{i}")] for i, w in enumerate(d.get("pay_wallets") or [])]
    if _none_ok(flow):
        rows.append([(t(chat_id, "pay.noWallet"), "pw:n")])
    rows.append([(t(chat_id, "pay.otherAmount"), "pa"), (t(chat_id, "common.cancel"), flow.get("ret") or "home")])
    await state.set_state(Pay.pick)
    await common.show(event, "\n".join(lines), ikb(rows))


async def _account_screen(event, state: FSMContext) -> None:
    chat_id = common.chat_id_of(event)
    d = await state.get_data()
    flow = d.get("pay") or {}
    kind = flow.get("kind")
    rows = [[(home.clip(_ICON.get(kind, "📈") + " " + o["name"], 40), f"pk:{i}")]
            for i, o in enumerate(d.get("pay_accounts") or [])]
    rows.append(ui.nav(chat_id, cancel=flow.get("ret") or "home"))
    await state.set_state(Pay.pick)
    await common.show(event, _header(chat_id, flow) + "\n\n" + t(chat_id, "pay.payInto"), ikb(rows))


async def _amount_screen(event, state: FSMContext) -> None:
    chat_id = common.chat_id_of(event)
    d = await state.get_data()
    flow = d.get("pay") or {}
    lines = [t(chat_id, "pay.sendAmount", name=esc(flow.get("name") or ""))]
    if flow.get("max") is not None:
        lines.append(t(chat_id, "pay.upTo", amount=fmt_money(flow["max"])))
    rows = [[(label, f"pay:q:{i}")] for i, (label, _) in enumerate(flow.get("quick") or [])]
    rows.append(ui.nav(chat_id, cancel=flow.get("ret") or "home"))
    await state.set_state(Pay.amount)
    await common.show(event, "\n".join(lines), ikb(rows))


async def start_quick(event, state: FSMContext, flow: dict, data: dict | None = None) -> None:
    """Start paying `flow`: {kind, ref, name, amount (None = ask), ret, max?, quick?, incoming?,
    accountId?, account?}. `data` is the advisor answer when the caller already has one."""
    chat_id = common.chat_id_of(event)
    flow = dict(flow)
    try:
        if data is None:
            data = await home.fetch(chat_id)
        if flow.get("kind") == "BANK" and not flow.get("desc"):
            flow["desc"] = await bank_description(chat_id, flow.get("ref"))
        options = None
        if flow.get("kind") in ("EMERGENCY", "INVESTMENTS") and flow.get("accountId") is None:
            holdings = await api.request(chat_id, "GET", "/finance/investments") or []
            options = _options(chat_id, flow["kind"], holdings)
    except Exception as exc:  # noqa: BLE001
        await state.clear()
        await report(event, exc, flow.get("ret") or "home")
        return
    if options is not None and not options:
        await state.clear()
        await common.show(event, t(chat_id, "pay.noAccount"), ikb([
            [(t(chat_id, "pay.addInvestment"), "sav:new:inv")],
            ui.nav(chat_id, back=flow.get("ret") or "home", home=True)]))
        return
    if options is not None and len(options) == 1:
        _choose(flow, options[0])
        options = None
    await state.set_state(Pay.pick)
    await state.set_data({"pay": flow, "pay_accounts": options, "pay_wallets": ordered_wallets(data)})
    if flow.get("amount") is None:
        await _amount_screen(event, state)
    elif options:
        await _account_screen(event, state)
    else:
        await _wallet_screen(event, state)


def _options(chat_id: int, kind: str, holdings: list) -> list[dict]:
    accounts = _accounts(kind, holdings)
    options = [{"id": i["id"], "name": str(i.get("name") or "—")} for i in accounts]
    if kind == "EMERGENCY":
        fund = {"id": _FUND, "name": t(chat_id, "pay.fundOption")}
        last = storage.pref("account.EMERGENCY")
        options = [fund, *options] if last == _FUND else [*options, fund]
    return options


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
    d = await state.get_data()
    if not d.get("pay"):
        await _stale(cb, state)
        return
    await common.ack(cb)
    await _amount_screen(cb, state)


async def _amount_chosen(event, state: FSMContext, amount: float) -> None:
    d = await state.get_data()
    flow = dict(d.get("pay") or {})
    flow["amount"] = amount
    await state.update_data(pay=flow)
    if d.get("pay_accounts"):
        await _account_screen(event, state)
    else:
        await _wallet_screen(event, state)


def _too_much(flow: dict, amount: float) -> bool:
    return flow.get("max") is not None and amount > home.n(flow["max"]) + _EPSILON


@router.message(StateFilter(Pay.amount))
async def on_amount_typed(message: Message, state: FSMContext) -> None:
    chat_id = common.chat_id_of(message)
    amount = parse_amount(message.text)
    if amount is None:
        await message.answer(t(chat_id, "common.positiveNumber"))
        return
    d = await state.get_data()
    flow = d.get("pay") or {}
    if not flow:
        await state.clear()
        await home.show_home(message)
        return
    if _too_much(flow, amount):
        await message.answer(t(chat_id, "pay.tooMuch", amount=fmt_money(flow["max"])))
        return
    await _amount_chosen(message, state, amount)


@router.message(StateFilter(Pay.pick))
async def on_typed_while_picking(message: Message, state: FSMContext) -> None:
    """Typing at the bot always records: "50000 lunch" here leaves the payment for a new draft."""
    from . import record  # record imports this module
    await state.clear()
    await record.on_text(message, state)


# ── Quick pay: recording ────────────────────────────────────────────────────
def _request(flow: dict, wallet: int | str | None) -> tuple[str, dict]:
    """The endpoint and body for this payment. `wallet` is a card id, None (cash) or "none"."""
    amount, today, kind, ref = flow["amount"], clock.today_iso(), flow["kind"], flow.get("ref")
    card_id = wallet if isinstance(wallet, int) and not isinstance(wallet, bool) else None
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
    if kind == "GIVEN":
        return f"/finance/loans-given/{ref}/mark-returned", {"amount": amount, "paymentDate": today, **card}
    if kind == "DONATION":
        # No recipient asked: saved without one, as the web does.
        return "/finance/donations", {"recipientName": "Anonymous", "anonymous": True, "amount": amount,
                                      "currency": CURRENCY, "donationDate": today, **card}
    if kind == "OUT":
        return f"/finance/investments/{ref}/withdraw", {
            "amount": amount, "currency": CURRENCY, "date": today, "cardId": card_id}
    if kind == "EMERGENCY" and flow.get("accountId") == _FUND:
        return "/emergencies", {"amount": amount, "currency": CURRENCY, "date": today, **card}
    target = ref if kind in ("GOAL", "HOLDING") else flow.get("accountId")
    body = {"amount": amount, "currency": CURRENCY, "date": today, **card}
    if wallet == _NONE:
        body["noWallet"] = True
    return f"/finance/investments/{target}/contribute", body


def _done(chat_id: int, flow: dict, wallet: str | None, noted: str) -> str:
    amount = fmt_money(flow["amount"])
    kind = flow["kind"]
    if kind == "GIVEN":
        return t(chat_id, "pay.doneBack", amount=amount, name=noted)
    if kind == "OUT":
        return t(chat_id, "pay.doneOut", amount=amount, name=noted, wallet=esc(wallet or ""))
    if kind in _SAVING:
        return t(chat_id, "pay.doneNoWallet" if wallet is None else "pay.doneSaved", amount=amount, name=noted)
    return t(chat_id, "pay.done", amount=amount, name=noted)


@router.callback_query(F.data.startswith("pw:"))
async def on_wallet(cb: CallbackQuery, state: FSMContext) -> None:
    """The last tap: record it from (or into) this wallet, then go back where it started."""
    chat_id = common.chat_id_of(cb)
    d = await state.get_data()
    raw = cb.data.split(":", 1)[1]
    flow = d.get("pay") or {}
    none = raw == "n"
    if (none and (not flow or not _none_ok(flow))) or (not none and _stale_data(d, "pay_wallets", raw)) \
            or d.get("pay_accounts") or flow.get("amount") is None:
        await _stale(cb, state)
        return
    await common.ack(cb)
    if not await common.gate(cb):
        return
    if none:
        wallet: int | str | None = _NONE
        wallet_label = None
    else:
        w = d["pay_wallets"][int(raw)]
        wallet = w.get("cardId") if w.get("type") != "CASH" else None
        wallet_label = wallet_name(chat_id, w)
    path, body = _request(flow, wallet)
    await common.begin_write(cb, chat_id)
    try:
        await api.request(chat_id, "POST", path, json=body)
    except Exception as exc:  # noqa: BLE001
        await state.clear()
        await report(cb, exc, flow.get("ret") or "home")
        return
    await state.clear()
    if not none:
        remember_wallet(wallet if isinstance(wallet, int) else None, "pay")
    if flow.get("accountId") is not None:
        storage.set_pref(f"account.{flow['kind']}", flow["accountId"])
    name = esc(flow["name"] + (f" · {flow['account']}" if flow.get("account") else ""))
    await back_to(cb, flow.get("ret"), _done(chat_id, flow, wallet_label, name))


# ── Forms ───────────────────────────────────────────────────────────────────
class PayForm(StatesGroup):
    """A form's question that takes typed text, and its button-only screens (card, pickers)."""
    text = State()
    pick = State()


@dataclass(frozen=True)
class Field:
    """One question. `kind` is text · amount · value (a total, may be 0) · month · date · day ·
    wallet · choice · person · category."""
    key: str
    label: str                                # i18n key: the card's label and the question
    kind: str
    optional: bool = False
    walk: bool = True                         # asked on the way to the card (else only via ✏️)
    hint: str | None = None                   # i18n key of a line under the question
    options: tuple[tuple[str, str], ...] = ()  # choice: (value, i18n key)
    none_label: str | None = None             # wallet: the "no wallet" answer's i18n key
    incoming: bool = False                    # wallet: the money comes in
    person: str | None = None                 # person: LENDER | BORROWER
    new_label: str | None = None              # person: "New lender…"
    future: bool = False                      # date: offer dates ahead rather than behind
    min_month: str | None = None              # month: the earliest month on offer
    skip_label: str | None = None             # the optional answer's button, default "Skip"


@dataclass(frozen=True)
class Spec:
    title: Callable[[int, dict], str]                     # (chat_id, form) → the header
    fields: Callable[[dict], list[Field]]                 # (form) → the questions for these answers
    save: Callable[[TelegramObject, int, dict], Awaitable[tuple[str, str | None]]]  # → (notice, ret)
    submit: str = "pay.f.save"                            # the Save button's i18n key
    lines: Callable[[int, dict], list[str]] | None = None  # more lines on the card
    check: Callable[[int, dict], str | None] | None = None  # a problem to show instead of saving


FORMS: dict[str, Spec] = {}
_TYPED = ("text", "amount", "value", "month", "date")
_TEXT_LIMIT = 255


def _spec(form: dict) -> Spec:
    return FORMS[form["spec"]]


def _fields(form: dict) -> list[Field]:
    return _spec(form).fields(form)


def _field(form: dict, key: str | None) -> Field | None:
    return next((f for f in _fields(form) if f.key == key), None)


async def open_form(event, state: FSMContext, spec: str, *, vals: dict | None = None,
                    ctx: dict | None = None, ret: str = "home", card: bool = False) -> None:
    """Start a registered form. `card=True` (an edit) opens on the card with `vals` filled in."""
    form = {"spec": spec, "vals": dict(vals or {}), "asked": [], "field": None, "ret": ret,
            "ctx": dict(ctx or {}), "card": card, "opts": [], "err": None, "typing": False}
    if card:
        form["asked"] = [f.key for f in _spec(form).fields(form)]
    await state.set_state(PayForm.pick)
    await state.set_data({"pf": form})
    await _next(event, state, form)


async def _next(event, state: FSMContext, form: dict) -> None:
    """Ask the next question still unanswered on the way in, else show the card."""
    pending = next((f for f in _fields(form) if f.walk and f.key not in form["asked"]), None)
    if pending is not None:
        await _ask(event, state, form, pending)
    else:
        form["card"] = True
        await _card(event, state, form)


async def _render(event, state: FSMContext, form: dict, text: str, kb: InlineKeyboardMarkup) -> None:
    """Draw the form's screen, keeping ONE live keyboard: a typed answer strips the previous one."""
    if isinstance(event, CallbackQuery):
        await common.show(event, text, kb)
        if event.message is not None:
            form["ui"] = event.message.message_id
        await state.update_data(pf=form)
        return
    previous = form.get("ui")
    if previous and isinstance(event, Message) and event.bot is not None:
        try:
            await event.bot.edit_message_reply_markup(chat_id=event.chat.id, message_id=previous,
                                                      reply_markup=None)
        except TelegramBadRequest:
            pass  # already gone or already bare — either way nothing is left to tap
    sent = await event.answer(text, reply_markup=kb)
    form["ui"] = sent.message_id
    await state.update_data(pf=form)


def _shown(chat_id: int, form: dict, f: Field) -> str:
    """An answer as the card shows it."""
    v = form["vals"].get(f.key)
    if f.kind in ("wallet", "category"):
        return esc(form["vals"].get(f.key + "Name") or "—")
    if v is None or v == "":
        return "—"
    if f.kind in ("amount", "value"):
        return fmt_money(v)
    if f.kind == "month":
        return month_label(chat_id, v)
    if f.kind == "date":
        return date_label(chat_id, v)
    if f.kind == "choice":
        return next((t(chat_id, label) for value, label in f.options if value == v), esc(v))
    return esc(v)


async def _ask(event, state: FSMContext, form: dict, f: Field) -> None:
    chat_id = common.chat_id_of(event)
    form["field"], form["typing"], form["opts"] = f.key, False, []
    lines = [_spec(form).title(chat_id, form), "", f"<b>{t(chat_id, f.label)}</b>"]
    rows: list[list[tuple[str, str]]] = []
    opts: list[dict] = []
    try:
        opts = await _options_for(chat_id, form, f)
    except Exception as exc:  # noqa: BLE001
        await state.clear()
        await report(event, exc, form["ret"])
        return
    if f.kind in ("text", "person") and not opts:
        lines.append(t(chat_id, "pay.f.askText"))
        form["typing"] = True
    elif f.kind in ("amount", "value"):
        lines.append(t(chat_id, "pay.f.askAmount"))
    elif f.kind == "month":
        lines += [t(chat_id, "pay.f.askMonth"), t(chat_id, "pay.f.year", year=form.get("year") or "")]
    elif f.kind == "date":
        lines.append(t(chat_id, "pay.f.askDate"))
    elif f.kind == "person":
        lines.append(t(chat_id, "pay.f.askPerson"))
    if f.hint:
        lines.append(t(chat_id, f.hint))
    if form["card"] and (form["vals"].get(f.key) not in (None, "") or form["vals"].get(f.key + "Name")):
        lines.append(t(chat_id, "pay.f.now", value=_shown(chat_id, form, f)))

    per_row = {"day": 7, "month": 3, "date": 2}.get(f.kind, 1)
    if f.kind in ("category", "person"):
        per_row = 2
    buttons = [(o["t"], f"pay:f:o:{i}") for i, o in enumerate(opts)]
    rows += ui.grid(buttons, per_row)
    if f.kind == "month":
        year = int(form.get("year") or 0)
        paging = [(f"{year + 1} ▶️", f"pay:f:y:{year + 1}")]
        if not f.min_month or year - 1 >= int(f.min_month[:4]):
            paging.insert(0, (f"◀️ {year - 1}", f"pay:f:y:{year - 1}"))
        rows.append(paging)
    if f.optional:
        rows.append([(t(chat_id, f.skip_label or "common.skip"), "pay:f:s")])
    back = "pay:f:c" if form["card"] else "pay:f:b"
    rows.append(ui.nav(chat_id, back=back, cancel=form["ret"]))
    form["opts"] = opts
    # A person can also be typed straight in: a new name needs no "New lender…" tap first.
    await state.set_state(PayForm.text if f.kind in _TYPED or f.kind == "person" else PayForm.pick)
    await _render(event, state, form, "\n".join(lines), ikb(rows))


async def _options_for(chat_id: int, form: dict, f: Field) -> list[dict]:
    """The buttons under a question: {"t": label, "v": value, "n": the name the card shows}."""
    if f.kind == "wallet":
        data = await home.fetch(chat_id)
        opts = [{"t": wallet_button(chat_id, w), "n": wallet_name(chat_id, w),
                 "v": "cash" if w.get("type") == "CASH" else w.get("cardId")}
                for w in ordered_wallets(data)]
        if f.none_label:
            opts.append({"t": t(chat_id, f.none_label), "v": _NONE, "n": t(chat_id, f.none_label)})
        return opts
    if f.kind == "choice":
        return [{"t": t(chat_id, label), "v": value} for value, label in f.options]
    if f.kind == "day":
        return [{"t": str(day), "v": day} for day in range(1, 32)]
    if f.kind == "month":
        current = form["vals"].get(f.key) or f.min_month or clock.month()
        if not form.get("year"):
            form["year"] = int(str(current)[:4])
        year = int(form["year"])
        floor = f.min_month or "0000-00"
        return [{"t": t(chat_id, f"common.mon.{m}"), "v": f"{year:04d}-{m:02d}"}
                for m in range(1, 13) if f"{year:04d}-{m:02d}" >= floor]
    if f.kind == "date":
        today = clock.today()
        if f.future:
            picks = [("pay.f.in1m", 1), ("pay.f.in3m", 3), ("pay.f.in6m", 6)]
            return [{"t": t(chat_id, key), "v": _plus_months(today, n).isoformat()} for key, n in picks]
        return [{"t": t(chat_id, "common.today"), "v": today.isoformat()},
                {"t": t(chat_id, "common.yesterday"), "v": (today - dt.timedelta(days=1)).isoformat()}]
    if f.kind == "category":
        roots = await api.request(chat_id, "GET", "/categories", params={"type": "EXPENSE"}) or []
        opts = [{"t": t(chat_id, "pay.f.noCategory"), "v": None, "n": t(chat_id, "pay.f.noCategory")}]
        for root in (r for r in roots if isinstance(r, dict) and r.get("parentId") is None):
            opts.append({"t": home.clip(cat_name(chat_id, root), 30), "v": root.get("id"),
                         "n": cat_name(chat_id, root)})
            for child in root.get("children") or []:
                label = f"{cat_name(chat_id, root)} › {cat_name(chat_id, child)}"
                opts.append({"t": home.clip(label, 30), "v": child.get("id"), "n": label})
        return opts
    if f.kind == "person" and not form.get("typing"):
        path = "/people/lenders" if f.person == "LENDER" else "/people/borrowers"
        try:
            people = await api.request(chat_id, "GET", path) or []
        except api.ApiError as exc:
            if exc.status == 404:  # a server that keeps no people: the name is typed, as before
                return []
            raise
        people = sorted((p for p in people if isinstance(p, dict)),
                        key=lambda p: (-int(home.n(p.get("times"))), -home.n(p.get("total"))))
        if not people:
            return []
        opts = [{"t": home.clip(str(p.get("name") or "—"), 30), "v": p.get("id"), "n": str(p.get("name") or "—")}
                for p in people[:20]]
        opts.append({"t": t(chat_id, f.new_label or "pay.f.newPerson"), "v": "new", "n": ""})
        return opts
    return []


def _plus_months(d: dt.date, n: int) -> dt.date:
    ym = shift_month(clock.month_of(d), n)
    last = int(last_day(ym)[8:10])
    return dt.date(int(ym[:4]), int(ym[5:7]), min(d.day, last))


async def _card(event, state: FSMContext, form: dict) -> None:
    chat_id = common.chat_id_of(event)
    spec = _spec(form)
    form["field"], form["typing"], form["opts"] = None, False, []
    lines = [spec.title(chat_id, form), ""]
    fields = _fields(form)
    for f in fields:
        lines.append(t(chat_id, "pay.f.row", label=t(chat_id, f.label), value=_shown(chat_id, form, f)))
    if spec.lines:
        extra = [line for line in spec.lines(chat_id, form) if line]
        if extra:
            lines += [""] + extra
    if form.get("err"):
        lines += ["", form["err"]]
    edits = [("✏️ " + home.clip(t(chat_id, f.label), 22), f"pay:f:e:{f.key}") for f in fields]
    rows = ui.grid(edits, 2)
    rows.append([(t(chat_id, spec.submit), "pay:f:ok"), (t(chat_id, "common.cancel"), form["ret"])])
    await state.set_state(PayForm.pick)
    await _render(event, state, form, "\n".join(lines), ikb(rows))


async def _answered(event, state: FSMContext, form: dict, f: Field) -> None:
    form["err"], form["year"] = None, None
    if f.key not in form["asked"]:
        form["asked"].append(f.key)
    await _next(event, state, form)


async def _form(cb: CallbackQuery, state: FSMContext) -> dict | None:
    """The open form, or None after telling the owner this button outlived it."""
    form = (await state.get_data()).get("pf")
    if not form or form.get("spec") not in FORMS:
        await _stale(cb, state)
        return None
    await common.ack(cb)
    return form


@router.callback_query(F.data.startswith("pay:f:o:"))
async def f_option(cb: CallbackQuery, state: FSMContext) -> None:
    form = await _form(cb, state)
    if form is None:
        return
    f = _field(form, form.get("field"))
    raw = cb.data.rsplit(":", 1)[1]
    opts = form.get("opts") or []
    if f is None or not raw.isdigit() or int(raw) >= len(opts):
        await _card(cb, state, form)
        return
    opt = opts[int(raw)]
    vals = form["vals"]
    if f.kind == "person" and opt["v"] == "new":
        form["typing"] = True
        await _ask_typed_name(cb, state, form, f)
        return
    vals[f.key] = opt["v"]
    if f.kind in ("wallet", "category"):
        vals[f.key + "Name"] = opt.get("n")
    if f.kind == "person":
        vals[f.key], vals[f.key + "Id"] = opt.get("n"), opt["v"]
    await _answered(cb, state, form, f)


async def _ask_typed_name(event, state: FSMContext, form: dict, f: Field) -> None:
    chat_id = common.chat_id_of(event)
    form["opts"] = []
    text = "\n".join([_spec(form).title(chat_id, form), "", f"<b>{t(chat_id, 'pay.f.name')}</b>",
                      t(chat_id, "pay.f.askText")])
    back = "pay:f:c" if form["card"] else "pay:f:b"
    await state.set_state(PayForm.text)
    await _render(event, state, form, text, ikb([ui.nav(chat_id, back=back, cancel=form["ret"])]))


@router.callback_query(F.data.startswith("pay:f:y:"))
async def f_year(cb: CallbackQuery, state: FSMContext) -> None:
    form = await _form(cb, state)
    if form is None:
        return
    f = _field(form, form.get("field"))
    raw = cb.data.rsplit(":", 1)[1]
    if f is None or f.kind != "month" or not raw.isdigit():
        await _card(cb, state, form)
        return
    floor = int((f.min_month or "2000")[:4])
    form["year"] = min(max(int(raw), floor), 2100)
    await _ask(cb, state, form, f)


@router.callback_query(F.data == "pay:f:s")
async def f_skip(cb: CallbackQuery, state: FSMContext) -> None:
    form = await _form(cb, state)
    if form is None:
        return
    f = _field(form, form.get("field"))
    if f is None or not f.optional:
        await _card(cb, state, form)
        return
    form["vals"][f.key] = None
    await _answered(cb, state, form, f)


@router.callback_query(F.data.startswith("pay:f:e:"))
async def f_edit(cb: CallbackQuery, state: FSMContext) -> None:
    form = await _form(cb, state)
    if form is None:
        return
    f = _field(form, cb.data.split(":", 3)[3])
    if f is None:
        await _card(cb, state, form)
        return
    form["year"] = None
    await _ask(cb, state, form, f)


@router.callback_query(F.data == "pay:f:c")
async def f_to_card(cb: CallbackQuery, state: FSMContext) -> None:
    form = await _form(cb, state)
    if form is not None:
        await _card(cb, state, form)


@router.callback_query(F.data == "pay:f:b")
async def f_back(cb: CallbackQuery, state: FSMContext) -> None:
    """Back on the way in: the question before this one (or out, from the first)."""
    form = await _form(cb, state)
    if form is None:
        return
    if form.get("typing") and _field(form, form.get("field")) and \
            _field(form, form["field"]).kind == "person" and form.get("opts") == []:
        form["typing"] = False
        f = _field(form, form["field"])
        if await _has_people(cb, form, f):
            await _ask(cb, state, form, f)
            return
    if not form["asked"]:
        await state.clear()
        await back_to(cb, form["ret"])
        return
    key = form["asked"].pop()
    f = _field(form, key)
    if f is None:
        await _next(cb, state, form)
        return
    form["year"] = None
    await _ask(cb, state, form, f)


async def _has_people(cb: CallbackQuery, form: dict, f: Field) -> bool:
    try:
        return bool(await _options_for(common.chat_id_of(cb), form, f))
    except Exception:  # noqa: BLE001
        return False


@router.callback_query(F.data == "pay:f:ok")
async def f_save(cb: CallbackQuery, state: FSMContext) -> None:
    chat_id = common.chat_id_of(cb)
    form = await _form(cb, state)
    if form is None:
        return
    if not await common.gate(cb):
        return
    spec = _spec(form)
    missing = next((f for f in _fields(form) if not f.optional and form["vals"].get(f.key) in (None, "")
                    and f.kind not in ("category",)), None)
    if missing is not None:
        await _ask(cb, state, form, missing)
        return
    problem = spec.check(chat_id, form) if spec.check else None
    if problem:
        form["err"] = f"⚠️ {problem}"
        await _card(cb, state, form)
        return
    await common.begin_write(cb, chat_id)
    try:
        notice, ret = await spec.save(cb, chat_id, form)
    except api.ApiError as exc:
        if isinstance(exc, api.Unreachable):
            form["err"] = t(chat_id, "common.serverUnreachable")
        else:
            form["err"] = f"❌ {esc(exc.message)}"
        await _card(cb, state, form)
        return
    except Exception as exc:  # noqa: BLE001 — NeedsLogin and the unexpected: say so, keep nothing half-done
        await state.clear()
        await report(cb, exc, form["ret"])
        return
    await state.clear()
    await back_to(cb, ret or form["ret"], notice)


@router.message(StateFilter(PayForm.text))
async def f_typed(message: Message, state: FSMContext) -> None:
    chat_id = common.chat_id_of(message)
    form = (await state.get_data()).get("pf")
    f = _field(form, form.get("field")) if form and form.get("spec") in FORMS else None
    if f is None:
        await state.clear()
        await home.show_home(message)
        return
    text = (message.text or "").strip()
    vals = form["vals"]
    if f.kind in ("text", "person"):
        if not text or len(text) > _TEXT_LIMIT:
            await message.answer(t(chat_id, "pay.f.errText"))
            return
        vals[f.key] = text
        if f.kind == "person":
            vals[f.key + "Id"] = None
    elif f.kind == "amount":
        amount = parse_amount(text)
        if amount is None:
            await message.answer(t(chat_id, "common.positiveNumber"))
            return
        vals[f.key] = amount
    elif f.kind == "value":
        value = parse_number(text)
        if value is None or value < 0:
            await message.answer(t(chat_id, "common.sendNumberExample"))
            return
        vals[f.key] = value
    elif f.kind == "month":
        month = parse_month(text)
        if month is None or (f.min_month and month < f.min_month):
            await message.answer(t(chat_id, "pay.f.errMonth"))
            return
        vals[f.key] = month
    elif f.kind == "date":
        day = parse_date(text)
        if day is None:
            await message.answer(t(chat_id, "pay.f.errDate"))
            return
        vals[f.key] = day
    else:
        await message.answer(t(chat_id, "pay.f.tapButton"))
        return
    await _answered(message, state, form, f)


@router.message(StateFilter(PayForm.pick))
async def f_typed_while_picking(message: Message, state: FSMContext) -> None:
    """A question answered with buttons: typed money still records, as everywhere else."""
    await on_typed_while_picking(message, state)


# ── Quick pay: the entry points ─────────────────────────────────────────────
# Registered after every other `pay:…` handler on purpose: this one takes whatever `pay:` is left,
# which is Home's `pay:KIND[:ref[:ret]]`.
@router.callback_query(F.data.startswith("pay:q:"))
async def on_quick_amount(cb: CallbackQuery, state: FSMContext) -> None:
    """A shortcut under the amount question — "All · 5 000 000 UZS", "Full"."""
    d = await state.get_data()
    flow = d.get("pay") or {}
    raw = cb.data.rsplit(":", 1)[1]
    quick = flow.get("quick") or []
    if not flow or not raw.isdigit() or int(raw) >= len(quick):
        await _stale(cb, state)
        return
    await common.ack(cb)
    await _amount_chosen(cb, state, float(quick[int(raw)][1]))


@router.callback_query(F.data.startswith("pay:m:"))
async def on_add_more(cb: CallbackQuery, state: FSMContext) -> None:
    """"Add more" on a savings row that is already met: `pay:m:KIND:ref[:ret]`, amount asked first."""
    chat_id = common.chat_id_of(cb)
    await common.ack(cb)
    if not await common.gate(cb):
        return
    parts = cb.data.split(":")
    kind = parts[2] if len(parts) > 2 else ""
    ref = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() and int(parts[3]) else None
    ret = ":".join(parts[4:]) or "home"
    if kind not in (*home.BUCKETS, "GOAL") or (kind == "GOAL" and ref is None):
        await _stale(cb, state)
        return
    name = t(chat_id, home.BUCKET_KEY[kind]) if kind in home.BUCKET_KEY else ""
    if kind == "GOAL":
        try:
            goal = await _holding(chat_id, ref)
        except Exception as exc:  # noqa: BLE001
            await report(cb, exc, ret)
            return
        if goal is None:
            await back_to(cb, ret, t(chat_id, "pay.gone"))
            return
        name = str(goal.get("name") or "—")
    await start_quick(cb, state, {"kind": kind, "ref": ref, "name": name, "amount": None, "ret": ret})


async def _holding(chat_id: int, ref: int | None) -> dict | None:
    holdings = await api.request(chat_id, "GET", "/finance/investments") or []
    return next((i for i in holdings if isinstance(i, dict) and i.get("id") == ref), None)


@router.callback_query(F.data.startswith("pay:"))
async def on_pay(cb: CallbackQuery, state: FSMContext) -> None:
    """A Pay button on Home or Savings: `pay:KIND[:ref[:ret]]`, paying what is due right now."""
    chat_id = common.chat_id_of(cb)
    await common.ack(cb)
    if not await common.gate(cb):
        return
    parts = cb.data.split(":")
    kind = parts[1] if len(parts) > 1 else ""
    ref = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None
    ret = ":".join(parts[3:]) or "home"
    try:
        data = await home.fetch(chat_id)
    except Exception as exc:  # noqa: BLE001
        await report(cb, exc, ret)
        return
    target = _target(chat_id, data, kind, ref)
    if target is None:
        await state.clear()
        await back_to(cb, ret, t(chat_id, "pay.gone"))
        return
    await start_quick(cb, state, {**target, "ret": ret}, data)
