"""Main-menu navigation + read pages: Dashboard, Overview, Settings."""
import datetime as dt

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from .. import api, common, keyboards
from ..config import CURRENCY
from ..i18n import set_lang, t
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
    chat_id = cb.message.chat.id
    if not store.is_active(chat_id):
        await cb.message.edit_text(t(chat_id, "common.sessionExpired"), reply_markup=keyboards.login_kb(chat_id))
        return
    page = cb.data.split(":", 1)[1]
    if page == "home":
        await cb.message.edit_text(keyboards.menu_text(chat_id), reply_markup=keyboards.main_menu_kb(chat_id))
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
    try:
        d = await api.request(chat_id, "GET", "/dashboard/summary", params={"currency": CURRENCY})
    except api.NeedsLogin:
        await cb.message.edit_text(t(chat_id, "common.sessionExpired"), reply_markup=keyboards.login_kb(chat_id))
        return
    except Exception:  # noqa: BLE001
        await cb.message.edit_text(t(chat_id, "menu.dashboardError"), reply_markup=keyboards.back_menu_kb(chat_id))
        return
    spendable = d.get('spendableBalance', d.get('availableBalance'))
    net_worth = d.get('netWorth', d.get('netBalance'))
    text = (
        f"{t(chat_id, 'menu.dashboard.title')} · {CURRENCY}\n\n"
        f"{t(chat_id, 'menu.dashboard.spendable')}: <b>{fmt_money(spendable)}</b>\n"
        f"{t(chat_id, 'menu.dashboard.netWorth')}: <b>{fmt_money(net_worth)}</b>\n"
        f"{t(chat_id, 'menu.dashboard.netWorthNote')}\n\n"
        f"{t(chat_id, 'menu.dashboard.income')}: {fmt_money(d.get('totalIncome'))}\n"
        f"{t(chat_id, 'menu.dashboard.expenses')}: {fmt_money(d.get('totalExpense'))}\n"
        f"{t(chat_id, 'menu.dashboard.transactions')}: {d.get('transactionCount', 0)}"
    )
    await cb.message.edit_text(text, reply_markup=keyboards.back_menu_kb(chat_id))


async def show_overview(cb: CallbackQuery) -> None:
    chat_id = cb.message.chat.id
    month = _month_now()
    try:
        t_data = await api.request(chat_id, "GET", "/overview/tier", params={"currency": CURRENCY, "month": month})
    except api.NeedsLogin:
        await cb.message.edit_text(t(chat_id, "common.sessionExpired"), reply_markup=keyboards.login_kb(chat_id))
        return
    except Exception:  # noqa: BLE001
        await cb.message.edit_text(t(chat_id, "menu.overviewError"), reply_markup=keyboards.back_menu_kb(chat_id))
        return
    lines = [
        f"{t(chat_id, 'menu.overview.title')} · {CURRENCY} · {month}",
        f"{t(chat_id, 'menu.overview.tier')}: <b>{esc(t_data.get('levelLabel', '—'))}</b>",
        f"{t(chat_id, 'menu.overview.stableIncome')}: {fmt_money(t_data.get('income'))}",
        f"{t(chat_id, 'menu.overview.leftMoney')}: {fmt_money(t_data.get('leftMoney'))}",
        f"{t(chat_id, 'menu.overview.debtPayments')}: {fmt_money(t_data.get('debtPayments'))}",
    ]
    # B-T-2: surface the gating / state flags so a withheld or paused allocation reads as
    # intentional, not broken. While any of these is set the backend returns a dormant stub.
    withheld = bool(
        t_data.get("missingStableIncome") or t_data.get("beforeTrackingStart") or t_data.get("subscriptionsPending")
    )
    if t_data.get("missingStableIncome"):
        lines.append(f"\n{t(chat_id, 'menu.overview.setIncomeWarning')}")
    if t_data.get("beforeTrackingStart"):
        lines.append(t(chat_id, "menu.overview.trackingStarts", month=esc(t_data.get("trackingStartMonth"))))
    if t_data.get("subscriptionsPending"):
        lines.append(f"\n{t(chat_id, 'menu.overview.subsPendingWarning')}")
        for ps in t_data.get("pendingSubscriptions") or []:
            lines.append("• " + t(
                chat_id, "menu.overview.subsPendingLine",
                name=esc(ps.get("name")), paid=fmt_money(ps.get("paid")), amount=fmt_money(ps.get("amount"))))

    allocation = t_data.get("allocation") or {}
    if not withheld:
        if allocation.get("scenarioLabel"):
            lines.append(f"\n{t(chat_id, 'menu.overview.allocationHeader', label=esc(allocation['scenarioLabel']))}")
        if allocation.get("allocationLocked"):
            lines.append(t(chat_id, "menu.overview.allocationLocked"))
        # Allocation %s apply to "left balance" = leftMoney − debtPayments (stable income −
        # mandatory subscriptions − monthly debt charge).
        if t_data.get("allocationBase") is not None:
            lines.append(t(chat_id, "menu.overview.baseNote", base=fmt_money(t_data.get("allocationBase"))))
        # B-T-1: render EVERY bucket. A 0% bucket is shown as "NO NEED" instead of being
        # silently dropped (which read as missing/broken data).
        for ln in allocation.get("lines") or []:
            label = esc(ln.get("label"))
            if not ln.get("recommended"):
                paid = ln.get("paidAmount")
                extra = t(chat_id, "menu.overview.bucketPaidExtra", paid=fmt_money(paid)) if paid else ""
                lines.append("• " + t(chat_id, "menu.overview.bucketNoNeed", label=label, extra=extra))
            else:
                lines.append("• " + t(
                    chat_id, "menu.overview.bucketLine", label=label,
                    minPercent=fmt_pct(ln.get("minPercent")), minAmount=fmt_money(ln.get("minAmount")),
                    paid=fmt_money(ln.get("paidAmount")), left=fmt_money(ln.get("remainingAmount"))))
        # B-T-3: action items carry paid/target progress, not just text.
        actions = allocation.get("actions") or []
        if actions:
            lines.append(f"\n{t(chat_id, 'menu.overview.actionsHeader')}")
            for a in actions:
                text = esc(a.get("text"))
                if a.get("action") and a.get("target"):
                    lines.append("• " + t(
                        chat_id, "menu.overview.actionProgress", text=text,
                        paid=fmt_money(a.get("paid")), target=fmt_money(a.get("target"))))
                else:
                    lines.append(f"• {text}")

    await cb.message.edit_text("\n".join(lines), reply_markup=keyboards.back_menu_kb(chat_id))


async def show_settings(cb: CallbackQuery) -> None:
    chat_id = cb.message.chat.id
    try:
        s = await api.request(chat_id, "GET", "/settings")
    except api.NeedsLogin:
        await cb.message.edit_text(t(chat_id, "common.sessionExpired"), reply_markup=keyboards.login_kb(chat_id))
        return
    except Exception:  # noqa: BLE001
        await cb.message.edit_text(t(chat_id, "menu.settingsError"), reply_markup=keyboards.back_menu_kb(chat_id))
        return
    income = fmt_money(s.get("monthlyStableIncome")) if s.get("monthlyStableIncome") else "—"
    text = (
        f"{t(chat_id, 'menu.settings.title')}\n\n"
        f"{t(chat_id, 'menu.settings.currency')}: <b>{CURRENCY}</b>\n\n"
        f"{t(chat_id, 'menu.settings.stableIncome')}: {income}"
    )
    await cb.message.edit_text(text, reply_markup=keyboards.settings_kb(chat_id))


# ── Danger Zone: factory reset ──────────────────────────────────────────────
@router.callback_query(F.data == "reset:start")
async def reset_start(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    chat_id = cb.message.chat.id
    if not store.is_active(chat_id):
        await cb.message.edit_text(t(chat_id, "common.sessionExpired"), reply_markup=keyboards.login_kb(chat_id))
        return
    await state.set_state(Reset.password)
    await cb.message.answer(
        f"{t(chat_id, 'menu.reset.title')}\n\n"
        f"{t(chat_id, 'menu.reset.body')}\n\n"
        f"{t(chat_id, 'menu.reset.prompt')}"
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
        await message.answer(t(chat_id, "common.sessionExpired"), reply_markup=keyboards.login_kb(chat_id))
        return
    try:
        await api.reset(chat_id, password)
    except api.NeedsLogin:
        await state.clear()
        store.lock(chat_id)
        await message.answer(t(chat_id, "common.sessionExpired"), reply_markup=keyboards.login_kb(chat_id))
        return
    except api.ApiError as exc:
        await state.clear()
        await message.answer(f"❌ {esc(exc.message)}", reply_markup=keyboards.back_menu_kb(chat_id))
        return
    except Exception:  # noqa: BLE001
        await state.clear()
        await message.answer(t(chat_id, "common.serverUnreachable"), reply_markup=keyboards.back_menu_kb(chat_id))
        return
    # Account is gone now — drop the session and send the user to a fresh login/signup.
    store.lock(chat_id)
    await state.clear()
    await message.answer(t(chat_id, "menu.reset.done"), reply_markup=keyboards.login_kb(chat_id))


# ── Language ────────────────────────────────────────────────────────────────
@router.callback_query(F.data == "lang:open")
async def lang_open(cb: CallbackQuery) -> None:
    await cb.answer()
    if not await common.gate(cb):
        return
    chat_id = cb.message.chat.id
    await cb.message.edit_text(
        f"{t(chat_id, 'lang.title')}\n\n{t(chat_id, 'lang.pick')}",
        reply_markup=keyboards.language_kb(chat_id))


@router.callback_query(F.data.startswith("lang:set:"))
async def lang_set(cb: CallbackQuery) -> None:
    await cb.answer()
    chat_id = cb.message.chat.id
    set_lang(chat_id, cb.data.rsplit(":", 1)[1])
    await cb.message.edit_text(
        f"{t(chat_id, 'lang.title')}\n\n{t(chat_id, 'lang.changed')}",
        reply_markup=keyboards.language_kb(chat_id))
