"""📐 Levels and savings rules — the bot's side of LEVELS-ALLOCATION-SPEC.md (§4, as the owner's
answers in §6 amend it).

* **Settings → Savings rules** (`lvl`): the level this month is on, its seven situations as text with
  the one in force marked ▸, and the line of changes ("Changes: from Nov 2026 · from Sep 2026"). One
  button, **Change this month's rule**: the three percentages in one message ("5 2 8") — a situation
  that splits at an amount left after bills and loans also takes the new split there ("5 2 8
  5000000"), since the split is set together with the percentages — then the month buttons the
  income uses (this month marked), then `PUT /levels/{level}/rules` for that one situation. Other
  levels and situations are for the website.
* **The notice** — Level 5 started (UP) or ended (DOWN): `GET /levels/notice?client=BOT`, shown once
  at the top of Home or Profile, whichever opens first, and marked seen there. UP offers Change: the
  same flow, on Level 5's rule, from the month Level 5 starts.
* Everything here reads `/levels` through `fetch` and `take_notice`: a server without it (404) gets
  None, and Settings, Profile and Home stay exactly as they were.

Callbacks owned here: `lvl`, `lvl:*`.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from .. import api, clock, common, keyboards, ui
from ..i18n import get_lang, t
from ..keyboards import esc, ikb
from ..money import fmt_money, fmt_num, parse_amount
from . import history, home

router = Router(name="levels")
log = logging.getLogger(__name__)
n = home.n

# The seven situations, in the order the web lists them, and the four that split at an amount left.
SITUATIONS = ("NO_DEBT", "BANK_LOAN_COMFORTABLE", "BANK_LOAN_TIGHT", "DEBTS_COMFORTABLE", "DEBTS_TIGHT",
              "BANK_AND_DEBTS", "HEAVY_DEBT")
SPLIT = frozenset({"BANK_LOAN_COMFORTABLE", "BANK_LOAN_TIGHT", "DEBTS_COMFORTABLE", "DEBTS_TIGHT"})
_NAME = {"NO_DEBT": "levels.s.noDebt", "BANK_LOAN_COMFORTABLE": "levels.s.bankMore",
         "BANK_LOAN_TIGHT": "levels.s.bankUnder", "DEBTS_COMFORTABLE": "levels.s.peopleMore",
         "DEBTS_TIGHT": "levels.s.peopleUnder", "BANK_AND_DEBTS": "levels.s.both", "HEAVY_DEBT": "levels.s.heavy"}
BUCKETS = ("donation", "emergency", "investments")
PAY_THRESHOLD = 60_000_000  # §1.1 — used when a payload does not say (`road.payThreshold`)
MONTHS_NEEDED = 3


class LevelRule(StatesGroup):
    """Change this month's rule: the typed numbers (the month buttons come after, on the same state —
    a number typed again there replaces the first)."""
    numbers = State()


# ── Reading the server (one place) ──────────────────────────────────────────
async def fetch(chat_id: int, quiet: bool = True) -> dict | None:
    """`GET /levels` for today. None from a server without it (404) — and, when `quiet`, on any
    other failure too, so a screen that only decorates itself with it never breaks."""
    try:
        data = await api.request(chat_id, "GET", "/levels", params={"date": clock.today_iso()})
    except api.NeedsLogin:
        raise
    except api.ApiError as exc:
        if exc.status == 404 or quiet:
            return None
        raise
    except Exception:  # noqa: BLE001
        if quiet:
            return None
        raise
    return data if isinstance(data, dict) and isinstance(data.get("levels"), list) else None


def level_entry(data: dict, level: Any) -> dict | None:
    return next((e for e in data.get("levels") or [] if isinstance(e, dict) and e.get("level") == level), None)


def version_at(entry: dict | None, month: str) -> dict:
    """The level's version in force in `month`: the latest `from` ≤ it, else the first one."""
    versions = sorted((v for v in (entry or {}).get("versions") or [] if isinstance(v, dict)),
                      key=lambda v: str(v.get("from") or ""))
    if not versions:
        return {}
    return next((v for v in reversed(versions) if str(v.get("from") or "") <= month), versions[0])


# ── Words ───────────────────────────────────────────────────────────────────
def situation_name(chat_id: int | None, key: str | None, cutoff: Any) -> str:
    """"Bank loan — under 5 000 000 UZS left" — never a code."""
    name = _NAME.get(key or "")
    return t(chat_id, name, cutoff=fmt_money(n(cutoff))) if name else "—"


def _pct(chat_id: int | None, value: Any) -> str:
    v = n(value)
    if v <= 0:
        return "—"
    text = str(int(v)) if v == int(v) else f"{v:.1f}"
    return text.replace(".", ",") if get_lang(chat_id) == "uz" else text


def percents_text(chat_id: int | None, p: dict | None) -> str:
    """"5 · 2 · 8%", a 0 as "—" (not asked): "5 · — · 5%"."""
    parts = [_pct(chat_id, (p or {}).get(b)) for b in BUCKETS]
    return " · ".join(parts) + ("%" if parts[-1] != "—" else "")


def millions(chat_id: int | None, amount: Any) -> str:
    """"61.2 M" / "61,2 mln"."""
    text = f"{n(amount) / 1_000_000:.1f}".rstrip("0").rstrip(".")
    if get_lang(chat_id) == "uz":
        text = text.replace(".", ",")
    return t(chat_id, "levels.millions", amount=text)


def month_short(chat_id: int | None, ym: str) -> str:
    """`2026-10` → "Oct 2026"."""
    return f"{ui.month_short(chat_id, ym)} {str(ym)[:4]}"


def level_line(chat_id: int | None, entry: dict, threshold: Any = PAY_THRESHOLD) -> str:
    level = entry.get("level")
    if level == 5:
        return t(chat_id, "levels.level.five", amount=fmt_money(n(threshold)))
    start, to = entry.get("leftFrom"), entry.get("leftTo")
    if to is None:
        return t(chat_id, "levels.level.over", n=level, start=fmt_money(n(start)))
    if not n(start):
        return t(chat_id, "levels.level.under", n=level, to=fmt_money(n(to)))
    return t(chat_id, "levels.level.band", n=level, start=fmt_money(n(start)), to=fmt_money(n(to)))


def months_text(chat_id: int | None, months: list, with_pay: bool = False) -> str:
    """"Nov, Dec" — or, `with_pay`, "Nov 61.2 M · Dec 64 M"."""
    rows = [m for m in months or [] if isinstance(m, dict) and history.valid_month(str(m.get("month") or "")[:7])]
    if with_pay:
        return " · ".join(f"{ui.month_short(chat_id, m['month'])} {millions(chat_id, m.get('pay'))}" for m in rows)
    return ", ".join(ui.month_short(chat_id, m["month"]) for m in rows)


# ── Profile's lines ─────────────────────────────────────────────────────────
def road_lines(chat_id: int | None, p: dict) -> list[str] | None:
    """The level card's line on Levels 4 and 5, from `/profile`'s `road` and `level5Since`. None on
    Levels 1–3 and from a server without them: the card then reads as it always did."""
    road = p.get("road") if isinstance(p.get("road"), dict) else None
    level = p.get("level")
    if "baseLevel" not in p or level not in (4, 5):
        return None
    threshold = n((road or {}).get("payThreshold")) or PAY_THRESHOLD
    need = int(n((road or {}).get("monthsNeeded")) or MONTHS_NEEDED)
    run = [m for m in (road or {}).get("months") or [] if isinstance(m, dict)]
    if level == 5:
        lines = [t(chat_id, "levels.five.since", month=month_short(chat_id, str(p.get("level5Since") or p.get("month") or clock.month())[:7]),
                   amount=fmt_money(threshold), base=p.get("baseLevel") or 4)]
        if run:
            lines.append(t(chat_id, "levels.five.under", n=len(run), need=need, months=months_text(chat_id, run)))
        return lines
    if road is None:
        return None
    count = (t(chat_id, "levels.road.count", n=len(run), need=need) + f" ({months_text(chat_id, run)})" if run
             else t(chat_id, "levels.road.none"))
    lines = [f"{t(chat_id, 'levels.road.toFive', amount=fmt_money(threshold))} — {count}."]
    if road.get("thisMonthSoFar") is not None:
        lines.append("<i>" + t(chat_id, "levels.road.thisMonth", month=ui.month_short(chat_id, str(p.get("month") or clock.month())[:7]),
                                 amount=millions(chat_id, road["thisMonthSoFar"])) + "</i>")
    return lines


def rule_line(chat_id: int | None, p: dict) -> str | None:
    """"Level 1 · Bank loan — under 5 000 000 UZS left", under "Your savings rule" (new servers only)."""
    rule = p.get("rule") if isinstance(p.get("rule"), dict) else {}
    if "baseLevel" not in p or rule.get("reason") not in _NAME or p.get("level") is None:
        return None
    return t(chat_id, "levels.ruleLine", n=p["level"], name=situation_name(chat_id, rule["reason"], rule.get("cutoff")))


def rule_from_line(chat_id: int | None, p: dict, data: dict | None) -> str | None:
    """"These percentages apply from Nov 2026" — when the version in force started after the first month."""
    start = str(p.get("ruleFrom") or "")[:7]
    first = str((data or {}).get("firstMonth") or "")[:7]
    if not history.valid_month(start) or not history.valid_month(first) or start <= first:
        return None
    return t(chat_id, "levels.ruleFrom", month=month_short(chat_id, start))


# ── The notice (Level 5 started or ended) ───────────────────────────────────
async def take_notice(chat_id: int, ret: str) -> tuple[list[str], list[list[tuple[str, str]]]] | None:
    """The oldest level change the bot has not shown: its lines and buttons, marked seen as it is
    taken (it is shown once, wherever the owner looks first). None when there is none, from a server
    without it, or on any failure — Home and Profile never wait on it."""
    try:
        notice = await api.request(chat_id, "GET", "/levels/notice", params={"client": "BOT", "date": clock.today_iso()})
    except Exception:  # noqa: BLE001 — 404 (no levels), unreachable, logged out: no notice
        return None
    if not isinstance(notice, dict) or notice.get("id") is None or notice.get("kind") not in ("UP", "DOWN"):
        return None
    try:
        await api.request(chat_id, "POST", f"/levels/notice/{notice['id']}/seen", params={"client": "BOT"})
    except Exception:  # noqa: BLE001 — it may then show once more; that is all
        log.info("couldn't mark level notice %s seen", notice.get("id"), exc_info=True)
    start = str(notice.get("from") or clock.month())[:7]
    percents = notice.get("percents") if isinstance(notice.get("percents"), dict) else {}
    threshold = fmt_money(PAY_THRESHOLD)
    rows: list[list[tuple[str, str]]] = []
    if notice["kind"] == "UP":
        lines = [t(chat_id, "levels.up.title"),
                 t(chat_id, "levels.up.pay", amount=threshold, months=months_text(chat_id, notice.get("months"), with_pay=True)),
                 t(chat_id, "levels.up.from", month=history.month_label(chat_id, start))]
        situation = notice.get("situation")
        if situation in _NAME:
            # The notice names the situation, not where it splits: that is Level 5's version at `from`.
            cutoff = None
            if situation in SPLIT:
                data = await fetch(chat_id)
                cutoff = version_at(level_entry(data, notice.get("level") or 5) if data else None, start).get("cutoff")
            lines.append(t(chat_id, "levels.situation", percents=percents_text(chat_id, percents),
                           name=situation_name(chat_id, situation, cutoff if cutoff is not None else 5_000_000)))
            amounts = notice.get("amounts") if isinstance(notice.get("amounts"), dict) else None
            if amounts:
                lines.append(t(chat_id, "levels.amounts", amounts=" · ".join(fmt_num(n(amounts.get(b))) for b in BUCKETS)
                               + " UZS"))
            rows.append([(t(chat_id, "levels.btn.ok"), f"lvl:ok:{ret}"),
                         (t(chat_id, "levels.btn.changeIt"), f"lvl:ch:{notice.get('level') or 5}:{situation}:{start}")])
        else:
            rows.append([(t(chat_id, "levels.btn.ok"), f"lvl:ok:{ret}")])
    else:
        level = notice.get("level")
        lines = [t(chat_id, "levels.down.title", n=level, month=month_short(chat_id, start)),
                 t(chat_id, "levels.down.body", amount=threshold, n=level, percents=percents_text(chat_id, percents),
                   months=" · ".join(ui.month_short(chat_id, m["month"]) for m in notice.get("months") or []
                                     if isinstance(m, dict) and history.valid_month(str(m.get("month") or "")[:7])))]
        rows.append([(t(chat_id, "levels.btn.ok"), f"lvl:ok:{ret}")])
    return lines, rows


@router.callback_query(F.data.startswith("lvl:ok:"))
async def on_notice_ok(cb: CallbackQuery, state: FSMContext) -> None:
    """OK — the notice was marked seen when it was shown; the screen is drawn again without it."""
    await common.ack(cb)
    await state.clear()
    if not await common.gate(cb):
        return
    if cb.data.endswith(":prof"):
        from . import profile  # profile imports this module
        await profile.show_profile(cb)
    else:
        await home.show_home(cb)


# ── Settings → Savings rules ────────────────────────────────────────────────
async def show_rules(event, notice: str | None = None, data: dict | None = None) -> None:
    chat_id = common.chat_id_of(event)
    if data is None:
        try:
            data = await fetch(chat_id, quiet=False)
        except Exception as exc:  # noqa: BLE001
            await home.report(event, exc)
            return
    if data is None:  # a server without levels: nothing to show here
        await common.show(event, t(chat_id, "levels.elsewhere"), ikb([ui.nav(chat_id, back="set", home=True)]))
        return
    month = str(data.get("month") or clock.month())[:7]
    level, situation = data.get("level"), data.get("situation")
    entry = level_entry(data, level) or {}
    version = version_at(entry, str(entry.get("inForce") or month)[:7])
    rules = version.get("rules") if isinstance(version.get("rules"), dict) else {}
    cutoff = version.get("cutoff")
    road = data.get("road") if isinstance(data.get("road"), dict) else {}
    lines = [notice, ""] if notice else []
    lines += [t(chat_id, "levels.title"), "", level_line(chat_id, entry, road.get("payThreshold") or PAY_THRESHOLD)]
    if situation in _NAME:
        lines.append(t(chat_id, "levels.thisMonth", name=situation_name(chat_id, situation, cutoff),
                       percents=percents_text(chat_id, data.get("percents") or rules.get(situation))))
    lines += ["", t(chat_id, "levels.legend")]
    for key in SITUATIONS:
        lines.append(t(chat_id, "levels.row", mark="▸" if key == situation else "•",
                       name=situation_name(chat_id, key, cutoff), percents=percents_text(chat_id, rules.get(key))))
    versions = sorted((str(v.get("from") or "")[:7] for v in entry.get("versions") or [] if isinstance(v, dict)),
                      reverse=True)
    if versions:
        lines += ["", t(chat_id, "levels.changes", list=" · ".join(t(chat_id, "levels.changeFrom", month=month_short(chat_id, v))
                                                                   for v in versions if history.valid_month(v)))]
    lines += ["", t(chat_id, "levels.elsewhere")]
    rows = [[(t(chat_id, "levels.btn.change"), "lvl:ch")]] if situation in _NAME else []
    if situation not in _NAME:
        lines.append(t(chat_id, "levels.noSituation"))
    rows.append(ui.nav(chat_id, back="set", home=True))
    await common.show(event, "\n".join(lines), ikb(rows))


@router.callback_query(F.data == "lvl")
async def on_rules(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    await state.clear()
    if not await common.gate(cb):
        return
    await show_rules(cb)


# ── Change this month's rule ────────────────────────────────────────────────
def month_choices(data: dict) -> list[str]:
    """The income's range: the first month a version may take to two months after this one."""
    now = clock.month()
    first = str(data.get("firstMonth") or "")[:7]
    month = min(first, now) if history.valid_month(first) else now
    out = []
    while month <= history.shift_month(now, 2):
        out.append(month)
        month = history.shift_month(month, 1)
    return out


@router.callback_query(F.data.startswith("lvl:ch"))
async def on_change(cb: CallbackQuery, state: FSMContext) -> None:
    """`lvl:ch` — this month's level and situation; `lvl:ch:{level}:{situation}:{YYYY-MM}` — the
    notice's (Level 5, from the month it starts)."""
    await common.ack(cb)
    if not await common.gate(cb):
        return
    chat_id = common.chat_id_of(cb)
    data, settings = await asyncio.gather(fetch(chat_id, quiet=False), api.request(chat_id, "GET", "/settings"),
                                          return_exceptions=True)
    if isinstance(data, BaseException):
        await home.report(cb, data)
        return
    if data is None:
        await show_rules(cb)
        return
    parts = cb.data.split(":")
    month = clock.month()
    level, situation = data.get("level"), data.get("situation")
    if len(parts) == 5 and parts[2].isdigit() and parts[3] in _NAME and history.valid_month(parts[4]):
        level, situation, month = int(parts[2]), parts[3], parts[4]
    if situation not in _NAME or level_entry(data, level) is None:
        await show_rules(cb, data=data)
        return
    version = version_at(level_entry(data, level), month)
    months = month_choices(data)
    if month not in months:
        months = sorted({*months, month})
    income = n((settings or {}).get("monthlyStableIncome")) if isinstance(settings, dict) else 0.0
    await state.set_state(LevelRule.numbers)
    await state.update_data(lv={"level": level, "situation": situation, "cutoff": version.get("cutoff"),
                                "now": ((version.get("rules") or {}).get(situation) or {}), "months": months,
                                "default": month, "income": income})
    await _ask_numbers(cb, state)


def _title(chat_id: int, lv: dict) -> str:
    return t(chat_id, "levels.ask.title", n=lv["level"], name=situation_name(chat_id, lv["situation"], lv.get("cutoff")))


async def _ask_numbers(event, state: FSMContext, error: str = "") -> None:
    chat_id = common.chat_id_of(event)
    lv = (await state.get_data()).get("lv") or {}
    lines = [_title(chat_id, lv), t(chat_id, "levels.ask.now", percents=percents_text(chat_id, lv.get("now"))), "",
             t(chat_id, "levels.ask.numbers")]
    if lv["situation"] in SPLIT:
        lines.append(t(chat_id, "levels.ask.split", cutoff=fmt_money(n(lv.get("cutoff"))),
                       example=int(n(lv.get("cutoff")) or 5_000_000)))
    if error:
        lines += ["", f"❌ {error}"]
    await state.set_state(LevelRule.numbers)
    await common.show(event, "\n".join(lines), ikb([ui.nav(chat_id, back="lvl", cancel="home")]))


_NUMBER = re.compile(r"^\d{1,3}(?:[.,]\d)?%?$")


def parse_rule(text: str | None, split: bool) -> tuple[dict | None, float | None, str | None]:
    """"5 2 8" → ({donation, emergency, investments}, split amount or None, problem key or None)."""
    tokens = (text or "").replace("%", " ").split()
    if len(tokens) < 3 or (len(tokens) > 3 and not split):
        return None, None, "levels.err.format"
    values = []
    for token in tokens[:3]:
        if not _NUMBER.match(token):
            return None, None, "levels.err.each" if token.replace(",", ".").replace(".", "", 1).isdigit() else "levels.err.format"
        values.append(float(token.replace(",", ".")))
    if any(v > 100 for v in values):
        return None, None, "levels.err.each"
    if sum(values) > 100 + 1e-9:
        return None, None, "levels.err.sum"
    cutoff = None
    if len(tokens) > 3:
        cutoff = parse_amount(" ".join(tokens[3:]))
        if cutoff is None:
            return None, None, "levels.err.split"
    return dict(zip(BUCKETS, values)), cutoff, None


@router.message(StateFilter(LevelRule.numbers))
async def on_numbers(message: Message, state: FSMContext) -> None:
    chat_id = common.chat_id_of(message)
    lv = (await state.get_data()).get("lv")
    if not isinstance(lv, dict):
        await state.clear()
        await home.show_home(message)
        return
    percents, cutoff, problem = parse_rule(message.text, lv["situation"] in SPLIT)
    if problem:
        await _ask_numbers(message, state, t(chat_id, problem))
        return
    await state.update_data(lv=dict(lv, new=percents, newCutoff=cutoff))
    await _ask_month(message, state)


async def _ask_month(event, state: FSMContext, error: str = "") -> None:
    chat_id = common.chat_id_of(event)
    lv = (await state.get_data()).get("lv") or {}
    new = lv.get("new") or {}
    lines = [_title(chat_id, lv), percents_text(chat_id, new)]
    if lv.get("newCutoff") is not None:
        lines.append(t(chat_id, "levels.splitAt", amount=fmt_money(lv["newCutoff"])))
    if n(lv.get("income")) > 0:
        lines.append(t(chat_id, "levels.amounts", amounts=" · ".join(fmt_num(round(n(lv["income"]) * n(new.get(b)) / 100))
                                                                     for b in BUCKETS) + " UZS"))
    lines += ["", t(chat_id, "levels.fromAsk"), t(chat_id, "settings.incomeFromHint")]
    if error:
        lines += ["", error]
    buttons = [(t(chat_id, "settings.incomeMonthNow", month=month_short(chat_id, m)) if m == lv.get("default")
                else month_short(chat_id, m), f"lvl:m:{m}") for m in lv.get("months") or []]
    await common.show(event, "\n".join(lines), ikb([*ui.grid(buttons, 3), ui.nav(chat_id, back="lvl:re", cancel="home")]))


@router.callback_query(F.data == "lvl:re")
async def on_numbers_again(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    if not await common.gate(cb):
        return
    if not isinstance((await state.get_data()).get("lv"), dict):
        await show_rules(cb)
        return
    await _ask_numbers(cb, state)


@router.callback_query(F.data.startswith("lvl:m:"))
async def on_month(cb: CallbackQuery, state: FSMContext) -> None:
    """`lvl:m:{YYYY-MM}` — save the one situation's change from that month."""
    chat_id = common.chat_id_of(cb)
    if not await common.gate(cb):
        return
    lv = (await state.get_data()).get("lv")
    month = cb.data.split(":", 2)[2]
    if not isinstance(lv, dict) or not lv.get("new") or month not in (lv.get("months") or []):
        await common.ack(cb, t(chat_id, "common.oldButton"), alert=True)
        await state.clear()
        await show_rules(cb)
        return
    await common.ack(cb)
    body: dict[str, Any] = {"from": month, "rules": {lv["situation"]: lv["new"]}}
    if lv.get("newCutoff") is not None and lv["situation"] in SPLIT:
        body["cutoff"] = lv["newCutoff"]
    await common.begin_write(cb, chat_id)
    try:
        saved = await api.request(chat_id, "PUT", f"/levels/{lv['level']}/rules", params={"date": clock.today_iso()}, json=body)
    except api.NeedsLogin:
        await state.clear()
        await common.show(cb, t(chat_id, "common.sessionExpired"), keyboards.login_kb(chat_id))
        return
    except api.ApiError as exc:
        await _ask_month(cb, state, t(chat_id, "common.serverUnreachable") if isinstance(exc, api.Unreachable)
                         else f"❌ {esc(exc.message)}")
        return
    await state.clear()
    data = saved if isinstance(saved, dict) and isinstance(saved.get("levels"), list) else None
    await show_rules(cb, t(chat_id, "levels.saved", n=lv["level"], month=month_short(chat_id, month)), data)
