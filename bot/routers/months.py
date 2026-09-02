"""Monthly-envelope: summary view, permanent month-close flow, and closed history."""
import datetime as dt

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from .. import api, common, keyboards
from ..config import CURRENCY
from ..i18n import t
from ..keyboards import esc, fmt_money, ikb
from ..states import CloseMonth

router = Router()


def _month_now() -> str:
    return dt.date.today().strftime("%Y-%m")


def _num(text: str):
    """Parse an end-of-month balance — any number incl. 0 / negative (an overdrawn card)."""
    v = (text or "").strip().replace(" ", "").replace(",", "")
    try:
        return float(v)
    except ValueError:
        return None


def _back_kb(chat_id: int):
    return ikb([[(t(chat_id, "months.backBtn"), "months:summary"), (t(chat_id, "common.menu"), "menu:home")]])


# ── summary view ────────────────────────────────────────────────────────────
async def show_menu(cb: CallbackQuery) -> None:
    await show_summary(cb)


async def show_summary(cb: CallbackQuery) -> None:
    chat_id = cb.message.chat.id
    month = _month_now()
    try:
        s = await api.request(chat_id, "GET", "/months/summary", params={"month": month, "currency": CURRENCY})
    except api.NeedsLogin:
        await cb.message.edit_text(t(chat_id, "common.sessionExpired"), reply_markup=keyboards.login_kb(chat_id))
        return
    except Exception:  # noqa: BLE001
        await cb.message.edit_text(t(chat_id, "months.summaryLoadError"), reply_markup=keyboards.back_menu_kb(chat_id))
        return
    closed = bool(s.get("closed"))
    lines = [
        t(chat_id, "months.summaryTitle", currency=CURRENCY, month=month),
        (t(chat_id, "months.closed") if closed else t(chat_id, "months.open")),
        "",
        t(chat_id, "months.startedWith", amount=fmt_money(s.get('startBalance'))),
        t(chat_id, "months.earned", amount=fmt_money(s.get('income'))),
    ]
    if closed:
        lines.append(t(chat_id, "months.spent", amount=fmt_money(s.get('totalSpent'))))
        lines.append(t(chat_id, "months.left", amount=fmt_money(s.get('leftover'))))
    lines += [
        "",
        t(chat_id, "months.whereItWent"),
        t(chat_id, "months.donation", amount=fmt_money(s.get('donation'))),
        t(chat_id, "months.emergency", amount=fmt_money(s.get('emergency'))),
        t(chat_id, "months.investments", amount=fmt_money(s.get('investments'))),
        t(chat_id, "months.stocks", amount=fmt_money(s.get('stocks'))),
        t(chat_id, "months.savingsGoals", amount=fmt_money(s.get('savings'))),
        t(chat_id, "months.taggedTotal", amount=fmt_money(s.get('taggedTotal'))),
    ]
    if closed:
        lines.append(t(chat_id, "months.everydaySpending", amount=fmt_money(s.get('everydaySpend'))))
    else:
        lines.append(t(chat_id, "months.everydayPending"))
    rows = []
    if not closed:
        rows.append([(t(chat_id, "months.closeThisMonth"), "months:close")])
    rows.append([(t(chat_id, "months.historyBtn"), "months:history")])
    rows.append([(t(chat_id, "common.menu"), "menu:home")])
    await cb.message.edit_text("\n".join(lines), reply_markup=ikb(rows))


async def show_history(cb: CallbackQuery) -> None:
    chat_id = cb.message.chat.id
    try:
        rows = await api.request(chat_id, "GET", "/months") or []
    except api.NeedsLogin:
        await cb.message.edit_text(t(chat_id, "common.sessionExpired"), reply_markup=keyboards.login_kb(chat_id))
        return
    except Exception:  # noqa: BLE001
        await cb.message.edit_text(t(chat_id, "months.historyLoadError"), reply_markup=_back_kb(chat_id))
        return
    lines = [t(chat_id, "months.historyTitle", currency=CURRENCY)]
    if not rows:
        lines.append(t(chat_id, "months.noneClosedYet"))
    for m in rows[:24]:
        lines.append("• " + t(
            chat_id, "months.historyLine", month=esc(m.get('month')), earned=fmt_money(m.get('income')),
            spent=fmt_money(m.get('totalSpent')), left=fmt_money(m.get('leftover'))))
    await cb.message.edit_text("\n".join(lines), reply_markup=_back_kb(chat_id))


@router.callback_query(F.data == "months:summary")
async def on_summary(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    await state.clear()
    if not await common.gate(cb):
        return
    await show_summary(cb)


@router.callback_query(F.data == "months:history")
async def on_history(cb: CallbackQuery) -> None:
    await cb.answer()
    if not await common.gate(cb):
        return
    await show_history(cb)


# ── close-month flow ────────────────────────────────────────────────────────
@router.callback_query(F.data == "months:close")
async def close_start(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    if not await common.stable_income_set(cb):
        return
    if not await common.gate(cb):
        return
    chat_id = cb.message.chat.id
    month = _month_now()
    try:
        p = await api.request(chat_id, "GET", "/months/preview", params={"month": month, "currency": CURRENCY})
    except api.NeedsLogin:
        await cb.message.edit_text(t(chat_id, "common.sessionExpired"), reply_markup=keyboards.login_kb(chat_id))
        return
    except Exception:  # noqa: BLE001
        await cb.message.edit_text(t(chat_id, "months.closePreviewError"), reply_markup=_back_kb(chat_id))
        return
    if not p.get("closeable"):
        reason = p.get("blockedReason") or t(chat_id, "months.cantCloseYet")
        await cb.message.edit_text(f"🔒 {esc(reason)}", reply_markup=_back_kb(chat_id))
        return
    wallets = p.get("wallets") or []
    if not wallets:
        await cb.message.edit_text(t(chat_id, "months.noWallets"), reply_markup=_back_kb(chat_id))
        return
    await state.set_state(CloseMonth.balance)
    await state.update_data(mc_month=month, mc_wallets=wallets, mc_index=0, mc_entered=[])
    await _mc_prompt(cb, state)


async def _mc_prompt(event, state: FSMContext) -> None:
    chat_id = common.chat_id_of(event)
    d = await state.get_data()
    wallets, idx = d["mc_wallets"], d["mc_index"]
    w = wallets[idx]
    computed = w.get("computedBalance")
    head = t(chat_id, "months.closeHeader", month=d['mc_month'], index=idx + 1, total=len(wallets))
    body = t(chat_id, "months.walletPrompt", label=esc(w.get('label')), computed=fmt_money(computed), currency=CURRENCY)
    rows = []
    if computed is not None:
        rows.append([(t(chat_id, "months.useComputed", amount=fmt_money(computed)), "mc:use")])
    rows.append([(t(chat_id, "common.cancel"), "mc:cancel")])
    await common.show(event, f"{head}\n{body}", ikb(rows))


async def _mc_record(event, state: FSMContext, value: float) -> None:
    d = await state.get_data()
    wallets, idx = d["mc_wallets"], d["mc_index"]
    w = wallets[idx]
    entered = list(d.get("mc_entered", []))
    entered.append({
        "walletType": w.get("walletType"),
        "cardId": w.get("cardId"),
        "currency": w.get("currency"),
        "enteredBalance": value,
    })
    idx += 1
    await state.update_data(mc_entered=entered, mc_index=idx)
    if idx < len(wallets):
        await _mc_prompt(event, state)
    else:
        await _mc_confirm(event, state)


@router.callback_query(StateFilter(CloseMonth.balance), F.data == "mc:use")
async def mc_use(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    d = await state.get_data()
    w = d["mc_wallets"][d["mc_index"]]
    await _mc_record(cb, state, w.get("computedBalance") or 0)


@router.message(StateFilter(CloseMonth.balance))
async def mc_balance(message: Message, state: FSMContext) -> None:
    val = _num(message.text)
    if val is None:
        await message.answer(t(message.chat.id, "common.sendNumberExample"))
        return
    await _mc_record(message, state, val)


async def _mc_confirm(event, state: FSMContext) -> None:
    chat_id = common.chat_id_of(event)
    d = await state.get_data()
    wallets = d["mc_wallets"]
    lines = [t(chat_id, "months.confirmCloseHeader", month=d['mc_month']), "", t(chat_id, "months.realBalancesEntered")]
    for i, e in enumerate(d["mc_entered"]):
        label = wallets[i].get("label") if i < len(wallets) else e["walletType"]
        lines.append(f"• {esc(label)}: {fmt_money(e['enteredBalance'])}")
    lines.append(t(chat_id, "months.permanentWarning"))
    await state.set_state(CloseMonth.confirm)
    await common.show(event, "\n".join(lines),
                      ikb([[(t(chat_id, "months.confirmClose"), "mc:ok")], [(t(chat_id, "common.cancel"), "mc:cancel")]]))


@router.callback_query(StateFilter(CloseMonth.confirm), F.data == "mc:ok")
async def mc_ok(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    chat_id = cb.message.chat.id
    d = await state.get_data()
    payload = {"month": d["mc_month"], "wallets": d["mc_entered"]}
    try:
        res = await api.request(chat_id, "POST", "/months/close", json=payload)
    except api.NeedsLogin:
        await state.clear()
        await cb.message.edit_text(t(chat_id, "common.sessionExpired"), reply_markup=keyboards.login_kb(chat_id))
        return
    except api.ApiError as exc:
        await state.clear()
        await cb.message.edit_text(f"❌ {esc(exc.message)}", reply_markup=_back_kb(chat_id))
        return
    except Exception:  # noqa: BLE001
        await state.clear()
        await cb.message.edit_text(t(chat_id, "common.serverUnreachable"), reply_markup=_back_kb(chat_id))
        return
    await state.clear()
    res = res or {}
    lines = [
        t(chat_id, "months.closedResultTitle", month=esc(res.get('month', d['mc_month'])), currency=CURRENCY),
        t(chat_id, "months.resultEarned", amount=fmt_money(res.get('income'))),
        t(chat_id, "months.resultSpent", amount=fmt_money(res.get('totalSpent'))),
        t(chat_id, "months.resultEveryday", amount=fmt_money(res.get('everydaySpend'))),
        t(chat_id, "months.resultLeftover", amount=fmt_money(res.get('leftover'))),
    ]
    await cb.message.edit_text("\n".join(lines), reply_markup=_back_kb(chat_id))


@router.callback_query(F.data == "mc:cancel")
async def mc_cancel(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    await state.clear()
    if not await common.gate(cb):
        return
    await show_summary(cb)
