"""Generic field-stepper create wizard (shared by Finance create + Cards create).

A caller starts it with `await wizard.start(event, state, spec)`; the spec drives the steps
and the final POST. Spec is stored in FSM memory (objects kept as-is, no serialization).

spec = {title, endpoint, back (callback_data), success, auto_currency, fields:[{key,label,kind,...}]}
kinds: text(+regex/regex_msg) | amount(>0) | number(any) | int(+min/max) | date(+today) | month | choice(choices=[(value,label)])
"""
import datetime as dt
import re

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from .. import api, common, keyboards
from ..keyboards import esc, ikb
from ..session import store
from ..states import Wizard

router = Router()


def _today() -> str:
    return dt.date.today().isoformat()


def _amount_pos(text: str):
    t = (text or "").strip().replace(" ", "").replace(",", "")
    try:
        v = float(t)
    except ValueError:
        return None
    return v if v > 0 else None


def _number(text: str):
    t = (text or "").strip().replace(" ", "").replace(",", "")
    try:
        return float(t)
    except ValueError:
        return None


async def start(event, state: FSMContext, spec: dict) -> None:
    await state.set_state(Wizard.step)
    await state.update_data(w_spec=spec, w_index=0, w_data={})
    await _prompt(event, state)


async def _prompt(event, state: FSMContext) -> None:
    d = await state.get_data()
    spec, idx = d["w_spec"], d["w_index"]
    field = spec["fields"][idx]
    cur = store.currency(common.chat_id_of(event))
    head = f"➕ <b>{spec['title']}</b> · step {idx + 1}/{len(spec['fields'])}"
    kind = field["kind"]
    rows = []
    if kind == "amount":
        body = f"Send <b>{field['label']}</b> in {cur}:"
    elif kind == "number":
        body = f"Send <b>{field['label']}</b> in {cur} (0 or more):"
    elif kind == "int":
        body = f"Send <b>{field['label']}</b> (a number):"
    elif kind == "date":
        body = f"Send <b>{field['label']}</b> as YYYY-MM-DD:"
        if field.get("today"):
            rows.append([("📅 Today", "wtoday")])
    elif kind == "month":
        body = f"Send <b>{field['label']}</b> as YYYY-MM:"
    elif kind == "choice":
        body = f"Pick <b>{field['label']}</b>:"
        for value, label in field["choices"]:
            rows.append([(label, f"wchoice:{value}")])
    else:
        body = f"Send <b>{field['label']}</b>:"
    if not field.get("required"):
        rows.append([("⏭ Skip", "wskip")])
    rows.append([("✖️ Cancel", "wcancel")])
    await common.show(event, f"{head}\n{body}", ikb(rows))


async def _set(state: FSMContext, key: str, value) -> None:
    d = await state.get_data()
    data = dict(d.get("w_data", {}))
    data[key] = value
    await state.update_data(w_data=data)


@router.callback_query(StateFilter(Wizard.step), F.data == "wskip")
async def on_skip(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    await _advance(cb, state)


@router.callback_query(StateFilter(Wizard.step), F.data == "wtoday")
async def on_today(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    d = await state.get_data()
    await _set(state, d["w_spec"]["fields"][d["w_index"]]["key"], _today())
    await _advance(cb, state)


@router.callback_query(StateFilter(Wizard.step), F.data.startswith("wchoice:"))
async def on_choice(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    d = await state.get_data()
    await _set(state, d["w_spec"]["fields"][d["w_index"]]["key"], cb.data.split(":", 1)[1])
    await _advance(cb, state)


@router.message(StateFilter(Wizard.step))
async def on_text(message: Message, state: FSMContext) -> None:
    d = await state.get_data()
    field = d["w_spec"]["fields"][d["w_index"]]
    raw = (message.text or "").strip()
    kind = field["kind"]
    if kind == "amount":
        val = _amount_pos(raw)
        if val is None:
            await message.answer("Send a positive number.")
            return
    elif kind == "number":
        val = _number(raw)
        if val is None:
            await message.answer("Send a number (e.g. 0 or 250000).")
            return
    elif kind == "int":
        try:
            val = int(raw)
        except ValueError:
            await message.answer("Send a whole number.")
            return
        if (field.get("min") is not None and val < field["min"]) or \
           (field.get("max") is not None and val > field["max"]):
            await message.answer(f"Enter a number between {field.get('min')} and {field.get('max')}.")
            return
    elif kind == "date":
        try:
            dt.date.fromisoformat(raw)
        except ValueError:
            await message.answer("Use the format YYYY-MM-DD.")
            return
        val = raw
    elif kind == "month":
        try:
            dt.date.fromisoformat(raw + "-01")
        except ValueError:
            await message.answer("Use the format YYYY-MM.")
            return
        val = raw + "-01"
    elif kind == "choice":
        await message.answer("Please tap one of the buttons.")
        return
    else:
        if field.get("regex") and not re.match(field["regex"], raw):
            await message.answer(field.get("regex_msg", "Invalid format."))
            return
        val = raw
    await _set(state, field["key"], val)
    await _advance(message, state)


async def _advance(event, state: FSMContext) -> None:
    d = await state.get_data()
    idx = d["w_index"] + 1
    await state.update_data(w_index=idx)
    if idx < len(d["w_spec"]["fields"]):
        await _prompt(event, state)
    else:
        await _finish(event, state)


async def _finish(event, state: FSMContext) -> None:
    chat_id = common.chat_id_of(event)
    d = await state.get_data()
    spec = d["w_spec"]
    payload = dict(d.get("w_data", {}))
    if spec.get("fixed"):
        payload.update(spec["fixed"])  # constant fields the user isn't prompted for (e.g. savingsGoal=true)
    if spec.get("auto_currency"):
        payload["currency"] = store.currency(chat_id)
    back_kb = ikb([[("⬅️ Back", spec["back"])]])
    try:
        await api.request(chat_id, "POST", spec["endpoint"], json=payload)
    except api.NeedsLogin:
        await state.clear()
        await common.show(event, "🔒 Session expired. Please log in.", keyboards.login_kb())
        return
    except api.ApiError as exc:
        await state.clear()
        await common.show(event, f"❌ {esc(exc.message)}", back_kb)
        return
    except Exception:  # noqa: BLE001
        await state.clear()
        await common.show(event, "❌ Couldn't reach the server.", back_kb)
        return
    await state.clear()
    await common.show(event, f"✅ {spec.get('success', 'Saved.')}", back_kb)


@router.callback_query(StateFilter(Wizard.step), F.data == "wcancel")
async def cancel(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    d = await state.get_data()
    back = (d.get("w_spec") or {}).get("back", "menu:home")
    await state.clear()
    await cb.message.edit_text("Cancelled.", reply_markup=ikb([[("⬅️ Back", back)]]))
