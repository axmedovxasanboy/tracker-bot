"""👤 Profile — the web's Profile page (`GET /profile`) as one message, in the web's order:

1. one sentence — "This month: set aside X — P% of Y";
2. the level — a whole number, never a sub-level — on its own line, with what is left after bills
   and where the next level starts; next month's rule when it changes;
3. the savings rule's percentages;
4. to set aside this month — percent × what the percentages apply to (and a month without a bonus);
5. {Month} so far — "Pay for {month}" (the salary, avans and bonus counted for it) and "Set aside
   so far", split into Saved and Given (the donation is Given, never Saved);
6. how it is worked out, last — why the rule asks what it asks, then the two ladders. What the
   percentages apply to is the monthly income from Settings plus this month's bonus: recording
   the salary never moves the targets, only a bonus does.

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
    month = str(p.get("month") or clock.month())[:7]
    income, allocated = p.get("incomeThisMonth"), p.get("allocatedThisMonth")

    # ── The sentence ──
    if isinstance(allocated, dict):
        total = fmt_money(n(allocated.get("total")))
        if allocated.get("percentOfBase") is not None:
            lines += [t(chat_id, "profile.lead", total=total, base=fmt_money(n(p.get("savingsBase"))),
                        percent=_decimal(chat_id, n(allocated["percentOfBase"]))), ""]
        else:
            lines += [t(chat_id, "profile.leadShort", total=total), ""]

    # ── The level ──
    level = p.get("level")
    nxt = p.get("nextLevelAt")
    quiet = [t(chat_id, "profile.leftAfterBills", amount=fmt_money(n(p.get("leftAfterBills"))))]
    if p.get("aboveCeiling"):
        quiet.append(t(chat_id, "profile.aboveCeiling"))
    elif nxt is not None:
        quiet.append(t(chat_id, "profile.nextLevel", n=(level or 0) + 1, amount=fmt_money(n(nxt))))
    elif level is not None:
        quiet.append(t(chat_id, "profile.topLevel"))
    lines += [t(chat_id, "profile.level", n=level) if level is not None else t(chat_id, "profile.noLevel"),
              " · ".join(quiet)]
    # Why the rule asks what it asks — said in "How it is worked out", at the end.
    rule = p.get("rule") if isinstance(p.get("rule"), dict) else {}
    cutoff = rule.get("cutoff")
    why = [_reason(chat_id, rule.get("reason"), cutoff)]
    if rule.get("smallMonthlyLoans"):
        # Monthly loan payments to people count only above 10% of the monthly income (a loan to
        # repay fast always does). Below it, say why they change nothing.
        limit = rule.get("monthlyLoanLimit")
        if limit is None and n(p.get("stableIncome")) > 0:
            limit = n(p.get("stableIncome")) / 10
        if limit is not None:
            why.append(t(chat_id, "profile.reason.smallMonthlyLoans", limit=fmt_money(n(limit))))
    why = [line for line in why if line]
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
    # As on Home: this month's amount plus what earlier months left unpaid (`carried`, when sent).
    base = n(p.get("savingsBase"))
    lines += ["", t(chat_id, "profile.setAsideTitle")]
    for b in buckets:
        carried = max(0.0, n(b.get("carried")))
        lines.append(t(chat_id, "profile.setAsideRow", name=bucket_name(chat_id, b["bucket"]),
                       amount=fmt_money(n(b.get("amount")) + carried)))
        if n(b.get("percent")) > 0:
            lines.append(t(chat_id, "profile.percentOf", percent=percent_text(chat_id, b.get("percent")),
                           base=fmt_money(base)) + home.carried_note(chat_id, b, month))
        elif carried > 0:
            lines.append("   " + home.carried_note(chat_id, b, month).removeprefix(" · "))
        else:
            lines.append(t(chat_id, "profile.notThisMonthRow"))
    carried_total = sum(max(0.0, n(b.get("carried"))) for b in buckets)
    lines.append(t(chat_id, "profile.total", value=fmt_money(n(p.get("totalAmount")) + carried_total)))
    parts = p.get("baseParts") if isinstance(p.get("baseParts"), dict) else None
    bonus = n(parts.get("bonus")) if parts else n(p.get("bonusThisMonth"))
    if bonus > 0:
        lines.append(t(chat_id, "profile.withoutBonus", amount=fmt_money(n(p.get("normalMonthTotal")))))
        lines.append("<i>" + " · ".join(f"{bucket_name(chat_id, b['bucket'])} {fmt_money(n(b.get('normalMonthAmount')))}"
                                        for b in buckets) + "</i>")

    # ── This month so far ──
    if isinstance(income, dict) or isinstance(allocated, dict):
        lines += ["", t(chat_id, "profile.soFar", month=history.month_name(chat_id, month))]
    if isinstance(income, dict):
        # "Pay for {month}": the lines the server marks `inBase` — salary, avans, bonus, counted for
        # the month they are for (not "In", which goes by the day the money arrived).
        in_base = sorted((line for line in income.get("lines") or []
                          if isinstance(line, dict) and line.get("inBase") is not False),
                         key=lambda line: -n(line.get("amount")))
        lines.append(t(chat_id, "profile.payFor", month=history.month_name(chat_id, month),
                       amount=fmt_money(sum(n(x.get("amount")) for x in in_base))))
        if not in_base:
            lines.append(t(chat_id, "profile.noIncomeYet"))
        for line in in_base:
            lines.append(t(chat_id, "profile.incomeRow", name=esc(cat_name(chat_id, line)),
                           amount=fmt_money(n(line.get("amount")))))
    if isinstance(allocated, dict):
        if isinstance(income, dict):
            lines.append("")
        rows = sorted((r for r in allocated.get("lines") or [] if isinstance(r, dict) and r.get("bucket") in _ORDER),
                      key=lambda r: _ORDER.index(r["bucket"]))
        lines.append(t(chat_id, "profile.setAsideSoFar", amount=fmt_money(n(allocated.get("total")))))
        if rows:  # set aside = saved + given: the donation is given, never saved
            given = sum(n(r.get("amount")) for r in rows if r["bucket"] == "DONATION")
            lines.append(t(chat_id, "profile.savedGiven", saved=fmt_money(max(0.0, n(allocated.get("total")) - given)),
                           given=fmt_money(given)))
        if "percentOfBase" not in allocated and allocated.get("percentOfIncome") is not None:
            lines.append(t(chat_id, "profile.ofIncome", percent=_decimal(chat_id, n(allocated["percentOfIncome"]))))
        for r in rows:
            share = r.get("percentOfBase") if "percentOfBase" in r else r.get("percentOfIncome")
            target = r.get("target")
            if target is not None:
                target = home.savings_total(r)  # this month's plus what earlier months left unpaid
            met = target is not None and n(target) > 0 and n(r.get("amount")) >= n(target)
            name = t(chat_id, "profile.given") if r["bucket"] == "DONATION" else bucket_name(chat_id, r["bucket"])
            lines.append(t(chat_id, "profile.allocRow", name=name,
                           amount=fmt_money(n(r.get("amount"))) + (" ✓" if met else ""),
                           share="—" if share is None else f"{_decimal(chat_id, n(share))}%"))
            extra = []
            if target is not None and n(target) > 0:
                extra.append(t(chat_id, "profile.ofTarget", amount=fmt_money(n(target)))
                             + home.carried_note(chat_id, r, month))
            if r.get("over") is not None and n(r.get("over")) > 0:
                extra.append(t(chat_id, "profile.overAdvice", amount=fmt_money(n(r["over"]))))
            if extra:
                lines.append("   <i>" + " · ".join(extra) + "</i>")

    # ── How it is worked out ──
    lines += ["", t(chat_id, "profile.howTitle"), *why, t(chat_id, "profile.levelLadder"),
              _rung(chat_id, " ", t(chat_id, "profile.income"), p.get("stableIncome")),
              _rung(chat_id, "−", t(chat_id, "profile.bills"), p.get("monthlyBills")),
              "<b>" + _rung(chat_id, "=", t(chat_id, "profile.afterBills"), p.get("leftAfterBills")) + "</b>"]
    if level is not None:
        if nxt is not None and not p.get("aboveCeiling"):
            lines.append(t(chat_id, "profile.levelResultNext", n=level, next=level + 1, amount=fmt_money(n(nxt))))
        else:
            lines.append(t(chat_id, "profile.levelResult", n=level))
    lines += ["", t(chat_id, "profile.baseLadder")]
    from_settings = bool(parts and parts.get("usesStableIncome"))
    if from_settings:
        # The base is the monthly income from Settings plus this month's bonus: recording the salary
        # or an avans never moves it. The lines are the bonus by category — shown one by one when
        # they add up to it, else (none sent, or a server whose lines still carry the salary) as one.
        lines.append(_rung(chat_id, " ", t(chat_id, "profile.incomeFromSettings"), parts.get("stableIncome")))
        bonus_lines = [x for x in parts.get("lines") or [] if isinstance(x, dict) and n(x.get("amount")) > 0]
        if bonus_lines and abs(sum(n(x.get("amount")) for x in bonus_lines) - n(parts.get("bonus"))) < 1:
            lines += [_rung(chat_id, "+", esc(cat_name(chat_id, x)), x.get("amount")) for x in bonus_lines]
        elif n(parts.get("bonus")) > 0:
            lines.append(_rung(chat_id, "+", t(chat_id, "profile.bonus"), parts.get("bonus")))
    elif parts:
        # An older server: the base is the salary received, and it sends those lines.
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
    if from_settings:
        lines.append(t(chat_id, "profile.salaryNote"))
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

