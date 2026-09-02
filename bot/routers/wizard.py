"""Generic field-stepper create wizard (shared by Finance create + Cards create).

A caller starts it with `await wizard.start(event, state, spec)`; the spec drives the steps
and the final POST. Spec is stored in FSM memory (objects kept as-is, no serialization).

spec = {title, endpoint, back (callback_data), success, auto_currency, fields:[{key,label,kind,...}]}
kinds: text(+regex/regex_msg) | amount(>0) | number(any) | int(+min/max) | date(+today) | month | choice(choices=[(value,label)]) | bool(+yes_label/no_label → True/False)

`title`, `success`, each field's `label`, `choices` labels and `yes_label`/`no_label` are all
i18n KEYS (looked up with `t()` at render time), not raw text — this is what lets one spec
serve every chat's language.
"""
import datetime as dt
import re

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from .. import api, common, keyboards
from ..config import CURRENCY
from ..i18n import t
from ..keyboards import esc, ikb
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
    chat_id = common.chat_id_of(event)
    d = await state.get_data()
    spec, idx = d["w_spec"], d["w_index"]
    field = spec["fields"][idx]
    head = t(chat_id, "wizard.stepHeader", title=t(chat_id, spec["title"]), index=idx + 1, total=len(spec["fields"]))
    kind = field["kind"]
    label = t(chat_id, field["label"])
    rows = []
    if kind == "amount":
        body = t(chat_id, "wizard.amountPrompt", label=label, currency=CURRENCY)
    elif kind == "number":
        body = t(chat_id, "wizard.numberPrompt", label=label, currency=CURRENCY)
    elif kind == "int":
        body = t(chat_id, "wizard.intPrompt", label=label)
    elif kind == "date":
        body = t(chat_id, "wizard.datePrompt", label=label)
        if field.get("today"):
            rows.append([(t(chat_id, "common.today"), "wtoday")])
    elif kind == "month":
        body = t(chat_id, "wizard.monthPrompt", label=label)
    elif kind == "choice":
        body = t(chat_id, "wizard.choicePrompt", label=label)
        for value, choice_key in field["choices"]:
            rows.append([(t(chat_id, choice_key), f"wchoice:{value}")])
    elif kind == "bool":
        body = f"<b>{label}</b>"
        rows.append([(t(chat_id, field.get("yes_label", "wizard.yesDefault")), "wbool:1")])
        rows.append([(t(chat_id, field.get("no_label", "wizard.noDefault")), "wbool:0")])
    else:
        body = t(chat_id, "wizard.textPrompt", label=label)
    if not field.get("required"):
        rows.append([(t(chat_id, "common.skip"), "wskip")])
    rows.append([(t(chat_id, "common.cancel"), "wcancel")])
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


@router.callback_query(StateFilter(Wizard.step), F.data.startswith("wbool:"))
async def on_bool(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    d = await state.get_data()
    await _set(state, d["w_spec"]["fields"][d["w_index"]]["key"], cb.data.split(":", 1)[1] == "1")
    await _advance(cb, state)


@router.message(StateFilter(Wizard.step))
async def on_text(message: Message, state: FSMContext) -> None:
    chat_id = message.chat.id
    d = await state.get_data()
    field = d["w_spec"]["fields"][d["w_index"]]
    raw = (message.text or "").strip()
    kind = field["kind"]
    if kind == "amount":
        val = _amount_pos(raw)
        if val is None:
            await message.answer(t(chat_id, "common.positiveNumber"))
            return
    elif kind == "number":
        val = _number(raw)
        if val is None:
            await message.answer(t(chat_id, "common.sendNumberExample"))
            return
    elif kind == "int":
        try:
            val = int(raw)
        except ValueError:
            await message.answer(t(chat_id, "wizard.wholeNumber"))
            return
        if (field.get("min") is not None and val < field["min"]) or \
           (field.get("max") is not None and val > field["max"]):
            await message.answer(t(chat_id, "wizard.numberRange", min=field.get('min'), max=field.get('max')))
            return
    elif kind == "date":
        try:
            dt.date.fromisoformat(raw)
        except ValueError:
            await message.answer(t(chat_id, "wizard.dateFormat"))
            return
        val = raw
    elif kind == "month":
        try:
            dt.date.fromisoformat(raw + "-01")
        except ValueError:
            await message.answer(t(chat_id, "wizard.monthFormat"))
            return
        val = raw + "-01"
    elif kind == "choice" or kind == "bool":
        await message.answer(t(chat_id, "wizard.tapButton"))
        return
    else:
        if field.get("regex") and not re.match(field["regex"], raw):
            await message.answer(t(chat_id, field.get("regex_msg", "wizard.invalidFormat")))
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
        payload["currency"] = CURRENCY
    back_kb = ikb([[(t(chat_id, "common.back"), spec["back"])]])
    try:
        await api.request(chat_id, "POST", spec["endpoint"], json=payload)
    except api.NeedsLogin:
        await state.clear()
        await common.show(event, t(chat_id, "common.sessionExpired"), keyboards.login_kb(chat_id))
        return
    except api.ApiError as exc:
        await state.clear()
        await common.show(event, f"❌ {esc(exc.message)}", back_kb)
        return
    except Exception:  # noqa: BLE001
        await state.clear()
        await common.show(event, t(chat_id, "common.serverUnreachable"), back_kb)
        return
    await state.clear()
    await common.show(event, f"✅ {t(chat_id, spec.get('success', 'wizard.savedDefault'))}", back_kb)


@router.callback_query(StateFilter(Wizard.step), F.data == "wcancel")
async def cancel(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    chat_id = cb.message.chat.id
    d = await state.get_data()
    back = (d.get("w_spec") or {}).get("back", "menu:home")
    await state.clear()
    await cb.message.edit_text(t(chat_id, "common.cancelled"), reply_markup=ikb([[(t(chat_id, "common.back"), back)]]))
