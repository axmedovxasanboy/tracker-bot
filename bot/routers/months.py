"""Monthly-envelope: summary view, permanent month-close flow, and closed history."""
import datetime as dt

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from .. import api, common, keyboards
from ..keyboards import esc, fmt_money, ikb
from ..session import store
from ..states import CloseMonth

router = Router()


def _month_now() -> str:
    return dt.date.today().strftime("%Y-%m")


def _num(text: str):
    """Parse an end-of-month balance — any number incl. 0 / negative (an overdrawn card)."""
    t = (text or "").strip().replace(" ", "").replace(",", "")
    try:
        return float(t)
    except ValueError:
        return None


def _back_kb():
    return ikb([[("⬅️ Months", "months:summary"), ("⬅️ Menu", "menu:home")]])


# ── summary view ────────────────────────────────────────────────────────────
async def show_menu(cb: CallbackQuery) -> None:
    await show_summary(cb)


async def show_summary(cb: CallbackQuery) -> None:
    chat_id = cb.message.chat.id
    cur = store.currency(chat_id)
    month = _month_now()
    try:
        s = await api.request(chat_id, "GET", "/months/summary", params={"month": month, "currency": cur})
    except api.NeedsLogin:
        await cb.message.edit_text("🔒 Session expired. Please log in.", reply_markup=keyboards.login_kb())
        return
    except Exception:  # noqa: BLE001
        await cb.message.edit_text("❌ Couldn't load the monthly summary.", reply_markup=keyboards.back_menu_kb())
        return
    closed = bool(s.get("closed"))
    lines = [
        f"🗓 <b>Monthly Summary</b> · {cur} · {month}",
        ("🔒 Closed" if closed else "🟡 Open — not closed yet"),
        "",
        f"▶️ Started with: {fmt_money(s.get('startBalance'), cur)}",
        f"📈 Earned: <b>{fmt_money(s.get('income'), cur)}</b>",
    ]
    if closed:
        lines.append(f"📉 Spent: <b>{fmt_money(s.get('totalSpent'), cur)}</b>")
        lines.append(f"💰 Left: <b>{fmt_money(s.get('leftover'), cur)}</b>")
    lines += [
        "",
        "<b>Where it went</b>",
        f"• Donation: {fmt_money(s.get('donation'), cur)}",
        f"• Emergency: {fmt_money(s.get('emergency'), cur)}",
        f"• Investments: {fmt_money(s.get('investments'), cur)}",
        f"• Stocks: {fmt_money(s.get('stocks'), cur)}",
        f"• Savings goals: {fmt_money(s.get('savings'), cur)}",
        f"• Tagged total: <b>{fmt_money(s.get('taggedTotal'), cur)}</b>",
    ]
    if closed:
        lines.append(f"• Everyday spending: {fmt_money(s.get('everydaySpend'), cur)}")
    else:
        lines.append("• Everyday spending: <i>known once you close the month</i>")
    if s.get("fxRatesUsingDefaults"):
        lines.append("\nℹ️ FX rates use built-in defaults — set real rates in Settings.")
    rows = []
    if not closed:
        rows.append([("🔒 Close this month", "months:close")])
    rows.append([("📜 History", "months:history")])
    rows.append([("⬅️ Menu", "menu:home")])
    await cb.message.edit_text("\n".join(lines), reply_markup=ikb(rows))


async def show_history(cb: CallbackQuery) -> None:
    chat_id = cb.message.chat.id
    try:
        rows = await api.request(chat_id, "GET", "/months") or []
    except api.NeedsLogin:
        await cb.message.edit_text("🔒 Session expired. Please log in.", reply_markup=keyboards.login_kb())
        return
    except Exception:  # noqa: BLE001
        await cb.message.edit_text("❌ Couldn't load history.", reply_markup=_back_kb())
        return
    lines = ["📜 <b>Closed months</b> · UZS\n"]
    if not rows:
        lines.append("No months closed yet.")
    for m in rows[:24]:
        lines.append(
            f"• <b>{esc(m.get('month'))}</b>: earned {fmt_money(m.get('income'), 'UZS')} · "
            f"spent {fmt_money(m.get('totalSpent'), 'UZS')} · left {fmt_money(m.get('leftover'), 'UZS')}")
    await cb.message.edit_text("\n".join(lines), reply_markup=_back_kb())


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
    if not await common.gate(cb):
        return
    chat_id = cb.message.chat.id
    cur = store.currency(chat_id)
    month = _month_now()
    try:
        p = await api.request(chat_id, "GET", "/months/preview", params={"month": month, "currency": cur})
    except api.NeedsLogin:
        await cb.message.edit_text("🔒 Session expired. Please log in.", reply_markup=keyboards.login_kb())
        return
    except Exception:  # noqa: BLE001
        await cb.message.edit_text("❌ Couldn't load the close preview.", reply_markup=_back_kb())
        return
    if not p.get("closeable"):
        reason = p.get("blockedReason") or "This month can't be closed yet."
        await cb.message.edit_text(f"🔒 {esc(reason)}", reply_markup=_back_kb())
        return
    wallets = p.get("wallets") or []
    if not wallets:
        await cb.message.edit_text("No wallets to reconcile for this month.", reply_markup=_back_kb())
        return
    await state.set_state(CloseMonth.balance)
    await state.update_data(mc_month=month, mc_wallets=wallets, mc_index=0, mc_entered=[])
    await _mc_prompt(cb, state)


async def _mc_prompt(event, state: FSMContext) -> None:
    d = await state.get_data()
    wallets, idx = d["mc_wallets"], d["mc_index"]
    w = wallets[idx]
    wcur = w.get("currency")
    computed = w.get("computedBalance")
    head = f"🔒 <b>Close {d['mc_month']}</b> · wallet {idx + 1}/{len(wallets)}"
    body = (
        f"<b>{esc(w.get('label'))}</b>\n"
        f"App computed: {fmt_money(computed, wcur)}\n\n"
        f"Send this wallet's <b>real balance</b> at month-end (in {wcur}):")
    rows = []
    if computed is not None:
        rows.append([(f"Use {fmt_money(computed, wcur)}", "mc:use")])
    rows.append([("✖️ Cancel", "mc:cancel")])
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
        await message.answer("Send a number (e.g. 0 or 250000).")
        return
    await _mc_record(message, state, val)


async def _mc_confirm(event, state: FSMContext) -> None:
    d = await state.get_data()
    wallets = d["mc_wallets"]
    lines = [f"🔒 <b>Confirm closing {d['mc_month']}</b>", "", "Real balances entered:"]
    for i, e in enumerate(d["mc_entered"]):
        label = wallets[i].get("label") if i < len(wallets) else e["walletType"]
        lines.append(f"• {esc(label)}: {fmt_money(e['enteredBalance'], e['currency'])}")
    lines.append("\n⚠️ This is <b>permanent</b> — the month locks and can't be reopened.")
    await state.set_state(CloseMonth.confirm)
    await common.show(event, "\n".join(lines),
                      ikb([[("✅ Confirm close", "mc:ok")], [("✖️ Cancel", "mc:cancel")]]))


@router.callback_query(StateFilter(CloseMonth.confirm), F.data == "mc:ok")
async def mc_ok(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    d = await state.get_data()
    payload = {"month": d["mc_month"], "wallets": d["mc_entered"]}
    try:
        res = await api.request(cb.message.chat.id, "POST", "/months/close", json=payload)
    except api.NeedsLogin:
        await state.clear()
        await cb.message.edit_text("🔒 Session expired. Please log in.", reply_markup=keyboards.login_kb())
        return
    except api.ApiError as exc:
        await state.clear()
        await cb.message.edit_text(f"❌ {esc(exc.message)}", reply_markup=_back_kb())
        return
    except Exception:  # noqa: BLE001
        await state.clear()
        await cb.message.edit_text("❌ Couldn't reach the server.", reply_markup=_back_kb())
        return
    await state.clear()
    res = res or {}
    lines = [
        f"✅ <b>{esc(res.get('month', d['mc_month']))} closed.</b> (UZS)",
        f"📈 Earned: {fmt_money(res.get('income'), 'UZS')}",
        f"📉 Spent: {fmt_money(res.get('totalSpent'), 'UZS')}",
        f"🧹 Everyday: {fmt_money(res.get('everydaySpend'), 'UZS')}",
        f"💰 Left → next month: {fmt_money(res.get('leftover'), 'UZS')}",
    ]
    await cb.message.edit_text("\n".join(lines), reply_markup=_back_kb())


@router.callback_query(F.data == "mc:cancel")
async def mc_cancel(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    await state.clear()
    if not await common.gate(cb):
        return
    await show_summary(cb)
