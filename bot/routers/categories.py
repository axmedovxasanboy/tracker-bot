"""Categories: list (two-level), add (root or sub, bonus flag for income), delete."""
from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from .. import api, common, keyboards
from ..i18n import cat_name, t
from ..keyboards import esc, ikb
from ..states import CatCreate

router = Router()


def _type_label(chat_id: int, typ: str) -> str:
    return {
        "INCOME": t(chat_id, "tx.income"), "EXPENSE": t(chat_id, "tx.expense"), "BOTH": t(chat_id, "cat.both"),
    }.get(typ, "?")


def _menu_kb(chat_id: int):
    return ikb([[(t(chat_id, "common.add"), "cat:add"), (t(chat_id, "common.delete"), "cat:del")],
               [(t(chat_id, "common.menu"), "menu:home")]])


def _back_kb(chat_id: int):
    return ikb([[(t(chat_id, "cat.backToCategories"), "cat:list")]])


async def _fetch_roots(cb: CallbackQuery):
    chat_id = cb.message.chat.id
    try:
        return await api.request(chat_id, "GET", "/categories") or []
    except api.NeedsLogin:
        await cb.message.edit_text(t(chat_id, "common.sessionExpired"), reply_markup=keyboards.login_kb(chat_id))
    except Exception:  # noqa: BLE001
        await cb.message.edit_text(t(chat_id, "cat.loadError"), reply_markup=keyboards.back_menu_kb(chat_id))
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
    chat_id = cb.message.chat.id
    roots = await _fetch_roots(cb)
    if roots is None:
        return
    lines = [t(chat_id, "cat.title")]
    for typ in ("INCOME", "EXPENSE", "BOTH"):
        group = [r for r in roots if r.get("type") == typ]
        if not group:
            continue
        lines.append(f"\n<b>{_type_label(chat_id, typ)}</b>")
        for r in group:
            lines.append(f"• {esc(cat_name(chat_id, r))}{' 🎁' if r.get('bonusIncome') else ''}")
            for ch in r.get("children", []):
                lines.append(f"   – {esc(cat_name(chat_id, ch))}{' 🎁' if ch.get('bonusIncome') else ''}")
    if len(lines) == 1:
        lines.append(f"\n{t(chat_id, 'cat.noneYet')}")
    await cb.message.edit_text("\n".join(lines), reply_markup=_menu_kb(chat_id))


# ── add ─────────────────────────────────────────────────────────────────────
@router.callback_query(F.data == "catcancel")
async def add_cancel(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    chat_id = cb.message.chat.id
    await state.clear()
    await cb.message.edit_text(t(chat_id, "common.cancelled"), reply_markup=_back_kb(chat_id))


@router.callback_query(F.data == "cat:add")
async def add_entry(cb: CallbackQuery, state: FSMContext) -> None:
    if not await common.gate(cb):
        return
    await cb.answer()
    chat_id = cb.message.chat.id
    await state.set_state(CatCreate.mode)
    await cb.message.edit_text(t(chat_id, "cat.newCategory"), reply_markup=ikb([
        [(t(chat_id, "cat.rootCategory"), "cmode:root"), (t(chat_id, "cat.subCategory"), "cmode:sub")],
        [(t(chat_id, "common.cancel"), "catcancel")],
    ]))


@router.callback_query(StateFilter(CatCreate.mode), F.data.startswith("cmode:"))
async def add_mode(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    chat_id = cb.message.chat.id
    if cb.data == "cmode:root":
        await state.set_state(CatCreate.root_name)
        await cb.message.edit_text(t(chat_id, "cat.sendName"),
                                   reply_markup=ikb([[(t(chat_id, "common.cancel"), "catcancel")]]))
        return
    roots = await _fetch_roots(cb)
    if roots is None:
        return
    if not roots:
        await cb.message.edit_text(t(chat_id, "cat.noRootsYet"), reply_markup=_back_kb(chat_id))
        await state.clear()
        return
    await state.update_data(c_roots=roots)
    await state.set_state(CatCreate.parent)
    rows = [[(f"{cat_name(chat_id, r)} ({_type_label(chat_id, r.get('type'))})", f"cparent:{r['id']}")] for r in roots]
    rows.append([(t(chat_id, "common.cancel"), "catcancel")])
    await cb.message.edit_text(t(chat_id, "cat.pickParent"), reply_markup=ikb(rows))


@router.message(StateFilter(CatCreate.root_name))
async def add_root_name(message: Message, state: FSMContext) -> None:
    chat_id = message.chat.id
    await state.update_data(c_name=(message.text or "").strip())
    await state.set_state(CatCreate.root_type)
    await message.answer(t(chat_id, "cat.pickType"), reply_markup=ikb([
        [(t(chat_id, "tx.income"), "ctype:INCOME"), (t(chat_id, "tx.expense"), "ctype:EXPENSE")],
        [(t(chat_id, "cat.both"), "ctype:BOTH")],
        [(t(chat_id, "common.cancel"), "catcancel")],
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
    chat_id = cb.message.chat.id
    pid = int(cb.data.split(":", 1)[1])
    d = await state.get_data()
    parent = next((r for r in d.get("c_roots", []) if r.get("id") == pid), None)
    if parent is None:
        await cb.message.edit_text(t(chat_id, "cat.parentGone"), reply_markup=_back_kb(chat_id))
        await state.clear()
        return
    await state.update_data(c_parentId=pid, c_type=parent.get("type"))
    await state.set_state(CatCreate.sub_name)
    await cb.message.edit_text(t(chat_id, "cat.parentHeader", name=esc(cat_name(chat_id, parent))),
                               reply_markup=ikb([[(t(chat_id, "common.cancel"), "catcancel")]]))


@router.message(StateFilter(CatCreate.sub_name))
async def add_sub_name(message: Message, state: FSMContext) -> None:
    await state.update_data(c_name=(message.text or "").strip())
    d = await state.get_data()
    if d.get("c_type") in ("INCOME", "BOTH"):
        await _ask_bonus(message, state)
    else:
        await _finish(message, state)


async def _ask_bonus(event, state: FSMContext) -> None:
    chat_id = common.chat_id_of(event)
    await state.set_state(CatCreate.bonus)
    await common.show(event, t(chat_id, "cat.bonusQuestion"),
                      ikb([[(t(chat_id, "cat.bonusYes"), "cbonus:yes"), (t(chat_id, "cat.bonusNo"), "cbonus:no")],
                          [(t(chat_id, "common.cancel"), "catcancel")]]))


@router.callback_query(StateFilter(CatCreate.bonus), F.data.startswith("cbonus:"))
async def add_bonus(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    await state.update_data(c_bonus=(cb.data.split(":", 1)[1] == "yes"))
    await _finish(cb, state)


async def _finish(event, state: FSMContext) -> None:
    chat_id = common.chat_id_of(event)
    d = await state.get_data()
    payload = {"name": d["c_name"], "type": d["c_type"]}
    if d.get("c_parentId") is not None:
        payload["parentId"] = d["c_parentId"]
    if "c_bonus" in d:
        payload["bonusIncome"] = d["c_bonus"]
    try:
        await api.request(chat_id, "POST", "/categories", json=payload)
    except api.NeedsLogin:
        await state.clear()
        await common.show(event, t(chat_id, "common.sessionExpired"), keyboards.login_kb(chat_id))
        return
    except api.ApiError as exc:
        await state.clear()
        await common.show(event, f"❌ {esc(exc.message)}", _back_kb(chat_id))
        return
    except Exception:  # noqa: BLE001
        await state.clear()
        await common.show(event, t(chat_id, "common.serverUnreachable"), _back_kb(chat_id))
        return
    await state.clear()
    await common.show(event, t(chat_id, "cat.created", name=esc(payload['name'])), _back_kb(chat_id))


# ── delete (non-destructive) ─────────────────────────────────────────────────
@router.callback_query(F.data == "cat:del")
async def del_list(cb: CallbackQuery) -> None:
    await cb.answer()
    if not await common.gate(cb):
        return
    chat_id = cb.message.chat.id
    roots = await _fetch_roots(cb)
    if roots is None:
        return
    rows = []
    for r in roots:
        if len(rows) >= 25:
            break
        rows.append([(cat_name(chat_id, r), f"catdel:{r['id']}")])
        for ch in r.get("children", []):
            if len(rows) >= 25:
                break
            rows.append([(f"   – {cat_name(chat_id, ch)}", f"catdel:{ch['id']}")])
    if not rows:
        await cb.message.edit_text(t(chat_id, "cat.noneToDelete"), reply_markup=_back_kb(chat_id))
        return
    rows.append([(t(chat_id, "cat.backToCategories"), "cat:list")])
    await cb.message.edit_text(t(chat_id, "cat.pickToDelete"), reply_markup=ikb(rows))


@router.callback_query(F.data.startswith("catdelok:"))
async def del_do(cb: CallbackQuery) -> None:
    await cb.answer()
    if not await common.gate(cb):
        return
    chat_id = cb.message.chat.id
    cid = int(cb.data.split(":")[1])
    try:
        await api.request(chat_id, "DELETE", f"/categories/{cid}")
    except api.NeedsLogin:
        await cb.message.edit_text(t(chat_id, "common.sessionExpired"), reply_markup=keyboards.login_kb(chat_id))
        return
    except api.ApiError as exc:
        await cb.message.edit_text(f"❌ {esc(exc.message)}", reply_markup=_back_kb(chat_id))
        return
    except Exception:  # noqa: BLE001
        await cb.message.edit_text(t(chat_id, "common.serverUnreachable"), reply_markup=_back_kb(chat_id))
        return
    await _render(cb)


@router.callback_query(F.data.startswith("catdel:"))
async def del_confirm(cb: CallbackQuery) -> None:
    await cb.answer()
    chat_id = cb.message.chat.id
    cid = int(cb.data.split(":")[1])
    await cb.message.edit_text(
        t(chat_id, "cat.deleteConfirm"),
        reply_markup=ikb([[(t(chat_id, "common.deleteYes"), f"catdelok:{cid}"), (t(chat_id, "common.no"), "cat:del")]]))
