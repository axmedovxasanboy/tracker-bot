"""Transactions: add, move money, the recent list, one transaction, edit, delete.

This is the screen the bot exists for, so a few rules are enforced here harder than anywhere
else. Each one is here because its absence cost the owner real money or real re-typing.

**One live screen per flow.** A typed answer edits the prompt that asked for it instead of
posting a reply underneath it. Answering leaves the previous message's keyboard on screen,
live-looking and — because the flow has moved to another state — permanently inert; two of
those used to appear in an ordinary add. `_render` keeps the flow's message id in FSM data and
edits that one message, whatever kind of event the answer arrived as.

**The questions are asked in an order that can be answered.** Direction → amount → kind →
category → (which holding / who received it) → wallet → date → description. The kind has to
come before the category, because the category list is filtered by it: asking the category
first offered fourteen roots including four that are locked to sub-types this flow cannot
produce, and the owner could pair "Loan Repayment" with "Regular expense" — a combination the
web app makes impossible and nothing server-side rejects.

**An INVESTMENT expense always names its target.** `TransactionService.autoCreateFinanceRecord`
creates a BRAND NEW Investment when `investmentId` is absent, named after the description or
after the literal word "Investment". Every monthly top-up of the same holding was spawning a
duplicate row, so the portfolio grew one piece of junk per transaction. DONATION has the same
shape with `counterpartyName`, so it asks who received it — unless the chosen category
anonymises donations, in which case the backend overwrites the name and asking would be theatre.

**A rejected write keeps the form.** The backend refuses a card expense over the card's balance
and refuses any date inside a closed month, and both verdicts used to arrive after eight steps
and take all eight with them. The wallet buttons now carry balances, the date step knows which
months are locked, and a 400 re-offers the confirmation with the answers intact.
"""
import datetime as dt
import logging
import time
from contextlib import suppress

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from .. import api, common, keyboards, ui
from ..clock import today_iso
from ..config import CURRENCY
from ..i18n import cat_name, t
from ..keyboards import esc, ikb
from ..money import fmt_money, parse_amount
from ..states import AddTx, EditTx, MoveMoney

log = logging.getLogger(__name__)
router = Router()
PAGE_SIZE = 6

# Telegram renders long button labels by truncating them itself, but it truncates rudely and
# the balance is the part that matters, so the name is what gets cut.
_LABEL_LIMIT = 60


class AddExtra(StatesGroup):
    """The two questions the add flow asks only for some kinds of expense.

    They live here rather than in `bot/states.py` because that module is another agent's file
    and adding a state to a group is not something two people can do at once. Each screen gets
    its own state for the reason states.py itself gives: two screens sharing a state also share
    their buttons, and a keyboard scrolled up in the chat then fires against the step the flow
    has since moved on to.
    """
    holding = State()        # pick an existing investment, or "a new one"
    holding_name = State()   # typed name for a new holding
    holding_type = State()   # REAL_ESTATE / BONDS / MUTUAL_FUND / GOLD / OTHER
    recipient = State()      # typed donation recipient


# ── The add flow's steps, in order ───────────────────────────────────────────
# `_step` walks this list and skips whatever does not apply to the entry being recorded, so
# neither the Back buttons nor the forward handlers have to know which steps a given kind of
# transaction has. Adding a step means adding it here and to `_ASK`.
_ORDER = ("type", "amount", "kind", "cat", "extra", "src", "date", "desc", "confirm")

# Only EXPENSE sub-types are offered. Loan sub-types are deliberately absent: they auto-create
# finance records that need a counterparty and a repayment plan the add flow never asks for,
# and the Finance section has dedicated flows for them.
EXPENSE_SUBTYPES = [
    ("REGULAR_EXPENSE", "tx.kindRegular"),
    ("DONATION", "tx.kindDonation"),
    ("EMERGENCY_CONTRIBUTION", "tx.kindEmergency"),
    ("INVESTMENT", "tx.kindInvestment"),
    ("STOCK_PURCHASE", "tx.kindStocks"),
]
SUBTYPE_KEY = dict(EXPENSE_SUBTYPES)

# InvestmentType, minus the STOCKS and CRYPTO values the backend retired.
INVESTMENT_TYPES = [
    ("REAL_ESTATE", "tx.invType.realEstate"),
    ("BONDS", "tx.invType.bonds"),
    ("MUTUAL_FUND", "tx.invType.mutualFund"),
    ("GOLD", "tx.invType.gold"),
    ("OTHER", "tx.invType.other"),
]

# The bucket codes OverviewService.bucketForSubType can return. Printing the server's own
# `label` would splice an English noun into an Uzbek sentence ("📊 <b>Donation</b>ga
# hisoblanadi"), so the code is mapped to a key the bot owns and the label is only a fallback.
_BUCKET_KEY = {
    "DONATION": "alloc.bucket.donation",
    "EMERGENCY": "alloc.bucket.emergency",
    "INVESTMENTS": "alloc.bucket.investments",
    "SAVINGS": "alloc.bucket.savings",
    "STOCKS": "alloc.bucket.stocks",
}

# The latest permanently closed month, per chat. A month closes once a month, so a short TTL
# is plenty and it keeps the add flow from paying a round trip per date step. A failed lookup
# is never cached: "I could not ask" must not become "nothing is locked" for two minutes.
_CLOSED_TTL = 120.0
_closed_cache: dict[int, tuple[float, str | None]] = {}


# ── Rendering ────────────────────────────────────────────────────────────────
async def _edit_prompt(bot, chat_id: int, message_id: int, text: str, kb) -> bool:
    """Put `text` on an existing message. False means that message is no longer reachable."""
    try:
        await bot.edit_message_text(text, chat_id=chat_id, message_id=message_id,
                                    reply_markup=kb)
    except TelegramBadRequest as exc:
        # "message is not modified" means the screen already says exactly this, which is a
        # successful render by any measure the user can see.
        return "message is not modified" in (exc.message or "").lower()
    except Exception:  # noqa: BLE001 - a vanished message must not abort the flow
        log.debug("could not edit the flow screen %s", message_id, exc_info=True)
        return False
    return True


async def _render(event, state: FSMContext, text: str, kb=None) -> None:
    """Render the flow's one live screen, whichever kind of event brought the answer.

    A tap edits the message the button was on. A typed answer edits the message that asked the
    question and deletes the echo, so the chat holds one screen showing the current step rather
    than a column of prompts whose keyboards all still look pressable.
    """
    if isinstance(event, CallbackQuery):
        await common.show(event, text, kb)
        if event.message is not None:
            await state.update_data(ui_msg=event.message.message_id)
        return
    data = await state.get_data()
    ui_msg = data.get("ui_msg")
    bot = getattr(event, "bot", None)
    if ui_msg and bot is not None and await _edit_prompt(bot, event.chat.id, ui_msg, text, kb):
        with suppress(Exception):
            await event.delete()  # the answer is on the prompt now; the echo is noise
        return
    sent = await event.answer(text, reply_markup=kb)
    await state.update_data(ui_msg=sent.message_id)


async def _saving(event, state: FSMContext) -> None:
    """In-flight feedback and the double-submit guard, before every write.

    On a tap this is `common.begin_write`: the screen becomes "Saving…" and loses its keyboard,
    so the impatient second tap has no button to hit. On a typed step there is no button to
    take away, so the same notice goes onto the flow's own screen instead of being stacked
    underneath it as a second message.
    """
    if isinstance(event, CallbackQuery):
        await common.begin_write(event, common.chat_id_of(event))
        return
    await _render(event, state, t(common.chat_id_of(event), "common.saving"), None)


def _err_text(chat_id: int, exc: Exception) -> str:
    """The one place an exception becomes a sentence the owner can read.

    `api.Unreachable` is a subclass of `ApiError`, so it has to be tested first or the owner
    gets httpx's English sentence instead of the translated "couldn't reach the server".
    """
    if isinstance(exc, api.Unreachable):
        return t(chat_id, "common.serverUnreachable")
    if isinstance(exc, api.ApiError):
        return f"❌ {esc(exc.message)}"
    return t(chat_id, "common.serverUnreachable")


async def _session_gone(event, state: FSMContext) -> None:
    chat_id = common.chat_id_of(event)
    await state.clear()
    await common.show(event, t(chat_id, "common.sessionExpired"), keyboards.login_kb(chat_id))


# ── Closed months ────────────────────────────────────────────────────────────
async def _latest_closed(chat_id: int) -> str | None:
    """The newest permanently closed month as "YYYY-MM", or None if none / unknown.

    `MonthCloseService.assertMonthOpen` rejects every write dated in or before this month, so
    knowing it up front is the difference between "pick a date from an open month" at the date
    step and an English 400 eight steps later with the whole form discarded.
    """
    hit = _closed_cache.get(chat_id)
    if hit is not None and time.monotonic() - hit[0] < _CLOSED_TTL:
        return hit[1]
    try:
        months = await api.request(chat_id, "GET", "/months") or []
    except Exception:  # noqa: BLE001 - this is a courtesy; the backend stays the authority
        return None
    latest = months[0].get("month") if months else None
    _closed_cache[chat_id] = (time.monotonic(), latest)
    return latest


async def _month_locked(chat_id: int, date_iso: str | None) -> str | None:
    """The locked month naming this date, or None when the date can still be written.

    "YYYY-MM" strings compare correctly as text, which is why no date arithmetic happens here.
    """
    if not date_iso:
        return None
    latest = await _latest_closed(chat_id)
    if latest and date_iso[:7] <= latest:
        return date_iso[:7]
    return None


# ── Section menu ─────────────────────────────────────────────────────────────
def _menu_kb(chat_id: int):
    return ikb([
        [(t(chat_id, "common.add"), "tx:add"), (t(chat_id, "tx.recentBtn"), "tx:recent")],
        [(t(chat_id, "tx.moveBtn"), "tx:move")],
        [(t(chat_id, "common.menu"), "menu:home")],
    ])


async def show_menu(event) -> None:
    """The Transactions section screen. `menu.py` imports this by name."""
    chat_id = common.chat_id_of(event)
    await common.show(event, t(chat_id, "tx.menuTitle"), _menu_kb(chat_id))


@router.callback_query(F.data == "tx:menu")
async def tx_menu(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    await state.clear()
    await show_menu(cb)


@router.callback_query(F.data == "tx:cancel")
async def tx_cancel(cb: CallbackQuery, state: FSMContext) -> None:
    # Deliberately not state-gated: Cancel is the one button that must still work after a
    # restart has taken the flow it belongs to with it.
    await common.ack(cb)
    chat_id = common.chat_id_of(cb)
    await state.clear()
    await common.show(cb, t(chat_id, "common.cancelled"), _menu_kb(chat_id))


@router.callback_query(F.data == "noop")
async def noop(cb: CallbackQuery) -> None:
    """A button that must exist but must do nothing — `ui.NOOP`. Answering it stops the
    spinner; leaving it unanswered is what makes a keyboard look broken."""
    await common.ack(cb)


# ── Add: entry points ────────────────────────────────────────────────────────
# `/add` is deliberately NOT registered here. `routers/quickadd.py` owns it, and its version
# does more (`/add 50000 lunch` goes straight to a draft) — but this router is included first,
# so a `Command("add")` here would shadow it and the command would silently lose half its
# behaviour. The guided flow is reached from the Transactions screen instead.
@router.callback_query(F.data == "tx:add")
async def add_entry(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    if not await common.gate(cb):
        return
    if not await common.stable_income_set(cb):
        return
    await state.clear()
    await _step(cb, state, "type")


# ── Add: the step walker ─────────────────────────────────────────────────────
def _extra_step(d: dict) -> str | None:
    """Which of the two "who/what is this for?" questions this entry needs, if either.

    A donation booked under a category that anonymises gets its recipient overwritten with
    "Anonymous" by `TransactionService.isAnonymousCategory`, so asking for a name there would
    be a question whose answer is thrown away.
    """
    sub = d.get("a_subType")
    if sub == "INVESTMENT":
        return "holding"
    if sub == "DONATION" and not d.get("a_catAnon"):
        return "recipient"
    return None


def _applies(step: str, d: dict) -> bool:
    if step == "kind":
        return d.get("a_type") == "EXPENSE"
    if step == "extra":
        return _extra_step(d) is not None
    return True


def _back_cb(step: str) -> str:
    """The callback the Back button on `step` carries: the previous step, or out of the flow."""
    i = _ORDER.index(step)
    return "tx:menu" if i == 0 else f"aback:{_ORDER[i - 1]}"


async def _step(event, state: FSMContext, step: str, *, back: bool = False) -> None:
    """Render `step`, skipping past the ones this particular entry does not need.

    The skip runs in the direction of travel, so Back over a step that does not apply keeps
    going backwards instead of bouncing off it and landing forwards again.
    """
    d = await state.get_data()
    i = _ORDER.index(step)
    delta = -1 if back else 1
    while 0 <= i < len(_ORDER) and not _applies(_ORDER[i], d):
        i += delta
    i = max(0, min(i, len(_ORDER) - 1))
    await _ASK[_ORDER[i]](event, state)


async def _advance(event, state: FSMContext, done: str) -> None:
    """Move on from the step just answered — or straight back to the confirmation.

    `a_revise` is set when the owner steps back out of the confirmation to change one answer.
    Without it, fixing a wallet after a rejected write means walking the whole form again,
    which is the cost this flow exists to remove.
    """
    d = await state.get_data()
    if d.get("a_revise"):
        await state.update_data(a_revise=False)
        await _ask_confirm(event, state)
        return
    await _step(event, state, _ORDER[_ORDER.index(done) + 1])


@router.callback_query(StateFilter(AddTx, AddExtra), F.data.startswith("aback:"))
async def add_back(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    target = cb.data.split(":", 1)[1]
    if target not in _ORDER:
        target = "type"
    if await state.get_state() == AddTx.confirm.state:
        await state.update_data(a_revise=True)
    await _step(cb, state, target, back=True)


# ── Add: direction ───────────────────────────────────────────────────────────
async def _ask_type(event, state: FSMContext) -> None:
    chat_id = common.chat_id_of(event)
    await state.set_state(AddTx.type)
    kb = ikb([
        [(t(chat_id, "tx.income"), "atype:INCOME"), (t(chat_id, "tx.expense"), "atype:EXPENSE")],
        ui.nav(chat_id, back="tx:menu", cancel="tx:cancel"),
    ])
    await _render(event, state,
                  f"{t(chat_id, 'tx.addTitle')}\n{t(chat_id, 'tx.incomeOrExpense')}", kb)


@router.callback_query(StateFilter(AddTx.type), F.data.startswith("atype:"))
async def add_type(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    a_type = cb.data.split(":", 1)[1]
    if a_type not in ("INCOME", "EXPENSE"):
        return
    # Income funds no allocation bucket and has no kind to pick, so its sub-type is settled
    # here rather than left as a hole for the confirm step to paper over.
    # `a_revise` off too: the direction invalidates every later answer, so a change made from
    # the confirmation screen has to walk the form again rather than jump back to it.
    await state.update_data(a_type=a_type,
                            a_subType="REGULAR_INCOME" if a_type == "INCOME" else None,
                            a_categoryId=None, a_catAnon=False, a_allCats=False,
                            a_investmentId=None, a_invName=None, a_invType=None,
                            a_recipient=None, a_revise=False)
    await _advance(cb, state, "type")


# ── Add: amount ──────────────────────────────────────────────────────────────
async def _ask_amount(event, state: FSMContext, error: str | None = None) -> None:
    chat_id = common.chat_id_of(event)
    d = await state.get_data()
    await state.set_state(AddTx.amount)
    key = "tx.addHeader.income" if d.get("a_type") == "INCOME" else "tx.addHeader.expense"
    text = t(chat_id, key, currency=CURRENCY)
    if error:
        text = f"{error}\n\n{text}"
    # A typed step still gets a keyboard. Without one the owner who realises they picked the
    # wrong direction is standing in an FSM state with nothing on screen to tap.
    kb = ikb([ui.nav(chat_id, back=_back_cb("amount"), cancel="tx:cancel")])
    await _render(event, state, text, kb)


@router.message(StateFilter(AddTx.amount))
async def add_amount(message: Message, state: FSMContext) -> None:
    chat_id = message.chat.id
    amount = parse_amount(message.text)
    if amount is None:
        await _ask_amount(message, state, error=t(chat_id, "tx.positiveNumber"))
        return
    await state.update_data(a_amount=amount)
    await _advance(message, state, "amount")


# ── Add: kind of expense ─────────────────────────────────────────────────────
async def _ask_kind(event, state: FSMContext) -> None:
    chat_id = common.chat_id_of(event)
    await state.set_state(AddTx.subtype)
    rows = ui.grid([(t(chat_id, key), f"asub:{code}") for code, key in EXPENSE_SUBTYPES], 2)
    rows.append(ui.nav(chat_id, back=_back_cb("kind"), cancel="tx:cancel"))
    await _render(event, state, t(chat_id, "tx.whatKind"), ikb(rows))


@router.callback_query(StateFilter(AddTx.subtype), F.data.startswith("asub:"))
async def add_subtype(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    code = cb.data.split(":", 1)[1]
    if code not in SUBTYPE_KEY:
        return
    d = await state.get_data()
    if code != d.get("a_subType"):
        # The category list is filtered by the kind and the holding belongs to it, so both
        # become invalid the moment the kind changes — and the flow has to walk forward again
        # rather than jumping back to a confirmation built on the old pairing.
        await state.update_data(a_subType=code, a_categoryId=None, a_catAnon=False,
                                a_allCats=False, a_investmentId=None, a_invName=None,
                                a_invType=None, a_recipient=None, a_revise=False)
    await _advance(cb, state, "kind")


# ── Add: category ────────────────────────────────────────────────────────────
async def _ask_category(event, state: FSMContext) -> None:
    chat_id = common.chat_id_of(event)
    d = await state.get_data()
    await state.set_state(AddTx.category)
    params: dict[str, str] = {"type": d.get("a_type") or "EXPENSE"}
    filtered = not d.get("a_allCats") and bool(d.get("a_subType"))
    if filtered:
        # CategoryService applies this filter to the roots, so the picker can no longer offer
        # a category locked to a sub-type this flow does not produce.
        params["subType"] = d["a_subType"]
    try:
        roots = await api.request(chat_id, "GET", "/categories", params=params) or []
    except api.NeedsLogin:
        await _session_gone(event, state)
        return
    except Exception as exc:  # noqa: BLE001
        kb = ikb([
            [(t(chat_id, "common.retry"), "aback:cat")],
            ui.nav(chat_id, back=_back_cb("cat"), cancel="tx:cancel"),
        ])
        await _render(event, state, _err_text(chat_id, exc) if isinstance(exc, api.ApiError)
                      else t(chat_id, "tx.catLoadError"), kb)
        return
    await state.update_data(a_roots=roots)
    rows = ui.grid([(cat_name(chat_id, r),
                     f"acatopen:{r['id']}" if r.get("children") else f"acat:{r['id']}")
                    for r in roots], 2)
    text = t(chat_id, "tx.pickCategory")
    if not roots:
        text = f"{text}\n\n{t(chat_id, 'tx.catNoneForKind')}"
    rows.append([(t(chat_id, "tx.skipCategory"), "acatskip")])
    if filtered:
        rows.append([(t(chat_id, "tx.catShowAll"), "acatall")])
    rows.append(ui.nav(chat_id, back=_back_cb("cat"), cancel="tx:cancel"))
    await _render(event, state, text, ikb(rows))


async def _set_category(state: FSMContext, before: dict, cat_id, *, anonymous: bool) -> None:
    """Store the category — and stop revising when the choice changes what is still to ask.

    A donation moved off an anonymising category needs its recipient after all, so jumping
    straight back to the confirmation would silently skip the question and let the backend
    name the donation after the description again.
    """
    after = {**before, "a_categoryId": cat_id, "a_catAnon": anonymous}
    patch = {"a_categoryId": cat_id, "a_catAnon": anonymous}
    if _extra_step(after) != _extra_step(before):
        patch["a_revise"] = False
    await state.update_data(**patch)


def _find_category(roots, cat_id):
    """The chosen category and its root, anywhere two levels deep."""
    for r in roots:
        if r.get("id") == cat_id:
            return r, r
        for child in r.get("children", []):
            if child.get("id") == cat_id:
                return child, r
    return None, None


@router.callback_query(StateFilter(AddTx.category), F.data.startswith("acat"))
async def add_cat(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    chat_id = common.chat_id_of(cb)
    data = await state.get_data()
    d = cb.data
    if d == "acatskip":
        await _set_category(state, data, None, anonymous=False)
        await _advance(cb, state, "cat")
    elif d == "acatall":
        await state.update_data(a_allCats=True)
        await _ask_category(cb, state)
    elif d == "acatback":
        await _ask_category(cb, state)
    elif d.startswith("acatopen:"):
        rid = int(d.split(":")[1])
        root = next((r for r in data.get("a_roots", []) if r.get("id") == rid), {})
        rows = [[(t(chat_id, "tx.useCategory", name=cat_name(chat_id, root)), f"acat:{rid}")]]
        rows += ui.grid([(cat_name(chat_id, ch), f"acat:{ch['id']}")
                         for ch in root.get("children", [])], 2)
        rows.append(ui.nav(chat_id, back="acatback", cancel="tx:cancel"))
        await _render(cb, state, t(chat_id, "tx.pickSubCategory"), ikb(rows))
    elif d.startswith("acat:"):
        cat_id = int(d.split(":")[1])
        chosen, root = _find_category(data.get("a_roots", []), cat_id)
        anonymous = bool((chosen or {}).get("anonymizes") or (root or {}).get("anonymizes"))
        await _set_category(state, data, cat_id, anonymous=anonymous)
        await _advance(cb, state, "cat")


# ── Add: which holding / who received it ─────────────────────────────────────
async def _ask_extra(event, state: FSMContext) -> None:
    d = await state.get_data()
    if _extra_step(d) == "holding":
        await _ask_holding(event, state)
    else:
        await _ask_recipient(event, state)


async def _ask_holding(event, state: FSMContext) -> None:
    """Pick the investment this money is going into, or say it is a new one.

    Sending `investmentId` is also what tells the backend which bucket to credit: a savings
    goal counts toward Savings goals and a plain holding toward Investments, and the flag lives
    on the record, so the bot only has to send the id.
    """
    chat_id = common.chat_id_of(event)
    try:
        holdings = await api.request(chat_id, "GET", "/finance/investments") or []
    except api.NeedsLogin:
        await _session_gone(event, state)
        return
    except Exception:  # noqa: BLE001
        # Never fall through to "create a new one" here: that is exactly the branch that has
        # been growing a duplicate holding per month.
        await state.set_state(AddExtra.holding)
        kb = ikb([
            [(t(chat_id, "common.retry"), "aback:extra")],
            ui.nav(chat_id, back=_back_cb("extra"), cancel="tx:cancel"),
        ])
        await _render(event, state, t(chat_id, "tx.investmentLoadError"), kb)
        return
    holdings = [h for h in holdings if h.get("currency") in (None, CURRENCY)]
    await state.update_data(
        a_invs=[{"id": h.get("id"), "name": h.get("name") or ""} for h in holdings])
    if not holdings:
        await _ask_holding_name(event, state, first=True)
        return
    await state.set_state(AddExtra.holding)
    rows = []
    for h in holdings:
        if h.get("savingsGoal"):
            mark = "🎯"
        elif h.get("emergencyFund"):
            mark = "🛟"
        else:
            mark = "📈"
        label = f"{mark} {h.get('name') or '—'} · {fmt_money(h.get('currentValue'))}"
        rows.append([(label[:_LABEL_LIMIT], f"ainv:{h['id']}")])
    rows.append([(t(chat_id, "tx.investmentNew"), "ainv:new")])
    rows.append(ui.nav(chat_id, back=_back_cb("extra"), cancel="tx:cancel"))
    await _render(event, state, t(chat_id, "tx.investmentWhich"), ikb(rows))


async def _ask_holding_name(event, state: FSMContext, *, first: bool = False) -> None:
    chat_id = common.chat_id_of(event)
    await state.set_state(AddExtra.holding_name)
    key = "tx.investmentFirst" if first else "tx.investmentNameAsk"
    # With no holdings at all there is no picker to go back to, so Back leaves the step.
    back = _back_cb("extra") if first else "aback:extra"
    kb = ikb([ui.nav(chat_id, back=back, cancel="tx:cancel")])
    await _render(event, state, t(chat_id, key), kb)


async def _ask_holding_type(event, state: FSMContext) -> None:
    chat_id = common.chat_id_of(event)
    await state.set_state(AddExtra.holding_type)
    rows = ui.grid([(t(chat_id, key), f"ainvt:{code}") for code, key in INVESTMENT_TYPES], 2)
    rows.append(ui.nav(chat_id, back="ainvt:back", cancel="tx:cancel"))
    await _render(event, state, t(chat_id, "tx.investmentTypeAsk"), ikb(rows))


@router.callback_query(StateFilter(AddExtra.holding), F.data.startswith("ainv:"))
async def add_holding(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    choice = cb.data.split(":", 1)[1]
    if choice == "new":
        await state.update_data(a_investmentId=None)
        await _ask_holding_name(cb, state)
        return
    await state.update_data(a_investmentId=int(choice), a_invName=None, a_invType=None)
    await _advance(cb, state, "extra")


@router.message(StateFilter(AddExtra.holding_name))
async def add_holding_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if not name:
        await _ask_holding_name(message, state)
        return
    await state.update_data(a_invName=name[:120], a_investmentId=None)
    await _ask_holding_type(message, state)


@router.callback_query(StateFilter(AddExtra.holding_type), F.data.startswith("ainvt:"))
async def add_holding_type(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    code = cb.data.split(":", 1)[1]
    if code == "back":
        await _ask_holding_name(cb, state)
        return
    if code not in dict(INVESTMENT_TYPES):
        return
    await state.update_data(a_invType=code)
    await _advance(cb, state, "extra")


async def _ask_recipient(event, state: FSMContext) -> None:
    chat_id = common.chat_id_of(event)
    await state.set_state(AddExtra.recipient)
    kb = ikb([
        [(t(chat_id, "common.skip"), "adon:skip")],
        ui.nav(chat_id, back=_back_cb("extra"), cancel="tx:cancel"),
    ])
    await _render(event, state, t(chat_id, "tx.donationWho"), kb)


@router.callback_query(StateFilter(AddExtra.recipient), F.data == "adon:skip")
async def add_recipient_skip(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    await state.update_data(a_recipient=None)
    await _advance(cb, state, "extra")


@router.message(StateFilter(AddExtra.recipient))
async def add_recipient(message: Message, state: FSMContext) -> None:
    await state.update_data(a_recipient=(message.text or "").strip()[:120] or None)
    await _advance(message, state, "extra")


# ── Add: which wallet ────────────────────────────────────────────────────────
def _card_label(card: dict, short: bool) -> str:
    """A wallet button carries its balance, because the backend refuses a card expense over it.

    Button text is not HTML-parsed, so the card name is NOT escaped here — `esc()` would put a
    literal `&amp;` on the button.
    """
    tail = f" ···{card.get('lastFourDigits')}" if card.get("lastFourDigits") else ""
    mark = "⚠️" if short else "💳"
    return f"{mark} {card.get('name') or 'Card'}{tail} · {fmt_money(card.get('currentBalance'))}"[
        :_LABEL_LIMIT]


def _as_float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


async def _fetch_cards(chat_id: int) -> list[dict]:
    cards = await api.request(chat_id, "GET", "/cards") or []
    return [c for c in cards if c.get("currency") == CURRENCY and c.get("type") != "CASH"]


async def _ask_source(event, state: FSMContext) -> None:
    chat_id = common.chat_id_of(event)
    d = await state.get_data()
    try:
        cards = await _fetch_cards(chat_id)
    except api.NeedsLogin:
        await _session_gone(event, state)
        return
    except Exception:  # noqa: BLE001
        # A swallowed failure used to render as "you have no cards", and the owner then
        # recorded a card payment as cash — wrong on two wallet balances, discovered at
        # month-close. Offering nothing is better than offering the wrong answer.
        await state.set_state(AddTx.source)
        kb = ikb([
            [(t(chat_id, "common.retry"), "aback:src")],
            ui.nav(chat_id, back=_back_cb("src"), cancel="tx:cancel"),
        ])
        await _render(event, state, t(chat_id, "tx.sourceLoadError"), kb)
        return
    await state.update_data(a_cards=[{
        "id": c.get("id"), "name": c.get("name"), "lastFourDigits": c.get("lastFourDigits"),
        "currentBalance": c.get("currentBalance"),
    } for c in cards])
    amount = _as_float(d.get("a_amount"))
    is_expense = d.get("a_type") == "EXPENSE"
    rows = [[(t(chat_id, "common.cashBtn"), "asrc:cash")]]
    any_short = False
    for c in cards:
        short = is_expense and _as_float(c.get("currentBalance")) < amount
        any_short = any_short or short
        rows.append([(_card_label(c, short), f"asrc:card:{c['id']}")])
    rows.append(ui.nav(chat_id, back=_back_cb("src"), cancel="tx:cancel"))
    text = t(chat_id, "tx.paymentSource" if is_expense else "tx.incomeSource")
    if any_short:
        text = f"{text}\n\n{t(chat_id, 'tx.cardShortNote', amount=fmt_money(amount))}"
    await state.set_state(AddTx.source)
    await _render(event, state, text, ikb(rows))


@router.callback_query(StateFilter(AddTx.source), F.data.startswith("asrc:"))
async def add_src(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    parts = cb.data.split(":")
    card_id = None if parts[1] == "cash" else int(parts[2])
    await state.update_data(a_cardId=card_id)
    await _advance(cb, state, "src")


# ── Add: date ────────────────────────────────────────────────────────────────
async def _ask_date(event, state: FSMContext, error: str | None = None) -> None:
    chat_id = common.chat_id_of(event)
    await state.set_state(AddTx.date)
    text = t(chat_id, "tx.dateHeader")
    locked = await _latest_closed(chat_id)
    if locked:
        text = f"{text}\n\n{t(chat_id, 'tx.lockedThrough', month=locked)}"
    if error:
        text = f"{error}\n\n{text}"
    kb = ikb([
        [(t(chat_id, "common.today"), "adate:today")],
        ui.nav(chat_id, back=_back_cb("date"), cancel="tx:cancel"),
    ])
    await _render(event, state, text, kb)


async def _accept_date(event, state: FSMContext, date_iso: str) -> None:
    """Store a date, unless it lands in a month the backend has locked."""
    chat_id = common.chat_id_of(event)
    locked = await _month_locked(chat_id, date_iso)
    if locked:
        await _ask_date(event, state, error=t(chat_id, "tx.monthClosed", month=locked))
        return
    await state.update_data(a_date=date_iso)
    await _advance(event, state, "date")


@router.callback_query(StateFilter(AddTx.date), F.data == "adate:today")
async def add_date_today(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    await _accept_date(cb, state, today_iso())


@router.message(StateFilter(AddTx.date))
async def add_date_typed(message: Message, state: FSMContext) -> None:
    chat_id = message.chat.id
    text = (message.text or "").strip()
    try:
        dt.date.fromisoformat(text)
    except ValueError:
        await _ask_date(message, state, error=t(chat_id, "tx.sendDateFormat"))
        return
    await _accept_date(message, state, text)


# ── Add: description ─────────────────────────────────────────────────────────
async def _ask_desc(event, state: FSMContext) -> None:
    chat_id = common.chat_id_of(event)
    await state.set_state(AddTx.desc)
    kb = ikb([
        [(t(chat_id, "common.skip"), "adesc:skip")],
        ui.nav(chat_id, back=_back_cb("desc"), cancel="tx:cancel"),
    ])
    await _render(event, state, t(chat_id, "tx.addDescription"), kb)


@router.callback_query(StateFilter(AddTx.desc), F.data == "adesc:skip")
async def add_desc_skip(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    await state.update_data(a_desc=None)
    await _advance(cb, state, "desc")


@router.message(StateFilter(AddTx.desc))
async def add_desc_typed(message: Message, state: FSMContext) -> None:
    await state.update_data(a_desc=(message.text or "").strip() or None)
    await _advance(message, state, "desc")


# ── Add: the allocation preview ──────────────────────────────────────────────
async def _allocation_preview(chat_id: int, sub_type, amount, date, investment_id=None):
    """Ask the backend what this draft would do to the allocation.

    The sub-type → bucket routing lives server-side, so the bot cannot promise a bucket the
    accounting would not credit — and `investmentId` is part of that routing: the same
    INVESTMENT expense counts toward Savings goals or Investments depending on the holding.
    Returns None on any failure; the preview is a nicety and must never block a transaction.
    """
    if not sub_type:
        return None
    payload = {"subType": sub_type, "amount": amount, "transactionDate": date}
    if investment_id is not None:
        payload["investmentId"] = investment_id
    try:
        return await api.request(
            chat_id, "POST", f"/overview/allocation-preview?currency={CURRENCY}", json=payload)
    except Exception:  # noqa: BLE001
        return None


def _bucket_label(chat_id: int, preview: dict) -> str:
    key = _BUCKET_KEY.get(preview.get("bucket") or "")
    return t(chat_id, key) if key else esc(str(preview.get("label") or ""))


def _progress_line(chat_id: int, preview: dict, *, saved: bool = False) -> str:
    """The bucket's remaining-target sentence, rebuilt from the numbers.

    `AllocationPreviewResponse.message` says the same three things in English prose with an
    ungrouped raw BigDecimal in it ("Leaves 300000.00 still to put aside for Donation."), on
    the single most-walked screen in the bot. Every figure it uses is in the same payload.

    `saved=True` is the after-the-fact view, where the draft amount is already in `paidBefore`:
    "this covers the rest" and "it was already covered" are both past tense by then, so the
    covered case says so plainly instead of implying the entry did nothing.
    """
    remaining = _as_float(preview.get("remainingAfter"))
    if remaining <= 0:
        if saved:
            return t(chat_id, "alloc.fullyCovered")
        return t(chat_id, "alloc.completes" if preview.get("completesBucket")
                 else "alloc.alreadyCovered")
    return t(chat_id, "alloc.stillToGo", amount=fmt_money(remaining))


def _format_preview(chat_id: int, preview, sub_type: str | None) -> str:
    """The confirm screen's allocation block. Empty only when there is nothing true to say."""
    if not preview or not preview.get("applicable"):
        # Stocks is the one bucket-looking choice in the kind picker that funds no bucket —
        # `bucketForSubType` returns null for STOCK_PURCHASE. Saying so beats a blank space
        # that reads like the preview failed to load.
        return f"\n\n{t(chat_id, 'alloc.stocksNoBucket')}" if sub_type == "STOCK_PURCHASE" else ""
    label = _bucket_label(chat_id, preview)
    if preview.get("bucketNotRecommended"):
        return (f"\n\n{t(chat_id, 'alloc.countsToward', label=label)}\n"
                f"{t(chat_id, 'alloc.notRequired')}")
    return (
        f"\n\n{t(chat_id, 'alloc.countsToward', label=label)}\n"
        f"{t(chat_id, 'alloc.target')}: {fmt_money(preview.get('recommended'))}\n"
        f"{t(chat_id, 'alloc.paidSoFar')}: {fmt_money(preview.get('paidBefore'))}\n"
        f"{t(chat_id, 'alloc.afterThis')}: <b>{fmt_money(preview.get('paidAfter'))}</b>\n"
        f"<i>{_progress_line(chat_id, preview)}</i>"
    )


# ── Add: confirm ─────────────────────────────────────────────────────────────
def _cat_label(chat_id: int, roots, cat_id) -> str:
    if cat_id is None:
        return t(chat_id, "common.none")
    chosen, root = _find_category(roots or [], cat_id)
    if chosen is None:
        return t(chat_id, "tx.selected")
    if chosen is root:
        return cat_name(chat_id, root)
    return f"{cat_name(chat_id, root)} → {cat_name(chat_id, chosen)}"


def _holding_label(chat_id: int, d: dict) -> str | None:
    if d.get("a_investmentId") is not None:
        name = next((i.get("name") for i in d.get("a_invs", [])
                     if i.get("id") == d["a_investmentId"]), None)
        return esc(name) if name else t(chat_id, "tx.selected")
    if d.get("a_invName"):
        return t(chat_id, "tx.newHolding", name=esc(d["a_invName"]))
    return None


async def _ask_confirm(event, state: FSMContext, error: str | None = None) -> None:
    chat_id = common.chat_id_of(event)
    d = await state.get_data()
    await state.set_state(AddTx.confirm)
    src = t(chat_id, "common.cash") if d.get("a_cardId") is None else next(
        (c.get("name") or "Card" for c in d.get("a_cards", [])
         if c.get("id") == d["a_cardId"]), "Card")
    type_key = "common.typeIncome" if d.get("a_type") == "INCOME" else "common.typeExpense"
    lines = [
        t(chat_id, "tx.confirmPlease"),
        "",
        f"{t(chat_id, 'tx.fieldType')}: <b>{t(chat_id, type_key)}</b>",
        f"{t(chat_id, 'tx.fieldAmount')}: <b>{fmt_money(d.get('a_amount'))}</b>",
    ]
    sub = d.get("a_subType")
    if d.get("a_type") == "EXPENSE":
        kind = t(chat_id, SUBTYPE_KEY[sub]) if sub in SUBTYPE_KEY else t(chat_id, "common.none")
        lines.append(f"{t(chat_id, 'tx.fieldKind')}: {esc(kind)}")
    lines.append(f"{t(chat_id, 'tx.fieldCategory')}: "
                 f"{esc(_cat_label(chat_id, d.get('a_roots', []), d.get('a_categoryId')))}")
    holding = _holding_label(chat_id, d)
    if holding:
        lines.append(f"{t(chat_id, 'tx.fieldHolding')}: {holding}")
    if d.get("a_recipient"):
        lines.append(f"{t(chat_id, 'tx.fieldRecipient')}: {esc(d['a_recipient'])}")
    lines += [
        f"{t(chat_id, 'tx.fieldSource')}: {esc(src)}",
        f"{t(chat_id, 'tx.fieldDate')}: {esc(d.get('a_date') or '')}",
        f"{t(chat_id, 'tx.fieldDescription')}: "
        f"{esc(d.get('a_desc') or t(chat_id, 'common.none'))}",
    ]
    text = "\n".join(lines)
    text += _format_preview(chat_id, await _allocation_preview(
        chat_id, sub, d.get("a_amount"), d.get("a_date"), d.get("a_investmentId")), sub)
    rows = [ui.confirm_row(chat_id, "aok", "tx:cancel")]
    if error:
        # A rejected write keeps every answer: the two things the backend rejects on are the
        # wallet's balance and the amount, so both are one tap away.
        text = f"{error}\n\n{t(chat_id, 'tx.saveFailedHint')}\n\n{text}"
        rows.append([(t(chat_id, "tx.changeSource"), "aback:src"),
                     (t(chat_id, "tx.changeAmount"), "aback:amount")])
    rows.append(ui.nav(chat_id, back=_back_cb("confirm")))
    await _render(event, state, text, ikb(rows))


_ASK = {
    "type": _ask_type,
    "amount": _ask_amount,
    "kind": _ask_kind,
    "cat": _ask_category,
    "extra": _ask_extra,
    "src": _ask_source,
    "date": _ask_date,
    "desc": _ask_desc,
    "confirm": _ask_confirm,
}


def _add_payload(d: dict) -> dict:
    payload = {
        "type": d["a_type"],
        "amount": d["a_amount"],
        "currency": CURRENCY,
        "transactionDate": d["a_date"],
        "subType": d.get("a_subType") or (
            "REGULAR_INCOME" if d["a_type"] == "INCOME" else "REGULAR_EXPENSE"),
        "cashAmount": d["a_amount"] if d.get("a_cardId") is None else 0,
    }
    if d.get("a_cardId") is not None:
        payload["cardId"] = d["a_cardId"]
    if d.get("a_categoryId") is not None:
        payload["categoryId"] = d["a_categoryId"]
    if d.get("a_desc"):
        payload["description"] = d["a_desc"]
    if d.get("a_investmentId") is not None:
        # The whole point of the holding step: without this the backend builds a new
        # Investment named after the description and the portfolio grows a duplicate row.
        payload["investmentId"] = d["a_investmentId"]
    elif d.get("a_subType") == "INVESTMENT":
        payload["counterpartyName"] = d.get("a_invName")
        payload["investmentType"] = d.get("a_invType") or "OTHER"
    if d.get("a_recipient"):
        payload["counterpartyName"] = d["a_recipient"]
    return payload


@router.callback_query(StateFilter(AddTx.confirm), F.data == "aok")
async def add_confirm(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    chat_id = common.chat_id_of(cb)
    d = await state.get_data()
    if not d.get("a_amount") or not d.get("a_date"):
        await common.show(cb, t(chat_id, "tx.flowExpiredBody"), _menu_kb(chat_id))
        await state.clear()
        return
    payload = _add_payload(d)
    # Two guards, because one is not enough on a 10-second POST over mobile data: dropping the
    # state means a second tap no longer matches this handler's filter, and `_saving` takes the
    # button away. Without both, an impatient double tap books the transaction twice and the
    # month is silently over on spend.
    await state.set_state(None)
    await _saving(cb, state)
    try:
        await api.request(chat_id, "POST", "/transactions", json=payload)
    except api.NeedsLogin:
        await _session_gone(cb, state)
        return
    except Exception as exc:  # noqa: BLE001
        await _ask_confirm(cb, state, error=_err_text(chat_id, exc))
        return
    after = await _allocation_preview(chat_id, payload["subType"], 0,
                                      payload["transactionDate"], d.get("a_investmentId"))
    key = "tx.savedOk.income" if payload["type"] == "INCOME" else "tx.savedOk.expense"
    text = t(chat_id, key, amount=fmt_money(payload["amount"]))
    if after and after.get("applicable") and not after.get("bucketNotRecommended"):
        text += "\n\n" + t(chat_id, "tx.savedProgressHeader",
                           label=_bucket_label(chat_id, after),
                           paid=fmt_money(after.get("paidBefore")),
                           target=fmt_money(after.get("recommended")))
        text += "\n" + _progress_line(chat_id, after, saved=True)
    elif payload["subType"] == "STOCK_PURCHASE":
        text += f"\n\n{t(chat_id, 'alloc.stocksNoBucket')}"
    await state.clear()
    await common.show(cb, text, _menu_kb(chat_id))


# ── Move money ───────────────────────────────────────────────────────────────
# POST /transactions/transfer writes a TRANSFER_OUT / TRANSFER_IN pair, so neither leg counts
# as income or spending. Without it, topping a card up from cash meant booking a fake income
# and a fake expense — which inflated both figures in the month the owner was about to close.
def _wallet_name(chat_id: int, cards, card_id) -> str:
    if card_id is None:
        return t(chat_id, "common.cash")
    return next((c.get("name") or "Card" for c in cards if c.get("id") == card_id), "Card")


def _move_wallet_rows(chat_id: int, cards, cash, prefix: str, exclude) -> list:
    rows = []
    if exclude != "cash":
        cash_label = t(chat_id, "common.cashBtn")
        if cash is not None:
            cash_label = f"{cash_label} · {fmt_money(cash)}"
        rows.append([(cash_label[:_LABEL_LIMIT], f"{prefix}cash")])
    for c in cards:
        if c.get("id") == exclude:
            continue
        rows.append([(_card_label(c, False), f"{prefix}{c['id']}")])
    return rows


@router.callback_query(F.data == "tx:move")
async def move_entry(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    if not await common.gate(cb):
        return
    if not await common.stable_income_set(cb):
        return
    await state.clear()
    await _move_ask_from(cb, state)


async def _move_ask_from(event, state: FSMContext) -> None:
    chat_id = common.chat_id_of(event)
    try:
        cards = await _fetch_cards(chat_id)
    except api.NeedsLogin:
        await _session_gone(event, state)
        return
    except Exception as exc:  # noqa: BLE001
        await common.show(event, _err_text(chat_id, exc) if isinstance(exc, api.ApiError)
                          else t(chat_id, "tx.moveCardsError"), _menu_kb(chat_id))
        return
    if not cards:
        # A transfer needs a card on at least one side (TransactionService.transferBalance).
        await common.show(event, t(chat_id, "tx.moveNoCards"), _menu_kb(chat_id))
        return
    cash = None
    try:
        pots = await api.request(chat_id, "GET", "/cash-balances") or []
        cash = next((p.get("currentBalance") for p in pots
                     if p.get("currency") == CURRENCY), None)
    except Exception:  # noqa: BLE001 - the figure is a courtesy, the transfer is not
        cash = None
    await state.update_data(mv_cards=[{
        "id": c.get("id"), "name": c.get("name"), "lastFourDigits": c.get("lastFourDigits"),
        "currentBalance": c.get("currentBalance"),
    } for c in cards], mv_cash=cash)
    await state.set_state(MoveMoney.source)
    rows = _move_wallet_rows(chat_id, cards, cash, "mv:from:", exclude=None)
    rows.append(ui.nav(chat_id, back="tx:menu", cancel="tx:cancel"))
    await _render(event, state, t(chat_id, "tx.moveTitle"), ikb(rows))


async def _move_ask_to(event, state: FSMContext) -> None:
    chat_id = common.chat_id_of(event)
    d = await state.get_data()
    await state.set_state(MoveMoney.target)
    # Excluding the source is what keeps the two rejections in transferBalance unreachable:
    # "both sides null" and "source and destination must be different".
    exclude = "cash" if d.get("mv_from") is None else d.get("mv_from")
    rows = _move_wallet_rows(chat_id, d.get("mv_cards", []), d.get("mv_cash"),
                             "mv:to:", exclude=exclude)
    rows.append(ui.nav(chat_id, back="mv:back:from", cancel="tx:cancel"))
    await _render(event, state, t(chat_id, "tx.moveTo"), ikb(rows))


async def _move_ask_amount(event, state: FSMContext, error: str | None = None) -> None:
    chat_id = common.chat_id_of(event)
    await state.set_state(MoveMoney.amount)
    text = t(chat_id, "tx.moveAmount", currency=CURRENCY)
    if error:
        text = f"{error}\n\n{text}"
    await _render(event, state, text,
                  ikb([ui.nav(chat_id, back="mv:back:to", cancel="tx:cancel")]))


async def _move_ask_date(event, state: FSMContext, error: str | None = None) -> None:
    chat_id = common.chat_id_of(event)
    await state.set_state(MoveMoney.date)
    text = t(chat_id, "tx.moveDate")
    locked = await _latest_closed(chat_id)
    if locked:
        text = f"{text}\n\n{t(chat_id, 'tx.lockedThrough', month=locked)}"
    if error:
        text = f"{error}\n\n{text}"
    kb = ikb([
        [(t(chat_id, "common.today"), "mv:today")],
        ui.nav(chat_id, back="mv:back:amount", cancel="tx:cancel"),
    ])
    await _render(event, state, text, kb)


async def _move_confirm_screen(event, state: FSMContext, error: str | None = None) -> None:
    chat_id = common.chat_id_of(event)
    d = await state.get_data()
    await state.set_state(MoveMoney.confirm)
    cards = d.get("mv_cards", [])
    text = "\n".join([
        t(chat_id, "tx.moveConfirm"),
        "",
        f"{t(chat_id, 'tx.fieldFrom')}: {esc(_wallet_name(chat_id, cards, d.get('mv_from')))}",
        f"{t(chat_id, 'tx.fieldTo')}: {esc(_wallet_name(chat_id, cards, d.get('mv_to')))}",
        f"{t(chat_id, 'tx.fieldAmount')}: <b>{fmt_money(d.get('mv_amount'))}</b>",
        f"{t(chat_id, 'tx.fieldDate')}: {esc(d.get('mv_date') or '')}",
        "",
        t(chat_id, "tx.moveNote"),
    ])
    if error:
        text = f"{error}\n\n{t(chat_id, 'tx.saveFailedHint')}\n\n{text}"
    rows = [ui.confirm_row(chat_id, "mv:ok", "tx:cancel"),
            ui.nav(chat_id, back="mv:back:date")]
    await _render(event, state, text, ikb(rows))


@router.callback_query(StateFilter(MoveMoney.source), F.data.startswith("mv:from:"))
async def move_from(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    choice = cb.data.split(":")[2]
    await state.update_data(mv_from=None if choice == "cash" else int(choice), mv_to=None)
    await _move_ask_to(cb, state)


@router.callback_query(StateFilter(MoveMoney.target), F.data.startswith("mv:to:"))
async def move_to(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    choice = cb.data.split(":")[2]
    await state.update_data(mv_to=None if choice == "cash" else int(choice))
    await _move_ask_amount(cb, state)


@router.message(StateFilter(MoveMoney.amount))
async def move_amount(message: Message, state: FSMContext) -> None:
    chat_id = message.chat.id
    amount = parse_amount(message.text)
    if amount is None:
        await _move_ask_amount(message, state, error=t(chat_id, "tx.positiveNumber"))
        return
    await state.update_data(mv_amount=amount)
    await _move_ask_date(message, state)


async def _move_accept_date(event, state: FSMContext, date_iso: str) -> None:
    chat_id = common.chat_id_of(event)
    locked = await _month_locked(chat_id, date_iso)
    if locked:
        await _move_ask_date(event, state, error=t(chat_id, "tx.monthClosed", month=locked))
        return
    await state.update_data(mv_date=date_iso)
    await _move_confirm_screen(event, state)


@router.callback_query(StateFilter(MoveMoney.date), F.data == "mv:today")
async def move_date_today(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    await _move_accept_date(cb, state, today_iso())


@router.message(StateFilter(MoveMoney.date))
async def move_date_typed(message: Message, state: FSMContext) -> None:
    chat_id = message.chat.id
    text = (message.text or "").strip()
    try:
        dt.date.fromisoformat(text)
    except ValueError:
        await _move_ask_date(message, state, error=t(chat_id, "tx.sendDateFormat"))
        return
    await _move_accept_date(message, state, text)


@router.callback_query(StateFilter(MoveMoney), F.data.startswith("mv:back:"))
async def move_back(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    target = cb.data.split(":")[2]
    if target == "from":
        await _move_ask_from(cb, state)
    elif target == "to":
        await _move_ask_to(cb, state)
    elif target == "amount":
        await _move_ask_amount(cb, state)
    else:
        await _move_ask_date(cb, state)


@router.callback_query(StateFilter(MoveMoney.confirm), F.data == "mv:ok")
async def move_ok(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    chat_id = common.chat_id_of(cb)
    d = await state.get_data()
    if not d.get("mv_amount") or not d.get("mv_date"):
        await common.show(cb, t(chat_id, "tx.flowExpiredBody"), _menu_kb(chat_id))
        await state.clear()
        return
    payload = {
        "fromCardId": d.get("mv_from"),
        "toCardId": d.get("mv_to"),
        "amount": d["mv_amount"],
        "transactionDate": d["mv_date"],
    }
    await state.set_state(None)
    await _saving(cb, state)
    try:
        await api.request(chat_id, "POST", "/transactions/transfer", json=payload)
    except api.NeedsLogin:
        await _session_gone(cb, state)
        return
    except Exception as exc:  # noqa: BLE001
        await _move_confirm_screen(cb, state, error=_err_text(chat_id, exc))
        return
    cards = d.get("mv_cards", [])
    text = t(chat_id, "tx.moveSaved", amount=fmt_money(d["mv_amount"]),
             source=esc(_wallet_name(chat_id, cards, d.get("mv_from"))),
             target=esc(_wallet_name(chat_id, cards, d.get("mv_to"))))
    await state.clear()
    await common.show(cb, text, _menu_kb(chat_id))


# ── Recent list ──────────────────────────────────────────────────────────────
async def _render_recent(event, state: FSMContext, page: int,
                         note: str | None = None) -> None:
    """The list itself, with no `ack` and no `gate` — so a delete can re-render it.

    Those two used to live inside the handler, and the delete path called the handler: the
    second answerCallbackQuery for one tap raised, the re-render never ran, and a transaction
    that really had been deleted left the confirmation screen frozen on screen.
    """
    chat_id = common.chat_id_of(event)
    try:
        data = await api.request(chat_id, "GET", "/transactions", params={
            "currency": CURRENCY, "page": page, "size": PAGE_SIZE,
            "sortBy": "transactionDate", "sortDir": "desc"})
    except api.NeedsLogin:
        await _session_gone(event, state)
        return
    except Exception as exc:  # noqa: BLE001
        await common.show(event, _err_text(chat_id, exc) if isinstance(exc, api.ApiError)
                          else t(chat_id, "tx.loadError"), _menu_kb(chat_id))
        return
    data = data or {}
    content = data.get("content", [])
    total_pages = max(1, data.get("totalPages", 1) or 1)
    if not content and page > 0:
        # The last row on this page was just deleted. Step back rather than claiming there are
        # no transactions at all.
        await _render_recent(event, state, min(page - 1, total_pages - 1), note)
        return
    if not content:
        await common.show(event, t(chat_id, "tx.noTransactionsYet"), _menu_kb(chat_id))
        return
    locked_through = await _latest_closed(chat_id)
    rows = []
    for tx in content:
        date = tx.get("transactionDate", "")
        sign = "＋" if tx.get("type") == "INCOME" else "－"
        marks = ""
        if tx.get("transferPairId") is not None:
            marks += "🔄"
        if locked_through and date[:7] <= locked_through:
            marks += "🔒"
        label = f"{marks}{date} {sign}{fmt_money(tx.get('amount'))}"
        if tx.get("description"):
            label += f" · {tx['description'][:18]}"
        rows.append([(label[:_LABEL_LIMIT], f"txview:{tx['id']}:{page}")])
    rows.append(ui.pager(chat_id, page, total_pages, "txpage:"))
    rows.append(ui.nav(chat_id, back="tx:menu"))
    title = t(chat_id, "tx.recentTitle", currency=CURRENCY)
    if note:
        title = f"{note}\n\n{title}"
    await common.show(event, title, ikb(rows))


@router.callback_query((F.data == "tx:recent") | F.data.startswith("txpage:"))
async def show_recent(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    if not await common.gate(cb):
        return
    page = 0
    if cb.data.startswith("txpage:"):
        tail = cb.data.split(":", 1)[1]
        page = int(tail) if tail.isdigit() else 0
    await _render_recent(cb, state, page)


# ── One transaction ──────────────────────────────────────────────────────────
def _tx_ids(data: str) -> tuple[int, int]:
    """`<prefix>:<id>[:<page>]` — the page is remembered so Back lands where the user was."""
    parts = data.split(":")
    page = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
    return int(parts[1]), page


async def _render_view(event, state: FSMContext, tid: int, page: int,
                       note: str | None = None) -> None:
    chat_id = common.chat_id_of(event)
    try:
        tx = await api.request(chat_id, "GET", f"/transactions/{tid}")
    except api.NeedsLogin:
        await _session_gone(event, state)
        return
    except Exception as exc:  # noqa: BLE001
        await common.show(event, _err_text(chat_id, exc) if isinstance(exc, api.ApiError)
                          else t(chat_id, "tx.viewLoadError"), _menu_kb(chat_id))
        return
    tx = tx or {}
    card = (tx.get("card") or {}).get("name") or t(chat_id, "common.cash")
    type_key = "common.typeIncome" if tx.get("type") == "INCOME" else "common.typeExpense"
    date = tx.get("transactionDate") or ""
    lines = [
        t(chat_id, "tx.txHeader", id=tid),
        f"{t(chat_id, type_key)} · <b>{fmt_money(tx.get('amount'))}</b>",
        f"{t(chat_id, 'tx.fieldDate')}: {esc(date or '—')}",
        f"{t(chat_id, 'tx.fieldCategory')}: {esc(cat_name(chat_id, tx.get('category')))}",
        f"{t(chat_id, 'tx.fieldSource')}: {esc(card)}",
        f"{t(chat_id, 'tx.fieldDescription')}: "
        f"{esc(tx.get('description') or t(chat_id, 'common.none'))}",
        f"{t(chat_id, 'tx.fieldNote')}: {esc(tx.get('note') or t(chat_id, 'common.none'))}",
    ]
    locked = await _month_locked(chat_id, date)
    is_transfer = tx.get("transferPairId") is not None
    rows = []
    if locked:
        # A closed month is permanent: the backend refuses both the edit and the delete, so
        # neither button is offered and the screen says why instead of finding out from a 400.
        lines.append("")
        lines.append(t(chat_id, "tx.lockedRow", month=locked))
    elif is_transfer:
        # Editing one leg would leave the pair disagreeing; deleting takes both, which is the
        # backend's own behaviour and the only coherent way to change a move.
        lines.append("")
        lines.append(t(chat_id, "tx.transferRow"))
        rows.append([(t(chat_id, "common.delete"), f"txdel:{tid}:{page}")])
    else:
        rows.append([(t(chat_id, "common.edit"), f"txed:start:{tid}:{page}"),
                     (t(chat_id, "common.delete"), f"txdel:{tid}:{page}")])
    if note:
        lines.insert(0, note)
        lines.insert(1, "")
    rows.append(ui.nav(chat_id, back=f"txpage:{page}"))
    await _render(event, state, "\n".join(lines), ikb(rows))


@router.callback_query(F.data.startswith("txview:"))
async def show_view(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    if not await common.gate(cb):
        return
    tid, page = _tx_ids(cb.data)
    await _render_view(cb, state, tid, page)


# ── Delete ───────────────────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("txdel:"))
async def ask_delete(cb: CallbackQuery) -> None:
    await common.ack(cb)
    chat_id = common.chat_id_of(cb)
    tid, page = _tx_ids(cb.data)
    kb = ikb([ui.confirm_row(chat_id, f"txdelok:{tid}:{page}", f"txview:{tid}:{page}",
                             cancel_key="common.no", destructive=True)])
    await common.show(cb, t(chat_id, "tx.deleteConfirm", id=tid), kb)


@router.callback_query(F.data.startswith("txdelok:"))
async def do_delete(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    if not await common.gate(cb):
        return
    chat_id = common.chat_id_of(cb)
    tid, page = _tx_ids(cb.data)
    await common.begin_write(cb, chat_id)
    try:
        await api.request(chat_id, "DELETE", f"/transactions/{tid}")
    except api.NeedsLogin:
        await _session_gone(cb, state)
        return
    except Exception as exc:  # noqa: BLE001
        kb = ikb([ui.nav(chat_id, back=f"txpage:{page}", menu=True)])
        await common.show(cb, _err_text(chat_id, exc), kb)
        return
    # The acknowledgement rides on the list the owner lands back in: a toast would be dropped
    # (the query was answered on entry) and a screen of its own would cost another tap.
    await _render_recent(cb, state, page, note=t(chat_id, "tx.deleted"))


# ── Edit ─────────────────────────────────────────────────────────────────────
# PUT /transactions/{id} takes the whole record, so every edit is "read it, change one field,
# send it all back". Nothing else in the bot issues a PUT; without this, a mistyped amount
# costs the entire eight-step re-entry.
def _edit_payload(tx: dict) -> dict:
    payload = {
        "type": tx.get("type"),
        "amount": tx.get("amount"),
        "currency": CURRENCY,
        "transactionDate": tx.get("transactionDate"),
        "subType": tx.get("subType"),
        "cashAmount": tx.get("cashAmount") or 0,
    }
    if (tx.get("category") or {}).get("id") is not None:
        payload["categoryId"] = tx["category"]["id"]
    if (tx.get("card") or {}).get("id") is not None:
        payload["cardId"] = tx["card"]["id"]
    for field in ("description", "note", "place", "fromLocation", "toLocation"):
        if tx.get(field):
            payload[field] = tx[field]
    # Carried through untouched: changing either would make the backend reverse the linked
    # finance record and build a fresh one (syncFinanceRecordOnUpdate), which is exactly the
    # duplicate-holding behaviour the add flow now avoids.
    for field in ("investmentId", "loanGivenId"):
        if tx.get(field) is not None:
            payload[field] = tx[field]
    return payload


def _normalise_cash(payload: dict) -> None:
    """Keep `cashAmount` inside the range the service validates: 0 ≤ cashAmount ≤ amount.

    A cardless row must carry the whole amount as cash (the cash-balance query depends on it).
    A card row keeps whatever cash split it had, clamped — so editing 1 500 000 down to 150 000
    charges the card the difference instead of failing validation.
    """
    amount = _as_float(payload.get("amount"))
    if payload.get("cardId") is None:
        payload["cashAmount"] = amount
    else:
        payload["cashAmount"] = min(_as_float(payload.get("cashAmount")), amount)


def _edit_menu_kb(chat_id: int, tid: int, page: int):
    rows = ui.grid([
        (t(chat_id, "tx.editAmount"), "txed:f:amount"),
        (t(chat_id, "tx.editDate"), "txed:f:date"),
        (t(chat_id, "tx.editCategory"), "txed:f:cat"),
        (t(chat_id, "tx.editDescription"), "txed:f:desc"),
        (t(chat_id, "tx.editSource"), "txed:f:src"),
    ], 2)
    rows.append(ui.nav(chat_id, back=f"txview:{tid}:{page}", cancel="tx:cancel"))
    return ikb(rows)


@router.callback_query(F.data.startswith("txed:start:"))
async def edit_start(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    if not await common.gate(cb):
        return
    chat_id = common.chat_id_of(cb)
    parts = cb.data.split(":")
    tid = int(parts[2])
    page = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0
    try:
        tx = await api.request(chat_id, "GET", f"/transactions/{tid}")
    except api.NeedsLogin:
        await _session_gone(cb, state)
        return
    except Exception as exc:  # noqa: BLE001
        await common.show(cb, _err_text(chat_id, exc) if isinstance(exc, api.ApiError)
                          else t(chat_id, "tx.viewLoadError"), _menu_kb(chat_id))
        return
    await state.clear()
    await state.update_data(e_id=tid, e_page=page, e_tx=tx or {})
    await state.set_state(EditTx.field)
    await _render(cb, state, t(chat_id, "tx.editWhat"), _edit_menu_kb(chat_id, tid, page))


@router.callback_query(StateFilter(EditTx.field), F.data.startswith("txed:f:"))
async def edit_field(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    chat_id = common.chat_id_of(cb)
    field = cb.data.split(":")[2]
    d = await state.get_data()
    back = f"txed:start:{d.get('e_id')}:{d.get('e_page', 0)}"
    if field == "amount":
        await state.set_state(EditTx.amount)
        await _render(cb, state, t(chat_id, "tx.editAmountAsk", currency=CURRENCY),
                      ikb([ui.nav(chat_id, back=back, cancel="tx:cancel")]))
    elif field == "date":
        await state.set_state(EditTx.date)
        await _render(cb, state, t(chat_id, "tx.editDateAsk"), ikb([
            [(t(chat_id, "common.today"), "txed:today")],
            ui.nav(chat_id, back=back, cancel="tx:cancel"),
        ]))
    elif field == "desc":
        await state.set_state(EditTx.desc)
        await _render(cb, state, t(chat_id, "tx.editDescAsk"), ikb([
            [(t(chat_id, "tx.editDescClear"), "txed:descclr")],
            ui.nav(chat_id, back=back, cancel="tx:cancel"),
        ]))
    elif field == "cat":
        await _edit_ask_category(cb, state)
    elif field == "src":
        await _edit_ask_source(cb, state)


async def _edit_ask_category(event, state: FSMContext) -> None:
    chat_id = common.chat_id_of(event)
    d = await state.get_data()
    tx = d.get("e_tx") or {}
    back = f"txed:start:{d.get('e_id')}:{d.get('e_page', 0)}"
    params = {"type": tx.get("type") or "EXPENSE"}
    if tx.get("subType"):
        params["subType"] = tx["subType"]
    try:
        roots = await api.request(chat_id, "GET", "/categories", params=params) or []
    except api.NeedsLogin:
        await _session_gone(event, state)
        return
    except Exception as exc:  # noqa: BLE001
        await _render(event, state, _err_text(chat_id, exc),
                      ikb([ui.nav(chat_id, back=back, cancel="tx:cancel")]))
        return
    await state.update_data(e_roots=roots)
    await state.set_state(EditTx.category)
    rows = ui.grid([(cat_name(chat_id, r),
                     f"txed:catopen:{r['id']}" if r.get("children") else f"txed:cat:{r['id']}")
                    for r in roots], 2)
    rows.append([(t(chat_id, "tx.skipCategory"), "txed:catclr")])
    rows.append(ui.nav(chat_id, back=back, cancel="tx:cancel"))
    await _render(event, state, t(chat_id, "tx.pickCategory"), ikb(rows))


async def _edit_ask_source(event, state: FSMContext) -> None:
    chat_id = common.chat_id_of(event)
    d = await state.get_data()
    tx = d.get("e_tx") or {}
    back = f"txed:start:{d.get('e_id')}:{d.get('e_page', 0)}"
    try:
        cards = await _fetch_cards(chat_id)
    except api.NeedsLogin:
        await _session_gone(event, state)
        return
    except Exception:  # noqa: BLE001
        await _render(event, state, t(chat_id, "tx.sourceLoadError"),
                      ikb([ui.nav(chat_id, back=back, cancel="tx:cancel")]))
        return
    amount = _as_float(tx.get("amount"))
    is_expense = tx.get("type") == "EXPENSE"
    rows = [[(t(chat_id, "common.cashBtn"), "txed:src:cash")]]
    any_short = False
    for c in cards:
        # The card this row already sits on gets its own amount back when the balance is
        # checked (checkCardBalance takes the existing row into account), so it is never short
        # against itself.
        same = (tx.get("card") or {}).get("id") == c.get("id")
        short = is_expense and not same and _as_float(c.get("currentBalance")) < amount
        any_short = any_short or short
        rows.append([(_card_label(c, short), f"txed:src:{c['id']}")])
    rows.append(ui.nav(chat_id, back=back, cancel="tx:cancel"))
    text = t(chat_id, "tx.editSourceAsk")
    if any_short:
        text = f"{text}\n\n{t(chat_id, 'tx.cardShortNote', amount=fmt_money(amount))}"
    await state.set_state(EditTx.field)
    await _render(event, state, text, ikb(rows))


async def _edit_apply(event, state: FSMContext, patch: dict) -> None:
    chat_id = common.chat_id_of(event)
    d = await state.get_data()
    tid = d.get("e_id")
    page = d.get("e_page", 0)
    if tid is None:
        await common.show(event, t(chat_id, "tx.flowExpiredBody"), _menu_kb(chat_id))
        await state.clear()
        return
    payload = _edit_payload(d.get("e_tx") or {})
    payload.update(patch)
    _normalise_cash(payload)
    await state.set_state(None)
    await _saving(event, state)
    try:
        await api.request(chat_id, "PUT", f"/transactions/{tid}", json=payload)
    except api.NeedsLogin:
        await _session_gone(event, state)
        return
    except Exception as exc:  # noqa: BLE001
        kb = ikb([
            [(t(chat_id, "common.retry"), f"txed:start:{tid}:{page}")],
            ui.nav(chat_id, back=f"txview:{tid}:{page}", menu=True),
        ])
        await _render(event, state, f"{_err_text(chat_id, exc)}\n\n"
                                    f"{t(chat_id, 'tx.saveFailedHint')}", kb)
        return
    await _render_view(event, state, tid, page, note=t(chat_id, "tx.editSaved"))
    await state.clear()


@router.message(StateFilter(EditTx.amount))
async def edit_amount(message: Message, state: FSMContext) -> None:
    chat_id = message.chat.id
    amount = parse_amount(message.text)
    if amount is None:
        d = await state.get_data()
        back = f"txed:start:{d.get('e_id')}:{d.get('e_page', 0)}"
        await _render(message, state,
                      f"{t(chat_id, 'tx.positiveNumber')}\n\n"
                      f"{t(chat_id, 'tx.editAmountAsk', currency=CURRENCY)}",
                      ikb([ui.nav(chat_id, back=back, cancel="tx:cancel")]))
        return
    await _edit_apply(message, state, {"amount": amount})


@router.callback_query(StateFilter(EditTx.date), F.data == "txed:today")
async def edit_date_today(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    await _edit_date_value(cb, state, today_iso())


@router.message(StateFilter(EditTx.date))
async def edit_date_typed(message: Message, state: FSMContext) -> None:
    chat_id = message.chat.id
    text = (message.text or "").strip()
    d = await state.get_data()
    back = f"txed:start:{d.get('e_id')}:{d.get('e_page', 0)}"
    try:
        dt.date.fromisoformat(text)
    except ValueError:
        await _render(message, state,
                      f"{t(chat_id, 'tx.sendDateFormat')}\n\n{t(chat_id, 'tx.editDateAsk')}",
                      ikb([ui.nav(chat_id, back=back, cancel="tx:cancel")]))
        return
    await _edit_date_value(message, state, text)


async def _edit_date_value(event, state: FSMContext, date_iso: str) -> None:
    chat_id = common.chat_id_of(event)
    d = await state.get_data()
    back = f"txed:start:{d.get('e_id')}:{d.get('e_page', 0)}"
    locked = await _month_locked(chat_id, date_iso)
    if locked:
        await _render(event, state,
                      f"{t(chat_id, 'tx.monthClosed', month=locked)}\n\n"
                      f"{t(chat_id, 'tx.editDateAsk')}",
                      ikb([[(t(chat_id, "common.today"), "txed:today")],
                           ui.nav(chat_id, back=back, cancel="tx:cancel")]))
        return
    await _edit_apply(event, state, {"transactionDate": date_iso})


@router.callback_query(StateFilter(EditTx.desc), F.data == "txed:descclr")
async def edit_desc_clear(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    await _edit_apply(cb, state, {"description": None})


@router.message(StateFilter(EditTx.desc))
async def edit_desc_typed(message: Message, state: FSMContext) -> None:
    await _edit_apply(message, state, {"description": (message.text or "").strip() or None})


@router.callback_query(StateFilter(EditTx.category), F.data.startswith("txed:cat"))
async def edit_category(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    chat_id = common.chat_id_of(cb)
    d = await state.get_data()
    parts = cb.data.split(":")
    if parts[1] == "catclr":
        await _edit_apply(cb, state, {"categoryId": None})
        return
    if parts[1] == "catopen":
        rid = int(parts[2])
        root = next((r for r in d.get("e_roots", []) if r.get("id") == rid), {})
        rows = [[(t(chat_id, "tx.useCategory", name=cat_name(chat_id, root)),
                  f"txed:cat:{rid}")]]
        rows += ui.grid([(cat_name(chat_id, ch), f"txed:cat:{ch['id']}")
                         for ch in root.get("children", [])], 2)
        rows.append(ui.nav(chat_id, back="txed:f:cat", cancel="tx:cancel"))
        await _render(cb, state, t(chat_id, "tx.pickSubCategory"), ikb(rows))
        return
    await _edit_apply(cb, state, {"categoryId": int(parts[2])})


@router.callback_query(StateFilter(EditTx.category), F.data == "txed:f:cat")
async def edit_category_back(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    await _edit_ask_category(cb, state)


@router.callback_query(StateFilter(EditTx.field), F.data.startswith("txed:src:"))
async def edit_source(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    choice = cb.data.split(":")[2]
    if choice == "cash":
        # cashAmount follows in `_normalise_cash`: a cardless row carries the whole amount.
        await _edit_apply(cb, state, {"cardId": None})
        return
    await _edit_apply(cb, state, {"cardId": int(choice), "cashAmount": 0})


# ── A screen that outlived its flow ──────────────────────────────────────────
# Every prefix above that is state-gated appears here, and this handler is registered LAST so
# the gated versions always win when the state is there. Without it, a tap on a confirm button
# after a restart matched no handler at all: Telegram held the spinner for fifteen seconds and
# then cleared it, the message never changed, and the transaction was simply lost in silence.
_STALE_PREFIXES = ("atype:", "acat", "asub:", "ainv", "adon:", "asrc:", "adate:", "adesc:",
                   "aok", "aback:", "mv:", "txed:")


@router.callback_query(F.data.startswith(_STALE_PREFIXES))
async def stale_screen(cb: CallbackQuery, state: FSMContext) -> None:
    chat_id = common.chat_id_of(cb)
    await common.ack(cb, t(chat_id, "tx.flowExpired"))
    if await state.get_state() is not None:
        # A keyboard scrolled up from an earlier step, tapped while the flow is still running
        # further down the chat. Say the button is stale and leave the live screen — and the
        # answers already given — exactly as they are.
        return
    await state.clear()
    await common.show(cb, t(chat_id, "tx.flowExpiredBody"), _menu_kb(chat_id))
