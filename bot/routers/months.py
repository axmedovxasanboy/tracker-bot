"""Monthly envelope: the month summary, the permanent close flow, the closed history.

Three properties of this screen shape the code more than anything else.

**A close is permanent.** `MonthCloseService.close` books a reconciliation transaction per
wallet and stores an immutable snapshot; no endpoint reopens a month. So everything up to
the final POST is reversible — Back walks the wallets backwards, a review step lets any
figure be corrected before the commit, and a refusal from the server keeps every balance
already typed instead of dropping the owner back at wallet one. The old flow cleared the
FSM on any error, which on the one irreversible screen in the bot meant re-typing three
balances to find out which of them the server disliked.

**The month is chosen, not assumed.** The backend closes months strictly in order
(`MonthCloseService.closeBlockedReason`): once June is closed, the only month it will accept
is July. A bot that only ever offers `clock.month()` is therefore one skipped month away
from never being able to close anything again — which is exactly what this file used to do,
with the server's English "Close months in order…" as its last word on the subject. The
month now comes from `GET /months` (what is already closed) plus the clock, the summary can
be stepped back through past months so an unclosed one is visible at all, and a blocked
month offers the month that *is* closeable as a one-tap alternative.

**A mark is not a payment.** `taggedTotal` counts "already paid" marks; `taggedRecorded` is
the half that actually left a wallet, and the only half a close freezes — the DTO states
both identities outright (`taggedTotal = taggedRecorded + markedNotMoved` and
`everydaySpend = totalSpent − taggedRecorded`). Wherever the two can differ they are printed
as separate lines, because the failure this prevents is the owner believing money moved when
it did not, on a screen whose arithmetic is then frozen forever.

**A check-in is the close without the lock.** Reconciling only at the close leaves a month of
small unrecorded spending to surface as one gap nobody can explain any more; a wallet check-in
(`WalletCheckInService`) books it every few days, as the same everyday-spending adjustment.
It walks the wallets exactly the way the close does, so it rides the same per-wallet flow —
Back, the per-wallet edit, the review, the stale-button recovery — and `mc_mode` in the FSM
data says which of the two is running. Only the intro, the review's wording and the final POST
differ. The server decides when one is allowed (never once the next would fall in next month:
the close is then at most five days away and reconciles the same wallets), so the web app and
the bot cannot disagree about it.

Callback namespace owned here: `months:*` (the read screens), `mc:*` (the per-wallet walk both
flows share) and `ci:*` (entering a check-in).
"""
import re

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from .. import api, clock, common, keyboards, ui
from ..config import CURRENCY
from ..i18n import t
from ..keyboards import esc, ikb
from ..money import fmt_money, parse_number
from ..states import CloseMonth

router = Router()

# `YYYY-MM` — the only shape `YearMonth.parse` accepts. Callback data is the one place a
# month string arrives from outside this module, so it is matched against this before it is
# spent on a query parameter or interpolated into a screen.
_MONTH = re.compile(r"\d{4}-(?:0[1-9]|1[0-2])")

# A month lifted back out of the backend's English refusal. `closeBlockedReason` composes
# prose with no machine-readable code beside it, so re-stating it in the owner's language
# means recognising the sentence and recovering the one variable it carries.
_YM_IN_TEXT = re.compile(r"\b(\d{4}-\d{2})\b")

# How far back the "which month?" picker offers to start. It only ever appears when NOTHING
# has been closed yet — the single case where the backend accepts any past month — and a
# year is as far back as an owner is plausibly reconstructing balances by hand.
_PICK_WINDOW = 12


# ── month arithmetic (pure, no calendar library needed for YYYY-MM) ──────────
def _month_index(month: str) -> int:
    """Months since year zero. Makes "the next month" and "how far behind" one subtraction."""
    return int(month[:4]) * 12 + int(month[5:7]) - 1


def _shift(month: str, delta: int) -> str:
    total = _month_index(month) + delta
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def _month_or_now(raw: str | None) -> str:
    """A validated `YYYY-MM`, or today's month. Never trusts the string it was handed."""
    return raw if raw and _MONTH.fullmatch(raw) else clock.month()


def _as_float(value) -> float | None:
    """The API sends BigDecimals as JSON numbers, but a null is a real answer here."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _tap_index(data: str) -> int | None:
    tail = data.rpartition(":")[2]
    return int(tail) if tail.isdigit() else None


# ── shared rendering pieces ─────────────────────────────────────────────────
def _back_kb(chat_id: int):
    return ikb([[(t(chat_id, "months.backBtn"), "months:summary"),
                 (t(chat_id, "common.menu"), "menu:home")]])


def _wallet_label(chat_id: int, wallet: dict) -> str:
    """The wallet's name in the owner's language.

    Card names are the owner's own data and are language-neutral, but the cash line's label
    is composed server-side as the English literal "Cash" (`MonthCloseService.preview`), and
    that line is emitted on essentially every close — this bot's default transaction source
    is cash. Printing it verbatim put one English word in the middle of an Uzbek screen and
    disagreed with the "Naqd" the owner sees on every transaction they have ever confirmed.
    """
    if str(wallet.get("walletType") or "").upper() == "CASH":
        return t(chat_id, "common.cash")
    return str(wallet.get("label") or t(chat_id, "months.unnamedWallet"))


def _recorded(payload: dict) -> float:
    """`taggedRecorded` — the set-aside money that really left a wallet.

    Preferred straight from the payload because it is the figure the close freezes. The
    fallback is the identity the DTO documents (`taggedTotal = taggedRecorded +
    markedNotMoved`), which is exact, but deriving it by default would silently disagree the
    day the server changes what counts as a mark.
    """
    value = _as_float(payload.get("taggedRecorded"))
    if value is not None:
        return value
    return (_as_float(payload.get("taggedTotal")) or 0.0) - (_as_float(payload.get("markedNotMoved")) or 0.0)


def _set_aside_lines(chat_id: int, payload: dict) -> list[str]:
    """The set-aside total, split into what moved and what was only marked.

    The split is only printed when there are marks: with `markedNotMoved` at zero the two
    figures are the same number and a second line would be noise on every other month.
    """
    lines = [t(chat_id, "months.taggedTotal", amount=fmt_money(payload.get("taggedTotal")))]
    marked = _as_float(payload.get("markedNotMoved")) or 0.0
    if marked > 0:
        lines.append(t(chat_id, "months.taggedRecorded", amount=fmt_money(_recorded(payload))))
        lines.append(t(chat_id, "months.markedNotMoved", amount=fmt_money(marked)))
        lines.append(t(chat_id, "months.marksNote"))
    return lines


async def _ready(event) -> bool:
    """Session first, income guard second.

    Order matters: `stable_income_set` makes an authenticated GET, so asking it first means a
    dead session is discovered by the guard rather than by the gate, and the owner is told
    about their income instead of being offered the log-in screen they actually need.
    """
    if not await common.gate(event):
        return False
    return await common.stable_income_set(event)


# ── wallet check-in: the pieces the shared walk needs ───────────────────────
def _mode(data: dict) -> str:
    """Which flow the shared per-wallet walk is serving. Anything but a check-in is the close."""
    return "checkin" if data.get("mc_mode") == "checkin" else "close"


def _day(iso) -> str:
    """`2026-09-20` → `20.09` — how a date is written here, and short enough to scan."""
    text = str(iso or "")
    return f"{text[8:10]}.{text[5:7]}" if len(text) >= 10 else "—"


async def _checkin_status(chat_id: int) -> dict | None:
    """Today's check-in status, or None when it cannot be read: the summary still renders.

    Today is the owner's Tashkent day from `bot.clock` — the server runs on UTC, and on the 1st
    before 05:00 its own clock would still be in the previous month.
    """
    try:
        return await api.request(chat_id, "GET", "/months/checkin",
                                 params={"date": clock.today_iso()}) or None
    except api.NeedsLogin:
        raise
    except Exception:  # noqa: BLE001
        return None


def _checkin_lines(chat_id: int, st: dict) -> list[str]:
    """Where the check-ins stand, for the summary and the check-in intro."""
    month = str(st.get("month") or "")
    if not st.get("allowed"):
        if st.get("blockedCode") != "MONTH_ENDING":
            return []
        days = int(st.get("daysUntilMonthEnd") or 0)
        key = ("months.checkIn.endsToday" if days <= 0
               else "months.checkIn.endsInDay" if days == 1
               else "months.checkIn.endsInDays")
        lines = [t(chat_id, key, month=month, days=days, date=_day(st.get("nextMonthStart")))]
    else:
        since = st.get("daysSinceLastReconciled")
        if since is None:
            lines = [t(chat_id, "months.checkIn.statusNever")]
        elif st.get("due"):
            lines = [t(chat_id, "months.checkIn.statusDue", days=since)]
        else:
            first = (t(chat_id, "months.checkIn.statusToday") if since == 0
                     else t(chat_id, "months.checkIn.statusYesterday") if since == 1
                     else t(chat_id, "months.checkIn.statusDaysAgo", days=since))
            nxt = (t(chat_id, "months.checkIn.nextOn", date=_day(st.get("nextDueOn")))
                   if st.get("nextDueOn") else t(chat_id, "months.checkIn.nextIsClose"))
            lines = [f"{first} {nxt}"]
    so_far = _as_float(st.get("everydaySoFar")) or 0.0
    if so_far > 0:
        lines.append(t(chat_id, "months.checkIn.soFar", amount=fmt_money(so_far)))
    elif so_far < 0:
        lines.append(t(chat_id, "months.checkIn.soFarSurplus", amount=fmt_money(-so_far)))
    return lines


# ── summary view ────────────────────────────────────────────────────────────
async def show_menu(cb: CallbackQuery, state: FSMContext | None = None) -> None:
    """Entry point for the main menu (`menu.py` imports this name)."""
    await show_summary(cb)


async def show_summary(event, month: str | None = None) -> None:
    chat_id = common.chat_id_of(event)
    month = _month_or_now(month)
    try:
        s = await api.request(chat_id, "GET", "/months/summary",
                              params={"month": month, "currency": CURRENCY}) or {}
    except api.NeedsLogin:
        await common.show(event, t(chat_id, "common.sessionExpired"), keyboards.login_kb(chat_id))
        return
    except api.Unreachable:
        await common.show(event, t(chat_id, "common.serverUnreachable"), keyboards.back_menu_kb(chat_id))
        return
    except Exception:  # noqa: BLE001
        await common.show(event, t(chat_id, "months.summaryLoadError"), keyboards.back_menu_kb(chat_id))
        return

    closed = bool(s.get("closed"))
    lines = [
        t(chat_id, "months.summaryTitle", currency=CURRENCY, month=month),
        (t(chat_id, "months.closed") if closed else t(chat_id, "months.open")),
        "",
        t(chat_id, "months.startedWith", amount=fmt_money(s.get("startBalance"))),
        t(chat_id, "months.earned", amount=fmt_money(s.get("income"))),
    ]
    if closed:
        # Spent / left are null until the real balances are entered, so they belong to the
        # closed branch only — `fmt_money(None)` would print an em dash on every open month.
        lines.append(t(chat_id, "months.spent", amount=fmt_money(s.get("totalSpent"))))
        lines.append(t(chat_id, "months.left", amount=fmt_money(s.get("leftover"))))
    lines += [
        "",
        t(chat_id, "months.whereItWent"),
        t(chat_id, "months.donation", amount=fmt_money(s.get("donation"))),
        t(chat_id, "months.emergency", amount=fmt_money(s.get("emergency"))),
        t(chat_id, "months.investments", amount=fmt_money(s.get("investments"))),
        t(chat_id, "months.stocks", amount=fmt_money(s.get("stocks"))),
        t(chat_id, "months.savingsGoals", amount=fmt_money(s.get("savings"))),
    ]
    lines += _set_aside_lines(chat_id, s)
    lines.append(t(chat_id, "months.everydaySpending", amount=fmt_money(s.get("everydaySpend")))
                 if closed else t(chat_id, "months.everydayPending"))

    now = clock.month()
    checkin = None
    if not closed and month == now:
        try:
            checkin = await _checkin_status(chat_id)
        except api.NeedsLogin:
            await common.show(event, t(chat_id, "common.sessionExpired"), keyboards.login_kb(chat_id))
            return
        if checkin:
            lines += [""] + _checkin_lines(chat_id, checkin)

    rows = []
    if checkin and checkin.get("allowed"):
        # First, above the close: mid-month the check-in is the thing to do, and closing a month
        # that still has days left would lock them.
        rows.append([(t(chat_id, "months.checkIn.btn"), "ci:start")])
    if not closed:
        label = (t(chat_id, "months.closeThisMonth") if month == now
                 else t(chat_id, "months.closeMonthBtn", month=month))
        rows.append([(label, f"mc:m:{month}")])
    # Stepping back through months is what makes a skipped month visible at all: the bot
    # used to render today's month and nothing else, so July and August could sit unclosed
    # for ever without anything on any screen saying so.
    step: list[tuple[str, str]] = [(f"◀️ {_shift(month, -1)}", f"months:sum:{_shift(month, -1)}")]
    if _month_index(month) < _month_index(now):
        step.append((f"{_shift(month, 1)} ▶️", f"months:sum:{_shift(month, 1)}"))
    rows.append(step)
    rows.append([(t(chat_id, "months.historyBtn"), "months:history"),
                 (t(chat_id, "common.menu"), "menu:home")])
    await common.show(event, "\n".join(lines), ikb(rows))


async def show_history(cb: CallbackQuery) -> None:
    chat_id = common.chat_id_of(cb)
    try:
        rows = await api.request(chat_id, "GET", "/months") or []
    except api.NeedsLogin:
        await common.show(cb, t(chat_id, "common.sessionExpired"), keyboards.login_kb(chat_id))
        return
    except api.Unreachable:
        await common.show(cb, t(chat_id, "common.serverUnreachable"), _back_kb(chat_id))
        return
    except Exception:  # noqa: BLE001
        await common.show(cb, t(chat_id, "months.historyLoadError"), _back_kb(chat_id))
        return
    lines = [t(chat_id, "months.historyTitle", currency=CURRENCY)]
    if not rows:
        lines.append(t(chat_id, "months.noneClosedYet"))
    for m in rows[:24]:
        lines.append("• " + t(
            chat_id, "months.historyLine", month=esc(m.get("month")),
            earned=fmt_money(m.get("income")), spent=fmt_money(m.get("totalSpent")),
            left=fmt_money(m.get("leftover"))))
    await common.show(cb, "\n".join(lines), _back_kb(chat_id))


@router.callback_query(F.data == "months:summary")
async def on_summary(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    await state.clear()  # leaving the close flow by the front door
    if not await common.gate(cb):
        return
    await show_summary(cb)


@router.callback_query(F.data == "months:history")
async def on_history(cb: CallbackQuery) -> None:
    await common.ack(cb)
    if not await common.gate(cb):
        return
    await show_history(cb)


@router.callback_query(F.data.startswith("months:sum:"))
async def on_summary_of(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    await state.clear()
    if not await common.gate(cb):
        return
    await show_summary(cb, cb.data.split(":", 2)[2])


# ── which month can be closed ───────────────────────────────────────────────
async def _closed_months(chat_id: int) -> list[str]:
    """Every closed month, oldest last-position first — `GET /months`, sorted ascending.

    `YYYY-MM` sorts correctly as a string, which is the whole reason the API speaks it.
    """
    rows = await api.request(chat_id, "GET", "/months") or []
    return sorted(str(r.get("month")) for r in rows if r.get("month"))


def _candidates(closed: list[str]) -> list[str]:
    """The months the backend would accept a close for, most recent first.

    With anything already closed the answer is exactly one month — `latest + 1` — because
    `closeBlockedReason` refuses every other. With nothing closed there is no ordering
    constraint yet, so the first close may start anywhere in the past and the owner gets a
    real choice.
    """
    now = clock.month()
    if closed:
        nxt = _shift(closed[-1], 1)
        return [nxt] if _month_index(nxt) <= _month_index(now) else []
    return [_shift(now, -i) for i in range(_PICK_WINDOW)]


async def _next_closeable(chat_id: int) -> str | None:
    """The one month a close would be accepted for right now, or None."""
    try:
        candidates = _candidates(await _closed_months(chat_id))
    except Exception:  # noqa: BLE001 — the block screen is still worth showing without it
        return None
    return candidates[0] if candidates else None


def _reason(chat_id: int, message: str | None) -> str:
    """Re-state the backend's English refusal in the owner's language where we recognise it.

    `closeBlockedReason` and `assertMonthOpen` compose prose and hand back no code, so this
    matches on the sentences themselves — brittle by nature, which is why the raw server
    string survives as the fallback rather than being swallowed. The month is recovered by
    regex, so it is digits and a dash by construction and cannot carry markup.
    """
    raw = " ".join((message or "").split())
    low = raw.lower()
    found = _YM_IN_TEXT.search(raw)
    month = found.group(1) if found else None
    if month and "already closed" in low:
        return t(chat_id, "months.blocked.alreadyClosed", month=month)
    if "current or a past month" in low:
        return t(chat_id, "months.blocked.futureMonth")
    if month and "in order" in low:
        return t(chat_id, "months.blocked.outOfOrder", month=month)
    if month and "closed and locked" in low:
        return t(chat_id, "months.blocked.locked", month=month)
    if "stable income" in low:
        return t(chat_id, "months.blocked.noIncome")
    return esc(raw) if raw else t(chat_id, "months.cantCloseYet")


async def _show_blocked(event, month: str, preview: dict) -> None:
    """Why this month cannot be closed — derived from state we hold, not from English prose.

    `alreadyClosed` is in the payload and the future-month test is arithmetic, so two of the
    three refusals never need the server's sentence at all. The third one needs to name the
    month that IS closeable, which `GET /months` answers; only if that call fails do we fall
    back to reading `blockedReason`.
    """
    chat_id = common.chat_id_of(event)
    nxt = await _next_closeable(chat_id)
    if preview.get("alreadyClosed"):
        text = t(chat_id, "months.blocked.alreadyClosed", month=month)
    elif _month_index(month) > _month_index(clock.month()):
        text = t(chat_id, "months.blocked.futureMonth")
    elif nxt:
        text = t(chat_id, "months.blocked.outOfOrder", month=nxt)
    else:
        text = _reason(chat_id, preview.get("blockedReason"))
    rows = []
    if nxt and nxt != month:
        # The whole point of the screen: one tap onto the month that can actually be closed.
        rows.append([(t(chat_id, "months.closeMonthBtn", month=nxt), f"mc:m:{nxt}")])
    rows.append(ui.nav(chat_id, back=f"months:sum:{month}", menu=True))
    await common.show(event, f"🔒 {text}", ikb(rows))


@router.callback_query(F.data == "months:close")
async def on_close(cb: CallbackQuery, state: FSMContext) -> None:
    """"Close a month" without naming one: resolve it, then pick or go straight in."""
    await common.ack(cb)
    if not await _ready(cb):
        return
    chat_id = common.chat_id_of(cb)
    try:
        closed = await _closed_months(chat_id)
    except api.NeedsLogin:
        await common.show(cb, t(chat_id, "common.sessionExpired"), keyboards.login_kb(chat_id))
        return
    except Exception:  # noqa: BLE001
        await common.show(cb, t(chat_id, "months.closePreviewError"), _back_kb(chat_id))
        return
    candidates = _candidates(closed)
    if not candidates:
        await common.show(cb, t(chat_id, "months.allClosed", month=esc(closed[-1])), _back_kb(chat_id))
        return
    if len(candidates) == 1:
        await _close_intro(cb, state, candidates[0])
        return
    await _show_picker(cb, candidates)


async def _show_picker(event, candidates: list[str]) -> None:
    chat_id = common.chat_id_of(event)
    rows = ui.grid([(m, f"mc:m:{m}") for m in candidates], 3)
    rows.append(ui.nav(chat_id, back="months:summary", menu=True))
    body = f"{t(chat_id, 'months.pickTitle')}\n\n{t(chat_id, 'months.pickBody')}"
    await common.show(event, body, ikb(rows))


@router.callback_query(F.data == "mc:pick")
async def on_pick(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    if not await _ready(cb):
        return
    chat_id = common.chat_id_of(cb)
    try:
        candidates = _candidates(await _closed_months(chat_id))
    except api.NeedsLogin:
        await common.show(cb, t(chat_id, "common.sessionExpired"), keyboards.login_kb(chat_id))
        return
    except Exception:  # noqa: BLE001
        await common.show(cb, t(chat_id, "months.closePreviewError"), _back_kb(chat_id))
        return
    if not candidates:
        await common.show(cb, t(chat_id, "months.cantCloseYet"), _back_kb(chat_id))
        return
    await _show_picker(cb, candidates)


@router.callback_query(F.data.startswith("mc:m:"))
async def on_month_chosen(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    if not await _ready(cb):
        return
    await _close_intro(cb, state, _month_or_now(cb.data.split(":", 2)[2]))


# ── close flow: intro ───────────────────────────────────────────────────────
def _wallet_keys(wallets: list[dict] | None) -> list[str]:
    return [f"{w.get('walletType')}:{w.get('cardId')}:{w.get('currency')}" for w in (wallets or [])]


async def _close_intro(event, state: FSMContext, month: str) -> None:
    """The screen that names the month and the figures before a single balance is typed.

    It doubles as Back's destination from the first wallet, so it re-reads the preview rather
    than replaying a cached one — and it keeps any balances already entered when the wallet
    set is unchanged, so stepping back out of the walk and into it again costs nothing.
    """
    chat_id = common.chat_id_of(event)
    try:
        p = await api.request(chat_id, "GET", "/months/preview",
                              params={"month": month, "currency": CURRENCY}) or {}
    except api.NeedsLogin:
        await common.show(event, t(chat_id, "common.sessionExpired"), keyboards.login_kb(chat_id))
        return
    except api.Unreachable:
        await common.show(event, t(chat_id, "common.serverUnreachable"), _back_kb(chat_id))
        return
    except api.ApiError as exc:
        await common.show(event, f"❌ {_reason(chat_id, exc.message)}", _back_kb(chat_id))
        return
    except Exception:  # noqa: BLE001
        await common.show(event, t(chat_id, "months.closePreviewError"), _back_kb(chat_id))
        return

    if not p.get("closeable"):
        await _show_blocked(event, month, p)
        return
    wallets = p.get("wallets") or []
    if not wallets:
        await common.show(event, t(chat_id, "months.noWallets"), _back_kb(chat_id))
        return

    data = await state.get_data()
    values = data.get("mc_values")
    # Balances carry over only from an interrupted close of this same month: a check-in's are
    # today's, not the month-end's, and reusing them here would put the wrong day's figures
    # into a record that can never be changed.
    if (_mode(data) != "close" or data.get("mc_month") != month or not isinstance(values, list)
            or _wallet_keys(data.get("mc_wallets")) != _wallet_keys(wallets)):
        values = [None] * len(wallets)
    await state.set_state(CloseMonth.month)
    await state.update_data(mc_mode="close", mc_month=month, mc_wallets=wallets,
                            mc_values=list(values), mc_index=0)

    behind = _month_index(clock.month()) - _month_index(month)
    lines = [t(chat_id, "months.introTitle", month=month)]
    if behind > 0:
        lines.append(t(chat_id, "months.pastMonthNote", count=behind))
    lines += [
        "",
        t(chat_id, "months.startedWith", amount=fmt_money(p.get("startBalance"))),
        t(chat_id, "months.earned", amount=fmt_money(p.get("income"))),
    ]
    lines += _set_aside_lines(chat_id, p)
    lines += [
        t(chat_id, "months.spendableNow", amount=fmt_money(p.get("spendableNow"))),
        "",
        t(chat_id, "months.introBody", count=len(wallets)),
        t(chat_id, "months.permanentWarning"),
    ]
    rows = [[(t(chat_id, "months.startBtn"), "mc:start")]]
    if len(_candidates([])) > 1 and not p.get("alreadyClosed"):
        # A choice of month only exists before the first close; offering "another month"
        # afterwards would be a button whose every alternative the server refuses.
        rows.append([(t(chat_id, "months.pickAnotherBtn"), "mc:pick")])
    rows.append(ui.nav(chat_id, back=f"months:sum:{month}", menu=True))
    await common.show(event, "\n".join(lines), ikb(rows))


@router.callback_query(F.data == "ci:start")
async def ci_start(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    if not await _ready(cb):
        return
    await _checkin_intro(cb, state)


async def _checkin_intro(event, state: FSMContext) -> None:
    """The check-in's first screen, and Back's destination from its first wallet.

    Re-reads the status every time rather than trusting the button that led here: the button
    may be days old, and the month may have crossed into its last five days since.
    """
    chat_id = common.chat_id_of(event)
    try:
        st = await api.request(chat_id, "GET", "/months/checkin",
                               params={"date": clock.today_iso()}) or {}
    except api.NeedsLogin:
        await common.show(event, t(chat_id, "common.sessionExpired"), keyboards.login_kb(chat_id))
        return
    except api.Unreachable:
        await common.show(event, t(chat_id, "common.serverUnreachable"), _back_kb(chat_id))
        return
    except api.ApiError as exc:
        await common.show(event, f"❌ {esc(exc.message)}", _back_kb(chat_id))
        return
    except Exception:  # noqa: BLE001
        await common.show(event, t(chat_id, "months.checkIn.loadError"), _back_kb(chat_id))
        return

    if not st.get("allowed"):
        await state.clear()
        lines = _checkin_lines(chat_id, st) or [f"🔒 {esc(st.get('blockedReason') or '')}"]
        await common.show(event, "\n".join(lines), _back_kb(chat_id))
        return
    wallets = st.get("wallets") or []
    if not wallets:
        await common.show(event, t(chat_id, "months.noWallets"), _back_kb(chat_id))
        return

    date = str(st.get("date") or clock.today_iso())
    data = await state.get_data()
    values = data.get("mc_values")
    if (_mode(data) != "checkin" or data.get("mc_date") != date or not isinstance(values, list)
            or _wallet_keys(data.get("mc_wallets")) != _wallet_keys(wallets)):
        values = [None] * len(wallets)
    await state.set_state(CloseMonth.month)
    await state.update_data(mc_mode="checkin", mc_date=date, mc_month=str(st.get("month") or clock.month()),
                            mc_wallets=wallets, mc_values=list(values), mc_index=0)

    lines = [t(chat_id, "months.checkIn.introTitle", date=_day(date)), ""]
    lines += _checkin_lines(chat_id, st)
    lines += ["", t(chat_id, "months.checkIn.introBody", count=len(wallets)),
              t(chat_id, "months.checkIn.recordFirst")]
    rows = [[(t(chat_id, "months.startBtn"), "mc:start")],
            ui.nav(chat_id, back="months:summary", menu=True)]
    await common.show(event, "\n".join(lines), ikb(rows))


async def _intro(event, state: FSMContext) -> None:
    """Back to the first screen of whichever flow is running."""
    d = await state.get_data()
    if _mode(d) == "checkin":
        await _checkin_intro(event, state)
    else:
        await _close_intro(event, state, d["mc_month"])


# ── close flow: one wallet at a time ────────────────────────────────────────
def _first_unset(values: list) -> int | None:
    for i, v in enumerate(values):
        if v is None:
            return i
    return None


async def _prompt(event, state: FSMContext) -> None:
    chat_id = common.chat_id_of(event)
    d = await state.get_data()
    wallets = d["mc_wallets"]
    idx = min(max(int(d.get("mc_index") or 0), 0), len(wallets) - 1)
    w = wallets[idx]
    computed = _as_float(w.get("computedBalance"))
    entered = d["mc_values"][idx]

    checkin = _mode(d) == "checkin"
    lines = [
        (t(chat_id, "months.checkIn.header", index=idx + 1, total=len(wallets)) if checkin
         else t(chat_id, "months.closeHeader", month=d["mc_month"], index=idx + 1, total=len(wallets))),
        "",
        f"<b>{esc(_wallet_label(chat_id, w))}</b>",
        t(chat_id, "months.walletComputed", amount=fmt_money(computed)),
    ]
    if computed is not None and computed < 0:
        lines.append(t(chat_id, "months.overdrawnNote"))
    lines += ["", t(chat_id, "months.checkIn.walletAsk" if checkin else "months.walletAsk", currency=CURRENCY)]

    rows = []
    if entered is not None:
        rows.append([(t(chat_id, "months.keepEntered", amount=fmt_money(entered)), f"mc:keep:{idx}")])
    if computed is not None:
        # `enteredBalance` is `@DecimalMin("0")`, so an overdrawn wallet's real computed
        # figure is a legal balance to *report* and an illegal one to *submit*. Offering it
        # as a button was a trap: the 400 only arrived after every other wallet was typed.
        offer = (t(chat_id, "months.useZero") if computed < 0
                 else t(chat_id, "months.checkIn.matchesBtn", amount=fmt_money(computed)) if checkin
                 else t(chat_id, "months.useComputed", amount=fmt_money(computed)))
        rows.append([(offer, f"mc:use:{idx}")])
    rows.append(ui.nav(chat_id, back=f"mc:back:{idx}", cancel="mc:cancel"))
    await state.set_state(CloseMonth.balance)
    await state.update_data(mc_index=idx)
    await common.show(event, "\n".join(lines), ikb(rows))


async def _record(event, state: FSMContext, value: float) -> None:
    """Store one wallet's balance, then go wherever there is still work to do.

    Values live in a slot per wallet rather than an append-only list, which is what makes
    Back and the review's per-wallet edit possible: answering an already-answered wallet
    overwrites its slot and lands straight back on the review, because nothing is unset.
    """
    d = await state.get_data()
    values = list(d["mc_values"])
    idx = min(max(int(d.get("mc_index") or 0), 0), len(values) - 1)
    values[idx] = float(value)
    nxt = _first_unset(values)
    await state.update_data(mc_values=values, mc_index=idx if nxt is None else nxt)
    if nxt is None:
        await _review(event, state)
    else:
        await _prompt(event, state)


@router.callback_query(StateFilter(CloseMonth.month), F.data == "mc:start")
async def mc_start(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    d = await state.get_data()
    nxt = _first_unset(d.get("mc_values") or [])
    if nxt is None:
        await _review(cb, state)
        return
    await state.update_data(mc_index=nxt)
    await _prompt(cb, state)


@router.callback_query(StateFilter(CloseMonth.balance), F.data.startswith("mc:use:"))
async def mc_use(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    d = await state.get_data()
    idx = _tap_index(cb.data)
    if idx != d.get("mc_index"):
        # The index is stamped into the callback data because every wallet shares one state:
        # a tap on the previous wallet's "Use 250 000", left on screen after a typed answer
        # posted a fresh message, would otherwise write that figure into the wallet being
        # asked for now.
        await _prompt(cb, state)
        return
    computed = _as_float(d["mc_wallets"][idx].get("computedBalance")) or 0.0
    await _record(cb, state, max(computed, 0.0))


@router.callback_query(StateFilter(CloseMonth.balance), F.data.startswith("mc:keep:"))
async def mc_keep(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    d = await state.get_data()
    idx = _tap_index(cb.data)
    if idx != d.get("mc_index"):
        await _prompt(cb, state)
        return
    previous = d["mc_values"][idx]
    if previous is None:
        await _prompt(cb, state)
        return
    await _record(cb, state, float(previous))


@router.callback_query(StateFilter(CloseMonth.balance), F.data.startswith("mc:back:"))
async def mc_back(cb: CallbackQuery, state: FSMContext) -> None:
    """One wallet backwards, and out to the intro from the first one.

    Cancel alone was never enough here: this is the one flow in the bot that cannot be undone
    after it commits, so a mistyped balance three wallets ago has to be reachable without
    throwing the other two away.
    """
    await common.ack(cb)
    d = await state.get_data()
    idx = int(d.get("mc_index") or 0)
    if idx <= 0:
        await _intro(cb, state)
        return
    await state.update_data(mc_index=idx - 1)
    await _prompt(cb, state)


@router.message(StateFilter(CloseMonth.balance))
async def mc_typed(message: Message, state: FSMContext) -> None:
    chat_id = common.chat_id_of(message)
    value = parse_number(message.text)
    if value is None:
        await message.answer(t(chat_id, "common.sendNumberExample"))
        return
    if value < 0:
        # Refused here, where one number can be fixed, rather than by the server after every
        # other wallet has been typed and the whole flow is about to be thrown away.
        await message.answer(t(chat_id, "months.negativeBalance"))
        return
    await _record(message, state, value)


@router.message(StateFilter(CloseMonth.month))
async def mc_typed_intro(message: Message, state: FSMContext) -> None:
    """A number typed at the intro must not fall through to the quick-add catch-all."""
    await message.answer(t(common.chat_id_of(message), "months.tapStart"))


# ── close flow: review and commit ───────────────────────────────────────────
async def _review(event, state: FSMContext, notice: str | None = None) -> None:
    """Every entered balance, correctable, with the commit underneath it."""
    chat_id = common.chat_id_of(event)
    d = await state.get_data()
    wallets, values = d["mc_wallets"], d["mc_values"]
    total = sum(v for v in values if v is not None)

    checkin = _mode(d) == "checkin"
    lines = []
    if notice:
        lines += [notice, ""]
    lines += [(t(chat_id, "months.checkIn.reviewHeader", date=_day(d.get("mc_date"))) if checkin
               else t(chat_id, "months.confirmCloseHeader", month=d["mc_month"])), "",
              t(chat_id, "months.realBalancesEntered")]
    for i, w in enumerate(wallets):
        lines.append(t(chat_id, "months.walletLine", index=i + 1,
                       label=esc(_wallet_label(chat_id, w)), amount=fmt_money(values[i])))
    if checkin:
        # The same arithmetic the server runs, per wallet: computed − entered, netted.
        gap = sum((_as_float(w.get("computedBalance")) or 0.0) - v
                  for w, v in zip(wallets, values) if v is not None)
        lines += ["", (t(chat_id, "months.checkIn.willRecord", amount=fmt_money(gap)) if gap > 0
                       else t(chat_id, "months.checkIn.willRecordSurplus", amount=fmt_money(-gap)) if gap < 0
                       else t(chat_id, "months.checkIn.willRecordNothing")),
                  "", t(chat_id, "months.checkIn.reviewHint")]
    else:
        lines += ["", t(chat_id, "months.reviewTotal", amount=fmt_money(total)),
                  t(chat_id, "months.permanentWarning"), "", t(chat_id, "months.reviewHint")]

    # Button text is not HTML-parsed, so the label goes in raw — esc() here would print a
    # literal &amp; on any card the owner named "Visa & co".
    rows = ui.grid([(t(chat_id, "months.editWalletBtn", label=_wallet_label(chat_id, w)), f"mc:edit:{i}")
                    for i, w in enumerate(wallets)], 2)
    rows.append([(t(chat_id, "months.checkIn.saveBtn") if checkin else t(chat_id, "months.confirmClose"), "mc:ok")])
    # Back from the review is the last wallet — the same screen the edit buttons open, so
    # there is one way in and one way out of every step.
    rows.append(ui.nav(chat_id, back=f"mc:edit:{len(wallets) - 1}", cancel="mc:cancel"))
    await state.set_state(CloseMonth.confirm)
    await common.show(event, "\n".join(lines), ikb(rows))


@router.callback_query(StateFilter(CloseMonth.confirm, CloseMonth.balance), F.data.startswith("mc:edit:"))
async def mc_edit(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    d = await state.get_data()
    idx = _tap_index(cb.data)
    if idx is None or not 0 <= idx < len(d.get("mc_wallets") or []):
        await _review(cb, state)
        return
    await state.update_data(mc_index=idx)
    await _prompt(cb, state)


@router.message(StateFilter(CloseMonth.confirm))
async def mc_typed_review(message: Message, state: FSMContext) -> None:
    await message.answer(t(common.chat_id_of(message), "months.tapConfirm"))


@router.callback_query(StateFilter(CloseMonth.confirm), F.data == "mc:ok")
async def mc_ok(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    chat_id = common.chat_id_of(cb)
    d = await state.get_data()
    wallets, values = d["mc_wallets"], d["mc_values"]
    missing = _first_unset(values)
    if missing is not None:  # only reachable from a replayed tap; ask for what is missing
        await state.update_data(mc_index=missing)
        await _prompt(cb, state)
        return

    entries = [{"walletType": w.get("walletType"), "cardId": w.get("cardId"),
                "currency": w.get("currency") or CURRENCY, "enteredBalance": v}
               for w, v in zip(wallets, values)]
    if _mode(d) == "checkin":
        await _commit_checkin(cb, state, d, entries)
        return
    payload = {"month": d["mc_month"], "wallets": entries}
    await common.begin_write(cb, chat_id)
    try:
        res = await api.request(chat_id, "POST", "/months/close", json=payload) or {}
    except api.NeedsLogin:
        await state.clear()
        await common.show(cb, t(chat_id, "common.sessionExpired"), keyboards.login_kb(chat_id))
        return
    except api.Unreachable:
        await _review(cb, state, t(chat_id, "common.serverUnreachable"))
        return
    except api.ApiError as exc:
        # The state is deliberately NOT cleared. A refusal here used to discard every balance
        # the owner had just typed, on the one flow that walks them wallet by wallet, and
        # left them to guess which figure the server disliked.
        await _review(cb, state, f"{t(chat_id, 'months.closeRefused')}\n{_reason(chat_id, exc.message)}")
        return
    except Exception:  # noqa: BLE001
        await _review(cb, state, t(chat_id, "common.serverUnreachable"))
        return

    await state.clear()
    month = str(res.get("month") or d["mc_month"])
    lines = [
        t(chat_id, "months.closedResultTitle", month=esc(month), currency=CURRENCY),
        t(chat_id, "months.resultEarned", amount=fmt_money(res.get("income"))),
        t(chat_id, "months.resultSpent", amount=fmt_money(res.get("totalSpent"))),
        t(chat_id, "months.resultEveryday", amount=fmt_money(res.get("everydaySpend"))),
        t(chat_id, "months.resultLeftover", amount=fmt_money(res.get("leftover"))),
    ]
    rows = []
    if _MONTH.fullmatch(month):
        nxt = _shift(month, 1)
        if _month_index(nxt) <= _month_index(clock.month()):
            # Catching up on skipped months is the case that made this flow unreachable in
            # the first place; offer the next one instead of making them navigate back.
            rows.append([(t(chat_id, "months.closeMonthBtn", month=nxt), f"mc:m:{nxt}")])
    rows.append([(t(chat_id, "months.backBtn"), "months:summary"),
                 (t(chat_id, "common.menu"), "menu:home")])
    await common.show(cb, "\n".join(lines), ikb(rows))


async def _commit_checkin(cb: CallbackQuery, state: FSMContext, d: dict, entries: list[dict]) -> None:
    chat_id = common.chat_id_of(cb)
    await common.begin_write(cb, chat_id)
    try:
        res = await api.request(chat_id, "POST", "/months/checkin",
                                json={"date": d.get("mc_date") or clock.today_iso(), "wallets": entries}) or {}
    except api.NeedsLogin:
        await state.clear()
        await common.show(cb, t(chat_id, "common.sessionExpired"), keyboards.login_kb(chat_id))
        return
    except api.Unreachable:
        await _review(cb, state, t(chat_id, "common.serverUnreachable"))
        return
    except api.ApiError as exc:
        # Kept, as for the close: the owner fixes one figure instead of retyping every wallet.
        await _review(cb, state, f"{t(chat_id, 'months.checkIn.refused')}\n{esc(exc.message)}")
        return
    except Exception:  # noqa: BLE001
        await _review(cb, state, t(chat_id, "common.serverUnreachable"))
        return

    await state.clear()
    recorded = _as_float(res.get("everydayRecorded")) or 0.0
    so_far = _as_float(res.get("everydaySoFar")) or 0.0
    lines = [
        t(chat_id, "months.checkIn.savedTitle"),
        (t(chat_id, "months.checkIn.savedSpent", amount=fmt_money(recorded)) if recorded > 0
         else t(chat_id, "months.checkIn.savedSurplus", amount=fmt_money(-recorded)) if recorded < 0
         else t(chat_id, "months.checkIn.savedMatched")),
    ]
    if so_far:
        lines.append(t(chat_id, "months.checkIn.soFar" if so_far > 0 else "months.checkIn.soFarSurplus",
                       amount=fmt_money(abs(so_far))))
    lines.append(t(chat_id, "months.checkIn.nextOn", date=_day(res.get("nextDueOn"))) if res.get("nextDueOn")
                 else t(chat_id, "months.checkIn.nextIsClose"))
    await common.show(cb, "\n".join(lines), _back_kb(chat_id))


@router.callback_query(F.data == "mc:cancel")
async def mc_cancel(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    await state.clear()
    if not await common.gate(cb):
        return
    await show_summary(cb)


async def _resume(event, state: FSMContext) -> bool:
    """Re-render whichever step the flow is really on. False when there is no flow left."""
    d = await state.get_data()
    if not d.get("mc_wallets") or not d.get("mc_month") or not isinstance(d.get("mc_values"), list):
        return False
    current = await state.get_state()
    if current == CloseMonth.confirm.state:
        await _review(event, state)
    elif current == CloseMonth.balance.state:
        await _prompt(event, state)
    elif current == CloseMonth.month.state:
        await _intro(event, state)
    else:
        return False
    return True


@router.callback_query(F.data.startswith("mc:"))
async def mc_stale(cb: CallbackQuery, state: FSMContext) -> None:
    """A close-flow tap no step above wanted — almost always an older message's button.

    Every typed balance posts a NEW message, so the earlier prompts stay in the chat with
    live buttons under them. This deliberately does not clear the flow: the owner may have
    three balances entered on the screen further down, and answering a stale tap by throwing
    them away would be the very failure the review step exists to prevent. It brings them
    back to the step the flow is on, and only says "expired" when there is genuinely nothing
    left — after a restart, since FSM state lives in memory.
    """
    await common.ack(cb)
    if not await common.gate(cb):
        return
    if await _resume(cb, state):
        return
    await state.clear()
    chat_id = common.chat_id_of(cb)
    rows = [[(t(chat_id, "months.startAgainBtn"), "months:close")],
            [(t(chat_id, "months.backBtn"), "months:summary"),
             (t(chat_id, "common.menu"), "menu:home")]]
    await common.show(cb, t(chat_id, "months.flowExpired"), ikb(rows))
