"""FSM state groups for every multi-step flow in the bot.

One group per flow, one state per SCREEN inside it. That granularity is not decoration: a
handler is selected by `StateFilter(X)`, so two screens that share a state also share their
buttons, and a stale keyboard scrolled up in the chat fires against whatever step the flow
has since moved on to. That is a live defect in the two flows that collapse many screens
into one state (`Wizard.step`, `CloseMonth.balance`): tapping the previous wallet's
"Use 250 000" writes that figure into the wallet being asked for now. Both keep their old
state names so existing handlers still compile, and both are being fixed by stamping the
step index into the callback data — but new flows should give each screen its own state and
avoid the whole class.

FSM *data* (the answers) is a plain dict per chat and is not declared here; the keys are
prefixed per flow (`a_*` add-transaction, `fa_*` finance action, `w_*` wizard, `mc_*` month
close) so two flows cannot read each other's leftovers.

Storage is `MemoryStorage`, so every state below is gone on restart. Flows must therefore
tolerate a tap arriving with no state at all — that is the stateless-fallback rule in
FIX-CONTRACT, not something a state group can solve.
"""
from aiogram.fsm.state import State, StatesGroup


class Auth(StatesGroup):
    """Typed login/signup. `password` is the one step whose message is deleted on receipt."""
    username = State()
    password = State()


class Settings(StatesGroup):
    """Settings values the bot can write itself, one PUT /settings per field.

    `income` is the important one: the backend refuses every money write until
    monthlyStableIncome is set, and the guard in `common.stable_income_set` offers a
    `settings:income` button that lands here — so this state is the only exit from the
    first-run wall for a phone-only owner.
    """
    income = State()
    tracking_month = State()   # allocationTrackingStartMonth, "YYYY-MM"


class AddTx(StatesGroup):
    """The full add-transaction flow: type → amount → category → subtype → source → date →
    description → confirm. Each step is its own state, which is why this is the one flow
    whose stale buttons are inert rather than harmful."""
    type = State()
    amount = State()
    category = State()
    subtype = State()
    source = State()
    date = State()
    desc = State()
    confirm = State()


class QuickAdd(StatesGroup):
    """The one-message path: "50000 lunch" typed at the menu becomes a draft, not a form.

    `confirm` holds the parsed draft on screen; the other states exist so a wrong guess can
    be corrected in one tap instead of throwing the draft away and retyping it.
    """
    confirm = State()
    amount = State()
    category = State()
    source = State()
    desc = State()


class EditTx(StatesGroup):
    """Fixing a saved transaction: pick the field, then type/tap the new value, then PUT.

    `field` is the chooser screen; the rest are the per-field editors. A typo in an amount
    is the most common one, and today it costs the whole eight-step re-entry.
    """
    field = State()
    amount = State()
    category = State()
    date = State()
    desc = State()


class MoveMoney(StatesGroup):
    """POST /transactions/transfer — cash onto a card, or card to card.

    Neither leg is income or expense, which is exactly why it needs its own flow: recording
    a top-up as an INCOME inflates the month the owner is about to close.
    """
    source = State()
    target = State()
    amount = State()
    date = State()
    confirm = State()


class FinAction(StatesGroup):
    """The shared money action behind Repay / Pay / Contribute / Mark returned / Mark paid,
    and (once it has a KIND_CFG entry) the bank-loan installment.

    `record` is the picker for flows that arrive without one — "top up an investment" from a
    Plan bucket, say, rather than from that investment's own row. `recipient` is the
    donation's who. `date` exists because a bill settled on the 30th and recorded on the 2nd
    belongs in September's envelope, not October's; without it every finance action is
    stamped today and lands in the wrong month.
    """
    record = State()
    recipient = State()
    amount = State()
    source = State()
    date = State()
    confirm = State()


class FinEdit(StatesGroup):
    """One-field edit of an existing finance record (PUT /finance/<section>/{id}).

    A whole-record edit re-drives the create wizard with the values prefilled; this group is
    for the narrow "fix the monthly payment" case where re-answering six prompts is absurd.
    """
    field = State()
    value = State()
    confirm = State()


class Marks(StatesGroup):
    """GET/DELETE /finance/mark-paid — the "already paid" marks.

    A mark is the one write with no transaction behind it, so it appears in no list and a
    mistyped one silently inflates every allocation bucket until it is deleted. `month`
    picks which month's marks to list; `confirm` is the delete's second tap.
    """
    month = State()
    confirm = State()


class Wizard(StatesGroup):
    """The generic spec-driven create wizard (finance records, cards, cash balances).

    `step` covers every field — see the module docstring — and `review` is the summary
    screen between the last field and the POST, so a six-field bank loan can be corrected
    before it is written rather than never.
    """
    step = State()
    review = State()


class CatCreate(StatesGroup):
    """Category create: root (name → type) or sub-category (parent → name → bonus flag)."""
    mode = State()
    root_name = State()
    root_type = State()
    parent = State()
    sub_name = State()
    bonus = State()


class CatEdit(StatesGroup):
    """Renaming a category. Deleting one silently detaches its children and nulls it on
    every transaction, so renaming is the only non-destructive way to fix a typo."""
    name = State()


class CardEdit(StatesGroup):
    """Editing a card (PUT /cards/{id}). Deleting a card detaches every transaction that
    referenced it, so "delete and re-add" is not a way to fix a mistyped bank name."""
    field = State()
    value = State()


class Reset(StatesGroup):
    """Danger Zone: the typed password confirming POST /settings/reset."""
    password = State()


class CloseMonth(StatesGroup):
    """Closing a month permanently: which month → one real balance per wallet → confirm.

    `month` exists because the backend closes months strictly in order: skip August and the
    only month it will accept is August, while a bot that asks for today's month can never
    offer it again.
    """
    month = State()
    balance = State()   # one prompt per wallet (index tracked in FSM data)
    confirm = State()


class GoalValue(StatesGroup):
    """Single step: a savings goal's new current value (POST /investments/{id}/value)."""
    amount = State()
