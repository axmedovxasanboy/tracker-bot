"""Main-menu navigation + read pages: Dashboard, Overview, Settings."""
import datetime as dt

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from .. import api, keyboards
from ..keyboards import esc, fmt_money, fmt_pct
from ..session import store

router = Router()


def _month_now() -> str:
    return dt.date.today().strftime("%Y-%m")


@router.callback_query(F.data.startswith("menu:"))
async def on_menu(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    await state.clear()  # navigating via the main menu resets any in-progress flow
    if not store.is_active(cb.message.chat.id):
        await cb.message.edit_text("🔒 Session expired. Please log in.", reply_markup=keyboards.login_kb())
        return
    page = cb.data.split(":", 1)[1]
    if page == "home":
        await cb.message.edit_text(keyboards.MENU_TEXT, reply_markup=keyboards.main_menu_kb())
    elif page == "dashboard":
        await show_dashboard(cb)
    elif page == "overview":
        await show_overview(cb)
    elif page == "settings":
        await show_settings(cb)
    elif page == "transactions":
        from .transactions import show_menu
        await show_menu(cb)
    elif page == "finance":
        from .finance import show_menu
        await show_menu(cb)
    elif page == "cards":
        from .cards import show_menu
        await show_menu(cb)
    elif page == "categories":
        from .categories import show_menu
        await show_menu(cb)


async def show_dashboard(cb: CallbackQuery) -> None:
    chat_id = cb.message.chat.id
    cur = store.currency(chat_id)
    try:
        d = await api.request(chat_id, "GET", "/dashboard/summary", params={"currency": cur})
    except api.NeedsLogin:
        await cb.message.edit_text("🔒 Session expired. Please log in.", reply_markup=keyboards.login_kb())
        return
    except Exception:  # noqa: BLE001
        await cb.message.edit_text("❌ Couldn't load the dashboard.", reply_markup=keyboards.back_menu_kb())
        return
    text = (
        f"📊 <b>Dashboard</b> · {cur}\n\n"
        f"💰 Available: <b>{fmt_money(d.get('availableBalance'), cur)}</b>\n"
        f"⚖️ Net balance: <b>{fmt_money(d.get('netBalance'), cur)}</b>\n"
        f"📈 Income: {fmt_money(d.get('totalIncome'), cur)}\n"
        f"📉 Expenses: {fmt_money(d.get('totalExpense'), cur)}\n"
        f"🧾 Transactions: {d.get('transactionCount', 0)}"
    )
    await cb.message.edit_text(text, reply_markup=keyboards.back_menu_kb())


async def show_overview(cb: CallbackQuery) -> None:
    chat_id = cb.message.chat.id
    cur = store.currency(chat_id)
    month = _month_now()
    try:
        t = await api.request(chat_id, "GET", "/overview/tier", params={"currency": cur, "month": month})
    except api.NeedsLogin:
        await cb.message.edit_text("🔒 Session expired. Please log in.", reply_markup=keyboards.login_kb())
        return
    except Exception:  # noqa: BLE001
        await cb.message.edit_text("❌ Couldn't load the overview.", reply_markup=keyboards.back_menu_kb())
        return
    lines = [
        f"🎯 <b>Overview</b> · {cur} · {month}",
        f"Tier: <b>{esc(t.get('levelLabel', '—'))}</b>",
        f"Stable income: {fmt_money(t.get('income'), cur)}",
        f"Left money: {fmt_money(t.get('leftMoney'), cur)}",
        f"Debt payments: {fmt_money(t.get('debtPayments'), cur)}",
    ]
    allocation = t.get("allocation") or {}
    if allocation.get("scenarioLabel"):
        lines.append(f"\n<b>Allocation</b> — {esc(allocation['scenarioLabel'])}")
    for ln in allocation.get("lines") or []:
        if not ln.get("recommended"):
            continue
        lines.append(
            f"• {esc(ln.get('label'))}: ≥{fmt_pct(ln.get('minPercent'))} "
            f"({fmt_money(ln.get('minAmount'), cur)}) · paid {fmt_money(ln.get('paidAmount'), cur)}, "
            f"left {fmt_money(ln.get('remainingAmount'), cur)}")
    actions = allocation.get("actions") or []
    if actions:
        lines.append("\n<b>Action items</b>")
        for a in actions:
            lines.append(f"• {esc(a.get('text'))}")
    await cb.message.edit_text("\n".join(lines), reply_markup=keyboards.back_menu_kb())


async def show_settings(cb: CallbackQuery) -> None:
    chat_id = cb.message.chat.id
    cur = store.currency(chat_id)
    try:
        s = await api.request(chat_id, "GET", "/settings")
    except api.NeedsLogin:
        await cb.message.edit_text("🔒 Session expired. Please log in.", reply_markup=keyboards.login_kb())
        return
    except Exception:  # noqa: BLE001
        await cb.message.edit_text("❌ Couldn't load settings.", reply_markup=keyboards.back_menu_kb())
        return
    income_cur = s.get("monthlyStableIncomeCurrency") or "—"
    income = fmt_money(s.get("monthlyStableIncome"), income_cur) if s.get("monthlyStableIncome") else "—"
    text = (
        f"⚙️ <b>Settings</b>\n\n"
        f"Display &amp; default currency: <b>{cur}</b>\n"
        f"<i>Used for the dashboard / overview and as the default when adding transactions.</i>\n\n"
        f"Stable income: {income}\n"
        f"FX: 1 USD = {fmt_money(s.get('usdToUzs'), 'UZS')} · 1 EUR = {fmt_money(s.get('eurToUzs'), 'UZS')}\n\n"
        f"Pick your currency:"
    )
    await cb.message.edit_text(text, reply_markup=keyboards.currency_kb(cur))


@router.callback_query(F.data.startswith("setcur:"))
async def on_set_currency(cb: CallbackQuery) -> None:
    chat_id = cb.message.chat.id
    if not store.is_active(chat_id):
        await cb.answer()
        await cb.message.edit_text("🔒 Session expired. Please log in.", reply_markup=keyboards.login_kb())
        return
    store.set_currency(chat_id, cb.data.split(":", 1)[1])
    await cb.answer("Currency updated")
    await show_settings(cb)
