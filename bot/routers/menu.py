"""Main-menu navigation + read pages: Dashboard, Overview, Settings."""
import datetime as dt

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from .. import api, keyboards
from ..keyboards import esc, fmt_money, fmt_pct
from ..session import store
from ..states import Reset

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
    elif page == "months":
        from .months import show_menu
        await show_menu(cb)
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
    spendable = d.get('spendableBalance', d.get('availableBalance'))
    net_worth = d.get('netWorth', d.get('netBalance'))
    text = (
        f"📊 <b>Dashboard</b> · {cur}\n\n"
        f"💵 Spendable: <b>{fmt_money(spendable, cur)}</b>\n"
        f"🏦 Net worth: <b>{fmt_money(net_worth, cur)}</b>\n"
        f"<i>Net worth = spendable + investments &amp; savings</i>\n\n"
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
    # B-T-2: surface the gating / state flags so a withheld or paused allocation reads as
    # intentional, not broken. While any of these is set the backend returns a dormant stub.
    withheld = bool(
        t.get("missingStableIncome") or t.get("beforeTrackingStart") or t.get("subscriptionsPending")
    )
    if t.get("missingStableIncome"):
        lines.append("\n⚠️ <b>Set your monthly income in Settings</b> — tier &amp; allocation can't be computed yet.")
    if t.get("fxRatesUsingDefaults"):
        lines.append("ℹ️ FX rates use built-in defaults — set real rates in Settings for accurate numbers.")
    if t.get("beforeTrackingStart"):
        lines.append(f"⏸ Allocation tracking starts <b>{esc(t.get('trackingStartMonth'))}</b> — nothing is due until then.")
    if t.get("subscriptionsPending"):
        lines.append("\n🔒 <b>Pay your mandatory subscriptions first</b> — allocation unlocks once they're covered.")
        for ps in t.get("pendingSubscriptions") or []:
            pcur = ps.get("currency", cur)
            lines.append(
                f"• {esc(ps.get('name'))}: {fmt_money(ps.get('paid'), pcur)} / {fmt_money(ps.get('amount'), pcur)} paid")

    allocation = t.get("allocation") or {}
    if not withheld:
        if allocation.get("scenarioLabel"):
            lines.append(f"\n<b>Allocation</b> — {esc(allocation['scenarioLabel'])}")
        if allocation.get("allocationLocked"):
            lines.append("🔒 Locked — pay the action items below to their targets first.")
        # Allocation %s apply to "left balance" = leftMoney − debtPayments (stable income −
        # mandatory subscriptions − monthly debt charge).
        if t.get("allocationBase") is not None:
            lines.append(f"<i>% of left balance {fmt_money(t.get('allocationBase'), cur)} (income − subscriptions − debt)</i>")
        # B-T-1: render EVERY bucket. A 0% bucket is shown as "NO NEED" instead of being
        # silently dropped (which read as missing/broken data).
        for ln in allocation.get("lines") or []:
            label = esc(ln.get("label"))
            if not ln.get("recommended"):
                paid = ln.get("paidAmount")
                extra = f" · paid {fmt_money(paid, cur)}" if paid else ""
                lines.append(f"• {label}: <i>NO NEED this month</i>{extra}")
            else:
                lines.append(
                    f"• {label}: ≥{fmt_pct(ln.get('minPercent'))} "
                    f"({fmt_money(ln.get('minAmount'), cur)}) · paid {fmt_money(ln.get('paidAmount'), cur)}, "
                    f"left {fmt_money(ln.get('remainingAmount'), cur)}")
        # B-T-3: action items carry paid/target progress, not just text.
        actions = allocation.get("actions") or []
        if actions:
            lines.append("\n<b>Action items</b>")
            for a in actions:
                text = esc(a.get("text"))
                if a.get("action") and a.get("target"):
                    lines.append(
                        f"• {text}\n   ↳ paid {fmt_money(a.get('paid'), cur)} / {fmt_money(a.get('target'), cur)}")
                else:
                    lines.append(f"• {text}")

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


# ── Danger Zone: factory reset ──────────────────────────────────────────────
@router.callback_query(F.data == "reset:start")
async def reset_start(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    if not store.is_active(cb.message.chat.id):
        await cb.message.edit_text("🔒 Session expired. Please log in.", reply_markup=keyboards.login_kb())
        return
    await state.set_state(Reset.password)
    await cb.message.answer(
        "⚠️ <b>Danger Zone — Clear everything</b>\n\n"
        "This permanently deletes <b>all</b> your data — transactions, cards, finance records, "
        "categories, settings, and your account — and starts the app over from zero. "
        "This <b>cannot be undone</b>.\n\n"
        "Type your <b>password</b> to confirm, or /cancel to abort."
    )


@router.message(StateFilter(Reset.password))
async def reset_password(message: Message, state: FSMContext) -> None:
    chat_id = message.chat.id
    password = message.text or ""
    try:
        await message.delete()  # don't leave the password in chat history
    except Exception:  # noqa: BLE001
        pass
    if not store.is_active(chat_id):
        await state.clear()
        await message.answer("🔒 Session expired. Please log in.", reply_markup=keyboards.login_kb())
        return
    try:
        await api.reset(chat_id, password)
    except api.NeedsLogin:
        await state.clear()
        store.lock(chat_id)
        await message.answer("🔒 Session expired. Please log in.", reply_markup=keyboards.login_kb())
        return
    except api.ApiError as exc:
        await state.clear()
        await message.answer(f"❌ {esc(exc.message)}", reply_markup=keyboards.back_menu_kb())
        return
    except Exception:  # noqa: BLE001
        await state.clear()
        await message.answer("❌ Couldn't reach the server.", reply_markup=keyboards.back_menu_kb())
        return
    # Account is gone now — drop the session and send the user to a fresh login/signup.
    store.lock(chat_id)
    await state.clear()
    await message.answer(
        "✅ Everything was cleared. The app has started over from zero.\n\n"
        "Tap below to create a new account.",
        reply_markup=keyboards.login_kb(),
    )
