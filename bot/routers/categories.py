"""Categories: list (two-level), add (root or sub, bonus flag for income), delete."""
from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from .. import api, common, keyboards
from ..keyboards import esc, ikb
from ..session import store
from ..states import CatCreate

router = Router()
TYPE_LABELS = {"INCOME": "Income", "EXPENSE": "Expense", "BOTH": "Both"}


def _menu_kb():
    return ikb([[("➕ Add", "cat:add"), ("🗑 Delete", "cat:del")], [("⬅️ Menu", "menu:home")]])


def _back_kb():
    return ikb([[("⬅️ Categories", "cat:list")]])


async def _fetch_roots(cb: CallbackQuery):
    try:
        return await api.request(cb.message.chat.id, "GET", "/categories") or []
    except api.NeedsLogin:
        await cb.message.edit_text("🔒 Session expired. Please log in.", reply_markup=keyboards.login_kb())
    except Exception:  # noqa: BLE001
        await cb.message.edit_text("❌ Couldn't load categories.", reply_markup=keyboards.back_menu_kb())
    return None


async def show_menu(cb: CallbackQuery) -> None:
    await _render(cb)


@router.callback_query(F.data == "cat:list")
async def cat_list(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    await state.clear()
    if not await common.gate(cb):
        return
    await _render(cb)


async def _render(cb: CallbackQuery) -> None:
    roots = await _fetch_roots(cb)
    if roots is None:
        return
    lines = ["🏷 <b>Categories</b>"]
    for typ in ("INCOME", "EXPENSE", "BOTH"):
        group = [r for r in roots if r.get("type") == typ]
        if not group:
            continue
        lines.append(f"\n<b>{TYPE_LABELS[typ]}</b>")
        for r in group:
            lines.append(f"• {esc(r.get('name'))}{' 🎁' if r.get('bonusIncome') else ''}")
            for ch in r.get("children", []):
                lines.append(f"   – {esc(ch.get('name'))}{' 🎁' if ch.get('bonusIncome') else ''}")
    if len(lines) == 1:
        lines.append("\nNo categories yet.")
    await cb.message.edit_text("\n".join(lines), reply_markup=_menu_kb())


# ── add ─────────────────────────────────────────────────────────────────────
@router.callback_query(F.data == "catcancel")
async def add_cancel(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    await state.clear()
    await cb.message.edit_text("Cancelled.", reply_markup=_back_kb())


@router.callback_query(F.data == "cat:add")
async def add_entry(cb: CallbackQuery, state: FSMContext) -> None:
    if not await common.gate(cb):
        return
    await cb.answer()
    await state.set_state(CatCreate.mode)
    await cb.message.edit_text("➕ <b>New category</b>\nRoot or sub-category?", reply_markup=ikb([
        [("📁 Root category", "cmode:root"), ("📂 Sub-category", "cmode:sub")],
        [("✖️ Cancel", "catcancel")],
    ]))


@router.callback_query(StateFilter(CatCreate.mode), F.data.startswith("cmode:"))
async def add_mode(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    if cb.data == "cmode:root":
        await state.set_state(CatCreate.root_name)
        await cb.message.edit_text("Send the <b>category name</b>:",
                                   reply_markup=ikb([[("✖️ Cancel", "catcancel")]]))
        return
    roots = await _fetch_roots(cb)
    if roots is None:
        return
    if not roots:
        await cb.message.edit_text("No root categories yet — create a root first.", reply_markup=_back_kb())
        await state.clear()
        return
    await state.update_data(c_roots=roots)
    await state.set_state(CatCreate.parent)
    rows = [[(f"{r.get('name')} ({TYPE_LABELS.get(r.get('type'), '?')})", f"cparent:{r['id']}")] for r in roots]
    rows.append([("✖️ Cancel", "catcancel")])
    await cb.message.edit_text("Pick the <b>parent</b>:", reply_markup=ikb(rows))


@router.message(StateFilter(CatCreate.root_name))
async def add_root_name(message: Message, state: FSMContext) -> None:
    await state.update_data(c_name=(message.text or "").strip())
    await state.set_state(CatCreate.root_type)
    await message.answer("Pick the <b>type</b>:", reply_markup=ikb([
        [("📈 Income", "ctype:INCOME"), ("📉 Expense", "ctype:EXPENSE")],
        [("🔀 Both", "ctype:BOTH")],
        [("✖️ Cancel", "catcancel")],
    ]))


@router.callback_query(StateFilter(CatCreate.root_type), F.data.startswith("ctype:"))
async def add_root_type(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    typ = cb.data.split(":", 1)[1]
    await state.update_data(c_type=typ)
    if typ in ("INCOME", "BOTH"):
        await _ask_bonus(cb, state)
    else:
        await _finish(cb, state)


@router.callback_query(StateFilter(CatCreate.parent), F.data.startswith("cparent:"))
async def add_parent(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    pid = int(cb.data.split(":", 1)[1])
    d = await state.get_data()
    parent = next((r for r in d.get("c_roots", []) if r.get("id") == pid), None)
    if parent is None:
        await cb.message.edit_text("That parent no longer exists.", reply_markup=_back_kb())
        await state.clear()
        return
    await state.update_data(c_parentId=pid, c_type=parent.get("type"))
    await state.set_state(CatCreate.sub_name)
    await cb.message.edit_text(f"Parent: <b>{esc(parent.get('name'))}</b>\nSend the <b>sub-category name</b>:",
                               reply_markup=ikb([[("✖️ Cancel", "catcancel")]]))


@router.message(StateFilter(CatCreate.sub_name))
async def add_sub_name(message: Message, state: FSMContext) -> None:
    await state.update_data(c_name=(message.text or "").strip())
    d = await state.get_data()
    if d.get("c_type") in ("INCOME", "BOTH"):
        await _ask_bonus(message, state)
    else:
        await _finish(message, state)


async def _ask_bonus(event, state: FSMContext) -> None:
    await state.set_state(CatCreate.bonus)
    await common.show(event,
                      "Counts as <b>bonus income</b>? (Bonus adds the tier % on top of that month's "
                      "allocation target — e.g. a holiday bonus or 13th salary.)",
                      ikb([[("Yes — bonus", "cbonus:yes"), ("No", "cbonus:no")], [("✖️ Cancel", "catcancel")]]))


@router.callback_query(StateFilter(CatCreate.bonus), F.data.startswith("cbonus:"))
async def add_bonus(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    await state.update_data(c_bonus=(cb.data.split(":", 1)[1] == "yes"))
    await _finish(cb, state)


async def _finish(event, state: FSMContext) -> None:
    d = await state.get_data()
    payload = {"name": d["c_name"], "type": d["c_type"]}
    if d.get("c_parentId") is not None:
        payload["parentId"] = d["c_parentId"]
    if "c_bonus" in d:
        payload["bonusIncome"] = d["c_bonus"]
    try:
        await api.request(common.chat_id_of(event), "POST", "/categories", json=payload)
    except api.NeedsLogin:
        await state.clear()
        await common.show(event, "🔒 Session expired. Please log in.", keyboards.login_kb())
        return
    except api.ApiError as exc:
        await state.clear()
        await common.show(event, f"❌ {esc(exc.message)}", _back_kb())
        return
    except Exception:  # noqa: BLE001
        await state.clear()
        await common.show(event, "❌ Couldn't reach the server.", _back_kb())
        return
    await state.clear()
    await common.show(event, f"✅ Category <b>{esc(payload['name'])}</b> created.", _back_kb())


# ── delete (non-destructive) ─────────────────────────────────────────────────
@router.callback_query(F.data == "cat:del")
async def del_list(cb: CallbackQuery) -> None:
    await cb.answer()
    if not await common.gate(cb):
        return
    roots = await _fetch_roots(cb)
    if roots is None:
        return
    rows = []
    for r in roots:
        if len(rows) >= 25:
            break
        rows.append([(f"{r.get('name')}", f"catdel:{r['id']}")])
        for ch in r.get("children", []):
            if len(rows) >= 25:
                break
            rows.append([(f"   – {ch.get('name')}", f"catdel:{ch['id']}")])
    if not rows:
        await cb.message.edit_text("No categories to delete.", reply_markup=_back_kb())
        return
    rows.append([("⬅️ Categories", "cat:list")])
    await cb.message.edit_text("🗑 Pick a category to delete:", reply_markup=ikb(rows))


@router.callback_query(F.data.startswith("catdelok:"))
async def del_do(cb: CallbackQuery) -> None:
    await cb.answer()
    if not await common.gate(cb):
        return
    cid = int(cb.data.split(":")[1])
    try:
        await api.request(cb.message.chat.id, "DELETE", f"/categories/{cid}")
    except api.NeedsLogin:
        await cb.message.edit_text("🔒 Session expired. Please log in.", reply_markup=keyboards.login_kb())
        return
    except api.ApiError as exc:
        await cb.message.edit_text(f"❌ {esc(exc.message)}", reply_markup=_back_kb())
        return
    except Exception:  # noqa: BLE001
        await cb.message.edit_text("❌ Couldn't reach the server.", reply_markup=_back_kb())
        return
    await _render(cb)


@router.callback_query(F.data.startswith("catdel:"))
async def del_confirm(cb: CallbackQuery) -> None:
    await cb.answer()
    cid = int(cb.data.split(":")[1])
    await cb.message.edit_text(
        "Delete this category? Sub-categories become roots and linked transactions keep their "
        "history but lose the category. Continue?",
        reply_markup=ikb([[("✅ Yes, delete", f"catdelok:{cid}"), ("✖️ No", "cat:del")]]))
