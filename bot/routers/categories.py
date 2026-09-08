"""Categories — the two-level tree, creating one, editing one, deleting one.

Four decisions shape this file.

**A create flow starts from nothing.** `cat:add` now clears the FSM before it sets its state,
and the answers it collects live in a single `c_new` dict written fresh on entry. Both halves
are needed. aiogram's `update_data` MERGES, so the old code — which set the state but never
cleared the bag — could carry a `c_parentId` out of an abandoned sub-category flow and into
the next "root category" POST, filing a top-level category under a parent the owner never
chose and never saw. Every exit that cleared state (`menu:*`, `cat:list`, Cancel, `/cancel`)
was optional; the ➕ Add button on a scrolled-up categories list was not one of them. With the
payload built fresh per run, a leaked key cannot reach the request even if the bag survives.

**Editing exists because deleting is not an undo.** `CategoryService.delete` detaches the
children (they become roots) and nulls the category on every transaction filed under it. Until
now that was the only way to fix a typo, so fixing a name cost a month of categorised history.
`PUT /categories/{id}` has always existed and nothing called it.

**A one-field edit still sends the whole category.** `CategoryService.applyRequest` writes the
entity from the request every time: an absent `parentId` promotes a sub-category to a root, an
absent `applicableSubType` clears it, and `anonymizes`/`bonusIncome` are read through
`Boolean.TRUE.equals(...)`, so an omitted flag is a silent `false`. The edit therefore echoes
the whole `CategoryResponse` back and changes exactly one key.

**Both names are editable, because both are displayed.** `cat_name()` shows `nameUz` on an
Uzbek screen and falls back to `name`. Renaming only the English half of a seeded category
would look like the rename had done nothing at all, so the edit screen shows both values and
lets the owner change either.

Callback namespaces owned here: `cat:*`, `catpick:*`, `catone:*`, `catname:*`, `catuz:*`,
`catbonus:*`, `catdel:*`, `catdelok:*`, `catcancel`, `cmode:*`, `ctype:*`, `cparent:*`,
`cbonus:*`, `cback:*`.
"""
import logging

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from .. import api, common, keyboards, ui
from ..i18n import cat_name, t
from ..keyboards import esc, ikb
from ..states import CatCreate, CatEdit

router = Router()

log = logging.getLogger(__name__)

# Categories per page in the picker. Twelve fills six two-wide rows and still leaves the
# pager and the navigation row on screen without scrolling on a phone.
_PAGE = 12

_TYPE_KEY = {"INCOME": "cat.typeIncome", "EXPENSE": "cat.typeExpense", "BOTH": "cat.typeBoth"}

# The same three types as one glyph, for button labels where the name has to fit beside it.
_TYPE_EMOJI = {"INCOME": "📈", "EXPENSE": "📉", "BOTH": "🔀"}

# The two types the allocation engine can treat as bonus income; asking about the flag on an
# expense category would be asking about something the backend ignores.
_BONUS_TYPES = ("INCOME", "BOTH")


def _type_label(chat_id: int, typ) -> str:
    key = _TYPE_KEY.get(typ)
    # An enum this bot has not been taught yet is escaped, not printed raw: it lands in
    # message text.
    return t(chat_id, key) if key else esc(typ or "—")


def _menu_kb(chat_id: int) -> InlineKeyboardMarkup:
    return ikb([[(t(chat_id, "common.add"), "cat:add"),
                 (t(chat_id, "common.edit"), "catpick:edit:0"),
                 (t(chat_id, "common.delete"), "catpick:del:0")],
                ui.nav(chat_id, menu=True)])


def _back_kb(chat_id: int) -> InlineKeyboardMarkup:
    return ikb([[(t(chat_id, "cat.backToCategories"), "cat:list")]])


def _id_at(data: str | None, index: int) -> int | None:
    """The integer at position `index` of a colon-split callback, or None.

    Callback data is the one string here that comes from outside this file — a button
    scrolled up in the chat, an update replayed after a restart — so ids are parsed, never
    assumed.
    """
    parts = (data or "").split(":")
    if len(parts) <= index:
        return None
    try:
        return int(parts[index])
    except ValueError:
        return None


async def _fetch_roots(event):
    """`GET /categories` — roots with their children nested. None means the error is shown."""
    chat_id = common.chat_id_of(event)
    try:
        return await api.request(chat_id, "GET", "/categories") or []
    except api.NeedsLogin:
        await common.show(event, t(chat_id, "common.sessionExpired"), keyboards.login_kb(chat_id))
    except api.Unreachable:
        await common.show(event, t(chat_id, "common.serverUnreachable"),
                          keyboards.back_menu_kb(chat_id))
    except Exception:  # noqa: BLE001
        log.exception("GET /categories failed for chat %s", chat_id)
        await common.show(event, t(chat_id, "cat.loadError"), keyboards.back_menu_kb(chat_id))
    return None


def _flatten(roots) -> list[tuple[dict, dict | None]]:
    """Every category as (row, parent) with each parent immediately before its children."""
    out: list[tuple[dict, dict | None]] = []
    for r in roots or []:
        if r.get("id") is None:
            continue
        out.append((r, None))
        for ch in r.get("children") or []:
            if ch.get("id") is not None:
                out.append((ch, r))
    return out


def _find(roots, cid: int) -> tuple[dict | None, dict | None]:
    for row, parent in _flatten(roots):
        if row.get("id") == cid:
            return row, parent
    return None, None


# ── the tree ─────────────────────────────────────────────────────────────────
async def show_menu(cb: CallbackQuery) -> None:
    """Entry point for `menu:categories` — the main menu imports this by name."""
    await _render(cb)


@router.callback_query(F.data == "cat:list")
async def cat_list(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    # The section root is the escape hatch from a half-finished create or edit: it abandons
    # the flow rather than leaving a state that would swallow the next message typed.
    await state.clear()
    if not await common.gate(cb):
        return
    await _render(cb)


async def _render(event, prefix: str = "") -> None:
    chat_id = common.chat_id_of(event)
    roots = await _fetch_roots(event)
    if roots is None:
        return
    lines = [prefix, ""] if prefix else []
    lines.append(t(chat_id, "cat.title"))
    for typ in ("INCOME", "EXPENSE", "BOTH"):
        group = [r for r in roots if r.get("type") == typ]
        if not group:
            continue
        lines.append(f"\n<b>{_type_label(chat_id, typ)}</b>")
        for r in group:
            lines.append(f"• {esc(cat_name(chat_id, r))}{' 🎁' if r.get('bonusIncome') else ''}")
            for ch in r.get("children") or []:
                lines.append(
                    f"   – {esc(cat_name(chat_id, ch))}{' 🎁' if ch.get('bonusIncome') else ''}")
    if not roots:
        lines.append(f"\n{t(chat_id, 'cat.noneYet')}")
    await common.show(event, "\n".join(lines), _menu_kb(chat_id))


# ── picking one to work on ───────────────────────────────────────────────────
# `cat:del` is the button the old build wrote into the chat, and Telegram replays updates
# queued while the container was down. It lands on the same picker in delete mode.
@router.callback_query(F.data == "cat:del")
@router.callback_query(F.data.startswith("catpick:"))
async def pick_list(cb: CallbackQuery) -> None:
    """`catpick:<edit|del>:<page>` — one paged picker, two destinations.

    The delete list used to stop at 25 buttons and say nothing about the rest, so a category
    created after the twenty-fifth could not be deleted from the bot at all.
    """
    await common.ack(cb)
    if not await common.gate(cb):
        return
    chat_id = common.chat_id_of(cb)
    parts = (cb.data or "").split(":")
    if parts[0] == "catpick":
        mode = parts[1] if len(parts) > 1 and parts[1] in ("edit", "del") else "edit"
    else:
        mode = "del"                       # the legacy `cat:del` button
    page = _id_at(cb.data, 2) or 0

    roots = await _fetch_roots(cb)
    if roots is None:
        return
    rows = _flatten(roots)
    if not rows:
        await common.show(cb, t(chat_id, "cat.noneYet"), _back_kb(chat_id))
        return

    pages = max(1, -(-len(rows) // _PAGE))  # ceil
    page = min(max(page, 0), pages - 1)
    window = rows[page * _PAGE:(page + 1) * _PAGE]

    target = "catone:" if mode == "edit" else "catdel:"
    items = []
    for row, parent in window:
        # Button text is not HTML-parsed, so it is never esc()'d — that would show a literal
        # &amp; to the owner. The dash marks a child, since two-wide rows lose indentation.
        name = str(cat_name(chat_id, row))[:24]
        items.append((f"– {name}" if parent else name, f"{target}{row['id']}"))

    kb_rows = ui.grid(items, 2)
    if pages > 1:
        # A lone "1/1" is noise; the pager earns its row only when there is somewhere to go.
        kb_rows.append(ui.pager(chat_id, page, pages, f"catpick:{mode}:"))
    kb_rows.append(ui.nav(chat_id, back="cat:list", menu=True))
    head = "cat.pickToEdit" if mode == "edit" else "cat.pickToDelete"
    await common.show(cb, t(chat_id, head), ikb(kb_rows))


# ── one category ─────────────────────────────────────────────────────────────
def _detail_screen(chat_id: int, row: dict,
                   parent: dict | None) -> tuple[str, InlineKeyboardMarkup]:
    cid = row["id"]
    lines = [
        t(chat_id, "cat.detailTitle", name=esc(cat_name(chat_id, row))),
        "",
        f"{t(chat_id, 'cat.labelName')}: {esc(row.get('name') or '—')}",
        f"{t(chat_id, 'cat.labelNameUz')}: {esc(row.get('nameUz') or '—')}",
        f"{t(chat_id, 'cat.labelType')}: {_type_label(chat_id, row.get('type'))}",
    ]
    if parent is not None:
        lines.append(t(chat_id, "cat.inside", name=esc(cat_name(chat_id, parent))))
    else:
        lines.append(t(chat_id, "cat.topLevel"))
    children = row.get("children") or []
    if children:
        lines.append(t(chat_id, "cat.children", n=len(children)))
    bonus = bool(row.get("bonusIncome"))
    if row.get("type") in _BONUS_TYPES:
        lines.append(t(chat_id, "cat.bonusOn" if bonus else "cat.bonusOff"))

    kb_rows = [[(t(chat_id, "cat.editNameBtn"), f"catname:{cid}"),
                (t(chat_id, "cat.editNameUzBtn"), f"catuz:{cid}")]]
    if row.get("type") in _BONUS_TYPES:
        kb_rows.append([(t(chat_id, "cat.bonusOffBtn" if bonus else "cat.bonusOnBtn"),
                         f"catbonus:{cid}")])
    kb_rows.append([(t(chat_id, "common.delete"), f"catdel:{cid}")])
    kb_rows.append(ui.nav(chat_id, back="catpick:edit:0", menu=True))
    return "\n".join(lines), ikb(kb_rows)


async def _render_detail(event, cid: int, prefix: str = "") -> None:
    chat_id = common.chat_id_of(event)
    roots = await _fetch_roots(event)
    if roots is None:
        return
    row, parent = _find(roots, cid)
    if row is None:
        await common.show(event, t(chat_id, "cat.gone"), _back_kb(chat_id))
        return
    text, kb = _detail_screen(chat_id, row, parent)
    await common.show(event, f"{prefix}\n\n{text}" if prefix else text, kb)


@router.callback_query(F.data.startswith("catone:"))
async def detail(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    if not await common.gate(cb):
        return
    chat_id = common.chat_id_of(cb)
    cid = _id_at(cb.data, 1)
    if cid is None:
        await common.show(cb, t(chat_id, "cat.gone"), _back_kb(chat_id))
        return
    # Opening a category ends any edit that was open on another one.
    await state.clear()
    await _render_detail(cb, cid)


# ── editing a category ───────────────────────────────────────────────────────
def _cat_payload(row: dict) -> dict:
    """Everything `PUT /categories/{id}` would otherwise reset — see the module docstring."""
    return {
        "name": row.get("name"),
        "nameUz": row.get("nameUz"),
        "type": row.get("type"),
        "color": row.get("color"),
        "icon": row.get("icon"),
        "applicableSubType": row.get("applicableSubType"),
        "parentId": row.get("parentId"),
        "kind": row.get("kind"),
        "descriptionLabel": row.get("descriptionLabel"),
        "descriptionRequired": row.get("descriptionRequired"),
        "anonymizes": row.get("anonymizes"),
        "bonusIncome": row.get("bonusIncome"),
    }


async def _edit_prompt(cb: CallbackQuery, state: FSMContext, field: str) -> None:
    chat_id = common.chat_id_of(cb)
    cid = _id_at(cb.data, 1)
    if cid is None:
        await common.show(cb, t(chat_id, "cat.gone"), _back_kb(chat_id))
        return
    roots = await _fetch_roots(cb)
    if roots is None:
        return
    row, _parent = _find(roots, cid)
    if row is None:
        await common.show(cb, t(chat_id, "cat.gone"), _back_kb(chat_id))
        return
    label = t(chat_id, "cat.labelName" if field == "name" else "cat.labelNameUz")
    await state.clear()
    await state.set_state(CatEdit.name)
    await state.update_data(ct_id=cid, ct_field=field, ct_row=row)
    body = t(chat_id, "cat.editPrompt", field=label, current=esc(row.get(field) or "—"))
    if field == "nameUz":
        # The backend treats a blank nameUz as "clear it", and Telegram cannot send an empty
        # message — so the screen has to name the sentinel that means the same thing.
        body = f"{body}\n{t(chat_id, 'cat.clearHint')}"
    await common.show(cb, body,
                      ikb([ui.nav(chat_id, back=f"catone:{cid}", cancel="cat:list")]))


@router.callback_query(F.data.startswith("catname:"))
async def edit_name(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    if not await common.gate(cb):
        return
    await _edit_prompt(cb, state, "name")


@router.callback_query(F.data.startswith("catuz:"))
async def edit_name_uz(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    if not await common.gate(cb):
        return
    await _edit_prompt(cb, state, "nameUz")


@router.message(StateFilter(CatEdit.name))
async def edit_typed(message: Message, state: FSMContext) -> None:
    chat_id = message.chat.id
    d = await state.get_data()
    cid, field, row = d.get("ct_id"), d.get("ct_field"), d.get("ct_row")
    if not isinstance(cid, int) or field not in ("name", "nameUz") or not isinstance(row, dict):
        await state.clear()
        await message.answer(t(chat_id, "cat.expired"), reply_markup=_back_kb(chat_id))
        return
    raw = (message.text or "").strip()
    if field == "nameUz" and raw in ("-", "—"):
        value = None                       # blank clears it; display falls back to `name`
    elif not raw:
        # Stay in the state: the owner is one keystroke from a valid answer, and dropping
        # them back to the category would mean re-opening two screens to try again.
        await message.answer(t(chat_id, "cat.emptyValue"))
        return
    else:
        value = raw
    if not await common.gate(message):
        await state.clear()
        return
    payload = _cat_payload(row)
    payload[field] = value
    await _save_cat(message, state, chat_id, cid, payload, back=f"catone:{cid}")


async def _save_cat(event, state: FSMContext, chat_id: int, cid: int,
                    payload: dict, back: str) -> None:
    """PUT the whole category, then show it as it now stands."""
    await common.begin_write(event, chat_id)
    try:
        await api.request(chat_id, "PUT", f"/categories/{cid}", json=payload)
    except api.NeedsLogin:
        await state.clear()
        await common.show(event, t(chat_id, "common.sessionExpired"), keyboards.login_kb(chat_id))
        return
    except api.Unreachable:
        await common.show(event, t(chat_id, "common.serverUnreachable"), _back_kb(chat_id))
        return
    except api.ApiError as exc:
        if exc.status == 404:
            await state.clear()
            await common.show(event, t(chat_id, "cat.gone"), _back_kb(chat_id))
            return
        # "Category 'Food' already exists in this scope" is the common one, and it is worth
        # more than a generic failure — but `begin_write` has taken the keyboard away, so the
        # way back has to travel with it.
        await common.show(event, f"❌ {esc(exc.message)}",
                          ikb([[(t(chat_id, "common.back"), back)]]))
        return
    except Exception:  # noqa: BLE001
        log.exception("PUT /categories/%s failed for chat %s", cid, chat_id)
        await common.show(event, t(chat_id, "cat.saveError"),
                          ikb([[(t(chat_id, "common.back"), back)]]))
        return
    await state.clear()
    # Re-read rather than render the PUT's own body: the detail screen names the parent, and
    # only the tree carries it.
    await _render_detail(event, cid, prefix=t(chat_id, "cat.saved"))


@router.callback_query(F.data.startswith("catbonus:"))
async def toggle_bonus(cb: CallbackQuery, state: FSMContext) -> None:
    """Flip `bonusIncome`. One tap, because the create flow asks the same question once and
    a wrong answer has no other way back."""
    await common.ack(cb)
    if not await common.gate(cb):
        return
    chat_id = common.chat_id_of(cb)
    cid = _id_at(cb.data, 1)
    if cid is None:
        await common.show(cb, t(chat_id, "cat.gone"), _back_kb(chat_id))
        return
    roots = await _fetch_roots(cb)
    if roots is None:
        return
    row, _parent = _find(roots, cid)
    if row is None:
        await common.show(cb, t(chat_id, "cat.gone"), _back_kb(chat_id))
        return
    payload = _cat_payload(row)
    payload["bonusIncome"] = not bool(row.get("bonusIncome"))
    await _save_cat(cb, state, chat_id, cid, payload, back=f"catone:{cid}")


# ── deleting a category ──────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("catdel:"))
async def del_confirm(cb: CallbackQuery) -> None:
    await common.ack(cb)
    if not await common.gate(cb):
        return
    chat_id = common.chat_id_of(cb)
    cid = _id_at(cb.data, 1)
    if cid is None:
        await common.show(cb, t(chat_id, "cat.gone"), _back_kb(chat_id))
        return
    roots = await _fetch_roots(cb)
    if roots is None:
        return
    row, _parent = _find(roots, cid)
    if row is None:
        await common.show(cb, t(chat_id, "cat.gone"), _back_kb(chat_id))
        return
    await common.show(
        cb, t(chat_id, "cat.deleteConfirm", name=esc(cat_name(chat_id, row))),
        ikb([ui.confirm_row(chat_id, f"catdelok:{cid}", f"catone:{cid}", destructive=True)]))


@router.callback_query(F.data.startswith("catdelok:"))
async def del_do(cb: CallbackQuery) -> None:
    await common.ack(cb)
    if not await common.gate(cb):
        return
    chat_id = common.chat_id_of(cb)
    cid = _id_at(cb.data, 1)
    if cid is None:
        await common.show(cb, t(chat_id, "cat.gone"), _back_kb(chat_id))
        return
    await common.begin_write(cb, chat_id)
    try:
        await api.request(chat_id, "DELETE", f"/categories/{cid}")
    except api.NeedsLogin:
        await common.show(cb, t(chat_id, "common.sessionExpired"), keyboards.login_kb(chat_id))
        return
    except api.Unreachable:
        await common.show(cb, t(chat_id, "common.serverUnreachable"), _back_kb(chat_id))
        return
    except api.ApiError as exc:
        # 404 means it is already gone — the second tap of a double-tap, or an update replayed
        # after a restart. The end state is the one that was asked for, so show it.
        if exc.status != 404:
            await common.show(cb, f"❌ {esc(exc.message)}", _back_kb(chat_id))
            return
    except Exception:  # noqa: BLE001
        log.exception("DELETE /categories/%s failed for chat %s", cid, chat_id)
        await common.show(cb, t(chat_id, "cat.deleteError"), _back_kb(chat_id))
        return
    await _render(cb, prefix=t(chat_id, "cat.deleted"))


# ── creating a category ──────────────────────────────────────────────────────
@router.callback_query(F.data == "catcancel")
async def add_cancel(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    chat_id = common.chat_id_of(cb)
    await state.clear()
    await common.show(cb, t(chat_id, "common.cancelled"), _back_kb(chat_id))


@router.callback_query(F.data == "cat:add")
async def add_entry(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    if not await common.gate(cb):
        return
    chat_id = common.chat_id_of(cb)
    # Clear FIRST, then open a fresh payload. See the module docstring: this is the line whose
    # absence let an abandoned sub-category flow choose the parent of the next root category.
    await state.clear()
    await state.set_state(CatCreate.mode)
    await state.update_data(c_new={})
    await common.show(cb, t(chat_id, "cat.newCategory"), ikb([
        [(t(chat_id, "cat.rootCategory"), "cmode:root"),
         (t(chat_id, "cat.subCategory"), "cmode:sub")],
        ui.nav(chat_id, back="cat:list", cancel="catcancel"),
    ]))


async def _put(state: FSMContext, **values) -> dict:
    """Merge answers into `c_new` — the create flow's own bag, never the shared one."""
    d = await state.get_data()
    new = dict(d.get("c_new") or {})
    new.update(values)
    await state.update_data(c_new=new)
    return new


@router.callback_query(StateFilter(CatCreate.mode), F.data.startswith("cmode:"))
async def add_mode(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    if cb.data == "cmode:root":
        await _ask_root_name(cb, state)
    elif cb.data == "cmode:sub":
        await _ask_parent(cb, state)
    else:
        await _expired(cb, state)


async def _ask_root_name(event, state: FSMContext) -> None:
    chat_id = common.chat_id_of(event)
    await state.set_state(CatCreate.root_name)
    await common.show(event, t(chat_id, "cat.sendName"),
                      ikb([ui.nav(chat_id, back="cat:add", cancel="catcancel")]))


async def _ask_parent(event, state: FSMContext) -> None:
    chat_id = common.chat_id_of(event)
    roots = await _fetch_roots(event)
    if roots is None:
        return
    if not roots:
        await state.clear()
        await common.show(event, t(chat_id, "cat.noRootsYet"), _back_kb(chat_id))
        return
    await state.set_state(CatCreate.parent)
    items = [(f"{_TYPE_EMOJI.get(r.get('type'), '•')} {str(cat_name(chat_id, r))[:20]}",
              f"cparent:{r['id']}")
             for r in roots if r.get("id") is not None]
    rows = ui.grid(items, 2)
    rows.append(ui.nav(chat_id, back="cat:add", cancel="catcancel"))
    await common.show(event, t(chat_id, "cat.pickParent"), ikb(rows))


@router.callback_query(StateFilter(CatCreate.parent), F.data.startswith("cparent:"))
async def add_parent(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    chat_id = common.chat_id_of(cb)
    pid = _id_at(cb.data, 1)
    roots = await _fetch_roots(cb)
    if roots is None:
        return
    parent = next((r for r in roots if r.get("id") == pid), None)
    if parent is None:
        await state.clear()
        await common.show(cb, t(chat_id, "cat.parentGone"), _back_kb(chat_id))
        return
    # A sub-category cannot contradict its parent's type — the picker is the type choice.
    await _put(state, parentId=pid, type=parent.get("type"),
               parentName=cat_name(chat_id, parent))
    await _ask_sub_name(cb, state)


async def _ask_sub_name(event, state: FSMContext) -> None:
    chat_id = common.chat_id_of(event)
    d = await state.get_data()
    new = d.get("c_new") or {}
    if not new.get("parentId"):
        await _expired(event, state)
        return
    await state.set_state(CatCreate.sub_name)
    await common.show(event, t(chat_id, "cat.parentHeader", name=esc(new.get("parentName") or "—")),
                      ikb([ui.nav(chat_id, back="cback:parent", cancel="catcancel")]))


@router.message(StateFilter(CatCreate.root_name))
async def add_root_name(message: Message, state: FSMContext) -> None:
    chat_id = message.chat.id
    name = (message.text or "").strip()
    if not name:
        await message.answer(t(chat_id, "cat.emptyValue"))
        return
    await _put(state, name=name)
    await _ask_root_type(message, state)


async def _ask_root_type(event, state: FSMContext) -> None:
    chat_id = common.chat_id_of(event)
    await state.set_state(CatCreate.root_type)
    await common.show(event, t(chat_id, "cat.pickType"), ikb([
        [(t(chat_id, "cat.typeIncome"), "ctype:INCOME"),
         (t(chat_id, "cat.typeExpense"), "ctype:EXPENSE")],
        [(t(chat_id, "cat.typeBoth"), "ctype:BOTH")],
        ui.nav(chat_id, back="cback:name", cancel="catcancel"),
    ]))


@router.callback_query(StateFilter(CatCreate.root_type), F.data.startswith("ctype:"))
async def add_root_type(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    typ = (cb.data or "").split(":", 1)[1]
    if typ not in _TYPE_KEY:
        await _expired(cb, state)
        return
    await _put(state, type=typ)
    if typ in _BONUS_TYPES:
        await _ask_bonus(cb, state, back="cback:type")
    else:
        await _finish(cb, state)


@router.message(StateFilter(CatCreate.sub_name))
async def add_sub_name(message: Message, state: FSMContext) -> None:
    chat_id = message.chat.id
    name = (message.text or "").strip()
    if not name:
        await message.answer(t(chat_id, "cat.emptyValue"))
        return
    new = await _put(state, name=name)
    if new.get("type") in _BONUS_TYPES:
        await _ask_bonus(message, state, back="cback:subname")
    else:
        await _finish(message, state)


async def _ask_bonus(event, state: FSMContext, back: str) -> None:
    chat_id = common.chat_id_of(event)
    await state.set_state(CatCreate.bonus)
    await common.show(event, t(chat_id, "cat.bonusQuestion"), ikb([
        [(t(chat_id, "cat.bonusYes"), "cbonus:yes"), (t(chat_id, "cat.bonusNo"), "cbonus:no")],
        ui.nav(chat_id, back=back, cancel="catcancel"),
    ]))


@router.callback_query(StateFilter(CatCreate.bonus), F.data.startswith("cbonus:"))
async def add_bonus(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    await _put(state, bonusIncome=(cb.data or "").endswith(":yes"))
    await _finish(cb, state)


@router.callback_query(F.data.startswith("cback:"))
async def add_back(cb: CallbackQuery, state: FSMContext) -> None:
    """Back inside the create flow — one step, not out of the whole thing.

    Every step is re-entered through the same function that first rendered it, so a Back can
    never leave the FSM pointing at a screen that is no longer on the phone.
    """
    await common.ack(cb)
    if not await common.gate(cb):
        return
    d = await state.get_data()
    if not isinstance(d.get("c_new"), dict):
        await _expired(cb, state)
        return
    step = (cb.data or "").split(":", 1)[1]
    if step == "name":
        await _ask_root_name(cb, state)
    elif step == "type":
        await _ask_root_type(cb, state)
    elif step == "parent":
        await _ask_parent(cb, state)
    elif step == "subname":
        await _ask_sub_name(cb, state)
    else:
        await _expired(cb, state)


async def _finish(event, state: FSMContext) -> None:
    chat_id = common.chat_id_of(event)
    d = await state.get_data()
    new = d.get("c_new") or {}
    if not new.get("name") or not new.get("type"):
        await _expired(event, state)
        return
    # Built key by key from this run's own dict. Nothing that was not answered during this
    # flow can reach the request — which is the whole point of `c_new`.
    payload = {"name": new["name"], "type": new["type"]}
    if new.get("parentId") is not None:
        payload["parentId"] = new["parentId"]
    if "bonusIncome" in new:
        payload["bonusIncome"] = new["bonusIncome"]

    await common.begin_write(event, chat_id)
    try:
        await api.request(chat_id, "POST", "/categories", json=payload)
    except api.NeedsLogin:
        await state.clear()
        await common.show(event, t(chat_id, "common.sessionExpired"), keyboards.login_kb(chat_id))
        return
    except api.Unreachable:
        await state.clear()
        await common.show(event, t(chat_id, "common.serverUnreachable"), _back_kb(chat_id))
        return
    except api.ApiError as exc:
        await state.clear()
        await common.show(event, f"❌ {esc(exc.message)}", _back_kb(chat_id))
        return
    except Exception:  # noqa: BLE001
        log.exception("POST /categories failed for chat %s", chat_id)
        await state.clear()
        await common.show(event, t(chat_id, "cat.saveError"), _back_kb(chat_id))
        return
    await state.clear()
    await common.show(event, t(chat_id, "cat.created", name=esc(payload["name"])),
                      _back_kb(chat_id))


async def _expired(event, state: FSMContext) -> None:
    chat_id = common.chat_id_of(event)
    await state.clear()
    await common.show(event, t(chat_id, "cat.expired"), _back_kb(chat_id))


# ── stateless fallbacks ──────────────────────────────────────────────────────
# Registered last, so the state-filtered handlers above always win. Storage is MemoryStorage:
# every flow in this file is gone after a restart, and `drop_pending_updates` is off, so a
# tap made while the container was down arrives with no state at all. Without these, that tap
# matches nothing, the spinner never stops and the owner is left staring at a dead screen.
@router.callback_query(F.data.startswith("cmode:"))
@router.callback_query(F.data.startswith("ctype:"))
@router.callback_query(F.data.startswith("cparent:"))
@router.callback_query(F.data.startswith("cbonus:"))
async def flow_expired(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    await _expired(cb, state)
