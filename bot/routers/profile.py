"""👤 Profile — the web's Profile page (`GET /profile`) as one message, in the web's order:

1. the level — a whole number, never a sub-level — with the progress to the next one, the reason
   the savings rule is what it is, and next month's rule when it changes;
2. the savings rule's percentages;
3. to set aside this month — percent × savings base = amount (and a month without a bonus);
4. {Month} so far — the income the percentages apply to, and what was set aside against it;
5. how it is worked out — the two ladders.

Callbacks owned here: `prof`.
"""
from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from .. import api, clock, common, ui
from ..i18n import cat_name, get_lang, t
from ..keyboards import esc, ikb
from ..money import fmt_money
from ..session import store
from . import history, home

router = Router(name="profile")

n = home.n

_REASON = {
    "NO_DEBT": "profile.reason.noDebt",
    "BANK_LOAN_COMFORTABLE": "profile.reason.bankComfortable",
    "BANK_LOAN_TIGHT": "profile.reason.bankTight",
    "DEBTS_COMFORTABLE": "profile.reason.debtsComfortable",
    "DEBTS_TIGHT": "profile.reason.debtsTight",
    "BANK_AND_DEBTS": "profile.reason.bankAndDebts",
    "HEAVY_DEBT": "profile.reason.heavyDebt",
    "CUSTOM": "profile.reason.custom",
    "NO_RULE": "profile.reason.noRule",
}
# The sentences that name the cutoff are left unsaid rather than said with a hole in them.
_NAMES_CUTOFF = frozenset({"BANK_LOAN_COMFORTABLE", "BANK_LOAN_TIGHT", "DEBTS_COMFORTABLE", "DEBTS_TIGHT"})
_ORDER = ("DONATION", "EMERGENCY", "INVESTMENTS", "GOALS")
_BAR = 10


def _decimal(chat_id: int | None, value: float, places: int = 1) -> str:
    text = f"{value:.{places}f}"
    return text.replace(".", ",") if get_lang(chat_id) == "uz" else text


def percent_text(chat_id: int | None, p) -> str:
    """"5", "2,5" — a whole percent bare, anything else with one decimal (the web's percentText)."""
    value = n(p)
    return str(int(value)) if value == int(value) else _decimal(chat_id, value)


def bucket_name(chat_id: int | None, bucket: str) -> str:
    if bucket == "GOALS":
        return t(chat_id, "profile.goals")
    return t(chat_id, home.BUCKET_KEY.get(bucket, "home.bucket.goal"))


def _known(rows) -> list[dict]:
    return [r for r in rows or [] if isinstance(r, dict) and r.get("bucket") in home.BUCKETS]


def _reason(chat_id: int | None, reason: str | None, cutoff) -> str | None:
    key = _REASON.get(reason or "")
    if not key or (reason in _NAMES_CUTOFF and cutoff is None):
        return None
    return t(chat_id, key, cutoff=fmt_money(n(cutoff)) if cutoff is not None else "")


def _rung(chat_id: int | None, sign: str, label: str, amount) -> str:
    return t(chat_id, "profile.rung", sign=sign, label=label, amount=fmt_money(n(amount)))


def compose(chat_id: int | None, p: dict) -> list[str]:
    lines: list[str] = []
    # ── The level ──
    level = p.get("level")
    lines += [t(chat_id, "profile.levelLabel"),
              t(chat_id, "profile.level", n=level) if level is not None else t(chat_id, "profile.noLevel"),
              t(chat_id, "profile.leftAfterBills", amount=fmt_money(n(p.get("leftAfterBills"))))]
    nxt, frm = p.get("nextLevelAt"), n(p.get("levelFrom"))
    if p.get("aboveCeiling"):
        lines.append(t(chat_id, "profile.aboveCeiling"))
    elif nxt is None:
        if level is not None:
            lines.append(t(chat_id, "profile.topLevel"))
    else:
        span = n(nxt) - frm
        pct = min(100.0, max(0.0, (n(p.get("leftAfterBills")) - frm) / span * 100)) if span > 0 else 0.0
        filled = round(pct / 100 * _BAR)
        lines.append(t(chat_id, "profile.progress", bar="▰" * filled + "▱" * (_BAR - filled), percent=int(pct)))
        lines.append(t(chat_id, "profile.nextLevel", n=(level or 0) + 1, amount=fmt_money(n(nxt))))
    cutoff = (p.get("rule") or {}).get("cutoff")
    why = _reason(chat_id, (p.get("rule") or {}).get("reason"), cutoff)
    if why:
        lines += ["", why]
    nm = p.get("nextMonth")
    if isinstance(nm, dict) and nm.get("month"):
        next_why = _reason(chat_id, nm.get("reason"), cutoff)
        percents = " · ".join(f"{percent_text(chat_id, b.get('percent'))}%" for b in _known(nm.get("buckets")))
        lines += ["", t(chat_id, "profile.fromMonth" if next_why else "profile.fromMonthShort",
                        month=history.month_label(chat_id, str(nm["month"])[:7]), percents=percents,
                        reason=next_why or "")]

    # ── The rule ──
    buckets = _known(p.get("buckets"))
    lines += ["", t(chat_id, "profile.ruleTitle")]
    for b in buckets:
        value = (f"{percent_text(chat_id, b.get('percent'))}%" if n(b.get("percent")) > 0
                 else t(chat_id, "profile.notThisMonth"))
        lines.append(t(chat_id, "profile.ruleRow", name=bucket_name(chat_id, b["bucket"]), value=value))
    lines.append(t(chat_id, "profile.total", value=f"{percent_text(chat_id, p.get('totalPercent'))}%"))

    # ── To set aside this month ──
    base = n(p.get("savingsBase"))
    lines += ["", t(chat_id, "profile.setAsideTitle")]
    for b in buckets:
        lines.append(t(chat_id, "profile.setAsideRow", name=bucket_name(chat_id, b["bucket"]),
                       amount=fmt_money(n(b.get("amount")))))
        lines.append(t(chat_id, "profile.percentOf", percent=percent_text(chat_id, b.get("percent")),
                       base=fmt_money(base)) if n(b.get("percent")) > 0 else t(chat_id, "profile.notThisMonthRow"))
    lines.append(t(chat_id, "profile.total", value=fmt_money(n(p.get("totalAmount")))))
    parts = p.get("baseParts") if isinstance(p.get("baseParts"), dict) else None
    bonus = n(parts.get("bonus")) if parts else n(p.get("bonusThisMonth"))
    if bonus > 0:
        lines.append(t(chat_id, "profile.withoutBonus", amount=fmt_money(n(p.get("normalMonthTotal")))))
        lines.append("<i>" + " · ".join(f"{bucket_name(chat_id, b['bucket'])} {fmt_money(n(b.get('normalMonthAmount')))}"
                                        for b in buckets) + "</i>")

    # ── This month so far ──
    income, allocated = p.get("incomeThisMonth"), p.get("allocatedThisMonth")
    if isinstance(income, dict) or isinstance(allocated, dict):
        month = str(p.get("month") or clock.month())[:7]
        lines += ["", t(chat_id, "profile.soFar", month=history.month_name(chat_id, month))]
    if isinstance(income, dict):
        # Only what the percentages apply to — salary, avans, bonus (the owner's call on the web).
        in_base = sorted((line for line in income.get("lines") or []
                          if isinstance(line, dict) and line.get("inBase") is not False),
                         key=lambda line: -n(line.get("amount")))
        lines.append(t(chat_id, "profile.incomeThisMonth", amount=fmt_money(sum(n(x.get("amount")) for x in in_base))))
        if not in_base:
            lines.append(t(chat_id, "profile.noIncomeYet"))
        for line in in_base:
            lines.append(t(chat_id, "profile.incomeRow", name=esc(cat_name(chat_id, line)),
                           amount=fmt_money(n(line.get("amount")))))
    if isinstance(allocated, dict):
        if isinstance(income, dict):
            lines.append("")
        lines.append(t(chat_id, "profile.setAsideSoFar", amount=fmt_money(n(allocated.get("total")))))
        if "percentOfBase" in allocated:
            if allocated.get("percentOfBase") is not None:
                lines.append(t(chat_id, "profile.ofBase", percent=_decimal(chat_id, n(allocated["percentOfBase"]))))
        elif allocated.get("percentOfIncome") is not None:
            lines.append(t(chat_id, "profile.ofIncome", percent=_decimal(chat_id, n(allocated["percentOfIncome"]))))
        rows = sorted((r for r in allocated.get("lines") or [] if isinstance(r, dict) and r.get("bucket") in _ORDER),
                      key=lambda r: _ORDER.index(r["bucket"]))
        for r in rows:
            share = r.get("percentOfBase") if "percentOfBase" in r else r.get("percentOfIncome")
            target = r.get("target")
            met = target is not None and n(target) > 0 and n(r.get("amount")) >= n(target)
            lines.append(t(chat_id, "profile.allocRow", name=bucket_name(chat_id, r["bucket"]),
                           amount=fmt_money(n(r.get("amount"))) + (" ✓" if met else ""),
                           share="—" if share is None else f"{_decimal(chat_id, n(share))}%"))
            extra = []
            if target is not None and n(target) > 0:
                extra.append(t(chat_id, "profile.ofTarget", amount=fmt_money(n(target))))
            if r.get("over") is not None and n(r.get("over")) > 0:
                extra.append(t(chat_id, "profile.overAdvice", amount=fmt_money(n(r["over"]))))
            if extra:
                lines.append("   <i>" + " · ".join(extra) + "</i>")

    # ── How it is worked out ──
    lines += ["", t(chat_id, "profile.howTitle"), t(chat_id, "profile.levelLadder"),
              _rung(chat_id, " ", t(chat_id, "profile.income"), p.get("stableIncome")),
              _rung(chat_id, "−", t(chat_id, "profile.bills"), p.get("monthlyBills")),
              "<b>" + _rung(chat_id, "=", t(chat_id, "profile.afterBills"), p.get("leftAfterBills")) + "</b>"]
    if level is not None:
        if nxt is not None and not p.get("aboveCeiling"):
            lines.append(t(chat_id, "profile.levelResultNext", n=level, next=level + 1, amount=fmt_money(n(nxt))))
        else:
            lines.append(t(chat_id, "profile.levelResult", n=level))
    lines += ["", t(chat_id, "profile.baseLadder")]
    if parts:
        if parts.get("usesStableIncome"):
            lines.append(_rung(chat_id, " ", t(chat_id, "profile.incomeUntilSalary"), parts.get("stableIncome")))
            if n(parts.get("bonus")) > 0:
                lines.append(_rung(chat_id, "+", t(chat_id, "profile.bonus"), parts.get("bonus")))
        else:
            ladder = sorted((x for x in parts.get("lines") or [] if isinstance(x, dict)), key=lambda x: -n(x.get("amount")))
            for i, x in enumerate(ladder):
                lines.append(_rung(chat_id, "+" if i else " ", esc(cat_name(chat_id, x)), x.get("amount")))
    else:
        # An older server still builds the base from what is left after bills and loans.
        lines += [_rung(chat_id, " ", t(chat_id, "profile.afterBills"), p.get("leftAfterBills")),
                  _rung(chat_id, "−", t(chat_id, "profile.loanPayments"), p.get("loanPayments")),
                  _rung(chat_id, "=", t(chat_id, "profile.forSavings"), p.get("leftForSavings"))]
        if n(p.get("bonusThisMonth")) > 0:
            lines.append(_rung(chat_id, "+", t(chat_id, "profile.bonus"), p.get("bonusThisMonth")))
    lines.append("<b>" + _rung(chat_id, "=", t(chat_id, "profile.base"), p.get("savingsBase")) + "</b>")
    return lines


async def show_profile(event) -> None:
    chat_id = common.chat_id_of(event)
    nav = ui.nav(chat_id, back="more", home=True)
    try:
        p = await api.request(chat_id, "GET", "/profile", params={"date": clock.today_iso()}) or {}
    except api.ApiError as exc:
        if exc.status == 404:  # a server from before this page
            await common.show(event, t(chat_id, "profile.outdated"), ikb([nav]))
            return
        await home.report(event, exc)
        return
    except Exception as exc:  # noqa: BLE001
        await home.report(event, exc)
        return
    session = store.get(chat_id)
    name = p.get("username") or (session.username if session is not None else "") or "—"
    head = [t(chat_id, "profile.title", name=esc(name)), ""]
    if p.get("missingStableIncome"):
        await common.show(event, "\n".join(head + [t(chat_id, "profile.incomeTitle"), t(chat_id, "profile.incomeUnset")]),
                          ikb([[(t(chat_id, "settings.incomeBtn"), "set:income")], nav]))
        return
    await common.show(event, "\n".join(head + compose(chat_id, p)), ikb([
        [(t(chat_id, "profile.changeIncomeBtn"), "set:income"), (t(chat_id, "home.more.savings"), "sav")],
        nav,
    ]))


@router.callback_query(F.data == "prof")
async def on_profile(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    await state.clear()
    if not await common.gate(cb):
        return
    await show_profile(cb)

