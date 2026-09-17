"""Finance: nine record sections, the money actions behind them, and the "already paid" marks.

Every screen here is built from one registry, `SECTIONS`. That is not tidiness for its own
sake: the eight sections used to be eight hand-written render functions that agreed on
nothing, so a capability added to one — a Pay button, a delete, a page — existed nowhere
else, and the owner's phone could create finance records but never correct one. A record is
now a *thing you can open*: the list gives it a row, the row opens a detail screen, and the
detail screen carries every verb the backend supports for it (pay / repay / contribute,
history, edit, delete, and pause for a subscription).

Four rules the registry encodes, each of them a bug that was live:

* **A create that moves money must ask which wallet it comes from.** `DonationRequest`,
  `InvestmentRequest` and `EmergencyRequest` all carry a `cardId` whose null branch books the
  whole amount against the cash pot (`FinanceService.createBucketTransaction`). The bot never
  sent one, so every donation and investment made from the phone silently drained cash
  whatever the owner actually paid with. The three specs that book a wallet transaction now
  declare `wallet` and are asked before the wizard starts.

* **An edit is a full replace, so it must round-trip the record.** Every `PUT /finance/*`
  maps the request onto the entity field by field (`applyMonthlyPayment`, `applyInvestment`,
  `updateDebt` …), which means an omitted field is not "unchanged" — it is *erased*. Each
  section therefore carries a `to_request` that rebuilds the whole body from the GET
  response; the edit overwrites exactly one key of it.

* **Dates are the product's primary key.** The money model is a monthly envelope and a month
  is closed permanently, so a rent payment settled on the 30th and recorded on the 2nd has to
  be bookable against the month it happened in. Every action ends with a date step (defaulting
  to today), and the mark's month is derived from it rather than from the clock.

* **Marks are the one write with no transaction behind it**, which is exactly why they need a
  list and an undo — `FinanceService.listMarks` says so in its own javadoc. A mistyped mark is
  otherwise invisible and permanent, and it inflates every allocation bucket for good.
"""
import datetime as dt

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from . import wizard
from .. import api, common, keyboards, ui
from ..clock import month as current_month
from ..clock import today, today_iso
from ..config import CURRENCY
from ..i18n import t
from ..keyboards import esc, ikb
from ..money import fmt_money, fmt_pct, parse_amount
from ..states import FinAction, FinEdit, GoalValue

router = Router()

# Six records to a page. A Telegram inline keyboard scrolls with the message rather than
# inside itself, so a section that renders one row per record plus Add, Back and a pager
# pushes its own actions off the bottom of the screen at about ten.
PAGE_SIZE = 6
# History is a "did I already pay this?" check, not an archive. Fifteen rows is more than a
# year of a monthly subscription and still fits in one message.
HISTORY_ROWS = 15

# The savings section used to answer to `fin:savings` while its create spec was keyed
# "goal". One key now, plus the old spelling so a button already sitting in the chat keeps
# working after the deploy.
SECTION_ALIASES = {"savings": "goal"}


# ── small shared helpers ────────────────────────────────────────────────────
def _find(items, cid):
    return next((c for c in items if c.get("id") == cid), None)


def _num(value) -> float:
    """A JSON number that may be null or a string, as a float. Never raises."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _yesterday_iso() -> str:
    return (today() - dt.timedelta(days=1)).isoformat()


def _valid_date(raw: str | None) -> str | None:
    """Normalise a typed YYYY-MM-DD, or None. Parsing only — `today` comes from clock.py."""
    try:
        return dt.date.fromisoformat((raw or "").strip()).isoformat()
    except ValueError:
        return None


def _shift_month(ym: str, delta: int) -> str:
    """"2026-01" shifted by ±N months. Arithmetic on the month index, so December wraps."""
    year, month = int(ym[:4]), int(ym[5:7])
    index = year * 12 + (month - 1) + delta
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


async def _report(event, exc: BaseException, kb, *, generic: str = "common.serverUnreachable") -> None:
    """Render a failed API call in the chat's language.

    `Unreachable` is checked before `ApiError` (it is a subclass) so a network blip shows the
    translated sentence rather than httpx's English one; a genuine 4xx keeps the backend's own
    message, because "amount: must not be null" is the only thing on screen that says which
    field the owner has to fix.
    """
    chat_id = common.chat_id_of(event)
    if isinstance(exc, api.NeedsLogin):
        await common.show(event, t(chat_id, "common.sessionExpired"), keyboards.login_kb(chat_id))
    elif isinstance(exc, api.Unreachable):
        await common.show(event, t(chat_id, "common.serverUnreachable"), kb)
    elif isinstance(exc, api.ApiError):
        await common.show(event, f"❌ {esc(exc.message)}", kb)
    else:
        # httpx transport failures on the main request reach routers raw (see api.py) —
        # deliberately, so they land here and get translated instead of printing in English.
        await common.show(event, t(chat_id, generic), kb)


async def _fetch(event, path: str, params: dict | None = None, kb=None):
    """GET a list, or None having already told the user why not."""
    chat_id = common.chat_id_of(event)
    try:
        return await api.request(chat_id, "GET", path, params=params) or []
    except Exception as exc:  # noqa: BLE001 — dispatched by type in _report
        await _report(event, exc, kb or _back_kb(chat_id), generic="fin.sectionLoadError")
        return None


# ── keyboards ───────────────────────────────────────────────────────────────
def _menu_kb(chat_id: int):
    return ikb([
        [(t(chat_id, "fin.menu.debts"), "fin:debt"), (t(chat_id, "fin.menu.loanGiven"), "fin:loangiven")],
        [(t(chat_id, "fin.menu.loanTaken"), "fin:loantaken"), (t(chat_id, "fin.menu.bankLoan"), "fin:bankloan")],
        [(t(chat_id, "fin.menu.subscriptions"), "fin:monthly"), (t(chat_id, "fin.menu.donations"), "fin:donation")],
        [(t(chat_id, "fin.menu.investments"), "fin:investment"), (t(chat_id, "fin.menu.savingsGoals"), "fin:goal")],
        [(t(chat_id, "fin.menu.emergency"), "fin:emergency"), (t(chat_id, "fin.menu.marks"), "fmarks")],
        [(t(chat_id, "common.menu"), "menu:home")],
    ])


def _back_kb(chat_id: int, section: str | None = None):
    if section and section in SECTIONS:
        return ikb([[(t(chat_id, "fin.backToSection"), f"fin:{section}"),
                     (t(chat_id, "fin.backToFinance"), "menu:finance")]])
    return ikb([[(t(chat_id, "fin.backToFinance"), "menu:finance")]])


async def _wallet_rows(event, *, none_cb: str | None = None, prefix: str = "fasrc:") -> tuple:
    """Cash + every UZS card, as one button per row.

    One per row rather than a grid: a card button carries a name and its last four digits,
    and two of those on one line truncate to nothing useful on a phone.

    **A failed GET /cards raises out of here** — it is not caught and turned into an empty
    list. A swallowed failure rendered as a picker offering Cash alone, which reads as "you
    have no cards": the owner then books a card payment against the cash pot, which is wrong
    on two wallet balances and is not discovered until month-close. Both callers show a retry
    instead. (`transactions.py` already refuses the same way, for the same reason.)
    """
    chat_id = common.chat_id_of(event)
    cards = await api.request(chat_id, "GET", "/cards") or []
    cards = [c for c in cards if c.get("currency") == CURRENCY and c.get("type") != "CASH"]
    rows = [[(t(chat_id, "common.cashBtn"), f"{prefix}cash")]]
    for c in cards:
        rows.append([(f"💳 {c.get('name', 'Card')} ···{c.get('lastFourDigits', '')}",
                      f"{prefix}card:{c['id']}")])
    if none_cb:
        rows.append([(t(chat_id, "fin.noneRecordOnly"), none_cb)])
    return rows, cards


# ── list-line renderers ─────────────────────────────────────────────────────
# Every renderer takes (chat_id, record, extra) so the registry can call them uniformly;
# `extra` carries whatever the section's `annotate` hook fetched once for the whole page.
def _line_debt(chat_id, d, extra):
    due = t(chat_id, "fin.suffixDue", date=esc(d["dueDate"])) if d.get("dueDate") else ""
    return t(chat_id, "fin.debtLine", name=esc(d.get("creditorName")),
             remaining=fmt_money(d.get("remainingAmount")),
             total=fmt_money(d.get("totalAmount")), due=due)


def _line_loan_taken(chat_id, l, extra):
    due = t(chat_id, "fin.suffixDue", date=esc(l["dueDate"])) if l.get("dueDate") else ""
    start = (t(chat_id, "fin.suffixPaysFrom", month=esc(l["paymentStartDate"][:7]))
             if l.get("paymentStartDate") else "")
    return t(chat_id, "fin.loanTakenLine", name=esc(l.get("lenderName")),
             remaining=fmt_money(l.get("remainingAmount")),
             total=fmt_money(l.get("totalAmount")), due=due, start=start)


def _line_loan_given(chat_id, l, extra):
    exp = (t(chat_id, "fin.suffixExpect", date=esc(l["expectedReturnDate"]))
           if l.get("expectedReturnDate") else "")
    return t(chat_id, "fin.loanGivenLine", name=esc(l.get("debtorName")),
             pending=fmt_money(l.get("pendingAmount")),
             total=fmt_money(l.get("totalAmount")), exp=exp)


def _line_bank_loan(chat_id, b, extra):
    monthly = (t(chat_id, "fin.suffixMonthly", amount=fmt_money(b.get("monthlyPayment")))
               if b.get("monthlyPayment") else "")
    end = t(chat_id, "fin.suffixEnds", date=esc(b["endDate"])) if b.get("endDate") else ""
    return t(chat_id, "fin.bankLoanLine", bank=esc(b.get("bankName")), loan=esc(b.get("loanName")),
             total=fmt_money(b.get("totalAmount")), monthly=monthly, end=end)


def _monthly_covered(m, extra) -> bool:
    """True when the Plan no longer counts this subscription as owing anything this month.

    Read from `pendingSubscriptions`, which is the same figure the Plan screen withholds the
    allocation over — so the bot and the Plan can never disagree about what is still due.
    A subscription absent from the pending list is fully covered by real payments plus marks.
    """
    return bool(extra.get("known")) and m.get("id") not in extra.get("pending", {})


def _line_monthly(chat_id, m, extra):
    active = "" if m.get("active", True) else t(chat_id, "fin.suffixPaused")
    due = t(chat_id, "fin.suffixDay", day=m["dueDay"]) if m.get("dueDay") else ""
    paid = ""
    if m.get("active", True) and extra.get("known"):
        if _monthly_covered(m, extra):
            paid = t(chat_id, "fin.suffixPaidThisMonth")
        elif extra["pending"].get(m.get("id"), 0) > 0:
            paid = t(chat_id, "fin.suffixPartlyPaid",
                     paid=fmt_money(extra["pending"][m["id"]]))
    return t(chat_id, "fin.monthlyLine", name=esc(m.get("name")), amount=fmt_money(m.get("amount")),
             due=due, active=active) + paid


def _line_donation(chat_id, d, extra):
    who = d.get("displayName") or d.get("recipientName") or "—"
    return t(chat_id, "fin.donationLine", date=esc(d.get("donationDate", "")),
             who=esc(who), amount=fmt_money(d.get("amount")))


def _investment_type(chat_id, code) -> str:
    """The type in the chat's language, from the same table the create wizard offers.

    The list used to print `str(enum).replace("_", " ").title()`, so the owner picked
    "Koʻchmas mulk" on one screen and was told he owned a "Real Estate" on the next. The
    fallback keeps an enum this bot has not been taught readable instead of blank.
    """
    key = INVESTMENT_TYPE_KEY.get(str(code or ""))
    return t(chat_id, key) if key else str(code or "").replace("_", " ")


def _line_investment(chat_id, i, extra):
    tag = t(chat_id, "fin.suffixOpening") if i.get("openingBalance") else ""
    return t(chat_id, "fin.investmentLine", name=esc(i.get("name")),
             type=esc(_investment_type(chat_id, i.get("type"))),
             amount=fmt_money(i.get("investedAmount")), tag=tag)


def _line_goal(chat_id, g, extra):
    value = g.get("currentValue")
    if value is None:
        value = g.get("investedAmount")
    tgt = (t(chat_id, "fin.suffixTarget", amount=fmt_money(g.get("targetAmount")))
           if g.get("targetAmount") is not None else "")
    prog = (t(chat_id, "fin.suffixProgress", pct=fmt_pct(g.get("progressPercent")))
            if g.get("progressPercent") is not None else "")
    return t(chat_id, "fin.savingsLine", name=esc(g.get("name")), value=fmt_money(value),
             target=tgt, progress=prog)


def _line_emergency(chat_id, e, extra):
    note = t(chat_id, "fin.suffixNote", note=esc(e["description"])) if e.get("description") else ""
    return t(chat_id, "fin.emergencyLine", date=esc(e.get("date", "")),
             amount=fmt_money(e.get("amount")), note=note)


# ── detail-screen extras ────────────────────────────────────────────────────
def _detail_monthly(chat_id, m, extra):
    out = []
    count = m.get("paymentCount") or 0
    if count:
        out.append(t(chat_id, "fin.detailPaidTotal", total=fmt_money(m.get("totalPaid")), count=count))
    if m.get("nextDueDate"):
        out.append(t(chat_id, "fin.detailNextDue", date=esc(m["nextDueDate"])))
    return out


def _detail_investment(chat_id, i, extra):
    out = []
    if i.get("broker"):
        out.append(t(chat_id, "fin.detailBroker", broker=esc(i["broker"])))
    if i.get("purchaseDate"):
        out.append(t(chat_id, "fin.detailSince", date=esc(i["purchaseDate"])))
    return out


def _detail_bank_loan(chat_id, b, extra):
    return [t(chat_id, "fin.detailSince", date=esc(b["takenDate"]))] if b.get("takenDate") else []


# ── PUT bodies ──────────────────────────────────────────────────────────────
# Every finance PUT maps the request onto the entity field by field, so an omitted field is
# erased rather than left alone. These rebuild the complete body from the GET response; the
# edit then overwrites exactly one key. Fields the backend only writes when non-null
# (paidAmount, receivedAmount, status) are deliberately left OUT, so an edit can never rewind
# a repayment that landed between the read and the write.
def _req_debt(r):
    return {"creditorName": r.get("creditorName"), "totalAmount": r.get("totalAmount"),
            "currency": CURRENCY, "borrowedDate": r.get("borrowedDate"),
            "dueDate": r.get("dueDate"), "paymentStartDate": r.get("paymentStartDate"),
            "description": r.get("description")}


def _req_loan_given(r):
    return {"debtorName": r.get("debtorName"), "totalAmount": r.get("totalAmount"),
            "currency": CURRENCY, "lentDate": r.get("lentDate"),
            "expectedReturnDate": r.get("expectedReturnDate"), "description": r.get("description")}


def _req_loan_taken(r):
    return {"lenderName": r.get("lenderName"), "totalAmount": r.get("totalAmount"),
            "currency": CURRENCY, "borrowedDate": r.get("borrowedDate"),
            "dueDate": r.get("dueDate"), "plannedMonthlyPayment": r.get("plannedMonthlyPayment"),
            "paymentStartDate": r.get("paymentStartDate"), "description": r.get("description")}


def _req_bank_loan(r):
    return {"bankName": r.get("bankName"), "loanName": r.get("loanName"),
            "totalAmount": r.get("totalAmount"), "currency": CURRENCY,
            "takenDate": r.get("takenDate"), "endDate": r.get("endDate"),
            "monthlyPayment": r.get("monthlyPayment")}


def _req_monthly(r):
    # nextDueDate, subscribedSince and the category are set unconditionally by
    # applyMonthlyPayment — dropping them from an edit would quietly wipe the schedule.
    return {"name": r.get("name"), "amount": r.get("amount"), "currency": CURRENCY,
            "dueDay": r.get("dueDay"), "active": bool(r.get("active", True)),
            "description": r.get("description"), "nextDueDate": r.get("nextDueDate"),
            "subscribedSince": r.get("subscribedSince"),
            "categoryId": (r.get("category") or {}).get("id")}


def _req_donation(r):
    return {"recipientName": r.get("recipientName"), "amount": r.get("amount"),
            "currency": CURRENCY, "donationDate": r.get("donationDate"),
            "description": r.get("description"), "anonymous": r.get("anonymous")}


def _req_investment(r):
    # openingBalance / emergencyFund / savingsGoal are re-derived from the request on every
    # update, so all three travel back or a plain rename would turn a savings goal into an
    # investment and move it between allocation buckets.
    #
    # currentValue is the one field that must NOT be echoed as it arrives. The COLUMN is
    # nullable and null means "this holding's value tracks its invested total"; the RESPONSE
    # never shows that null, because InvestmentResponse.from() substitutes investedAmount for
    # it. Sending the response figure straight back into applyInvestment's bare
    # `setCurrentValue(req.getCurrentValue())` therefore pins a tracking holding at whatever it
    # was worth on the day it was edited — and a plain rename was enough to do it. After that,
    # a top-up booked from the Transactions screen (TransactionService -> addFundsToInvestment)
    # raises investedAmount alone, currentValue stands still, and net worth silently stops
    # growing.
    #
    # The response cannot tell us which of the two it handed us, so we infer it: a value equal
    # to the invested total is read as the fallback and sent as null. That misreads the case
    # where a genuinely tracked value happens to equal the invested total — a holding that has
    # not moved since it was bought, or one whose value was just re-pinned to it — and converts
    # it back to tracking. Nothing on screen changes (the two figures are identical at that
    # moment), the holding simply resumes growing with its contributions, and "📈 Value"
    # re-pins it in one tap. The opposite mistake is silent and permanent, so the tie goes to
    # null.
    current = r.get("currentValue")
    tracked = current is not None and _num(current) != _num(r.get("investedAmount"))
    return {"name": r.get("name"), "type": r.get("type"), "investedAmount": r.get("investedAmount"),
            "currency": CURRENCY, "purchaseDate": r.get("purchaseDate"), "broker": r.get("broker"),
            "description": r.get("description"), "emergencyFund": bool(r.get("emergencyFund")),
            "savingsGoal": bool(r.get("savingsGoal")), "targetAmount": r.get("targetAmount"),
            "currentValue": current if tracked else None,
            "openingBalance": bool(r.get("openingBalance"))}


def _req_emergency(r):
    return {"amount": r.get("amount"), "currency": CURRENCY, "date": r.get("date"),
            "description": r.get("description")}


# ── editable fields ─────────────────────────────────────────────────────────
# `kind` mirrors the create wizard's vocabulary. `optional` adds a Clear button, because a
# due date entered by mistake otherwise has no way back to empty.
INVESTMENT_TYPES = [
    ("REAL_ESTATE", "fin.investmentType.realEstate"), ("BONDS", "fin.investmentType.bonds"),
    ("MUTUAL_FUND", "fin.investmentType.mutualFund"), ("GOLD", "fin.investmentType.gold"),
    ("OTHER", "fin.investmentType.other"),
]
INVESTMENT_TYPE_KEY = dict(INVESTMENT_TYPES)

_EDIT_DEBT = [
    {"key": "creditorName", "label": "fin.create.debt.creditorName", "kind": "text"},
    {"key": "totalAmount", "label": "fin.field.totalAmount", "kind": "amount"},
    {"key": "dueDate", "label": "fin.field.dueDate", "kind": "date", "optional": True},
    {"key": "description", "label": "fin.field.description", "kind": "text", "optional": True},
]
_EDIT_LOAN_GIVEN = [
    {"key": "debtorName", "label": "fin.create.loanGiven.debtorName", "kind": "text"},
    {"key": "totalAmount", "label": "fin.create.loanGiven.amountLent", "kind": "amount"},
    {"key": "expectedReturnDate", "label": "fin.create.loanGiven.expectedReturnDate",
     "kind": "date", "optional": True},
    {"key": "description", "label": "fin.field.description", "kind": "text", "optional": True},
]
_EDIT_LOAN_TAKEN = [
    {"key": "lenderName", "label": "fin.create.loanTaken.lenderName", "kind": "text"},
    {"key": "totalAmount", "label": "fin.field.totalAmount", "kind": "amount"},
    {"key": "dueDate", "label": "fin.field.dueDate", "kind": "date", "optional": True},
    {"key": "plannedMonthlyPayment", "label": "fin.field.plannedMonthly",
     "kind": "amount", "optional": True},
    {"key": "description", "label": "fin.field.description", "kind": "text", "optional": True},
]
_EDIT_BANK_LOAN = [
    {"key": "bankName", "label": "fin.create.bankLoan.bankName", "kind": "text"},
    {"key": "loanName", "label": "fin.create.bankLoan.loanNameType", "kind": "text"},
    {"key": "totalAmount", "label": "fin.field.totalAmount", "kind": "amount"},
    {"key": "monthlyPayment", "label": "fin.create.bankLoan.monthlyPayment",
     "kind": "amount", "optional": True},
    {"key": "endDate", "label": "fin.create.bankLoan.endDate", "kind": "date", "optional": True},
]
_EDIT_MONTHLY = [
    {"key": "name", "label": "fin.field.name", "kind": "text"},
    {"key": "amount", "label": "fin.create.monthly.monthlyAmount", "kind": "amount"},
    {"key": "dueDay", "label": "fin.create.monthly.dueDay", "kind": "int", "min": 1, "max": 31},
    {"key": "description", "label": "fin.field.description", "kind": "text", "optional": True},
]
_EDIT_DONATION = [
    {"key": "recipientName", "label": "fin.create.donation.recipient", "kind": "text"},
    {"key": "amount", "label": "fin.field.amount", "kind": "amount"},
    {"key": "donationDate", "label": "fin.field.date", "kind": "date"},
    {"key": "description", "label": "fin.field.description", "kind": "text", "optional": True},
]
_EDIT_INVESTMENT = [
    {"key": "name", "label": "fin.field.name", "kind": "text"},
    {"key": "type", "label": "fin.field.type", "kind": "choice", "choices": INVESTMENT_TYPES},
    {"key": "broker", "label": "fin.create.investment.broker", "kind": "text", "optional": True},
    {"key": "description", "label": "fin.field.description", "kind": "text", "optional": True},
]
_EDIT_GOAL = [
    {"key": "name", "label": "fin.create.goal.goalName", "kind": "text"},
    {"key": "targetAmount", "label": "fin.create.goal.targetAmount", "kind": "amount", "optional": True},
    {"key": "description", "label": "fin.field.description", "kind": "text", "optional": True},
]
_EDIT_EMERGENCY = [
    {"key": "amount", "label": "fin.field.amount", "kind": "amount"},
    {"key": "date", "label": "fin.field.date", "kind": "date"},
    {"key": "description", "label": "fin.field.description", "kind": "text", "optional": True},
]


# ── the section registry ────────────────────────────────────────────────────
# `action` describes the money verb a record supports:
#   kind        which payload shape fa_confirm builds
#   open(rec)   the record can take that verb at all
#   due(rec,x)  it is still owed right now — the list offers the button only for these, the
#               detail screen offers it whenever `open`, so a second payment stays possible
SECTIONS = {
    "debt": {
        "path": "/finance/debts", "title": "fin.debtsTitle", "create": "debt",
        "label": lambda r: r.get("creditorName") or "?",
        "line": _line_debt, "to_request": _req_debt, "edit": _EDIT_DEBT,
        "history": "/finance/debts/{id}/repayments",
        "action": {"kind": "repay", "verb": "fin.verbRepayDebt", "btn": "fin.repayBtn",
                   "endpoint": "/finance/debts/{id}/repay", "suggest": "remainingAmount",
                   "markkind": "DEBT",
                   "open": lambda r: _num(r.get("remainingAmount")) > 0},
    },
    "loangiven": {
        "path": "/finance/loans-given", "title": "fin.loansGivenTitle", "create": "loangiven",
        "label": lambda r: r.get("debtorName") or "?",
        "line": _line_loan_given, "to_request": _req_loan_given, "edit": _EDIT_LOAN_GIVEN,
        "history": "/finance/loans-given/{id}/repayments",
        # The one INBOUND action in the bot: markLoanGivenReturned books an INCOME, so the
        # source screen has to ask where the money ARRIVED, not where it is paid from.
        "action": {"kind": "repay", "verb": "fin.verbMarkReturned", "btn": "fin.returnedByBtn",
                   "endpoint": "/finance/loans-given/{id}/mark-returned",
                   "suggest": "pendingAmount", "inbound": True,
                   "open": lambda r: _num(r.get("pendingAmount")) > 0},
    },
    "loantaken": {
        "path": "/finance/loans-taken", "title": "fin.loansTakenTitle", "create": "loantaken",
        "label": lambda r: r.get("lenderName") or "?",
        "line": _line_loan_taken, "to_request": _req_loan_taken, "edit": _EDIT_LOAN_TAKEN,
        "history": "/finance/loans-taken/{id}/repayments",
        "action": {"kind": "repay", "verb": "fin.verbRepayLoan", "btn": "fin.repayBtn",
                   "endpoint": "/finance/loans-taken/{id}/repay", "suggest": "remainingAmount",
                   "markkind": "PERSONAL_LOAN",
                   "open": lambda r: _num(r.get("remainingAmount")) > 0},
    },
    "bankloan": {
        "path": "/finance/bank-loans", "title": "fin.bankLoansTitle", "create": "bankloan",
        "label": lambda r: f"{r.get('bankName') or '?'} — {r.get('loanName') or '?'}",
        "line": _line_bank_loan, "to_request": _req_bank_loan, "edit": _EDIT_BANK_LOAN,
        "detail": _detail_bank_loan,
        # A bank loan has no /repay endpoint and no paid_amount column — the installment
        # exists only as the schedule on the row — so paying one is a BANK_LOAN_PAYMENT
        # transaction, exactly as the web app books it. That sub-type is what
        # OverviewService.computeMonthPaid counts toward the "paid X of Y" strip the bot
        # itself renders on the Plan screen; a plain expense contributes nothing there.
        "action": {"kind": "bankpay", "verb": "fin.verbPayInstallment",
                   "btn": "fin.payInstallmentBtn", "endpoint": "/transactions",
                   "suggest": "monthlyPayment", "markkind": "BANK",
                   "open": lambda r: True},
    },
    "monthly": {
        "path": "/finance/monthly-payments", "title": "fin.subscriptionsTitle", "create": "monthly",
        "label": lambda r: r.get("name") or "?",
        "line": _line_monthly, "to_request": _req_monthly, "edit": _EDIT_MONTHLY,
        "detail": _detail_monthly, "history": "/finance/monthly-payments/{id}/payments",
        "annotate": lambda event: _monthly_annotate(event), "pausable": True,
        "action": {"kind": "pay", "verb": "fin.verbPay", "btn": "fin.payBtn",
                   "endpoint": "/finance/monthly-payments/{id}/pay", "suggest": "amount",
                   "markkind": "SUBSCRIPTION",
                   "open": lambda r: bool(r.get("active", True)),
                   "due": lambda r, x: bool(r.get("active", True)) and not _monthly_covered(r, x)},
    },
    "donation": {
        "path": "/finance/donations", "title": "fin.donationsTitle", "create": "donation",
        "label": lambda r: r.get("displayName") or r.get("recipientName") or "?",
        "line": _line_donation, "to_request": _req_donation, "edit": _EDIT_DONATION,
        # deleteDonation takes the donation's transaction with it (2026-09-17), as for the rest.
        "delete_warn": "fin.deleteReversesMoney",
    },
    "investment": {
        "path": "/finance/investments", "title": "fin.investmentsTitle", "create": "investment",
        "select": lambda r: not r.get("savingsGoal"),
        "label": lambda r: r.get("name") or "?",
        "line": _line_investment, "to_request": _req_investment, "edit": _EDIT_INVESTMENT,
        "detail": _detail_investment, "history": "/finance/investments/{id}/contributions",
        "delete_warn": "fin.deleteReversesMoney",
        "action": {"kind": "contribute", "verb": "fin.verbContribute", "btn": "fin.addToBtn",
                   "endpoint": "/finance/investments/{id}/contribute", "suggest": None,
                   "open": lambda r: not r.get("openingBalance")},
    },
    "goal": {
        "path": "/finance/investments", "title": "fin.savingsTitle", "create": "goal",
        "select": lambda r: bool(r.get("savingsGoal")),
        "empty": "fin.noSavingsGoalsYet",
        "label": lambda r: r.get("name") or "?",
        "line": _line_goal, "to_request": _req_investment, "edit": _EDIT_GOAL,
        "detail": _detail_investment, "history": "/finance/investments/{id}/contributions",
        "valuable": True, "delete_warn": "fin.deleteReversesMoney",
        "action": {"kind": "contribute", "verb": "fin.verbContribute", "btn": "fin.addToGoalBtn",
                   "endpoint": "/finance/investments/{id}/contribute", "suggest": None,
                   "open": lambda r: True},
    },
    "emergency": {
        "path": "/emergencies", "title": "fin.emergencyTitle", "create": "emergency",
        "label": lambda r: r.get("description") or r.get("date") or "?",
        "line": _line_emergency, "to_request": _req_emergency, "edit": _EDIT_EMERGENCY,
        "delete_warn": "fin.deleteReversesMoney",
    },
}


async def _monthly_annotate(event) -> dict:
    """Which subscriptions still owe money this month, from the Plan's own figures.

    One extra GET buys the whole "is this already paid?" question: `pendingSubscriptions` is
    the very list the Plan withholds the allocation over, so the subscriptions screen and the
    Plan can never disagree. When the call fails we return `known: False` and every Pay button
    stays offered — degrading to the old behaviour, never to a hidden button.

    An empty list is only an ANSWER when the Plan is actually computing one. `OverviewService`
    short-circuits it — `(missingIncome || beforeTrackingStart) ? List.of() :
    pendingSubscriptions(month)` — so a dormant tier hands back exactly what "everything is
    already paid" looks like. Trusting it stamped every subscription "✅ paid this month" and
    took its Pay button away over a setting the owner had simply not filled in yet, on the one
    screen whose whole job is to say what is still owed. Both dormant states are therefore read
    as UNKNOWN, with a line on the screen saying why. `subscriptionsPending` is not one of
    them: when it is true the list is populated and authoritative, which is the case this
    annotation was built for.
    """
    chat_id = common.chat_id_of(event)
    try:
        tier = await api.request(chat_id, "GET", "/overview/tier",
                                 params={"month": current_month(), "currency": CURRENCY}) or {}
    except Exception:  # noqa: BLE001
        return {}
    if tier.get("missingStableIncome"):
        return {"note": t(chat_id, "fin.subsUnknownIncome")}
    if tier.get("beforeTrackingStart"):
        return {"note": t(chat_id, "fin.subsUnknownTracking",
                          month=esc(tier.get("trackingStartMonth") or "—"))}
    pending = tier.get("pendingSubscriptions")
    if pending is None:
        # The one field the whole answer rests on is absent or null. "No key" is not "no
        # pending subscriptions", so it does not get to settle anything either.
        return {}
    return {"known": True,
            "pending": {p.get("id"): _num(p.get("paid")) for p in pending}}


def _section_of(raw: str) -> str:
    return SECTION_ALIASES.get(raw, raw)


def _action_due(spec, rec, extra) -> bool:
    act = spec.get("action")
    if not act or not act["open"](rec):
        return False
    due = act.get("due")
    return due(rec, extra) if due else True


# ── section menu ────────────────────────────────────────────────────────────
async def show_menu(cb: CallbackQuery) -> None:
    """The Finance landing screen. Called by menu.py's `menu:finance`."""
    chat_id = common.chat_id_of(cb)
    await common.show(cb, t(chat_id, "fin.menuTitle"), _menu_kb(chat_id))


# ── section lists ───────────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("fin:"))
async def on_section(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    if not await common.gate(cb):
        return
    # Walking into a list abandons whatever half-finished action was on another screen —
    # which is also what stops a previous record's "Use 500 000" from spending on this one.
    await state.clear()
    parts = cb.data.split(":")
    section = _section_of(parts[1])
    if section not in SECTIONS:
        await common.show(cb, t(cb.message.chat.id, "common.unknownSection"),
                          _back_kb(common.chat_id_of(cb)))
        return
    page = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
    await render_section(cb, section, page)


async def render_section(event, section: str, page: int = 0) -> None:
    chat_id = common.chat_id_of(event)
    spec = SECTIONS[section]
    rows = await _fetch(event, spec["path"])
    if rows is None:
        return
    if spec.get("select"):
        rows = [r for r in rows if spec["select"](r)]
    extra = await spec["annotate"](event) if spec.get("annotate") else {}

    pages = max(1, (len(rows) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = min(max(page, 0), pages - 1)
    window = rows[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]

    lines = [t(chat_id, spec["title"])]
    if not rows:
        lines.append(t(chat_id, spec.get("empty", "common.nothingHere")))
    elif extra.get("note"):
        # Already translated and escaped by the annotate hook — it is the hook that knows
        # WHY it could not answer. Said out loud, because a screen that quietly stops
        # marking things paid looks identical to one where nothing is paid.
        lines.append(extra["note"])
    kb_rows = []
    for rec in window:
        lines.append("• " + spec["line"](chat_id, rec, extra))
        kb_rows.append(_record_row(chat_id, section, rec, extra, page))
    if pages > 1:
        lines.append(t(chat_id, "fin.showingCount", shown=len(window), total=len(rows)))
        kb_rows.append(ui.pager(chat_id, page, pages, f"fin:{section}:"))
    kb_rows.append([(t(chat_id, "common.add"), f"fcreate:{spec['create']}")])
    kb_rows.append([(t(chat_id, "fin.backToFinance"), "menu:finance")])
    await common.show(event, "\n".join(lines), ikb(kb_rows))


def _record_row(chat_id, section, rec, extra, page):
    """One row per record: the money verb when it is due, plus a ⚙️ into the detail screen."""
    spec = SECTIONS[section]
    rid = rec.get("id")
    name = str(spec["label"](rec))
    manage = (t(chat_id, "fin.manageBtn"), f"fview:{section}:{rid}:{page}")
    if _action_due(spec, rec, extra):
        # Button text is NOT HTML-parsed, so the name goes in raw — esc() here would print
        # a literal &amp; on the owner's keyboard.
        return [(t(chat_id, spec["action"]["btn"], name=name[:18]), f"fact:{section}:{rid}"), manage]
    return [(t(chat_id, "fin.manageNamedBtn", name=name[:26]), f"fview:{section}:{rid}:{page}")]


# ── one record ──────────────────────────────────────────────────────────────
async def _load(event, section: str, rid: int):
    """Fetch a section and pick one record out of it, or render "gone" and return None."""
    chat_id = common.chat_id_of(event)
    rows = await _fetch(event, SECTIONS[section]["path"])
    if rows is None:
        return None
    rec = _find(rows, rid)
    if rec is None:
        await common.show(event, t(chat_id, "fin.recordGone"), _back_kb(chat_id, section))
        return None
    return rec


def _detail_text(chat_id, section, rec, extra) -> str:
    spec = SECTIONS[section]
    lines = [t(chat_id, spec["title"]).strip(), "• " + spec["line"](chat_id, rec, extra)]
    if spec.get("detail"):
        lines.extend(spec["detail"](chat_id, rec, extra))
    desc = (rec.get("description") or "").strip()
    if desc and section != "emergency":  # the emergency line already carries its note
        lines.append(t(chat_id, "fin.detailDescription", text=esc(desc)))
    return "\n".join(lines)


@router.callback_query(F.data.startswith("fview:"))
async def show_record(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    if not await common.gate(cb):
        return
    await state.clear()
    chat_id = common.chat_id_of(cb)
    parts = cb.data.split(":")
    section = _section_of(parts[1])
    if section not in SECTIONS or not parts[2].isdigit():
        await common.show(cb, t(chat_id, "common.unknownSection"), _back_kb(chat_id))
        return
    rid = int(parts[2])
    page = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0
    spec = SECTIONS[section]
    rec = await _load(cb, section, rid)
    if rec is None:
        return
    extra = await spec["annotate"](cb) if spec.get("annotate") else {}

    rows = []
    act = spec.get("action")
    if act and act["open"](rec):
        rows.append([(t(chat_id, act["btn"], name=str(spec["label"](rec))[:18]),
                      f"fact:{section}:{rid}")])
    second = []
    if spec.get("history"):
        second.append((t(chat_id, "fin.historyBtn"), f"fhist:{section}:{rid}"))
    if spec.get("valuable"):
        second.append((t(chat_id, "fin.valueBtn"), f"goal:value:{rid}"))
    rows.append(second)
    if spec.get("pausable"):
        paused = not rec.get("active", True)
        rows.append([(t(chat_id, "fin.resumeBtn" if paused else "fin.pauseBtn"),
                      f"ftog:{section}:{rid}")])
    rows.append([(t(chat_id, "common.edit"), f"fedit:{section}:{rid}"),
                 (t(chat_id, "common.delete"), f"fdel:{section}:{rid}")])
    rows.append([(t(chat_id, "fin.backToSection"), f"fin:{section}:{page}"),
                 (t(chat_id, "fin.backToFinance"), "menu:finance")])
    await common.show(cb, _detail_text(chat_id, section, rec, extra), ikb(rows))


# ── payment history ─────────────────────────────────────────────────────────
def _tx_source(chat_id, tx) -> str:
    card = tx.get("card") or {}
    if card.get("name"):
        digits = card.get("lastFourDigits")
        return f"{card['name']} ···{digits}" if digits else str(card["name"])
    return t(chat_id, "common.cash")


@router.callback_query(F.data.startswith("fhist:"))
async def show_history(cb: CallbackQuery) -> None:
    await common.ack(cb)
    if not await common.gate(cb):
        return
    chat_id = common.chat_id_of(cb)
    _, raw_section, sid = cb.data.split(":")
    section = _section_of(raw_section)
    spec = SECTIONS.get(section)
    if not spec or not spec.get("history") or not sid.isdigit():
        await common.show(cb, t(chat_id, "common.unknownSection"), _back_kb(chat_id))
        return
    rid = int(sid)
    rec = await _load(cb, section, rid)
    if rec is None:
        return
    back = ikb([[(t(chat_id, "common.back"), f"fview:{section}:{rid}")]])
    rows = await _fetch(cb, spec["history"].format(id=rid), kb=back)
    if rows is None:
        return
    lines = [t(chat_id, "fin.historyTitle", name=esc(spec["label"](rec)))]
    if not rows:
        lines.append(t(chat_id, "fin.historyEmpty"))
    for tx in rows[:HISTORY_ROWS]:
        lines.append("• " + t(chat_id, "fin.historyLine", date=esc(tx.get("transactionDate", "")),
                              amount=fmt_money(tx.get("amount")),
                              source=esc(_tx_source(chat_id, tx))))
    if len(rows) > HISTORY_ROWS:
        lines.append(t(chat_id, "fin.historyMore", total=len(rows), shown=HISTORY_ROWS))
    await common.show(cb, "\n".join(lines), back)


# ── pause / resume a subscription ───────────────────────────────────────────
@router.callback_query(F.data.startswith("ftog:"))
async def toggle_active(cb: CallbackQuery) -> None:
    """Flip a subscription's `active` flag.

    This is the exit from a permanent chore: while an active subscription is unpaid,
    `pendingSubscriptions` withholds the WHOLE allocation block for the month, so a service
    cancelled in real life had to be re-marked or fake-paid every single month forever.
    """
    await common.ack(cb)
    if not await common.gate(cb):
        return
    chat_id = common.chat_id_of(cb)
    _, raw_section, sid = cb.data.split(":")
    section = _section_of(raw_section)
    spec = SECTIONS.get(section)
    if not spec or not spec.get("pausable") or not sid.isdigit():
        await common.show(cb, t(chat_id, "common.unknownSection"), _back_kb(chat_id))
        return
    rid = int(sid)
    rec = await _load(cb, section, rid)
    if rec is None:
        return
    body = spec["to_request"](rec)
    body["active"] = not rec.get("active", True)
    await common.begin_write(cb, chat_id)
    try:
        await api.request(chat_id, "PUT", f"{spec['path']}/{rid}", json=body)
    except Exception as exc:  # noqa: BLE001
        await _report(cb, exc, _back_kb(chat_id, section))
        return
    key = "fin.resumed" if body["active"] else "fin.paused"
    await common.show(cb, t(chat_id, key, name=esc(spec["label"](rec))),
                      ikb([[(t(chat_id, "fin.backToSection"), f"fin:{section}"),
                            (t(chat_id, "fin.backToFinance"), "menu:finance")]]))


# ── delete a record ─────────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("fdelok:"))
async def delete_record_ok(cb: CallbackQuery) -> None:
    await common.ack(cb)
    if not await common.gate(cb):
        return
    chat_id = common.chat_id_of(cb)
    _, raw_section, sid = cb.data.split(":")
    section = _section_of(raw_section)
    spec = SECTIONS.get(section)
    if not spec or not sid.isdigit():
        await common.show(cb, t(chat_id, "common.unknownSection"), _back_kb(chat_id))
        return
    await common.begin_write(cb, chat_id)
    try:
        await api.request(chat_id, "DELETE", f"{spec['path']}/{int(sid)}")
    except Exception as exc:  # noqa: BLE001
        # The backend refuses a debt or loan that already has payments against it, and any
        # record whose month is closed. Both arrive as a 400 whose sentence is the answer.
        await _report(cb, exc, _back_kb(chat_id, section))
        return
    await common.show(cb, t(chat_id, "fin.deleted"),
                      ikb([[(t(chat_id, "fin.backToSection"), f"fin:{section}"),
                            (t(chat_id, "fin.backToFinance"), "menu:finance")]]))


@router.callback_query(F.data.startswith("fdel:"))
async def delete_record(cb: CallbackQuery) -> None:
    await common.ack(cb)
    if not await common.gate(cb):
        return
    chat_id = common.chat_id_of(cb)
    _, raw_section, sid = cb.data.split(":")
    section = _section_of(raw_section)
    spec = SECTIONS.get(section)
    if not spec or not sid.isdigit():
        await common.show(cb, t(chat_id, "common.unknownSection"), _back_kb(chat_id))
        return
    rid = int(sid)
    rec = await _load(cb, section, rid)
    if rec is None:
        return
    text = t(chat_id, "fin.deleteConfirm", line=spec["line"](chat_id, rec, {}))
    if spec.get("delete_warn"):
        text += "\n\n" + t(chat_id, spec["delete_warn"])
    await common.show(cb, text, ikb([
        ui.confirm_row(chat_id, f"fdelok:{section}:{rid}", f"fview:{section}:{rid}",
                       cancel_key="common.back", destructive=True),
    ]))


# ── edit one field ──────────────────────────────────────────────────────────
def _field_value(rec, field):
    return rec.get(field["key"])


def _field_display(chat_id, field, value) -> str:
    if value is None or value == "":
        return t(chat_id, "common.none")
    kind = field["kind"]
    if kind == "amount":
        return fmt_money(value)
    if kind == "choice":
        return _investment_type(chat_id, value) if field["key"] == "type" else str(value)
    return str(value)


@router.callback_query(F.data.startswith("fedit:"))
async def edit_entry(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    if not await common.gate(cb):
        return
    chat_id = common.chat_id_of(cb)
    _, raw_section, sid = cb.data.split(":")
    section = _section_of(raw_section)
    spec = SECTIONS.get(section)
    if not spec or not sid.isdigit():
        await common.show(cb, t(chat_id, "common.unknownSection"), _back_kb(chat_id))
        return
    rid = int(sid)
    rec = await _load(cb, section, rid)
    if rec is None:
        return
    # The record travels in FSM data so the confirmation can rebuild the full PUT body
    # without a second round trip — and so the body it writes is the one the owner was shown.
    await state.set_state(FinEdit.field)
    await state.set_data({"fe_section": section, "fe_id": rid, "fe_rec": rec})
    items = [(t(chat_id, f["label"]), f"fedf:{i}") for i, f in enumerate(spec["edit"])]
    rows = ui.grid(items, 2)
    rows.append([(t(chat_id, "common.back"), f"fview:{section}:{rid}"),
                 (t(chat_id, "common.cancel"), "fact:cancel")])
    await common.show(cb, t(chat_id, "fin.editTitle", name=esc(spec["label"](rec))), ikb(rows))


@router.callback_query(StateFilter(FinEdit.field, FinEdit.value, FinEdit.confirm),
                       F.data.startswith("fedf:"))
async def edit_pick_field(cb: CallbackQuery, state: FSMContext) -> None:
    """Render the editor for one field. Also the Back target from the confirmation screen."""
    await common.ack(cb)
    chat_id = common.chat_id_of(cb)
    d = await state.get_data()
    spec = SECTIONS[d["fe_section"]]
    index = int(cb.data.split(":")[1])
    if not 0 <= index < len(spec["edit"]):
        await common.show(cb, t(chat_id, "common.unknownSection"), _back_kb(chat_id))
        return
    await state.update_data(fe_index=index)
    await _edit_prompt(cb, state)


async def _edit_prompt(event, state: FSMContext) -> None:
    chat_id = common.chat_id_of(event)
    d = await state.get_data()
    spec = SECTIONS[d["fe_section"]]
    field = spec["edit"][d["fe_index"]]
    current = _field_display(chat_id, field, _field_value(d["fe_rec"], field))
    label = t(chat_id, field["label"])
    kind = field["kind"]
    rows = []
    if kind == "amount":
        body = t(chat_id, "fin.editPromptAmount", label=label, current=esc(current), currency=CURRENCY)
    elif kind == "int":
        body = t(chat_id, "fin.editPromptInt", label=label, current=esc(current),
                 min=field.get("min"), max=field.get("max"))
    elif kind == "date":
        body = t(chat_id, "fin.editPromptDate", label=label, current=esc(current))
        rows.append([(t(chat_id, "common.today"), "fedset:today")])
    elif kind == "choice":
        body = t(chat_id, "fin.editPromptChoice", label=label, current=esc(current))
        rows.extend(ui.grid([(t(chat_id, key), f"fedset:{value}")
                             for value, key in field["choices"]], 2))
    else:
        body = t(chat_id, "fin.editPrompt", label=label, current=esc(current))
    if field.get("optional"):
        rows.append([(t(chat_id, "fin.editClearBtn"), "fedclr")])
    rows.append([(t(chat_id, "common.back"), f"fedit:{d['fe_section']}:{d['fe_id']}"),
                 (t(chat_id, "common.cancel"), "fact:cancel")])
    await state.set_state(FinEdit.value)
    await common.show(event, body, ikb(rows))


async def _edit_confirm(event, state: FSMContext, value) -> None:
    chat_id = common.chat_id_of(event)
    d = await state.get_data()
    spec = SECTIONS[d["fe_section"]]
    field = spec["edit"][d["fe_index"]]
    await state.update_data(fe_value=value)
    await state.set_state(FinEdit.confirm)
    old = _field_display(chat_id, field, _field_value(d["fe_rec"], field))
    new = _field_display(chat_id, field, value)
    await common.show(event, t(chat_id, "fin.editConfirm", label=t(chat_id, field["label"]),
                               old=esc(old), new=esc(new)), ikb([
        ui.confirm_row(chat_id, "fedok", "fact:cancel"),
        [(t(chat_id, "common.back"), f"fedf:{d['fe_index']}")],
    ]))


@router.callback_query(StateFilter(FinEdit.value), F.data == "fedclr")
async def edit_clear(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    await _edit_confirm(cb, state, None)


@router.callback_query(StateFilter(FinEdit.value), F.data.startswith("fedset:"))
async def edit_set(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    raw = cb.data.split(":", 1)[1]
    d = await state.get_data()
    field = SECTIONS[d["fe_section"]]["edit"][d["fe_index"]]
    value = today_iso() if (field["kind"] == "date" and raw == "today") else raw
    await _edit_confirm(cb, state, value)


@router.message(StateFilter(FinEdit.value))
async def edit_typed(message: Message, state: FSMContext) -> None:
    chat_id = message.chat.id
    d = await state.get_data()
    field = SECTIONS[d["fe_section"]]["edit"][d["fe_index"]]
    raw = (message.text or "").strip()
    kind = field["kind"]
    if kind == "amount":
        value = parse_amount(raw)
        if value is None:
            await message.answer(t(chat_id, "common.positiveNumber"))
            return
    elif kind == "int":
        try:
            value = int(raw)
        except ValueError:
            await message.answer(t(chat_id, "fin.editWholeNumber"))
            return
        if not (field.get("min", value) <= value <= field.get("max", value)):
            await message.answer(t(chat_id, "fin.editRange", min=field.get("min"), max=field.get("max")))
            return
    elif kind == "date":
        value = _valid_date(raw)
        if value is None:
            await message.answer(t(chat_id, "fin.dateFormat", example=today_iso()))
            return
    elif kind == "choice":
        await message.answer(t(chat_id, "fin.editTapButton"))
        return
    else:
        value = raw
    await _edit_confirm(message, state, value)


@router.callback_query(StateFilter(FinEdit.confirm), F.data == "fedok")
async def edit_ok(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    chat_id = common.chat_id_of(cb)
    d = await state.get_data()
    section = d["fe_section"]
    spec = SECTIONS[section]
    field = spec["edit"][d["fe_index"]]
    body = spec["to_request"](d["fe_rec"])
    body[field["key"]] = d.get("fe_value")
    await common.begin_write(cb, chat_id)
    try:
        await api.request(chat_id, "PUT", f"{spec['path']}/{d['fe_id']}", json=body)
    except Exception as exc:  # noqa: BLE001
        await state.clear()
        await _report(cb, exc, _back_kb(chat_id, section))
        return
    await state.clear()
    await common.show(cb, t(chat_id, "fin.edited", label=t(chat_id, field["label"])),
                      ikb([[(t(chat_id, "fin.backToRecord"), f"fview:{section}:{d['fe_id']}"),
                            (t(chat_id, "fin.backToSection"), f"fin:{section}")]]))


# ── money action: amount → source → date → confirm ──────────────────────────
@router.callback_query(F.data == "fact:cancel")
async def fa_cancel(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    chat_id = common.chat_id_of(cb)
    d = await state.get_data()
    section = d.get("fa_section") or d.get("fe_section")
    await state.clear()
    await common.show(cb, t(chat_id, "common.cancelled"), _back_kb(chat_id, section))


@router.callback_query(F.data.startswith("fact:"))
async def fa_entry(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    if not await common.gate(cb):
        return
    if not await common.stable_income_set(cb):
        return
    chat_id = common.chat_id_of(cb)
    _, raw_section, sid = cb.data.split(":")
    section = _section_of(raw_section)
    spec = SECTIONS.get(section)
    if not spec or not spec.get("action") or not sid.isdigit():
        await common.show(cb, t(chat_id, "common.unknownSection"), _back_kb(chat_id))
        return
    rid = int(sid)
    rec = await _load(cb, section, rid)
    if rec is None:
        return
    act = spec["action"]
    suggested = _num(rec.get(act["suggest"])) if act.get("suggest") else 0.0
    # set_data, not update_data: this REPLACES the whole FSM payload, so a suggested amount
    # left behind by another record's flow can never be spent on this one.
    await state.set_state(FinAction.amount)
    await state.set_data({
        "fa_section": section, "fa_refid": rid, "fa_kind": act["kind"],
        "fa_endpoint": act["endpoint"].format(id=rid), "fa_verb": act["verb"],
        "fa_name": spec["label"](rec), "fa_markkind": act.get("markkind"),
        "fa_inbound": bool(act.get("inbound")), "fa_currency": CURRENCY,
        "fa_suggested": suggested if suggested > 0 else None,
        "fa_mark": False, "fa_date": today_iso(),
        "fa_bank": rec.get("bankName"), "fa_loan": rec.get("loanName"),
    })
    await _fa_amount(cb, state)


async def _fa_amount(event, state: FSMContext) -> None:
    chat_id = common.chat_id_of(event)
    d = await state.get_data()
    rows = []
    if d.get("fa_suggested"):
        rows.append([(t(chat_id, "fin.useSuggested", amount=fmt_money(d["fa_suggested"])),
                      f"fause:{d['fa_refid']}")])
    if d.get("fa_markkind") and not d.get("fa_mark"):
        rows.append([(t(chat_id, "fin.alreadyPaidBtn"), f"famark:{d['fa_refid']}")])
    rows.append(ui.nav(chat_id, back=f"fview:{d['fa_section']}:{d['fa_refid']}",
                       cancel="fact:cancel"))
    await state.set_state(FinAction.amount)
    if d.get("fa_mark"):
        body = t(chat_id, "fin.markAlreadyPaid", name=esc(d["fa_name"]), currency=CURRENCY)
    else:
        body = t(chat_id, "fin.sendAmountPrompt", verb=t(chat_id, d["fa_verb"]),
                 name=esc(d["fa_name"]), currency=CURRENCY)
    await common.show(event, body, ikb(rows))


async def _stale(cb: CallbackQuery, state: FSMContext, sid: str) -> bool:
    """True when this button was drawn for a different record than the flow now holds.

    Two live menu messages are enough to get here: start a repay on one, start a contribution
    on the other, then scroll back and tap the first message's "Use 500 000". The state
    filter still passes, so without the record id in the callback data that tap used to spend
    the debt's remaining balance on the savings goal.
    """
    d = await state.get_data()
    if sid.isdigit() and int(sid) == d.get("fa_refid"):
        return False
    await common.ack(cb, t(common.chat_id_of(cb), "fin.staleButton"), alert=True)
    return True


@router.callback_query(StateFilter(FinAction.amount), F.data.startswith("famark:"))
async def fa_mark_start(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    if await _stale(cb, state, cb.data.split(":", 1)[1]):
        return
    await state.update_data(fa_mark=True)
    await _fa_amount(cb, state)


@router.callback_query(StateFilter(FinAction.amount), F.data.startswith("fause:"))
async def fa_use(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    if await _stale(cb, state, cb.data.split(":", 1)[1]):
        return
    d = await state.get_data()
    if not d.get("fa_suggested"):
        await common.ack(cb, t(common.chat_id_of(cb), "fin.staleButton"), alert=True)
        return
    await state.update_data(fa_amount=d["fa_suggested"])
    await _fa_after_amount(cb, state)


@router.message(StateFilter(FinAction.amount))
async def fa_amount(message: Message, state: FSMContext) -> None:
    amount = parse_amount(message.text)
    if amount is None:
        await message.answer(t(message.chat.id, "common.positiveNumber"))
        return
    await state.update_data(fa_amount=amount)
    await _fa_after_amount(message, state)


async def _fa_after_amount(event, state: FSMContext) -> None:
    """A mark moves no money, so it skips the wallet question and goes straight to the date."""
    d = await state.get_data()
    if d.get("fa_mark"):
        await _fa_date(event, state)
    else:
        await _fa_source(event, state)


async def _fa_source(event, state: FSMContext) -> None:
    chat_id = common.chat_id_of(event)
    d = await state.get_data()
    none_cb = "fasrc:none" if d["fa_kind"] == "contribute" else None
    # The state is set BEFORE the fetch so the retry button below is dispatched by
    # `fa_back` — which re-enters this function — however the fetch goes.
    await state.set_state(FinAction.source)
    try:
        rows, cards = await _wallet_rows(event, none_cb=none_cb)
    except Exception as exc:  # noqa: BLE001 — dispatched by type in _report
        # Never fall through to a Cash-only picker: see _wallet_rows. Nothing has been
        # written at this point, so the amount and the record are still safe in the FSM and
        # Retry resumes exactly here.
        await _report(event, exc, ikb([
            [(t(chat_id, "common.retry"), "faback:source")],
            ui.nav(chat_id, back="faback:amount", cancel="fact:cancel"),
        ]), generic="fin.walletsLoadError")
        return
    await state.update_data(fa_cards=cards)
    rows.append(ui.nav(chat_id, back="faback:amount", cancel="fact:cancel"))
    # markLoanGivenReturned books an INCOME: the money is ARRIVING, so asking "pay from"
    # here (and confirming "From: Cash") stated the whole transaction backwards.
    key = "fin.receiveInto" if d.get("fa_inbound") else "fin.payFrom"
    await common.show(event, t(chat_id, key, currency=CURRENCY), ikb(rows))


@router.callback_query(StateFilter(FinAction.source), F.data.startswith("fasrc:"))
async def fa_src(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    if cb.data == "fasrc:none":
        await state.update_data(fa_cardId=None, fa_noWallet=True)
    elif cb.data == "fasrc:cash":
        await state.update_data(fa_cardId=None, fa_noWallet=False)
    else:
        await state.update_data(fa_cardId=int(cb.data.split(":")[2]), fa_noWallet=False)
    await _fa_date(cb, state)


async def _fa_date(event, state: FSMContext) -> None:
    """The step that makes a month envelope usable: a bill settled on the 30th and recorded
    on the 2nd belongs in the month it was settled in, not the month it was typed in."""
    chat_id = common.chat_id_of(event)
    d = await state.get_data()
    rows = [[(t(chat_id, "common.today"), "fadate:today"),
             (t(chat_id, "fin.yesterdayBtn"), "fadate:yesterday")]]
    back = "faback:amount" if d.get("fa_mark") else "faback:source"
    rows.append(ui.nav(chat_id, back=back, cancel="fact:cancel"))
    await state.set_state(FinAction.date)
    key = "fin.markMonthPrompt" if d.get("fa_mark") else "fin.datePrompt"
    await common.show(event, t(chat_id, key, example=today_iso()), ikb(rows))


@router.callback_query(StateFilter(FinAction.date), F.data.startswith("fadate:"))
async def fa_date_pick(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    choice = cb.data.split(":", 1)[1]
    await state.update_data(fa_date=_yesterday_iso() if choice == "yesterday" else today_iso())
    await _fa_confirm_screen(cb, state)


@router.message(StateFilter(FinAction.date))
async def fa_date_typed(message: Message, state: FSMContext) -> None:
    value = _valid_date(message.text)
    if value is None:
        await message.answer(t(message.chat.id, "fin.dateFormat", example=today_iso()))
        return
    await state.update_data(fa_date=value)
    await _fa_confirm_screen(message, state)


async def _fa_confirm_screen(event, state: FSMContext) -> None:
    chat_id = common.chat_id_of(event)
    d = await state.get_data()
    await state.set_state(FinAction.confirm)
    if d.get("fa_mark"):
        text = (t(chat_id, "fin.markConfirmHeader", name=esc(d["fa_name"]),
                  amount=fmt_money(d["fa_amount"]))
                + t(chat_id, "fin.markMonthLine", month=esc(d["fa_date"][:7])))
        ok_cb = "famarkok"
    else:
        card_id = d.get("fa_cardId")
        if d.get("fa_noWallet"):
            source_line = t(chat_id, "fin.fromNone")
        else:
            name = t(chat_id, "common.cash") if card_id is None else next(
                (c.get("name", "Card") for c in d.get("fa_cards", []) if c["id"] == card_id), "Card")
            source_line = t(chat_id, "fin.intoSource" if d.get("fa_inbound") else "fin.fromSource",
                            source=esc(name))
        text = (t(chat_id, "fin.confirmHeader", name=esc(d["fa_name"]),
                  amount=fmt_money(d["fa_amount"]))
                + source_line + t(chat_id, "fin.onDate", date=esc(d["fa_date"])))
        ok_cb = "faok"
    await common.show(event, text, ikb([
        ui.confirm_row(chat_id, ok_cb, "fact:cancel"),
        [(t(chat_id, "common.back"), "faback:date")],
    ]))


@router.callback_query(StateFilter(FinAction.amount, FinAction.source, FinAction.date,
                                  FinAction.confirm),
                       F.data.startswith("faback:"))
async def fa_back(cb: CallbackQuery, state: FSMContext) -> None:
    """One Back handler for the whole conversation — every step can walk backwards."""
    await common.ack(cb)
    step = cb.data.split(":", 1)[1]
    if step == "amount":
        await _fa_amount(cb, state)
    elif step == "source":
        await _fa_source(cb, state)
    else:
        await _fa_date(cb, state)


def _fa_payload(chat_id, d) -> dict:
    """The request body for whichever verb this flow is running."""
    amount, date, card_id = d["fa_amount"], d["fa_date"], d.get("fa_cardId")
    kind = d["fa_kind"]
    if kind == "pay":
        payload = {"amount": amount, "paymentDate": date,
                   "mode": "CARD" if card_id is not None else "CASH"}
    elif kind == "contribute":
        payload = {"amount": amount, "currency": CURRENCY, "date": date}
        if d.get("fa_noWallet"):
            payload["noWallet"] = True
            return payload
    elif kind == "bankpay":
        # No /repay endpoint exists for a bank loan: the installment IS a transaction, and
        # only the BANK_LOAN_PAYMENT sub-type feeds the Plan's "paid X of Y" strip.
        payload = {"type": "EXPENSE", "subType": "BANK_LOAN_PAYMENT", "amount": amount,
                   "currency": CURRENCY, "transactionDate": date,
                   "description": t(chat_id, "fin.bankInstallmentDesc",
                                    bank=d.get("fa_bank") or "", loan=d.get("fa_loan") or ""),
                   "cashAmount": 0 if card_id is not None else amount}
    else:  # repay / mark-returned
        payload = {"amount": amount, "paymentDate": date}
    if card_id is not None:
        payload["cardId"] = card_id
    return payload


@router.callback_query(StateFilter(FinAction.confirm), F.data == "faok")
async def fa_confirm(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    chat_id = common.chat_id_of(cb)
    d = await state.get_data()
    section = d.get("fa_section")
    payload = _fa_payload(chat_id, d)
    await common.begin_write(cb, chat_id)
    try:
        await api.request(chat_id, "POST", d["fa_endpoint"], json=payload)
    except Exception as exc:  # noqa: BLE001
        await state.clear()
        await _report(cb, exc, _back_kb(chat_id, section))
        return
    await state.clear()
    await common.show(cb, t(chat_id, "fin.recorded", amount=fmt_money(d["fa_amount"]),
                            name=esc(d["fa_name"])), _back_kb(chat_id, section))


@router.callback_query(StateFilter(FinAction.confirm), F.data == "famarkok")
async def fa_mark_ok(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    chat_id = common.chat_id_of(cb)
    d = await state.get_data()
    section = d.get("fa_section")
    payload = {"kind": d["fa_markkind"], "refId": d.get("fa_refid"), "amount": d["fa_amount"],
               "currency": d["fa_currency"], "month": d["fa_date"][:7]}
    await common.begin_write(cb, chat_id)
    try:
        await api.request(chat_id, "POST", "/finance/mark-paid", json=payload)
    except Exception as exc:  # noqa: BLE001
        await state.clear()
        await _report(cb, exc, _back_kb(chat_id, section))
        return
    await state.clear()
    await common.show(cb, t(chat_id, "fin.markedPaid", amount=fmt_money(d["fa_amount"]),
                            name=esc(d["fa_name"])),
                      ikb([[(t(chat_id, "fin.menu.marks"), f"fmarks:{d['fa_date'][:7]}")],
                           [(t(chat_id, "fin.backToSection"), f"fin:{section}"),
                            (t(chat_id, "fin.backToFinance"), "menu:finance")]]))


# ── "already paid" marks: the list and the undo ─────────────────────────────
# Which list holds the record a mark points at, and the field that names it.
_MARK_SOURCES = {
    "SUBSCRIPTION": ("/finance/monthly-payments", lambda r: r.get("name")),
    "PERSONAL_LOAN": ("/finance/loans-taken", lambda r: r.get("lenderName")),
    "DEBT": ("/finance/debts", lambda r: r.get("creditorName")),
    "BANK": ("/finance/bank-loans", lambda r: f"{r.get('bankName')} — {r.get('loanName')}"),
}
_MARK_KIND_KEY = {
    "SUBSCRIPTION": "fin.markKind.subscription", "PERSONAL_LOAN": "fin.markKind.personalLoan",
    "DEBT": "fin.markKind.debt", "BANK": "fin.markKind.bank", "BUCKET": "fin.markKind.bucket",
}
_MARK_BUCKET_KEY = {
    "DONATION": "fin.markBucket.donation", "EMERGENCY": "fin.markBucket.emergency",
    "INVESTMENTS": "fin.markBucket.investments", "STOCKS": "fin.markBucket.stocks",
}


async def _mark_names(event, marks) -> dict:
    """Resolve every mark's target name, fetching only the lists actually referenced."""
    chat_id = common.chat_id_of(event)
    names: dict[tuple[str, int], str] = {}
    for kind in {m.get("kind") for m in marks if m.get("refId")}:
        source = _MARK_SOURCES.get(kind)
        if not source:
            continue
        try:
            rows = await api.request(chat_id, "GET", source[0]) or []
        except Exception:  # noqa: BLE001 — a name we cannot resolve falls back to the kind
            continue
        for row in rows:
            names[(kind, row.get("id"))] = str(source[1](row))
    return names


def _mark_label(chat_id, mark, names) -> str:
    kind = mark.get("kind") or ""
    if kind == "BUCKET":
        key = _MARK_BUCKET_KEY.get(mark.get("bucket") or "")
        return t(chat_id, key) if key else str(mark.get("bucket") or "—")
    return names.get((kind, mark.get("refId"))) or t(chat_id, _MARK_KIND_KEY.get(kind, "common.none"))


@router.callback_query(F.data.startswith("fmarks"))
async def show_marks(cb: CallbackQuery, state: FSMContext) -> None:
    """Every "already paid" mark for a month, each with an undo.

    A mark is the only paid figure with no transaction behind it, so before this screen a
    mistyped one appeared in no list and could not be removed — it just raised the allocation
    base and every bucket target derived from it, permanently.
    """
    await common.ack(cb)
    if not await common.gate(cb):
        return
    await state.clear()
    chat_id = common.chat_id_of(cb)
    parts = cb.data.split(":", 1)
    month = parts[1] if len(parts) > 1 and len(parts[1]) == 7 else current_month()
    marks = await _fetch(cb, "/finance/mark-paid", params={"month": month})
    if marks is None:
        return
    names = await _mark_names(cb, marks)
    lines = [t(chat_id, "fin.marksTitle", month=esc(month))]
    if not marks:
        lines.append(t(chat_id, "fin.marksEmpty"))
    else:
        lines.append(t(chat_id, "fin.marksNote"))
    rows = []
    for mark in marks:
        label = _mark_label(chat_id, mark, names)
        note = t(chat_id, "fin.suffixNote", note=esc(mark["note"])) if mark.get("note") else ""
        lines.append("• " + t(chat_id, "fin.markLine",
                              kind=esc(t(chat_id, _MARK_KIND_KEY.get(mark.get("kind") or "", "common.none"))),
                              name=esc(label), amount=fmt_money(mark.get("amount")), note=note))
        rows.append([(t(chat_id, "fin.markDelBtn", name=label[:24]), f"fmarkdel:{mark['id']}")])
    rows.append([("◀️", f"fmarks:{_shift_month(month, -1)}"),
                 (month, f"fmarks:{month}"),
                 ("▶️", f"fmarks:{_shift_month(month, 1)}")])
    rows.append([(t(chat_id, "fin.backToFinance"), "menu:finance")])
    await common.show(cb, "\n".join(lines), ikb(rows))


@router.callback_query(F.data.startswith("fmarkdelok:"))
async def mark_delete_ok(cb: CallbackQuery) -> None:
    await common.ack(cb)
    if not await common.gate(cb):
        return
    chat_id = common.chat_id_of(cb)
    mid = cb.data.split(":", 1)[1]
    back = ikb([[(t(chat_id, "fin.menu.marks"), "fmarks"),
                 (t(chat_id, "fin.backToFinance"), "menu:finance")]])
    if not mid.isdigit():
        await common.show(cb, t(chat_id, "common.unknownSection"), back)
        return
    await common.begin_write(cb, chat_id)
    try:
        await api.request(chat_id, "DELETE", f"/finance/mark-paid/{int(mid)}")
    except api.ApiError as exc:
        # A closed month locks its marks exactly as it locks its transactions
        # (MonthCloseService.assertMonthOpen), and that is the one refusal worth naming: the
        # owner is otherwise left thinking the delete simply failed.
        text = f"❌ {esc(exc.message)}"
        if "closed" in (exc.message or "").lower():
            text += "\n\n" + t(chat_id, "fin.markMonthClosed")
        await common.show(cb, text, back)
        return
    except Exception as exc:  # noqa: BLE001
        await _report(cb, exc, back)
        return
    await common.show(cb, t(chat_id, "fin.markDeleted"), back)


@router.callback_query(F.data.startswith("fmarkdel:"))
async def mark_delete(cb: CallbackQuery) -> None:
    await common.ack(cb)
    if not await common.gate(cb):
        return
    chat_id = common.chat_id_of(cb)
    mid = cb.data.split(":", 1)[1]
    if not mid.isdigit():
        await common.show(cb, t(chat_id, "common.unknownSection"), _back_kb(chat_id))
        return
    await common.show(cb, t(chat_id, "fin.markDelConfirm"), ikb([
        ui.confirm_row(chat_id, f"fmarkdelok:{mid}", "fmarks",
                       cancel_key="common.back", destructive=True),
    ]))


# ── create (generic wizard, with the wallet question in front of it) ────────
# `wallet` says whether the create books a real wallet transaction:
#   "always"          — it always does (donation, emergency contribution)
#   "unless_opening"  — only when the owner says this is new money, not an existing holding
# Those three specs are the ones whose backend DTO carries a cardId; the other five create
# no transaction at all, so a wallet question there would be a lie.
CREATE_SECTIONS = {
    "debt": {"title": "fin.create.debt.title", "endpoint": "/finance/debts", "back": "fin:debt",
             "success": "fin.create.debt.success", "auto_currency": True, "fields": [
                 {"key": "creditorName", "label": "fin.create.debt.creditorName", "kind": "text", "required": True},
                 {"key": "totalAmount", "label": "fin.field.totalAmount", "kind": "amount", "required": True},
                 {"key": "borrowedDate", "label": "fin.create.debt.borrowedDate", "kind": "date", "required": True, "today": True},
                 {"key": "dueDate", "label": "fin.field.dueDate", "kind": "date", "required": False},
                 {"key": "paymentStartDate", "label": "fin.field.paymentStartMonth", "kind": "month", "required": False},
                 {"key": "description", "label": "fin.field.description", "kind": "text", "required": False},
             ]},
    "loangiven": {"title": "fin.create.loanGiven.title", "endpoint": "/finance/loans-given", "back": "fin:loangiven",
                  "success": "fin.create.loanGiven.success", "auto_currency": True, "fields": [
                      {"key": "debtorName", "label": "fin.create.loanGiven.debtorName", "kind": "text", "required": True},
                      {"key": "totalAmount", "label": "fin.create.loanGiven.amountLent", "kind": "amount", "required": True},
                      {"key": "lentDate", "label": "fin.create.loanGiven.lentDate", "kind": "date", "required": True, "today": True},
                      {"key": "expectedReturnDate", "label": "fin.create.loanGiven.expectedReturnDate", "kind": "date", "required": False},
                      {"key": "description", "label": "fin.field.description", "kind": "text", "required": False},
                  ]},
    "loantaken": {"title": "fin.create.loanTaken.title", "endpoint": "/finance/loans-taken", "back": "fin:loantaken",
                  "success": "fin.create.loanTaken.success", "auto_currency": True, "fields": [
                      {"key": "lenderName", "label": "fin.create.loanTaken.lenderName", "kind": "text", "required": True},
                      {"key": "totalAmount", "label": "fin.field.totalAmount", "kind": "amount", "required": True},
                      {"key": "borrowedDate", "label": "fin.create.loanTaken.borrowedDate", "kind": "date", "required": True, "today": True},
                      {"key": "dueDate", "label": "fin.field.dueDate", "kind": "date", "required": False},
                      {"key": "paymentStartDate", "label": "fin.field.paymentStartMonth", "kind": "month", "required": False},
                      {"key": "description", "label": "fin.field.description", "kind": "text", "required": False},
                  ]},
    "bankloan": {"title": "fin.create.bankLoan.title", "endpoint": "/finance/bank-loans", "back": "fin:bankloan",
                 "success": "fin.create.bankLoan.success", "auto_currency": True, "fields": [
                     {"key": "bankName", "label": "fin.create.bankLoan.bankName", "kind": "text", "required": True},
                     {"key": "loanName", "label": "fin.create.bankLoan.loanNameType", "kind": "text", "required": True},
                     {"key": "totalAmount", "label": "fin.field.totalAmount", "kind": "amount", "required": True},
                     {"key": "monthlyPayment", "label": "fin.create.bankLoan.monthlyPayment", "kind": "amount", "required": False},
                     {"key": "takenDate", "label": "fin.create.bankLoan.takenDate", "kind": "date", "required": True, "today": True},
                     {"key": "endDate", "label": "fin.create.bankLoan.endDate", "kind": "date", "required": False},
                 ]},
    "monthly": {"title": "fin.create.monthly.title", "endpoint": "/finance/monthly-payments", "back": "fin:monthly",
                "success": "fin.create.monthly.success", "auto_currency": True, "fields": [
                    {"key": "name", "label": "fin.field.name", "kind": "text", "required": True},
                    {"key": "amount", "label": "fin.create.monthly.monthlyAmount", "kind": "amount", "required": True},
                    {"key": "dueDay", "label": "fin.create.monthly.dueDay", "kind": "int", "required": True, "min": 1, "max": 31},
                    {"key": "description", "label": "fin.field.description", "kind": "text", "required": False},
                ]},
    "donation": {"title": "fin.create.donation.title", "endpoint": "/finance/donations", "back": "fin:donation",
                 "success": "fin.create.donation.success", "auto_currency": True, "wallet": "always", "fields": [
                     {"key": "recipientName", "label": "fin.create.donation.recipient", "kind": "text", "required": True},
                     {"key": "amount", "label": "fin.field.amount", "kind": "amount", "required": True},
                     {"key": "donationDate", "label": "fin.field.date", "kind": "date", "required": True, "today": True},
                     {"key": "description", "label": "fin.field.description", "kind": "text", "required": False},
                 ]},
    "investment": {"title": "fin.create.investment.title", "endpoint": "/finance/investments", "back": "fin:investment",
                   "success": "fin.create.investment.success", "auto_currency": True,
                   "wallet": "unless_opening", "opening_key": "openingBalance",
                   "opening_prompt": "fin.create.investment.openingBalanceQ",
                   "opening_yes": "fin.create.investment.openingYes",
                   "opening_no": "fin.create.investment.openingNo", "fields": [
                       {"key": "name", "label": "fin.field.name", "kind": "text", "required": True},
                       {"key": "type", "label": "fin.field.type", "kind": "choice", "required": True, "choices": INVESTMENT_TYPES},
                       {"key": "investedAmount", "label": "fin.create.investment.amountInvested", "kind": "amount", "required": True},
                       {"key": "broker", "label": "fin.create.investment.broker", "kind": "text", "required": False},
                       {"key": "purchaseDate", "label": "fin.create.investment.purchaseDate", "kind": "date", "required": True, "today": True},
                       {"key": "description", "label": "fin.field.description", "kind": "text", "required": False},
                   ]},
    "goal": {"title": "fin.create.goal.title", "endpoint": "/finance/investments", "back": "fin:goal",
             "success": "fin.create.goal.success", "auto_currency": True,
             "fixed": {"savingsGoal": True, "type": "OTHER"},
             "wallet": "unless_opening", "opening_key": "openingBalance",
             "opening_prompt": "fin.create.goal.openingQ",
             "opening_yes": "fin.create.goal.openingYes",
             "opening_no": "fin.create.goal.openingNo", "fields": [
                 {"key": "name", "label": "fin.create.goal.goalName", "kind": "text", "required": True},
                 {"key": "investedAmount", "label": "fin.create.goal.amountSaved", "kind": "amount", "required": True},
                 {"key": "targetAmount", "label": "fin.create.goal.targetAmount", "kind": "amount", "required": False},
                 {"key": "currentValue", "label": "fin.create.goal.currentValue", "kind": "amount", "required": False},
                 {"key": "purchaseDate", "label": "fin.create.goal.startDate", "kind": "date", "required": True, "today": True},
                 {"key": "description", "label": "fin.create.goal.notes", "kind": "text", "required": False},
             ]},
    "emergency": {"title": "fin.create.emergency.title", "endpoint": "/emergencies", "back": "fin:emergency",
                  "success": "fin.create.emergency.success", "auto_currency": True, "wallet": "always", "fields": [
                      {"key": "amount", "label": "fin.field.amount", "kind": "amount", "required": True},
                      {"key": "date", "label": "fin.field.date", "kind": "date", "required": True, "today": True},
                      {"key": "description", "label": "fin.field.description", "kind": "text", "required": False},
                  ]},
}


@router.callback_query(F.data.startswith("fcreate:"))
async def create_entry(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    if not await common.gate(cb):
        return
    if not await common.stable_income_set(cb):
        return
    chat_id = common.chat_id_of(cb)
    section = _section_of(cb.data.split(":", 1)[1])
    spec = CREATE_SECTIONS.get(section)
    if not spec:
        await common.show(cb, t(chat_id, "common.unknownSection"), _back_kb(chat_id))
        return
    await state.clear()
    wallet = spec.get("wallet")
    if wallet == "unless_opening":
        await common.show(cb, f"{t(chat_id, spec['title'])}\n\n{t(chat_id, spec['opening_prompt'])}",
                          ikb([[(t(chat_id, spec["opening_yes"]), f"fcopen:{section}:1")],
                               [(t(chat_id, spec["opening_no"]), f"fcopen:{section}:0")],
                               ui.nav(chat_id, back=f"fin:{section}", cancel="fact:cancel")]))
        return
    if wallet == "always":
        await _create_source(cb, section, opening=False)
        return
    await wizard.start(cb, state, spec)


@router.callback_query(F.data.startswith("fcopen:"))
async def create_opening(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    if not await common.gate(cb):
        return
    _, section, flag = cb.data.split(":")
    section = _section_of(section)
    if section not in CREATE_SECTIONS:
        await common.show(cb, t(common.chat_id_of(cb), "common.unknownSection"),
                          _back_kb(common.chat_id_of(cb)))
        return
    if flag == "1":
        # An opening balance books no transaction at all (createInvestment returns early), so
        # there is no wallet to debit and nothing to ask.
        await _create_start(cb, state, section, opening=True, card_id=None)
        return
    await _create_source(cb, section, opening=False)


async def _create_source(event, section: str, *, opening: bool) -> None:
    """Ask which wallet the new record's money comes out of, before the wizard starts.

    It has to be asked here rather than as a wizard field: the wizard posts the moment its
    last field is answered, and a spec has no way to add one. Without it `cardId` was never
    sent, and FinanceService.createBucketTransaction's null branch books the whole amount
    against cash — so every donation and every investment made from the phone drained the
    cash pot whatever the owner actually paid with.
    """
    chat_id = common.chat_id_of(event)
    spec = CREATE_SECTIONS[section]
    unless_opening = spec.get("wallet") == "unless_opening"
    back = f"fcreate:{section}" if unless_opening else f"fin:{section}"
    # Retry re-enters this screen by the same door the owner came through: the "new purchase"
    # answer for the two specs that ask about an opening balance, the Add button for the rest.
    retry = f"fcopen:{section}:0" if unless_opening else f"fcreate:{section}"
    try:
        rows, _cards = await _wallet_rows(event, prefix=f"fcsrc:{section}:{int(opening)}:")
    except Exception as exc:  # noqa: BLE001 — dispatched by type in _report
        # Same refusal as the action flow: a Cash-only picker here would charge a donation or
        # an investment to the cash pot whatever the owner actually paid with, which is
        # exactly the bug the wallet question was added to fix.
        await _report(event, exc, ikb([
            [(t(chat_id, "common.retry"), retry)],
            ui.nav(chat_id, back=back, cancel="fact:cancel"),
        ]), generic="fin.walletsLoadError")
        return
    rows.append(ui.nav(chat_id, back=back, cancel="fact:cancel"))
    await common.show(event, f"{t(chat_id, spec['title'])}\n\n{t(chat_id, 'fin.create.sourceQ')}",
                      ikb(rows))


@router.callback_query(F.data.startswith("fcsrc:"))
async def create_source_pick(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    if not await common.gate(cb):
        return
    parts = cb.data.split(":")
    section = _section_of(parts[1])
    if section not in CREATE_SECTIONS:
        await common.show(cb, t(common.chat_id_of(cb), "common.unknownSection"),
                          _back_kb(common.chat_id_of(cb)))
        return
    opening = parts[2] == "1"
    card_id = int(parts[4]) if parts[3] == "card" else None
    await _create_start(cb, state, section, opening=opening, card_id=card_id)


async def _create_start(event, state: FSMContext, section: str, *,
                        opening: bool, card_id: int | None) -> None:
    """Run the generic wizard with the answers we already have pinned as constants."""
    spec = CREATE_SECTIONS[section]
    fixed = dict(spec.get("fixed") or {})
    if spec.get("opening_key"):
        fixed[spec["opening_key"]] = opening
    if card_id is not None:
        fixed["cardId"] = card_id
    await wizard.start(event, state, {**spec, "fixed": fixed})


# ── savings goal: update current value ──────────────────────────────────────
@router.callback_query(F.data.startswith("goal:value:"))
async def gv_entry(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    if not await common.gate(cb):
        return
    chat_id = common.chat_id_of(cb)
    sid = cb.data.split(":")[2]
    if not sid.isdigit():
        await common.show(cb, t(chat_id, "common.unknownSection"), _back_kb(chat_id))
        return
    gid = int(sid)
    rec = await _load(cb, "goal", gid)
    if rec is None:
        return
    current = rec.get("currentValue")
    if current is None:
        current = rec.get("investedAmount")
    await state.set_state(GoalValue.amount)
    await state.set_data({"gv_id": gid, "gv_name": rec.get("name", "?")})
    await common.show(cb, t(chat_id, "fin.updateValueHeader", name=esc(rec.get("name")),
                            current=fmt_money(current), currency=CURRENCY),
                      ikb([ui.nav(chat_id, back=f"fview:goal:{gid}", cancel="fact:cancel")]))


@router.message(StateFilter(GoalValue.amount))
async def gv_amount(message: Message, state: FSMContext) -> None:
    chat_id = message.chat.id
    value = parse_amount(message.text)
    if value is None:
        await message.answer(t(chat_id, "common.positiveNumber"))
        return
    d = await state.get_data()
    await common.begin_write(message, chat_id)
    try:
        await api.request(chat_id, "POST", f"/finance/investments/{d['gv_id']}/value",
                          json={"currentValue": value})
    except Exception as exc:  # noqa: BLE001
        await state.clear()
        await _report(message, exc, _back_kb(chat_id, "goal"))
        return
    await state.clear()
    await common.show(message, t(chat_id, "fin.updatedValue", name=esc(d["gv_name"]),
                                 value=fmt_money(value)), _back_kb(chat_id, "goal"))


# ── A screen that outlived its flow ─────────────────────────────────────────
# Every callback in this file that is gated behind a FinAction / FinEdit state, and nothing
# else. Registered LAST, so a live flow's state-filtered handler always wins and this only
# sees the taps that matched nothing at all.
#
# Storage is MemoryStorage and `drop_pending_updates` is off, so both halves of the problem
# are routine: a restart empties every flow, and a tap made while the container was down
# arrives afterwards with no state behind it. Without this handler that tap matched no
# handler in any router — Telegram spun the button for about fifteen seconds, then cleared
# it, the message never changed, and the owner had no way to tell a lost repayment from a
# recorded one. Every other router grew this fallback during the rebuild; finance, the one
# with two multi-step money flows in it, did not.
#
# The prefixes NOT listed here are the point of the list. `fact:`, `fedit:`, `fdel:`,
# `fmarkdel:`, `fview:`, `fhist:`, `ftog:`, `fmarks`, `fcreate:` and `goal:value:` carry
# their record's id in the callback data and are answered by stateless handlers above: they
# work perfectly after a restart, and swallowing them here would break the one route back
# into a flow.
_STALE_PREFIXES = ("fedf:", "fedclr", "fedset:", "fedok",
                   "famark:", "famarkok", "fause:", "fasrc:", "fadate:", "faback:", "faok")


@router.callback_query(F.data.startswith(_STALE_PREFIXES))
async def stale_screen(cb: CallbackQuery, state: FSMContext) -> None:
    chat_id = common.chat_id_of(cb)
    await common.ack(cb, t(chat_id, "fin.flowExpired"))
    if await state.get_state() is not None:
        # A keyboard scrolled up from an earlier step of a flow that is still running further
        # down the chat — the state exists, it just does not match this button. Say so and
        # leave the live screen, and the answers already given, exactly as they are.
        return
    await state.clear()
    await common.show(cb, t(chat_id, "fin.flowExpiredBody"), _back_kb(chat_id))
