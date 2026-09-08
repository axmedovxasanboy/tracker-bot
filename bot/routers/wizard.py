"""Generic field-stepper create wizard — every create flow in Finance and Wallets runs on it.

A caller starts it with `await wizard.start(event, state, spec)`; the spec drives the steps,
the review screen and the final POST. The spec object is kept in FSM memory as-is (no
serialization), so a caller may hand over closures, tuples, anything.

    spec = {
        title:         i18n key for the flow's name ("Bank loan")
        endpoint:      API path, POSTed to
        back:          callback_data of the screen this flow was opened from
        success:       i18n key shown after the write            (optional)
        auto_currency: True adds {"currency": "UZS"} to the body (optional)
        fixed:         constants merged into the body            (optional)
        review:        force the review screen on/off            (optional — see below)
        fields:        [{key, label, kind, required, …}]
    }

    kinds: text (+regex/regex_msg) · amount (>0) · number (any sign, 0 allowed) ·
           int (+min/max) · date (+today) · month · choice (choices=[(value, label_key)]) ·
           bool (+yes_label/no_label → True/False)

`title`, `success`, every `label`, every choice label and `yes_label`/`no_label` are i18n
KEYS resolved with `t()` at render time, never raw text. That is what lets one spec serve
both languages — and it is also what makes the review screen possible, because the stepper
can print back what it collected using the very words it asked with.

Unknown spec keys are ignored, so a section may hang its own metadata on a spec (finance.py
carries `wallet`, `opening_key`, `opening_prompt` … for the questions it asks *before* the
wizard starts) without this module knowing anything about it.

Three things this stepper has to get right, each of which it used to get wrong:

* **A button belongs to the step it was drawn for.** Every step shares one FSM state, which
  is unavoidable — `StateFilter` is the only handler filter available and a spec has a
  variable number of steps. So the step index is stamped into the callback data instead, and
  a tap whose index is not the current one is refused and its keyboard stripped. Without it,
  scrolling up and tapping the previous prompt's "Skip" silently skipped whichever field was
  being asked for *now*: a required date was never asked, never set, and the POST died with
  "must not be null" after six answers had already been typed.

* **`required` is enforced where the value is set, not where the button is drawn.** Drawing
  no Skip button is a hint, not a rule; the rule lives in `_advance` and `_save`.

* **Nothing is written until the owner has seen it.** Finance records cannot be edited from
  the bot at all for several sections, so a mistyped 500 000 000 UZS bank loan used to be
  permanent. Every multi-field form now ends on a review screen where each answer is one tap
  from being corrected, and a rejected POST returns to that screen with the backend's
  complaint on top and every answer still in hand — instead of clearing the form.
"""
import datetime as dt
import logging
import re

from aiogram import F, Router
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from .. import api, common, keyboards, ui
from ..clock import today_iso
from ..config import CURRENCY
from ..i18n import t
from ..keyboards import esc, ikb
from ..money import fmt_money, parse_amount, parse_number
from ..states import Wizard

log = logging.getLogger(__name__)
router = Router(name="wizard")

# Every callback_data this module owns. The tuple is the filter for two catch-alls at the
# bottom of the file, so a prefix added here without a handler becomes a visible "this form
# is no longer open" rather than a button that spins for ever.
PREFIXES = ("wcancel", "wback:", "wskip:", "wtoday:", "wchoice:", "wbool:", "wrev:")


def _is_wizard_cb(cb: CallbackQuery) -> bool:
    return (cb.data or "").startswith(PREFIXES)


def _not_wizard_cb(cb: CallbackQuery) -> bool:
    return not (cb.data or "").startswith(PREFIXES)


# ── spec helpers ────────────────────────────────────────────────────────────
def _fields(spec: dict) -> list[dict]:
    return spec.get("fields") or []


def _wants_review(spec: dict) -> bool:
    """Whether this spec ends on a review screen.

    Opt-out rather than opt-in, because the specs that need it most are the ones written by
    somebody who has never read this module. A single-field spec is its own review — the one
    answer is the only thing on screen and Back re-asks it — so it skips the extra tap unless
    the spec asks for it explicitly with `review: True`.
    """
    review = spec.get("review")
    if review is None:
        return len(_fields(spec)) > 1
    return bool(review)


def _answered(data: dict, field: dict) -> bool:
    """True when this field holds a real answer.

    `0`, `0.0` and `False` are answers — a zero opening balance and a "no" on an
    opening-balance question are both things the owner meant — so this tests for absence,
    not falsiness.
    """
    value = data.get(field["key"])
    return value is not None and value != ""


def _missing_required(spec: dict, data: dict) -> list[int]:
    return [i for i, field in enumerate(_fields(spec))
            if field.get("required") and not _answered(data, field)]


def _display(chat_id: int, field: dict, data: dict) -> str:
    """One answer, rendered for the review screen and for the "currently" line.

    Everything the owner typed is `esc()`d — it lands in HTML message text. Everything that
    came from the spec (a choice label, a yes/no label) is an i18n string and is not, for the
    same reason the labels around it are not.
    """
    if not _answered(data, field):
        return t(chat_id, "wizard.notSet")
    value = data[field["key"]]
    kind = field.get("kind", "text")
    if kind in ("amount", "number"):
        return esc(fmt_money(value))
    if kind == "bool":
        key = field.get("yes_label", "wizard.yesDefault") if value \
            else field.get("no_label", "wizard.noDefault")
        return t(chat_id, key)
    if kind == "choice":
        for choice_value, label_key in field.get("choices") or []:
            if str(choice_value) == str(value):
                return t(chat_id, label_key)
        return esc(str(value))
    if kind == "month":
        # Stored as the first of the month, because the backend fields are LocalDate. The
        # owner answered "2026-09" and that is what they should read back.
        return esc(str(value)[:7])
    return esc(str(value))


# ── FSM data ────────────────────────────────────────────────────────────────
# w_spec  the spec object          w_index  the step being asked (== len(fields) on review)
# w_data  answers so far           w_edit   True while correcting one field from the review
async def _set(state: FSMContext, key: str, value) -> None:
    d = await state.get_data()
    data = dict(d.get("w_data") or {})
    data[key] = value
    await state.update_data(w_data=data)


async def _clear(state: FSMContext, key: str) -> None:
    """Drop an answer. Skip has to erase, not merely decline to write: a field answered,
    then revisited and skipped, would otherwise still carry its first value into the POST."""
    d = await state.get_data()
    data = dict(d.get("w_data") or {})
    data.pop(key, None)
    await state.update_data(w_data=data)


async def _active(event, state: FSMContext) -> dict | None:
    """The wizard's FSM data, or None once it has told the user the form is gone.

    `MemoryStorage` dies with the process and `drop_pending_updates` is False, so a tap made
    before a restart arrives after it with a state but no data behind it.
    """
    d = await state.get_data()
    if d.get("w_spec"):
        return d
    await state.clear()
    chat_id = common.chat_id_of(event)
    await common.show(event, t(chat_id, "wizard.expired"), keyboards.back_menu_kb(chat_id))
    return None


def _idx(data: str | None, position: int) -> int | None:
    """The step index stamped into a callback, or None if the button predates the format."""
    parts = (data or "").split(":")
    if len(parts) <= position:
        return None
    try:
        return int(parts[position])
    except ValueError:
        return None


def _tail(data: str | None, position: int) -> str:
    """Everything from segment `position` on, colons intact — a choice value keeps its shape."""
    parts = (data or "").split(":", position)
    return parts[position] if len(parts) > position else ""


def _field_at(spec: dict, idx: int | None) -> dict | None:
    """The field at `idx`, or None when the index is out of the spec's range.

    Updates are fed as detached tasks, so two taps can be in flight at once and the index in
    FSM data can briefly point one past the last field while a step hands over to the review.
    Every caller that would index a list therefore asks through here.
    """
    fields = _fields(spec)
    if not isinstance(idx, int) or not 0 <= idx < len(fields):
        return None
    return fields[idx]


async def _disarm(cb: CallbackQuery) -> None:
    """Take the keyboard off a prompt that has been overtaken by a later step.

    A typed answer makes the next prompt a NEW message, which leaves the previous prompt on
    screen with live buttons. The index check already refuses those taps; stripping the
    keyboard means the owner sees why, instead of tapping a dead button repeatedly.

    Cosmetic, and therefore not allowed to fail loudly: every Telegram error is swallowed,
    not just the "message is not modified"/"message to edit not found" pair one would expect.
    The message may be older than 48 hours, may have been deleted, or the call may simply not
    get through — and letting any of that escape would abort a handler that has already
    acknowledged the tap, leaving the owner with a screen that never changed.
    """
    msg = cb.message
    if not isinstance(msg, Message):
        return
    try:
        await msg.edit_reply_markup(reply_markup=None)
    except TelegramAPIError:
        log.debug("stale prompt for callback %s could not be disarmed", cb.id, exc_info=True)


async def _index_ok(cb: CallbackQuery, state: FSMContext, wanted: int | None) -> bool:
    """The whole point of stamping the index into the callback data.

    Every step shares `Wizard.step`, so `StateFilter` matches a Skip drawn three steps ago
    just as happily as the one on screen. This is the check that says which field the button
    was drawn for, and it is the difference between "I have no end date" and silently never
    being asked for a required date at all.
    """
    d = await state.get_data()
    if wanted is not None and wanted == d.get("w_index"):
        return True
    await common.ack(cb, t(common.chat_id_of(cb), "wizard.stepMoved"))
    await _disarm(cb)
    return False


# ── the flow ────────────────────────────────────────────────────────────────
async def start(event, state: FSMContext, spec: dict) -> None:
    """Open a form. The caller has already gated and asked whatever it needs to ask."""
    await state.set_state(Wizard.step)
    await state.update_data(w_spec=spec, w_index=0, w_data={}, w_edit=False)
    if not _fields(spec):
        # A spec with nothing to ask is a spec whose whole body is `fixed`. Post it.
        await _save(event, state)
        return
    await _prompt(event, state)


async def _prompt(event, state: FSMContext, banner: str | None = None) -> None:
    chat_id = common.chat_id_of(event)
    d = await state.get_data()
    spec = d["w_spec"]
    fields = _fields(spec)
    idx = d.get("w_index", 0)
    if not isinstance(idx, int) or not 0 <= idx < len(fields):
        await _review(event, state)
        return
    field = fields[idx]
    kind = field.get("kind", "text")
    label = t(chat_id, field["label"])
    editing = bool(d.get("w_edit"))

    lines: list[str] = []
    if banner:
        lines += [banner, ""]
    lines.append(t(chat_id, "wizard.stepHeader", title=t(chat_id, spec["title"]),
                   index=idx + 1, total=len(fields)))
    rows: list[list[tuple[str, str]]] = []

    if kind == "amount":
        lines.append(t(chat_id, "wizard.amountPrompt", label=label, currency=CURRENCY))
        lines.append(t(chat_id, "wizard.amountHint"))
    elif kind == "number":
        lines.append(t(chat_id, "wizard.numberPrompt", label=label, currency=CURRENCY))
        lines.append(t(chat_id, "wizard.amountHint"))
    elif kind == "int":
        lines.append(t(chat_id, "wizard.intPrompt", label=label))
    elif kind == "date":
        lines.append(t(chat_id, "wizard.datePrompt", label=label))
        if field.get("today"):
            rows.append([(t(chat_id, "common.today"), f"wtoday:{idx}")])
    elif kind == "month":
        lines.append(t(chat_id, "wizard.monthPrompt", label=label))
    elif kind == "choice":
        lines.append(t(chat_id, "wizard.choicePrompt", label=label))
        rows.extend(ui.grid([(t(chat_id, label_key), f"wchoice:{idx}:{value}")
                             for value, label_key in field.get("choices") or []], 2))
    elif kind == "bool":
        lines.append(t(chat_id, "wizard.boolPrompt", label=label))
        rows.append([(t(chat_id, field.get("yes_label", "wizard.yesDefault")), f"wbool:{idx}:1"),
                     (t(chat_id, field.get("no_label", "wizard.noDefault")), f"wbool:{idx}:0")])
    else:
        lines.append(t(chat_id, "wizard.textPrompt", label=label))

    if _answered(d.get("w_data") or {}, field):
        lines.append(t(chat_id, "wizard.currently", value=_display(chat_id, field, d["w_data"])))
    if not field.get("required"):
        rows.append([(t(chat_id, "common.skip"), f"wskip:{idx}")])
    if editing or idx > 0:
        # Cancel abandons the whole form; Back retreats one step, or returns to the review
        # when this step was opened from it.
        rows.append(ui.nav(chat_id, back=f"wback:{idx}", cancel="wcancel"))
    else:
        # On step one there is no earlier step, and backing out of a form with nothing in it
        # IS cancelling it. Two buttons that do the same thing would only ask the owner to
        # pick between them.
        rows.append(ui.nav(chat_id, back=f"wback:{idx}"))
    await common.show(event, "\n".join(lines), ikb(rows))


async def _advance(event, state: FSMContext) -> None:
    """Leave the current step: to the review if it was opened from there, else forwards."""
    chat_id = common.chat_id_of(event)
    d = await state.get_data()
    spec = d["w_spec"]
    fields = _fields(spec)
    idx = d.get("w_index", 0)
    if isinstance(idx, int) and 0 <= idx < len(fields):
        field = fields[idx]
        if field.get("required") and not _answered(d.get("w_data") or {}, field):
            # The real enforcement of `required`. Hiding the Skip button only hides one way
            # past; this is the one no stale keyboard and no unexpected input can get around.
            await _prompt(event, state,
                          banner=t(chat_id, "wizard.required", label=t(chat_id, field["label"])))
            return
    if d.get("w_edit"):
        await state.update_data(w_edit=False)
        await _review(event, state)
        return
    nxt = (idx if isinstance(idx, int) else 0) + 1
    await state.update_data(w_index=nxt)
    if nxt < len(fields):
        await _prompt(event, state)
    elif _wants_review(spec):
        await _review(event, state)
    else:
        await _save(event, state)


async def _review(event, state: FSMContext, banner: str | None = None) -> None:
    """Everything the form collected, with each answer one tap from being corrected."""
    chat_id = common.chat_id_of(event)
    d = await state.get_data()
    spec = d["w_spec"]
    fields = _fields(spec)
    data = d.get("w_data") or {}
    await state.set_state(Wizard.review)
    # The index parks one past the last field so the review's own Back carries a number the
    # step guard accepts, and so a stale prompt from the last step is refused like any other.
    await state.update_data(w_index=len(fields), w_edit=False)

    lines: list[str] = []
    if banner:
        lines += [banner, ""]
    lines.append(t(chat_id, "wizard.reviewTitle", title=t(chat_id, spec["title"])))
    lines.append(t(chat_id, "wizard.reviewHint"))
    lines.append("")
    lines += [t(chat_id, "wizard.reviewLine", index=i + 1, label=t(chat_id, field["label"]),
                value=_display(chat_id, field, data))
              for i, field in enumerate(fields)]

    rows = ui.grid([(t(chat_id, "wizard.fieldBtn", index=i + 1, label=t(chat_id, field["label"])),
                     f"wrev:f:{i}")
                    for i, field in enumerate(fields)], 2)
    # Save on a row of its own: it is the only irreversible button on the screen and it
    # should not sit thumb-width from a field it would be easy to mean instead.
    rows.append([(t(chat_id, "wizard.saveBtn"), "wrev:save")])
    rows.append(ui.nav(chat_id, back=f"wback:{len(fields)}", cancel="wcancel"))
    await common.show(event, "\n".join(lines), ikb(rows))


async def _save(event, state: FSMContext) -> None:
    chat_id = common.chat_id_of(event)
    d = await state.get_data()
    spec = d["w_spec"]
    fields = _fields(spec)
    data = dict(d.get("w_data") or {})

    missing = _missing_required(spec, data)
    if missing:
        idx = missing[0]
        await state.set_state(Wizard.step)
        # `w_edit` so answering the field returns here rather than walking the rest of the
        # form again — the other answers are already given.
        await state.update_data(w_index=idx, w_edit=True)
        await _prompt(event, state,
                      banner=t(chat_id, "wizard.required",
                               label=t(chat_id, fields[idx]["label"])))
        return

    payload = dict(data)
    if spec.get("fixed"):
        payload.update(spec["fixed"])  # constants the owner is not prompted for (savingsGoal…)
    if spec.get("auto_currency"):
        payload["currency"] = CURRENCY

    back = spec.get("back") or "menu:home"
    await common.begin_write(event, chat_id)
    try:
        await api.request(chat_id, "POST", spec["endpoint"], json=payload)
    except api.NeedsLogin:
        # The only failure the form cannot be retried through: re-authenticating clears the
        # state anyway, so there is nothing to hold on to.
        await state.clear()
        await common.show(event, t(chat_id, "common.sessionExpired"), keyboards.login_kb(chat_id))
        return
    except api.Unreachable:
        await _review(event, state, banner=t(chat_id, "common.serverUnreachable"))
        return
    except api.ApiError as exc:
        # The backend names the field it rejected ("borrowedDate: must not be null"). Putting
        # that on top of the review, with every answer still in place, turns six lost minutes
        # into one tap — the old code cleared the state here and threw the form away.
        await _review(event, state, banner=f"❌ {esc(exc.message)}")
        return
    except Exception:  # noqa: BLE001
        log.exception("wizard POST %s failed", spec.get("endpoint"))
        await _review(event, state, banner=t(chat_id, "common.serverUnreachable"))
        return
    await state.clear()
    await common.show(event, f"✅ {t(chat_id, spec.get('success', 'wizard.savedDefault'))}",
                      ikb([[(t(chat_id, "common.back"), back)]]))


# ── handlers ────────────────────────────────────────────────────────────────
# Registration order is the resolution order inside this router's observers, so the specific
# handlers come first and the two catch-alls at the bottom pick up what is left.
@router.callback_query(StateFilter(Wizard.step, Wizard.review), F.data == "wcancel")
async def on_cancel(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    chat_id = common.chat_id_of(cb)
    d = await state.get_data()
    back = ((d.get("w_spec") or {}).get("back")) or "menu:home"
    await state.clear()
    await common.show(cb, t(chat_id, "common.cancelled"),
                      ikb([[(t(chat_id, "common.back"), back)]]))


@router.callback_query(StateFilter(Wizard.step, Wizard.review), F.data.startswith("wback:"))
async def on_back(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    d = await _active(cb, state)
    if d is None:
        return
    idx = _idx(cb.data, 1)
    if not await _index_ok(cb, state, idx):
        return
    if d.get("w_edit"):
        # Backing out of a correction leaves the value exactly as the review showed it.
        await state.update_data(w_edit=False)
        await _review(cb, state)
        return
    if idx <= 0:
        await on_cancel(cb, state)
        return
    await state.set_state(Wizard.step)
    await state.update_data(w_index=idx - 1)
    await _prompt(cb, state)


@router.callback_query(StateFilter(Wizard.step), F.data.startswith("wskip:"))
async def on_skip(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    d = await _active(cb, state)
    if d is None:
        return
    idx = _idx(cb.data, 1)
    if not await _index_ok(cb, state, idx):
        return
    field = _field_at(d["w_spec"], idx)
    if field is None:
        await _review(cb, state)
        return
    if field.get("required"):
        # No Skip is drawn for a required field, so this button came from a spec that has
        # since changed under a live keyboard. Refuse it here rather than at the POST.
        chat_id = common.chat_id_of(cb)
        await _prompt(cb, state, banner=t(chat_id, "wizard.required",
                                          label=t(chat_id, field["label"])))
        return
    await _clear(state, field["key"])
    await _advance(cb, state)


@router.callback_query(StateFilter(Wizard.step), F.data.startswith("wtoday:"))
async def on_today(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    d = await _active(cb, state)
    if d is None:
        return
    idx = _idx(cb.data, 1)
    if not await _index_ok(cb, state, idx):
        return
    field = _field_at(d["w_spec"], idx)
    if field is None:
        await _review(cb, state)
        return
    # clock.today_iso(), not date.today(): the container runs UTC and the owner does not, so
    # between midnight and 05:00 Tashkent `date.today()` names yesterday — and on the 1st it
    # names the previous month, which is an envelope that may already be closed.
    await _set(state, field["key"], today_iso())
    await _advance(cb, state)


@router.callback_query(StateFilter(Wizard.step), F.data.startswith("wchoice:"))
async def on_choice(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    d = await _active(cb, state)
    if d is None:
        return
    idx = _idx(cb.data, 1)
    if not await _index_ok(cb, state, idx):
        return
    field = _field_at(d["w_spec"], idx)
    if field is None:
        await _review(cb, state)
        return
    value = _tail(cb.data, 2)
    if value not in {str(choice_value) for choice_value, _ in field.get("choices") or []}:
        # An enum value this field does not offer would be a 400 from the backend six steps
        # later; ask again instead.
        await _prompt(cb, state, banner=t(common.chat_id_of(cb), "wizard.invalidFormat"))
        return
    await _set(state, field["key"], value)
    await _advance(cb, state)


@router.callback_query(StateFilter(Wizard.step), F.data.startswith("wbool:"))
async def on_bool(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    d = await _active(cb, state)
    if d is None:
        return
    idx = _idx(cb.data, 1)
    if not await _index_ok(cb, state, idx):
        return
    field = _field_at(d["w_spec"], idx)
    if field is None:
        await _review(cb, state)
        return
    await _set(state, field["key"], _tail(cb.data, 2) == "1")
    await _advance(cb, state)


@router.callback_query(StateFilter(Wizard.review), F.data == "wrev:save")
async def on_save(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    if await _active(cb, state) is None:
        return
    await _save(cb, state)


@router.callback_query(StateFilter(Wizard.review), F.data.startswith("wrev:f:"))
async def on_review_field(cb: CallbackQuery, state: FSMContext) -> None:
    await common.ack(cb)
    d = await _active(cb, state)
    if d is None:
        return
    idx = _idx(cb.data, 2)
    if idx is None or not 0 <= idx < len(_fields(d["w_spec"])):
        await _review(cb, state)
        return
    await state.set_state(Wizard.step)
    await state.update_data(w_index=idx, w_edit=True)
    await _prompt(cb, state)


@router.message(StateFilter(Wizard.step), F.text)
async def on_text(message: Message, state: FSMContext) -> None:
    chat_id = message.chat.id
    d = await _active(message, state)
    if d is None:
        return
    field = _field_at(d["w_spec"], d.get("w_index"))
    if field is None:
        await _review(message, state)
        return
    kind = field.get("kind", "text")
    raw = (message.text or "").strip()

    if not raw:
        # Whitespace only. On an optional field that reads as "leave it empty"; on a required
        # one it is the thing the form must not accept.
        if field.get("required"):
            await _prompt(message, state, banner=t(chat_id, "wizard.required",
                                                   label=t(chat_id, field["label"])))
            return
        await _clear(state, field["key"])
        await _advance(message, state)
        return

    if kind == "amount":
        # bot.money, not a local float(): the owner writes money the way Uzbekistan does, and
        # the old copy read "50.000" as fifty.
        val = parse_amount(raw)
        if val is None:
            await _prompt(message, state, banner=t(chat_id, "common.positiveNumber"))
            return
    elif kind == "number":
        val = parse_number(raw)
        if val is None:
            await _prompt(message, state, banner=t(chat_id, "common.sendNumberExample"))
            return
    elif kind == "int":
        parsed = parse_number(raw)
        if parsed is None or parsed != int(parsed):
            await _prompt(message, state, banner=t(chat_id, "wizard.wholeNumber"))
            return
        val = int(parsed)
        low, high = field.get("min"), field.get("max")
        if (low is not None and val < low) or (high is not None and val > high):
            if low is not None and high is not None:
                banner = t(chat_id, "wizard.numberRange", min=low, max=high)
            elif low is not None:
                banner = t(chat_id, "wizard.numberMin", min=low)
            else:
                banner = t(chat_id, "wizard.numberMax", max=high)
            await _prompt(message, state, banner=banner)
            return
    elif kind == "date":
        try:
            val = dt.date.fromisoformat(raw).isoformat()  # normalised, so "20260907" is fine
        except ValueError:
            await _prompt(message, state, banner=t(chat_id, "wizard.dateFormat"))
            return
    elif kind == "month":
        try:
            # The backend fields are LocalDate, so a month is stored as its first day.
            val = dt.date.fromisoformat(f"{raw}-01").isoformat()
        except ValueError:
            await _prompt(message, state, banner=t(chat_id, "wizard.monthFormat"))
            return
    elif kind in ("choice", "bool"):
        await _prompt(message, state, banner=t(chat_id, "wizard.tapButton"))
        return
    else:
        if field.get("regex") and not re.match(field["regex"], raw):
            await _prompt(message, state,
                          banner=t(chat_id, field.get("regex_msg", "wizard.invalidFormat")))
            return
        val = raw

    await _set(state, field["key"], val)
    await _advance(message, state)


@router.message(StateFilter(Wizard.step))
async def on_non_text(message: Message, state: FSMContext) -> None:
    """A voice note, photo or sticker at a typed step.

    `(message.text or "").strip()` used to turn every one of these into a valid-looking empty
    answer: the wizard said nothing, moved on, and the form died at the POST naming a field
    the owner was sure they had filled in. The owner dictates most of their Telegram messages,
    so this is the ordinary way to lose a six-field form, not an exotic one.
    """
    chat_id = message.chat.id
    d = await _active(message, state)
    if d is None:
        return
    field = _field_at(d["w_spec"], d.get("w_index"))
    if field is None:
        await _review(message, state)
        return
    await _prompt(message, state,
                  banner=t(chat_id, "wizard.textOnly", label=t(chat_id, field["label"])))


@router.message(StateFilter(Wizard.review))
async def on_review_text(message: Message, state: FSMContext) -> None:
    """Typing at the review re-posts it, so the buttons are back at the bottom of the chat."""
    if await _active(message, state) is None:
        return
    await _review(message, state, banner=t(message.chat.id, "wizard.tapButton"))


@router.callback_query(StateFilter(Wizard.step, Wizard.review), _is_wizard_cb)
async def on_stale(cb: CallbackQuery) -> None:
    """A wizard button from a step the form has moved past, or from the wrong screen.

    Reached only after every handler above has declined it, which means either the index does
    not match or the button belongs to the other screen (a review's Save tapped while a field
    is being corrected). Either way it must not act on the field being asked for now.
    """
    await common.ack(cb, t(common.chat_id_of(cb), "wizard.stepMoved"))
    await _disarm(cb)


@router.callback_query(StateFilter(Wizard.step, Wizard.review), _not_wizard_cb)
async def on_leave(cb: CallbackQuery, state: FSMContext) -> None:
    """Any non-wizard button tapped mid-form ends the form, then hands the tap onwards.

    Without this, walking away from a half-filled wizard (its own Back link, a Finance
    section, a card) left `Wizard.step` set with a dead spec behind it, and the next thing
    the owner typed anywhere in the bot was swallowed as a field answer. `SkipHandler` is
    aiogram's own mechanism for "not mine after all": `TelegramEventObserver.trigger` catches
    it and carries on down the handler list and into the routers registered after this one,
    which is where every one of those buttons is actually handled. The query is deliberately
    left unanswered so the real handler can answer it.
    """
    await state.clear()
    raise SkipHandler


@router.callback_query(_is_wizard_cb)
async def on_expired(cb: CallbackQuery) -> None:
    """A wizard button with no wizard behind it — the process restarted, or the form is done.

    `drop_pending_updates` is False, so taps made while the container was down arrive after
    it comes back, and MemoryStorage came back empty. Say so instead of leaving a spinner.
    Another flow's state is left alone: this only replaces the stale form's own message.
    """
    await common.ack(cb)
    chat_id = common.chat_id_of(cb)
    await common.show(cb, t(chat_id, "wizard.expired"), keyboards.back_menu_kb(chat_id))
