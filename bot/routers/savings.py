"""🎯 Savings — the web's Savings page (tracker-frontend pages/Savings.tsx), in the bot.

One screen with this month's savings (Pay / Add more on each row, through `pay.py`) and a line
per section, then a screen per section:

* **Goals** — progress, "{monthly} a month from {Mon}", "by {deadline}", On track / Behind; add,
  edit, add money, delete. A goal is a savings-goal holding (GET/POST/PUT /finance/investments).
* **Emergency fund** — ONE total over both places it is kept (the plain contributions of
  GET /emergencies and the emergency-flagged holdings), then the entries, newest first.
* **Investments** — per account "Put in X · now Y · +Z (+P%)"; add, add money, update value
  ("What changed?" first), take money out, edit, delete.
* **Donations** — this year's total, the latest entries, add one (amount, wallet, recipient).

Figures are the web's: a holding is worth its server `value` (else current value, else what went
in), growth is `putIn` against that, and a goal's plan is `goalPlan` (components/savings/goalPlan.ts).

Callbacks owned here: `sav` and `sav:*`.
"""
from __future__ import annotations

import asyncio
import math
from typing import Any

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, TelegramObject

from .. import api, clock, common, ui
from ..config import CURRENCY
from ..i18n import UZ, get_lang, t
from ..keyboards import esc, ikb
from ..money import fmt_money, fmt_num
from . import home, pay
from .pay import Field, Spec

router = Router(name="savings")

# BOT-A's "☰ More" menu, where Savings is opened from.
MORE = "more"
_LATEST = 5
_n = home.n


# ── Figures ─────────────────────────────────────────────────────────────────
def growth(i: dict, value: float | None = None) -> dict[str, Any]:
    """What went into a holding and what it is worth now — the server's figures, else worked out."""
    put_in = _n(i.get("putIn")) if i.get("putIn") is not None else _n(i.get("investedAmount"))
    if value is None:
        now = next((_n(i.get(k)) for k in ("value", "currentValue", "investedAmount") if i.get(k) is not None), 0.0)
    else:
        now = value
    diff = _n(i.get("growth")) if value is None and i.get("growth") is not None else now - put_in
    if value is None and "growthPercent" in i:
        pct = i.get("growthPercent")
    else:
        pct = round(diff / put_in * 1000) / 10 if put_in > 0 else None
    return {"putIn": put_in, "value": now, "growth": diff, "percent": pct}


def value_of(i: dict) -> float:
    return growth(i)["value"]


def growth_text(chat_id: int | None, g: dict) -> str:
    """"Put in 1 000 000 UZS · now 1 120 000 UZS · +120 000 UZS (+12.0%)"."""
    line = t(chat_id, "savings.growth", putIn=fmt_money(g["putIn"]), value=fmt_money(g["value"]))
    if abs(g["growth"]) < 1:
        return line
    sign = "+" if g["growth"] > 0 else "−"
    chip = f"{sign}{fmt_money(abs(g['growth']))}"
    if g["percent"] is not None:
        pct = f"{abs(_n(g['percent'])):.1f}"
        chip += f" ({sign}{pct.replace('.', ',') if get_lang(chat_id) == UZ else pct}%)"
    return f"{line} · {'📈' if g['growth'] > 0 else '📉'} {chip}"


def goal_plan(remaining: float, monthly: float, deadline: str | None, month: str,
              start: str | None) -> dict[str, Any]:
    """The web's goalPlan: what each month to the deadline needs, when `monthly` gets there."""
    deadline_month = deadline[:7] if deadline else None
    start_month = start[:7] if start else None
    first = start_month if start_month and start_month > month else month
    months_left = max(1, pay.months_between(first, deadline_month) + 1) if deadline_month else None
    needed = math.ceil(remaining / months_left / 10_000) * 10_000 if months_left and remaining > 0 else None
    reach = pay.shift_month(first, math.ceil(remaining / monthly) - 1) if remaining > 0 and monthly > 0 else None
    return {"needed": needed, "reach": reach, "deadline": deadline_month,
            "late": bool(deadline_month and reach and reach > deadline_month)}


def _start_of(g: dict) -> str:
    return str(g.get("paymentStartDate") or g.get("purchaseDate") or "")[:7]


def goal_lines(chat_id: int, g: dict) -> list[str]:
    month = clock.month()
    value, target = value_of(g), g.get("targetAmount")
    lines = [f"🎯 <b>{esc(g.get('name') or '—')}</b>"]
    if target is not None and _n(target) > 0:
        pct = min(100.0, value / _n(target) * 100)
        done = t(chat_id, "savings.done") if pct >= 100 else f"{math.floor(pct)}%"
        lines.append(t(chat_id, "savings.goal.ofTarget", value=fmt_num(value), target=fmt_money(target)) + f" · {done}")
    else:
        lines.append(fmt_money(value))
    monthly, start = _n(g.get("monthlyContribution")), _start_of(g)
    plan = goal_plan(max(0.0, _n(target) - value), monthly, g.get("targetDate"), month, start)
    parts = []
    if monthly > 0:
        parts.append(t(chat_id, "savings.goal.perMonthFrom", amount=fmt_money(monthly),
                       month=pay.month_label(chat_id, start)) if start > month
                     else t(chat_id, "savings.goal.perMonth", amount=fmt_money(monthly)))
    if plan["deadline"]:
        parts.append(t(chat_id, "savings.goal.by", month=pay.month_label(chat_id, plan["deadline"])))
    if parts:
        lines.append(" · ".join(parts))
    if plan["deadline"] and target is not None and _n(target) > 0 and value < _n(target):
        lines.append(t(chat_id, "savings.goal.onTrack") if monthly > 0 and not plan["late"]
                     else t(chat_id, "savings.goal.behind", amount=fmt_money(plan["needed"] or 0)))
    g_ = growth(g)
    if g.get("currentValue") is not None and abs(g_["growth"]) >= 1:
        lines.append(growth_text(chat_id, g_))
    return lines


def _split(holdings: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    """Goals · emergency-fund holdings · investments — the page's three kinds of holding."""
    goals = [i for i in holdings if i.get("savingsGoal")]
    emergency = [i for i in holdings if i.get("emergencyFund") and not i.get("savingsGoal")]
    rest = [i for i in holdings if not i.get("savingsGoal") and not i.get("emergencyFund")]
    return goals, emergency, rest


async def _list(chat_id: int, path: str) -> list[dict]:
    return [x for x in await api.request(chat_id, "GET", path) or [] if isinstance(x, dict)]


async def _holding(chat_id: int, ref: int) -> dict | None:
    return next((i for i in await _list(chat_id, "/finance/investments") if i.get("id") == ref), None)


def _id(cb: CallbackQuery) -> int | None:
    raw = cb.data.rsplit(":", 1)[1]
    return int(raw) if raw.isdigit() else None


async def _enter(cb: CallbackQuery, state: FSMContext) -> bool:
    """Every screen: answer the tap, drop any half-done form, check the session."""
    await common.ack(cb)
    await state.clear()
    return await common.gate(cb)


def _with_notice(notice: str | None, text: str) -> str:
    return f"{notice}\n\n{text}" if notice else text


# ── The page ────────────────────────────────────────────────────────────────
@router.callback_query(F.data == "sav")
async def on_savings(cb: CallbackQuery, state: FSMContext) -> None:
    if await _enter(cb, state):
        await show_savings(cb)


async def show_savings(event: TelegramObject, notice: str | None = None) -> None:
    chat_id = common.chat_id_of(event)
    try:
        data, holdings, donations, emergencies = await asyncio.gather(
            home.fetch(chat_id), _list(chat_id, "/finance/investments"),
            _list(chat_id, "/finance/donations"), _list(chat_id, "/emergencies"))
    except Exception as exc:  # noqa: BLE001
        await pay.report(event, exc, "sav")
        return
    goals, em_holdings, invest = _split(holdings)
    lines = [t(chat_id, "savings.title"), "", t(chat_id, "savings.month.title")]
    rows = home.savings_rows(data)
    buttons: list[tuple[str, str]] = []
    if data.get("missingStableIncome") and not rows:
        lines.append(t(chat_id, "savings.noIncome"))
    elif not rows:
        lines.append(t(chat_id, "savings.month.nothing"))
    else:
        left = sum(max(0.0, _n(r.get("remaining"))) for r in rows)
        lines.append(t(chat_id, "savings.month.left", amount=fmt_money(left)) if left > 0
                     else t(chat_id, "savings.month.allDone"))
        for r in rows:
            name = home.savings_name(chat_id, r)
            ref = r.get("refId") if r.get("bucket") == "GOAL" else 0
            if _n(r.get("remaining")) <= 0:
                over = _n(r.get("paid")) - _n(r.get("target")) if _n(r.get("target")) > 0 else 0
                row = t(chat_id, "savings.month.done", name=esc(name), amount=fmt_money(_n(r.get("paid"))))
                if over >= 1:
                    row += " · " + t(chat_id, "savings.month.over", amount=fmt_money(over))
                lines.append(row)
                buttons.append((home.clip("➕ " + name), f"pay:m:{r['bucket']}:{ref}:sav"))
            else:
                lines.append(t(chat_id, "savings.month.row", name=esc(name), paid=fmt_num(_n(r.get("paid"))),
                               target=fmt_money(_n(r.get("target")))))
                buttons.append((home.clip("💳 " + name), f"pay:{r['bucket']}:{ref}:sav"))
    em_total = sum(_n(e.get("amount")) for e in emergencies) + sum(value_of(i) for i in em_holdings)
    year = clock.today_iso()[:4]
    given = sum(_n(d.get("amount")) for d in donations if str(d.get("donationDate") or "").startswith(year))
    lines += ["",
              t(chat_id, "savings.line.goals", count=len(goals)),
              t(chat_id, "savings.line.emergency", amount=fmt_money(em_total)),
              t(chat_id, "savings.line.investments", amount=fmt_money(sum(value_of(i) for i in invest))),
              t(chat_id, "savings.line.donations", year=year, amount=fmt_money(given))]
    kb = ui.grid(buttons, 2)
    kb += [[(t(chat_id, "savings.btn.goals"), "sav:goals"), (t(chat_id, "savings.btn.emergency"), "sav:em")],
           [(t(chat_id, "savings.btn.investments"), "sav:inv"), (t(chat_id, "savings.btn.donations"), "sav:don")],
           [(t(chat_id, "savings.btn.add"), "sav:add")],
           ui.nav(chat_id, back=MORE, home=True)]
    await common.show(event, _with_notice(notice, "\n".join(lines)), ikb(kb))


# ── Goals ───────────────────────────────────────────────────────────────────
@router.callback_query(F.data == "sav:goals")
async def on_goals(cb: CallbackQuery, state: FSMContext) -> None:
    if await _enter(cb, state):
        await show_goals(cb)


async def show_goals(event: TelegramObject, notice: str | None = None) -> None:
    chat_id = common.chat_id_of(event)
    try:
        goals, _, _ = _split(await _list(chat_id, "/finance/investments"))
    except Exception as exc:  # noqa: BLE001
        await pay.report(event, exc, "sav:goals")
        return
    lines = [t(chat_id, "savings.goals.title")]
    if not goals:
        lines += ["", t(chat_id, "savings.goals.empty")]
    for g in goals:
        lines += [""] + goal_lines(chat_id, g)
    kb = ui.grid([(home.clip("🎯 " + str(g.get("name") or "—")), f"sav:g:{g['id']}") for g in goals], 2)
    kb += [[(t(chat_id, "savings.btn.addGoal"), "sav:new:goal")], ui.nav(chat_id, back="sav", home=True)]
    await common.show(event, _with_notice(notice, "\n".join(lines)), ikb(kb))


@router.callback_query(F.data.startswith("sav:g:"))
async def on_goal(cb: CallbackQuery, state: FSMContext) -> None:
    ref = _id(cb)
    if ref is not None and await _enter(cb, state):
        await show_goal(cb, ref)


async def show_goal(event: TelegramObject, ref: int, notice: str | None = None) -> None:
    chat_id = common.chat_id_of(event)
    try:
        g = await _holding(chat_id, ref)
    except Exception as exc:  # noqa: BLE001
        await pay.report(event, exc, f"sav:g:{ref}")
        return
    if g is None or not g.get("savingsGoal"):
        await show_goals(event, notice or t(chat_id, "savings.gone"))
        return
    kb = [[(t(chat_id, "savings.btn.topUp"), f"sav:top:{ref}")],
          [(t(chat_id, "savings.btn.edit"), f"sav:eg:{ref}"), (t(chat_id, "savings.btn.delete"), f"sav:del:goal:{ref}")],
          ui.nav(chat_id, back="sav:goals", home=True)]
    await common.show(event, _with_notice(notice, "\n".join(goal_lines(chat_id, g))), ikb(kb))


# ── Emergency fund ──────────────────────────────────────────────────────────
@router.callback_query(F.data.in_({"sav:em", "sav:em:all"}))
async def on_emergency(cb: CallbackQuery, state: FSMContext) -> None:
    if await _enter(cb, state):
        await show_emergency(cb, show_all=cb.data.endswith(":all"))


async def show_emergency(event: TelegramObject, notice: str | None = None, show_all: bool = False) -> None:
    chat_id = common.chat_id_of(event)
    try:
        holdings, contributions = await asyncio.gather(_list(chat_id, "/finance/investments"),
                                                       _list(chat_id, "/emergencies"))
    except Exception as exc:  # noqa: BLE001
        await pay.report(event, exc, "sav:em")
        return
    _, em_holdings, _ = _split(holdings)
    total = sum(_n(e.get("amount")) for e in contributions) + sum(value_of(i) for i in em_holdings)
    entries = sorted([("h", str(i.get("purchaseDate") or ""), i) for i in em_holdings]
                     + [("c", str(e.get("date") or ""), e) for e in contributions],
                     key=lambda x: x[1], reverse=True)
    shown = entries if show_all else entries[:_LATEST]
    lines = [t(chat_id, "savings.em.title"), f"<b>{fmt_money(total)}</b>"]
    kb: list[list[tuple[str, str]]] = []
    if not entries:
        lines += ["", t(chat_id, "savings.em.empty")]
    for kind, day, e in shown:
        if kind == "h":
            lines += ["", t(chat_id, "savings.em.holding", name=esc(e.get("name") or "—"),
                            amount=fmt_money(value_of(e)), date=pay.date_label(chat_id, day)),
                      "   " + growth_text(chat_id, growth(e))]
            kb.append([(home.clip("🛟 " + str(e.get("name") or "—"), 40), f"sav:h:{e['id']}")])
        else:
            note = f" · {esc(e['description'])}" if e.get("description") else ""
            lines += ["", t(chat_id, "savings.em.entry", date=pay.date_label(chat_id, day),
                            amount=fmt_money(_n(e.get("amount")))) + note]
            kb.append([(t(chat_id, "savings.btn.deleteEntry", date=pay.date_label(chat_id, day),
                          amount=fmt_num(_n(e.get("amount")))), f"sav:del:em:{e['id']}")])
    if len(entries) > _LATEST:
        kb.append([(t(chat_id, "savings.showLess") if show_all
                    else t(chat_id, "savings.showAll", count=len(entries)), "sav:em" if show_all else "sav:em:all")])
    kb += [[(t(chat_id, "savings.btn.addEmergency"), "pay:m:EMERGENCY:0:sav:em")], ui.nav(chat_id, back="sav", home=True)]
    await common.show(event, _with_notice(notice, "\n".join(lines)), ikb(kb))


# ── Investments ─────────────────────────────────────────────────────────────
@router.callback_query(F.data == "sav:inv")
async def on_investments(cb: CallbackQuery, state: FSMContext) -> None:
    if await _enter(cb, state):
        await show_investments(cb)


async def show_investments(event: TelegramObject, notice: str | None = None) -> None:
    chat_id = common.chat_id_of(event)
    try:
        _, _, invest = _split(await _list(chat_id, "/finance/investments"))
    except Exception as exc:  # noqa: BLE001
        await pay.report(event, exc, "sav:inv")
        return
    lines = [t(chat_id, "savings.inv.title")]
    if not invest:
        lines += ["", t(chat_id, "savings.inv.empty")]
    else:
        lines.append(f"<b>{fmt_money(sum(value_of(i) for i in invest))}</b>")
    for i in invest:
        broker = f" · {esc(i['broker'])}" if i.get("broker") else ""
        lines += ["", f"📈 <b>{esc(i.get('name') or '—')}</b>{broker}", "   " + growth_text(chat_id, growth(i))]
    kb = ui.grid([(home.clip("📈 " + str(i.get("name") or "—")), f"sav:h:{i['id']}") for i in invest], 2)
    kb += [[(t(chat_id, "savings.btn.addInvestment"), "sav:new:inv")], ui.nav(chat_id, back="sav", home=True)]
    await common.show(event, _with_notice(notice, "\n".join(lines)), ikb(kb))


@router.callback_query(F.data.startswith("sav:h:"))
async def on_holding(cb: CallbackQuery, state: FSMContext) -> None:
    ref = _id(cb)
    if ref is not None and await _enter(cb, state):
        await show_holding(cb, ref)


async def show_holding(event: TelegramObject, ref: int, notice: str | None = None) -> None:
    """One investment or emergency-fund account: what it is worth, and what can be done with it."""
    chat_id = common.chat_id_of(event)
    try:
        i = await _holding(chat_id, ref)
    except Exception as exc:  # noqa: BLE001
        await pay.report(event, exc, f"sav:h:{ref}")
        return
    if i is None:
        await show_savings(event, notice or t(chat_id, "savings.gone"))
        return
    if i.get("savingsGoal"):
        await show_goal(event, ref, notice)
        return
    emergency = bool(i.get("emergencyFund"))
    lines = [f"{'🛟' if emergency else '📈'} <b>{esc(i.get('name') or '—')}</b>"]
    if i.get("broker"):
        lines.append(esc(i["broker"]))
    lines += [f"<b>{fmt_money(value_of(i))}</b>", growth_text(chat_id, growth(i))]
    kb = [[(t(chat_id, "savings.btn.topUp"), f"sav:top:{ref}"), (t(chat_id, "savings.btn.value"), f"sav:val:{ref}")]]
    if value_of(i) > 0:
        kb.append([(t(chat_id, "savings.btn.out"), f"sav:out:{ref}")])
    row = [] if emergency else [(t(chat_id, "savings.btn.edit"), f"sav:ei:{ref}")]
    row.append((t(chat_id, "savings.btn.delete"), f"sav:del:{'emh' if emergency else 'inv'}:{ref}"))
    kb += [row, ui.nav(chat_id, back="sav:em" if emergency else "sav:inv", home=True)]
    await common.show(event, _with_notice(notice, "\n".join(lines)), ikb(kb))


@router.callback_query(F.data.startswith("sav:top:"))
async def on_top_up(cb: CallbackQuery, state: FSMContext) -> None:
    """Add money to one goal or account: amount → wallet (or "Not from a wallet")."""
    chat_id = common.chat_id_of(cb)
    ref = _id(cb)
    if ref is None or not await _enter(cb, state):
        return
    try:
        i = await _holding(chat_id, ref)
    except Exception as exc:  # noqa: BLE001
        await pay.report(cb, exc, f"sav:h:{ref}")
        return
    if i is None:
        await show_savings(cb, t(chat_id, "savings.gone"))
        return
    goal = bool(i.get("savingsGoal"))
    await pay.start_quick(cb, state, {"kind": "GOAL" if goal else "HOLDING", "ref": ref,
                                      "name": str(i.get("name") or "—"), "amount": None,
                                      "ret": f"sav:g:{ref}" if goal else f"sav:h:{ref}"})


@router.callback_query(F.data.startswith("sav:out:"))
async def on_take_out(cb: CallbackQuery, state: FSMContext) -> None:
    """Take money out: amount (or All) → into which wallet. Not counted as income."""
    chat_id = common.chat_id_of(cb)
    ref = _id(cb)
    if ref is None or not await _enter(cb, state):
        return
    try:
        i = await _holding(chat_id, ref)
    except Exception as exc:  # noqa: BLE001
        await pay.report(cb, exc, f"sav:h:{ref}")
        return
    if i is None or value_of(i) <= 0:
        await show_savings(cb, t(chat_id, "savings.gone"))
        return
    value = value_of(i)
    await pay.start_quick(cb, state, {
        "kind": "OUT", "ref": ref, "name": str(i.get("name") or "—"), "amount": None, "max": value,
        "quick": [[t(chat_id, "savings.out.all", amount=fmt_money(value)), value]], "incoming": True,
        "note": t(chat_id, "savings.out.walletHelp"), "ret": f"sav:h:{ref}"})


@router.callback_query(F.data.startswith("sav:val:"))
async def on_update_value(cb: CallbackQuery, state: FSMContext) -> None:
    """"What changed?" — money put in is Add money; only a moved value is set here."""
    chat_id = common.chat_id_of(cb)
    ref = _id(cb)
    if ref is None or not await _enter(cb, state):
        return
    try:
        i = await _holding(chat_id, ref)
    except Exception as exc:  # noqa: BLE001
        await pay.report(cb, exc, f"sav:h:{ref}")
        return
    if i is None:
        await show_savings(cb, t(chat_id, "savings.gone"))
        return
    text = "\n".join([t(chat_id, "savings.value.title", name=esc(i.get("name") or "—")), "",
                      t(chat_id, "savings.value.whatChanged"), "",
                      t(chat_id, "savings.value.addedHint"), t(chat_id, "savings.value.movedHint")])
    await common.show(cb, text, ikb([
        [(t(chat_id, "savings.value.added"), f"sav:top:{ref}")],
        [(t(chat_id, "savings.value.moved"), f"sav:valv:{ref}")],
        ui.nav(chat_id, back=f"sav:h:{ref}", home=True)]))


@router.callback_query(F.data.startswith("sav:valv:"))
async def on_new_value(cb: CallbackQuery, state: FSMContext) -> None:
    chat_id = common.chat_id_of(cb)
    ref = _id(cb)
    if ref is None or not await _enter(cb, state):
        return
    try:
        i = await _holding(chat_id, ref)
    except Exception as exc:  # noqa: BLE001
        await pay.report(cb, exc, f"sav:h:{ref}")
        return
    if i is None:
        await show_savings(cb, t(chat_id, "savings.gone"))
        return
    await pay.open_form(cb, state, "sav.value", ctx={"id": ref, "holding": i}, ret=f"sav:h:{ref}")


# ── Donations ───────────────────────────────────────────────────────────────
@router.callback_query(F.data == "sav:don")
async def on_donations(cb: CallbackQuery, state: FSMContext) -> None:
    if await _enter(cb, state):
        await show_donations(cb)


async def show_donations(event: TelegramObject, notice: str | None = None) -> None:
    chat_id = common.chat_id_of(event)
    try:
        donations = await _list(chat_id, "/finance/donations")
    except Exception as exc:  # noqa: BLE001
        await pay.report(event, exc, "sav:don")
        return
    donations.sort(key=lambda d: str(d.get("donationDate") or ""), reverse=True)
    year = clock.today_iso()[:4]
    given = sum(_n(d.get("amount")) for d in donations if str(d.get("donationDate") or "").startswith(year))
    lines = [t(chat_id, "savings.don.title"), f"<b>{fmt_money(given)}</b> · " + t(chat_id, "savings.don.thisYear", year=year)]
    kb: list[list[tuple[str, str]]] = []
    if not donations:
        lines += ["", t(chat_id, "savings.don.empty")]
    for d in donations[:_LATEST]:
        who = t(chat_id, "savings.don.anonymous") if d.get("anonymous") else str(d.get("displayName") or d.get("recipientName") or "—")
        note = f" · {esc(d['description'])}" if d.get("description") else ""
        lines.append(t(chat_id, "savings.don.row", date=pay.date_label(chat_id, d.get("donationDate")),
                       name=esc(who), amount=fmt_money(_n(d.get("amount")))) + note)
        kb.append([(t(chat_id, "savings.btn.deleteEntry", date=pay.date_label(chat_id, d.get("donationDate")),
                      amount=fmt_num(_n(d.get("amount")))), f"sav:del:don:{d['id']}")])
    kb += [[(t(chat_id, "savings.btn.addDonation"), "sav:new:don")], ui.nav(chat_id, back="sav", home=True)]
    await common.show(event, _with_notice(notice, "\n".join(lines)), ikb(kb))


# ── Add ─────────────────────────────────────────────────────────────────────
@router.callback_query(F.data == "sav:add")
async def on_add(cb: CallbackQuery, state: FSMContext) -> None:
    chat_id = common.chat_id_of(cb)
    if not await _enter(cb, state):
        return
    await common.show(cb, t(chat_id, "savings.add.title"), ikb([
        [(t(chat_id, "savings.btn.addGoal"), "sav:new:goal")],
        [(t(chat_id, "savings.btn.addInvestment"), "sav:new:inv")],
        [(t(chat_id, "savings.btn.addDonation"), "sav:new:don")],
        [(t(chat_id, "savings.btn.addEmergency"), "pay:m:EMERGENCY:0:sav")],
        ui.nav(chat_id, back="sav", home=True)]))


@router.callback_query(F.data.startswith("sav:new:"))
async def on_new(cb: CallbackQuery, state: FSMContext) -> None:
    what = cb.data.split(":", 2)[2]
    if not await _enter(cb, state):
        return
    if what == "goal":
        await pay.open_form(cb, state, "sav.goal", vals={"start": pay.shift_month(clock.month(), 1)}, ret="sav:goals")
    elif what == "inv":
        await pay.open_form(cb, state, "sav.inv", vals={"date": clock.today_iso()}, ret="sav:inv")
    elif what == "don":
        await pay.open_form(cb, state, "sav.don", vals={"date": clock.today_iso()}, ret="sav:don")
    else:
        await show_savings(cb)


@router.callback_query(F.data.startswith("sav:eg:"))
async def on_edit_goal(cb: CallbackQuery, state: FSMContext) -> None:
    await _edit(cb, state, goal=True)


@router.callback_query(F.data.startswith("sav:ei:"))
async def on_edit_investment(cb: CallbackQuery, state: FSMContext) -> None:
    await _edit(cb, state, goal=False)


async def _edit(cb: CallbackQuery, state: FSMContext, goal: bool) -> None:
    chat_id = common.chat_id_of(cb)
    ref = _id(cb)
    if ref is None or not await _enter(cb, state):
        return
    try:
        i = await _holding(chat_id, ref)
    except Exception as exc:  # noqa: BLE001
        await pay.report(cb, exc, "sav")
        return
    if i is None:
        await show_savings(cb, t(chat_id, "savings.gone"))
        return
    if goal:
        vals = {"name": i.get("name") or "", "target": i.get("targetAmount"),
                "monthly": i.get("monthlyContribution"), "start": _start_of(i) or None,
                "deadline": str(i.get("targetDate") or "")[:7] or None}
        await pay.open_form(cb, state, "sav.goal", vals=vals, ctx={"id": ref, "holding": i},
                            ret=f"sav:g:{ref}", card=True)
    else:
        await pay.open_form(cb, state, "sav.inv", vals={"name": i.get("name") or "", "broker": i.get("broker")},
                            ctx={"id": ref, "holding": i}, ret=f"sav:h:{ref}", card=True)


# ── Delete ──────────────────────────────────────────────────────────────────
# goal · inv (an investment) · emh (an emergency-fund account) · em (a fund contribution) · don
_DELETE = {
    "goal": ("savings.del.goal", "/finance/investments/{id}", "savings.deleted.goal", "sav:goals", "sav:g:{id}"),
    "inv": ("savings.del.inv", "/finance/investments/{id}", "savings.deleted.inv", "sav:inv", "sav:h:{id}"),
    "emh": ("savings.del.inv", "/finance/investments/{id}", "savings.deleted.inv", "sav:em", "sav:h:{id}"),
    "em": ("savings.del.em", "/emergencies/{id}", "savings.deleted.em", "sav:em", "sav:em"),
    "don": ("savings.del.don", "/finance/donations/{id}", "savings.deleted.don", "sav:don", "sav:don"),
}


def _delete_target(data: str) -> tuple[str, int] | None:
    parts = data.split(":")
    if len(parts) != 4 or parts[2] not in _DELETE or not parts[3].isdigit():
        return None
    return parts[2], int(parts[3])


@router.callback_query(F.data.startswith("sav:del:"))
async def on_delete(cb: CallbackQuery, state: FSMContext) -> None:
    chat_id = common.chat_id_of(cb)
    target = _delete_target(cb.data)
    if target is None or not await _enter(cb, state):
        return
    kind, ref = target
    question, _, _, _, back = _DELETE[kind]
    await pay.confirm(cb, t(chat_id, question), f"sav:dely:{kind}:{ref}", back.format(id=ref))


@router.callback_query(F.data.startswith("sav:dely:"))
async def on_delete_yes(cb: CallbackQuery, state: FSMContext) -> None:
    chat_id = common.chat_id_of(cb)
    target = _delete_target(cb.data)
    if target is None or not await _enter(cb, state):
        return
    kind, ref = target
    _, path, done, after, _ = _DELETE[kind]
    await common.begin_write(cb, chat_id)
    try:
        await api.request(chat_id, "DELETE", path.format(id=ref))
    except Exception as exc:  # noqa: BLE001
        await pay.report(cb, exc, after)
        return
    await route(cb, "✅ " + t(chat_id, done), after)


# ── Where a flow comes back to ──────────────────────────────────────────────
async def route(event: TelegramObject, notice: str | None, ret: str) -> None:
    """Render the Savings screen a callback names, with `notice` on top."""
    parts = ret.split(":")
    ref = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None
    what = parts[1] if len(parts) > 1 else ""
    if what == "goals":
        await show_goals(event, notice)
    elif what == "g" and ref is not None:
        await show_goal(event, ref, notice)
    elif what == "h" and ref is not None:
        await show_holding(event, ref, notice)
    elif what == "em":
        await show_emergency(event, notice)
    elif what == "inv":
        await show_investments(event, notice)
    elif what == "don":
        await show_donations(event, notice)
    else:
        await show_savings(event, notice)


pay.register_return("sav", route)


# ── Forms ───────────────────────────────────────────────────────────────────
def _wallet(vals: dict, key: str = "wallet") -> dict[str, Any]:
    """A wallet answer as the API takes it: {cardId} for a card, nothing for cash."""
    w = vals.get(key)
    return {"cardId": w} if isinstance(w, int) and not isinstance(w, bool) else {}


def _remember(vals: dict, key: str = "wallet") -> None:
    w = vals.get(key)
    if w == "cash":
        pay.remember_wallet(None, "pay")
    elif isinstance(w, int) and not isinstance(w, bool):
        pay.remember_wallet(w, "pay")


def request_from(i: dict, patch: dict) -> dict:
    """An edit sends every field back (the endpoint overwrites them all), with `patch` on top."""
    current, invested = i.get("currentValue"), _n(i.get("investedAmount"))
    body = {
        "name": i.get("name"), "type": i.get("type") or "OTHER", "investedAmount": invested,
        "currency": i.get("currency") or CURRENCY, "purchaseDate": i.get("purchaseDate"),
        "broker": i.get("broker"), "description": i.get("description"),
        "emergencyFund": bool(i.get("emergencyFund")), "savingsGoal": bool(i.get("savingsGoal")),
        "targetAmount": i.get("targetAmount"),
        # A value equal to what went in goes back as null, so the holding keeps following its total.
        "currentValue": current if current is not None and abs(_n(current) - invested) > 0.001 else None,
        "openingBalance": bool(i.get("openingBalance")),
        "targetDate": i.get("targetDate"), "monthlyContribution": i.get("monthlyContribution"),
    }
    if "paymentStartDate" in i:
        body["paymentStartDate"] = i.get("paymentStartDate")
    body.update(patch)
    return body


# Goal: name, target, monthly payment (required), payments start, deadline, already have.
def _goal_fields(form: dict) -> list[Field]:
    fields = [
        Field("name", "savings.f.goalName", "text"),
        Field("target", "savings.f.target", "amount"),
        Field("monthly", "savings.f.monthly", "amount"),
        Field("start", "savings.f.start", "month", walk=False),
        Field("deadline", "savings.f.deadline", "month", optional=True, min_month=clock.month(),
              skip_label="savings.f.noDeadline"),
    ]
    if "id" not in form["ctx"]:
        fields.append(Field("have", "savings.f.have", "amount", optional=True, hint="savings.f.haveHelp"))
    return fields


def _goal_title(chat_id: int, form: dict) -> str:
    return t(chat_id, "savings.f.editGoal" if "id" in form["ctx"] else "savings.f.addGoal")


def _goal_lines(chat_id: int, form: dict) -> list[str]:
    v = form["vals"]
    target, monthly = _n(v.get("target")), _n(v.get("monthly"))
    if target <= 0 or monthly <= 0:
        return []
    held = form["ctx"].get("holding")
    already = value_of(held) if held else _n(v.get("have"))
    plan = goal_plan(max(0.0, target - already), monthly, v.get("deadline"), clock.month(), v.get("start"))
    if not plan["reach"]:
        return []
    key = "savings.f.reachLate" if plan["late"] else "savings.f.reachBy"
    return [t(chat_id, key, monthly=fmt_money(monthly), month=pay.month_label(chat_id, plan["reach"]),
              needed=fmt_money(plan["needed"] or 0))]


async def _goal_save(event: TelegramObject, chat_id: int, form: dict) -> tuple[str, str | None]:
    v = form["vals"]
    name = str(v["name"]).strip()
    patch = {"name": name, "targetAmount": v["target"], "monthlyContribution": v["monthly"],
             "targetDate": pay.last_day(v["deadline"]) if v.get("deadline") else None,
             "paymentStartDate": f"{v.get('start') or pay.shift_month(clock.month(), 1)}-01"}
    if "id" in form["ctx"]:
        ref = form["ctx"]["id"]
        await api.request(chat_id, "PUT", f"/finance/investments/{ref}", json=request_from(form["ctx"]["holding"], patch))
        return "✅ " + t(chat_id, "savings.f.goalSaved", name=esc(name)), None
    await api.request(chat_id, "POST", "/finance/investments", json={
        **patch, "type": "OTHER", "investedAmount": _n(v.get("have")), "currency": CURRENCY,
        "purchaseDate": clock.today_iso(), "savingsGoal": True, "emergencyFund": False,
        "currentValue": None, "openingBalance": True})
    return "✅ " + t(chat_id, "savings.f.goalAdded", name=esc(name)), None


pay.FORMS["sav.goal"] = Spec(title=_goal_title, fields=_goal_fields, save=_goal_save,
                             lines=_goal_lines, submit="pay.f.save")


# Investment: name, amount, from wallet or "I already own it", date. An edit changes the name
# and the broker only — money goes in with Add money, a new value with Update value.
def _inv_fields(form: dict) -> list[Field]:
    if "id" in form["ctx"]:
        return [Field("name", "savings.f.invName", "text"),
                Field("broker", "savings.f.broker", "text", optional=True)]
    return [Field("name", "savings.f.invName", "text"),
            Field("amount", "savings.f.amount", "amount"),
            Field("wallet", "savings.f.from", "wallet", none_label="savings.f.alreadyOwn"),
            Field("date", "savings.f.date", "date", walk=False)]


def _inv_title(chat_id: int, form: dict) -> str:
    return t(chat_id, "savings.f.editInv" if "id" in form["ctx"] else "savings.f.addInv")


def _inv_lines(chat_id: int, form: dict) -> list[str]:
    return [t(chat_id, "savings.f.alreadyOwnHelp")] if form["vals"].get("wallet") == "none" else []


async def _inv_save(event: TelegramObject, chat_id: int, form: dict) -> tuple[str, str | None]:
    v = form["vals"]
    name = str(v["name"]).strip()
    if "id" in form["ctx"]:
        body = request_from(form["ctx"]["holding"], {"name": name, "broker": (v.get("broker") or "").strip() or None})
        await api.request(chat_id, "PUT", f"/finance/investments/{form['ctx']['id']}", json=body)
        return "✅ " + t(chat_id, "savings.f.invSaved"), None
    await api.request(chat_id, "POST", "/finance/investments", json={
        "name": name, "type": "OTHER", "investedAmount": v["amount"], "currency": CURRENCY,
        "purchaseDate": v.get("date") or clock.today_iso(), "emergencyFund": False, "savingsGoal": False,
        "targetAmount": None, "currentValue": None, "openingBalance": v.get("wallet") == "none",
        **_wallet(v)})
    _remember(v)
    return "✅ " + t(chat_id, "savings.f.invAdded", name=esc(name)), None


pay.FORMS["sav.inv"] = Spec(title=_inv_title, fields=_inv_fields, save=_inv_save, lines=_inv_lines)


# Donation: amount, wallet, recipient (optional — saved as "Anonymous" without one), date.
def _don_fields(form: dict) -> list[Field]:
    return [Field("amount", "savings.f.amount", "amount"),
            Field("wallet", "savings.f.from", "wallet"),
            Field("recipient", "savings.f.recipient", "text", optional=True, hint="savings.f.recipientHint"),
            Field("date", "savings.f.date", "date", walk=False)]


async def _don_save(event: TelegramObject, chat_id: int, form: dict) -> tuple[str, str | None]:
    v = form["vals"]
    recipient = (v.get("recipient") or "").strip()
    await api.request(chat_id, "POST", "/finance/donations", json={
        "recipientName": recipient or "Anonymous", "anonymous": not recipient, "amount": v["amount"],
        "currency": CURRENCY, "donationDate": v.get("date") or clock.today_iso(), **_wallet(v)})
    _remember(v)
    return "✅ " + t(chat_id, "savings.f.donAdded", amount=fmt_money(v["amount"])), None


pay.FORMS["sav.don"] = Spec(title=lambda chat_id, form: t(chat_id, "savings.f.addDon"),
                            fields=_don_fields, save=_don_save, submit="pay.f.add")


# Update value: the new total, with the growth it means shown before saving.
def _value_title(chat_id: int, form: dict) -> str:
    i = form["ctx"]["holding"]
    return "\n".join([t(chat_id, "savings.value.title", name=esc(i.get("name") or "—")),
                      growth_text(chat_id, growth(i))])


def _value_lines(chat_id: int, form: dict) -> list[str]:
    value = form["vals"].get("value")
    if value is None:
        return []
    return [t(chat_id, "savings.value.after"), growth_text(chat_id, growth(form["ctx"]["holding"], _n(value)))]


async def _value_save(event: TelegramObject, chat_id: int, form: dict) -> tuple[str, str | None]:
    await api.request(chat_id, "POST", f"/finance/investments/{form['ctx']['id']}/value",
                      json={"currentValue": form["vals"]["value"]})
    return "✅ " + t(chat_id, "savings.value.saved"), None


pay.FORMS["sav.value"] = Spec(
    title=_value_title, save=_value_save, lines=_value_lines, submit="savings.value.submit",
    fields=lambda form: [Field("value", "savings.value.label", "value", hint="savings.value.hint")])
