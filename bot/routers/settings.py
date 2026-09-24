"""⚙️ Settings — the web's Settings page: language, the monthly income, Categories, the month
Tracker counts from (read-only), the Danger Zone, help and lock.

The income is here because the backend refuses every money write until it is set, and the guard
that says so (on recording) needs a way through that works from the phone.

**Categories** (the web's Categories page): Expense / Income lists, one category's screen with its
sub-categories, Add (name in English, an optional Uzbek name, the type), Rename, Add sub-category
(it inherits its parent's type, colour and settings, as on the web) and Delete (asks first;
transactions lose the link and sub-categories become top-level — the server's rule).

**Danger Zone** — "Clear everything" (`POST /settings/reset`) asks twice, then for the account
password, which is deleted from the chat as soon as it is read, as the login does. A wrong password
keeps the prompt open; success wipes the account, so the session is locked and the owner is sent to
sign up again.

Callbacks owned here: `set`, `set:*`, `lang:*`, `cat`, `cat:*`.
"""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from .. import api, common, keyboards, ui
from ..i18n import cat_name, get_lang, set_lang, t
from ..keyboards import esc, ikb
from ..money import fmt_money, parse_amount
from ..session import store
from ..states import Settings
from . import history, home

router = Router(name="settings")
log = logging.getLogger(__name__)

_NAME_LIMIT = 100
_DEFAULT_COLOR = "#6366f1"  # the web form's default
TYPES = ("EXPENSE", "INCOME")


class CatFlow(StatesGroup):
    """Adding or renaming a category: the English name, then the Uzbek one."""
    name = State()
    name_uz = State()


class Danger(StatesGroup):
    """Clear everything: the one step whose message (the password) is deleted on receipt."""
    password = State()


def _error(chat_id: int, exc: api.ApiError) -> str:
    return t(chat_id, "common.serverUnreachable") if isinstance(exc, api.Unreachable) else f"❌ {esc(exc.message)}"


# ── The screen ──────────────────────────────────────────────────────────────
async def show_settings(event, notice: str | None = None) -> None:
    chat_id = common.chat_id_of(event)
    try:
        s = await api.request(chat_id, "GET", "/settings") or {}
    except Exception as exc:  # noqa: BLE001
        await home.report(event, exc)
        return
    income = home.n(s.get("monthlyStableIncome"))
    other = "uz" if get_lang(chat_id) == "en" else "en"
    lines = [notice, ""] if notice else []
    lines += [t(chat_id, "settings.title"), "",
              t(chat_id, "settings.income", amount=fmt_money(income) if income else t(chat_id, "settings.notSet"))]
    start = str(s.get("allocationTrackingStartMonth") or "")[:7]
    lines.append(t(chat_id, "settings.countingFrom", month=history.month_label(chat_id, start))
                 if history.valid_month(start) else t(chat_id, "settings.countingNotSet"))
    await common.show(event, "\n".join(lines), ikb([
        [(t(chat_id, "settings.langBtn"), f"lang:{other}"), (t(chat_id, "settings.incomeBtn"), "set:income")],
        [(t(chat_id, "settings.categoriesBtn"), "cat"), (t(chat_id, "settings.dangerBtn"), "set:danger")],
        [(t(chat_id, "settings.helpBtn"), "sys:help"), (t(chat_id, "settings.lockBtn"), "lock")],
        ui.nav(chat_id, back="more", home=True),
    ]))


@router.message(Command("settings"))
async def settings_cmd(message: Message, state: FSMContext) -> None:
    await state.clear()
    if not await common.gate(message):
        return
    await show_settings(message)


@router.callback_query(F.data == "set")
async def on_settings(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    await state.clear()
    if not await common.gate(cb):
        return
    await show_settings(cb)


# Ungated: a logged-out owner who cannot read the login prompt is exactly who needs to switch.
@router.callback_query(F.data.startswith("lang:"))
async def on_lang(cb: CallbackQuery) -> None:
    chat_id = common.chat_id_of(cb)
    choice = cb.data.split(":", 1)[1]
    if choice not in ("en", "uz"):
        await common.ack(cb)
        return
    set_lang(chat_id, choice)
    await common.ack(cb, t(chat_id, "lang.changed"))
    if store.is_active(chat_id):
        await show_settings(cb)
    else:
        await common.show(cb, t(chat_id, "auth.welcome"), keyboards.login_kb(chat_id))


# ── Monthly income ──────────────────────────────────────────────────────────
@router.callback_query(F.data == "set:income")
async def on_income(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    if not await common.gate(cb):
        return
    chat_id = common.chat_id_of(cb)
    await state.set_state(Settings.income)
    await common.show(cb, f"{t(chat_id, 'settings.incomeTitle')}\n\n{t(chat_id, 'settings.incomeAsk')}",
                      ikb([ui.nav(chat_id, back="set", cancel="home")]))


@router.message(StateFilter(Settings.income))
async def on_income_typed(message: Message, state: FSMContext) -> None:
    chat_id = message.chat.id
    amount = parse_amount(message.text)
    if amount is None:
        await message.answer(t(chat_id, "settings.incomeAsk"))
        return
    if not await common.gate(message):
        await state.clear()
        return
    try:
        # Only the one field: SettingsService.update writes solely what the request carries.
        await api.request(chat_id, "PUT", "/settings", json={"monthlyStableIncome": amount})
    except api.NeedsLogin:
        await state.clear()
        await common.show(message, t(chat_id, "common.sessionExpired"), keyboards.login_kb(chat_id))
        return
    except api.ApiError as exc:
        # Still in the state, so the next number typed is another attempt.
        await message.answer(_error(chat_id, exc))
        return
    await state.clear()
    await home.show_home(message, t(chat_id, "settings.incomeSaved", amount=fmt_money(amount)))


# ── Categories ──────────────────────────────────────────────────────────────
async def _tree(event) -> list[dict] | None:
    """Every top-level category with its children; None after reporting a failure."""
    try:
        cats = await api.request(common.chat_id_of(event), "GET", "/categories") or []
    except Exception as exc:  # noqa: BLE001
        await home.report(event, exc)
        return None
    return [c for c in cats if isinstance(c, dict)]


def _find(roots: list[dict], cat_id: int) -> tuple[dict | None, dict | None]:
    """(the category, its parent or None)."""
    for root in roots:
        if root.get("id") == cat_id:
            return root, None
        for child in root.get("children") or []:
            if child.get("id") == cat_id:
                return child, root
    return None, None


def _type_word(chat_id: int, cat_type: str) -> str:
    return t(chat_id, "settings.cat.typeIncome" if cat_type == "INCOME" else "settings.cat.typeExpense")


def _id_of(data: str) -> int | None:
    raw = data.split(":")[2] if data.count(":") >= 2 else ""
    return int(raw) if raw.isdigit() else None


async def show_categories(event, notice: str | None = None) -> None:
    chat_id = common.chat_id_of(event)
    roots = await _tree(event)
    if roots is None:
        return
    count = {k: sum(1 for r in roots if r.get("type") == k) for k in TYPES}
    lines = [notice, ""] if notice else []
    lines += [t(chat_id, "settings.cat.title"), "", t(chat_id, "settings.cat.intro"),
              t(chat_id, "settings.cat.count", expense=count["EXPENSE"], income=count["INCOME"])]
    await common.show(event, "\n".join(lines), ikb([
        [(t(chat_id, "settings.cat.expenseBtn"), "cat:l:EXPENSE"), (t(chat_id, "settings.cat.incomeBtn"), "cat:l:INCOME")],
        [(t(chat_id, "settings.cat.addBtn"), "cat:n")],
        ui.nav(chat_id, back="set", home=True),
    ]))


async def show_category_list(event, cat_type: str, notice: str | None = None) -> None:
    chat_id = common.chat_id_of(event)
    roots = await _tree(event)
    if roots is None:
        return
    mine = [r for r in roots if r.get("type") == cat_type]
    lines = [notice, ""] if notice else []
    lines += [t(chat_id, "settings.cat.incomeTitle" if cat_type == "INCOME" else "settings.cat.expenseTitle"), ""]
    if not mine:
        lines.append(t(chat_id, "settings.cat.none"))
    for r in mine:
        subs = len(r.get("children") or [])
        lines.append(t(chat_id, "settings.cat.rowSubs", name=esc(cat_name(chat_id, r)), count=subs) if subs
                     else t(chat_id, "settings.cat.row", name=esc(cat_name(chat_id, r))))
    buttons = [(home.clip(cat_name(chat_id, r)), f"cat:o:{r['id']}") for r in mine if r.get("id") is not None]
    await common.show(event, "\n".join(lines), ikb([
        *ui.grid(buttons, 2),
        [(t(chat_id, "settings.cat.addBtn"), f"cat:n:{cat_type}")],
        ui.nav(chat_id, back="cat", home=True),
    ]))


async def show_category(event, cat_id: int, notice: str | None = None) -> None:
    chat_id = common.chat_id_of(event)
    roots = await _tree(event)
    if roots is None:
        return
    cat, parent = _find(roots, cat_id)
    if cat is None:
        await common.show(event, t(chat_id, "settings.cat.gone"), ikb([ui.nav(chat_id, back="cat", home=True)]))
        return
    lines = [notice, ""] if notice else []
    lines += [f"🏷 <b>{esc(cat_name(chat_id, cat))}</b> · {_type_word(chat_id, cat.get('type'))}"]
    if parent is not None:
        lines.append(t(chat_id, "settings.cat.subOf", name=esc(cat_name(chat_id, parent))))
    lines += ["", t(chat_id, "settings.cat.nameEn", name=esc(cat.get("name") or "—")),
              t(chat_id, "settings.cat.nameUz", name=esc(cat["nameUz"])) if (cat.get("nameUz") or "").strip()
              else t(chat_id, "settings.cat.nameUzNone")]
    rows: list[list[tuple[str, str]]] = []
    if parent is None:
        children = [c for c in cat.get("children") or [] if c.get("id") is not None]
        lines += ["", t(chat_id, "settings.cat.subsTitle")]
        if not children:
            lines.append(t(chat_id, "settings.cat.subsNone"))
        for c in children:
            lines.append(t(chat_id, "settings.cat.row", name=esc(cat_name(chat_id, c))))
        rows += ui.grid([(home.clip(cat_name(chat_id, c)), f"cat:o:{c['id']}") for c in children], 2)
        rows.append([(t(chat_id, "settings.cat.addSubBtn"), f"cat:s:{cat_id}")])
    rows.append([(t(chat_id, "settings.cat.renameBtn"), f"cat:r:{cat_id}"), (t(chat_id, "common.delete"), f"cat:d:{cat_id}")])
    back = f"cat:o:{parent['id']}" if parent is not None else f"cat:l:{cat.get('type') if cat.get('type') in TYPES else 'EXPENSE'}"
    rows.append(ui.nav(chat_id, back=back, home=True))
    await common.show(event, "\n".join(lines), ikb(rows))


async def _open(cb: CallbackQuery, state: FSMContext) -> bool:
    await common.ack(cb)
    if not await common.gate(cb):
        return False
    await state.set_state(None)
    return True


@router.callback_query(F.data == "cat")
async def on_categories(cb: CallbackQuery, state: FSMContext) -> None:
    if await _open(cb, state):
        await show_categories(cb)


@router.callback_query(F.data.startswith("cat:l:"))
async def on_category_list(cb: CallbackQuery, state: FSMContext) -> None:
    if await _open(cb, state):
        cat_type = cb.data.split(":")[2]
        await show_category_list(cb, cat_type if cat_type in TYPES else "EXPENSE")


@router.callback_query(F.data.startswith("cat:o:"))
async def on_category(cb: CallbackQuery, state: FSMContext) -> None:
    if not await _open(cb, state):
        return
    cat_id = _id_of(cb.data)
    if cat_id is None:
        await show_categories(cb)
        return
    await show_category(cb, cat_id)


# Add / add sub-category / rename: the English name, then the Uzbek one.
async def _ask_name(event, state: FSMContext, cf: dict) -> None:
    chat_id = common.chat_id_of(event)
    await state.set_state(CatFlow.name)
    await state.update_data(cf=cf)
    rows = []
    if cf.get("mode") == "edit":
        rows.append([(home.clip(t(chat_id, "common.keep", value=cf.get("oldName") or "")), "cat:k")])
    rows.append(ui.nav(chat_id, cancel=cf.get("back") or "cat"))
    await common.show(event, t(chat_id, "settings.cat.askName", title=esc(cf.get("title") or "")), ikb(rows))


async def _ask_name_uz(event, state: FSMContext, cf: dict) -> None:
    chat_id = common.chat_id_of(event)
    await state.set_state(CatFlow.name_uz)
    await state.update_data(cf=cf)
    rows = []
    old = (cf.get("oldNameUz") or "").strip()
    if cf.get("mode") == "edit" and old:
        rows.append([(home.clip(t(chat_id, "common.keep", value=old)), "cat:u:=")])
        rows.append([(t(chat_id, "settings.cat.clearUz"), "cat:u:-")])
    else:
        rows.append([(t(chat_id, "common.skip"), "cat:u:-")])
    rows.append(ui.nav(chat_id, cancel=cf.get("back") or "cat"))
    await common.show(event, t(chat_id, "settings.cat.askNameUz", title=esc(cf.get("title") or "")), ikb(rows))


@router.callback_query(F.data == "cat:n")
async def on_add_pick_type(cb: CallbackQuery, state: FSMContext) -> None:
    if not await _open(cb, state):
        return
    chat_id = common.chat_id_of(cb)
    await common.show(cb, t(chat_id, "settings.cat.pickType"), ikb([
        [(t(chat_id, "settings.cat.expenseBtn"), "cat:n:EXPENSE"), (t(chat_id, "settings.cat.incomeBtn"), "cat:n:INCOME")],
        ui.nav(chat_id, back="cat", home=True),
    ]))


@router.callback_query(F.data.startswith("cat:n:"))
async def on_add(cb: CallbackQuery, state: FSMContext) -> None:
    if not await _open(cb, state):
        return
    chat_id = common.chat_id_of(cb)
    cat_type = cb.data.split(":")[2]
    if cat_type not in TYPES:
        cat_type = "EXPENSE"
    await _ask_name(cb, state, {"mode": "new", "type": cat_type, "title": t(chat_id, "settings.cat.addTitle"),
                                "back": f"cat:l:{cat_type}"})


@router.callback_query(F.data.startswith("cat:s:"))
async def on_add_sub(cb: CallbackQuery, state: FSMContext) -> None:
    if not await _open(cb, state):
        return
    chat_id = common.chat_id_of(cb)
    roots = await _tree(cb)
    if roots is None:
        return
    parent, grand = _find(roots, _id_of(cb.data) or -1)
    if parent is None or grand is not None:
        await show_categories(cb)
        return
    await _ask_name(cb, state, {"mode": "sub", "parent": parent,
                                "title": t(chat_id, "settings.cat.addSubTitle", name=cat_name(chat_id, parent)),
                                "back": f"cat:o:{parent['id']}"})


@router.callback_query(F.data.startswith("cat:r:"))
async def on_rename(cb: CallbackQuery, state: FSMContext) -> None:
    if not await _open(cb, state):
        return
    chat_id = common.chat_id_of(cb)
    roots = await _tree(cb)
    if roots is None:
        return
    cat, _ = _find(roots, _id_of(cb.data) or -1)
    if cat is None:
        await show_categories(cb)
        return
    await _ask_name(cb, state, {"mode": "edit", "cat": cat, "oldName": cat.get("name") or "",
                                "oldNameUz": cat.get("nameUz") or "",
                                "title": t(chat_id, "settings.cat.editTitle", name=cat_name(chat_id, cat)),
                                "back": f"cat:o:{cat['id']}"})


@router.callback_query(F.data == "cat:k")
async def on_keep_name(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    if not await common.gate(cb):
        return
    cf = (await state.get_data()).get("cf")
    if not isinstance(cf, dict) or cf.get("mode") != "edit":
        await show_categories(cb)
        return
    await _ask_name_uz(cb, state, dict(cf, name=cf.get("oldName")))


@router.message(StateFilter(CatFlow.name))
async def on_name_typed(message: Message, state: FSMContext) -> None:
    chat_id = common.chat_id_of(message)
    cf = (await state.get_data()).get("cf")
    if not isinstance(cf, dict):
        await state.clear()
        await show_categories(message)
        return
    name = " ".join((message.text or "").split())
    if not name:
        await message.answer(t(chat_id, "settings.cat.askName", title=esc(cf.get("title") or "")))
        return
    if len(name) > _NAME_LIMIT:
        await message.answer(t(chat_id, "settings.cat.tooLong", limit=_NAME_LIMIT))
        return
    await _ask_name_uz(message, state, dict(cf, name=name))


@router.message(StateFilter(CatFlow.name_uz))
async def on_name_uz_typed(message: Message, state: FSMContext) -> None:
    chat_id = common.chat_id_of(message)
    cf = (await state.get_data()).get("cf")
    if not isinstance(cf, dict) or not cf.get("name"):
        await state.clear()
        await show_categories(message)
        return
    name_uz = " ".join((message.text or "").split())
    if len(name_uz) > _NAME_LIMIT:
        await message.answer(t(chat_id, "settings.cat.tooLong", limit=_NAME_LIMIT))
        return
    await _save_category(message, state, dict(cf, nameUz=name_uz))


@router.callback_query(F.data.startswith("cat:u:"))
async def on_name_uz_button(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    if not await common.gate(cb):
        return
    cf = (await state.get_data()).get("cf")
    if not isinstance(cf, dict) or not cf.get("name"):
        await state.clear()
        await show_categories(cb)
        return
    keep = cb.data.endswith("=")
    await _save_category(cb, state, dict(cf, nameUz=(cf.get("oldNameUz") or "") if keep else ""))


def category_payload(cf: dict) -> dict:
    """The web's request for each of the three: a new category, a sub-category (it inherits its
    parent's type, colour and settings), an edit (every other field carried over unchanged)."""
    name, name_uz = cf["name"], cf.get("nameUz") or ""
    if cf["mode"] == "sub":
        p = cf["parent"]
        body = {"name": name, "nameUz": name_uz, "type": p.get("type"), "color": p.get("color") or _DEFAULT_COLOR,
                "applicableSubType": p.get("applicableSubType"), "parentId": p.get("id"),
                "descriptionLabel": p.get("descriptionLabel"), "descriptionRequired": p.get("descriptionRequired")}
    elif cf["mode"] == "edit":
        c = cf["cat"]
        body = {"name": name, "nameUz": name_uz, "type": c.get("type"), "color": c.get("color"),
                "icon": c.get("icon"), "applicableSubType": c.get("applicableSubType"),
                "parentId": c.get("parentId"), "descriptionLabel": c.get("descriptionLabel"),
                "descriptionRequired": c.get("descriptionRequired"), "anonymizes": c.get("anonymizes"),
                "bonusIncome": c.get("bonusIncome")}
    else:
        body = {"name": name, "nameUz": name_uz, "type": cf["type"], "color": _DEFAULT_COLOR}
    return {k: v for k, v in body.items() if v is not None}


async def _save_category(event, state: FSMContext, cf: dict) -> None:
    chat_id = common.chat_id_of(event)
    if not await common.gate(event):
        await state.clear()
        return
    if isinstance(event, CallbackQuery):
        await common.begin_write(event, chat_id)
    try:
        if cf["mode"] == "edit":
            saved = await api.request(chat_id, "PUT", f"/categories/{cf['cat']['id']}", json=category_payload(cf))
        else:
            saved = await api.request(chat_id, "POST", "/categories", json=category_payload(cf))
    except api.NeedsLogin:
        await state.clear()
        await common.show(event, t(chat_id, "common.sessionExpired"), keyboards.login_kb(chat_id))
        return
    except api.ApiError as exc:
        # A clash ("already exists in this scope") is a name problem: ask for the name again.
        await common.show(event, _error(chat_id, exc))
        await _ask_name(event, state, cf)
        return
    await state.clear()
    cat_id = (saved or {}).get("id") if isinstance(saved, dict) else None
    notice = t(chat_id, "settings.cat.saved")
    if cat_id is not None:
        await show_category(event, int(cat_id), notice)
    else:
        await show_categories(event, notice)


# Delete
@router.callback_query(F.data.startswith("cat:d:"))
async def on_delete(cb: CallbackQuery, state: FSMContext) -> None:
    if not await _open(cb, state):
        return
    chat_id = common.chat_id_of(cb)
    roots = await _tree(cb)
    if roots is None:
        return
    cat, _ = _find(roots, _id_of(cb.data) or -1)
    if cat is None:
        await show_categories(cb)
        return
    await common.show(cb, "\n\n".join([t(chat_id, "settings.cat.deleteTitle", name=esc(cat_name(chat_id, cat))),
                                       t(chat_id, "settings.cat.deleteMessage")]), ikb([
        [(t(chat_id, "common.delete"), f"cat:x:{cat['id']}")],
        ui.nav(chat_id, cancel=f"cat:o:{cat['id']}"),
    ]))


@router.callback_query(F.data.startswith("cat:x:"))
async def on_delete_confirmed(cb: CallbackQuery, state: FSMContext) -> None:
    if not await _open(cb, state):
        return
    chat_id = common.chat_id_of(cb)
    cat_id = _id_of(cb.data)
    roots = await _tree(cb)
    if roots is None or cat_id is None:
        return
    cat, parent = _find(roots, cat_id)
    await common.begin_write(cb, chat_id)
    try:
        await api.request(chat_id, "DELETE", f"/categories/{cat_id}")
    except api.NeedsLogin:
        await common.show(cb, t(chat_id, "common.sessionExpired"), keyboards.login_kb(chat_id))
        return
    except api.ApiError as exc:
        if exc.status != 404:
            await common.show(cb, _error(chat_id, exc), ikb([ui.nav(chat_id, back=f"cat:o:{cat_id}", home=True)]))
            return
    notice = t(chat_id, "settings.cat.deleted")
    if parent is not None:
        await show_category(cb, parent["id"], notice)
    elif cat is not None and cat.get("type") in TYPES:
        await show_category_list(cb, cat["type"], notice)
    else:
        await show_categories(cb, notice)


# ── Danger Zone ─────────────────────────────────────────────────────────────
@router.callback_query(F.data == "set:danger")
async def on_danger(cb: CallbackQuery, state: FSMContext) -> None:
    if not await _open(cb, state):
        return
    chat_id = common.chat_id_of(cb)
    await common.show(cb, f"{t(chat_id, 'settings.danger.title')}\n\n{t(chat_id, 'settings.danger.body')}", ikb([
        [(t(chat_id, "settings.danger.clearBtn"), "set:reset")],
        ui.nav(chat_id, back="set", home=True),
    ]))


@router.callback_query(F.data == "set:reset")
async def on_reset(cb: CallbackQuery, state: FSMContext) -> None:
    if not await _open(cb, state):
        return
    chat_id = common.chat_id_of(cb)
    await common.show(cb, f"{t(chat_id, 'settings.danger.confirmTitle')}\n\n{t(chat_id, 'settings.danger.confirmBody')}",
                      ikb([[(t(chat_id, "settings.danger.continueBtn"), "set:resetpw")],
                           ui.nav(chat_id, cancel="set")]))


@router.callback_query(F.data == "set:resetpw")
async def on_reset_password(cb: CallbackQuery, state: FSMContext) -> None:
    if not await _open(cb, state):
        return
    chat_id = common.chat_id_of(cb)
    await state.set_state(Danger.password)
    await common.show(cb, f"{t(chat_id, 'settings.danger.passwordTitle')}\n\n{t(chat_id, 'settings.danger.passwordAsk')}",
                      ikb([ui.nav(chat_id, cancel="set")]))


async def _delete_quietly(message: Message) -> bool:
    """Delete the message the password was typed into. False when it is still in the history."""
    try:
        await message.delete()
    except Exception:  # noqa: BLE001
        # Never log the message itself: it is the password.
        log.warning("Couldn't delete the reset-password message in chat %s.", message.chat.id, exc_info=True)
        return False
    return True


@router.message(StateFilter(Danger.password))
async def on_reset_typed(message: Message, state: FSMContext) -> None:
    chat_id = common.chat_id_of(message)
    password = message.text or ""
    kept = not await _delete_quietly(message) if password else False
    warn = [t(chat_id, "settings.danger.notDeleted")] if kept else []
    retry = ikb([ui.nav(chat_id, cancel="set")])
    if not password:
        await common.show(message, t(chat_id, "settings.danger.passwordAsk"), retry)
        return
    if not await common.gate(message):
        await state.clear()
        return
    await message.answer(t(chat_id, "settings.danger.clearing"))
    try:
        # auth_retry=False: a 401 here is the endpoint's own "Incorrect password.", not a stale token,
        # and a factory reset must never be sent twice.
        await api.request(chat_id, "POST", "/settings/reset", json={"password": password}, auth_retry=False)
    except api.NeedsLogin:
        await state.clear()
        await common.show(message, "\n\n".join([t(chat_id, "common.sessionExpired"), *warn]),
                          keyboards.login_kb(chat_id))
        return
    except api.ApiError as exc:
        reason = t(chat_id, "settings.danger.wrong") if exc.status == 401 else _error(chat_id, exc)
        await common.show(message, "\n\n".join([reason, *warn]), retry)  # still in the state: type it again
        return
    await state.clear()
    # The account and its tokens are gone; the next step is signing up again.
    store.lock(chat_id)
    await common.show(message, "\n\n".join([t(chat_id, "settings.danger.done"), *warn]), keyboards.login_kb(chat_id))
