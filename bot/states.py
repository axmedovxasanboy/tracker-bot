"""FSM state groups, one per flow and one state per screen that reads typed text.

Storage is `MemoryStorage`, so every state is gone on restart. Buttons are therefore handled
without a StateFilter wherever a stale screen could be tapped, and check the flow's data by
hand — a screen that outlived a restart then says so instead of spinning.

FSM data keys are prefixed per flow (`rec*` recording, `pay*` paying, `ci_*` checking wallets).
"""
from aiogram.fsm.state import State, StatesGroup


class Auth(StatesGroup):
    """Typed login/signup. `password` is the one step whose message is deleted on receipt."""
    username = State()
    password = State()


class Settings(StatesGroup):
    """The monthly stable income — the backend refuses every money write until it is set."""
    income = State()


class Record(StatesGroup):
    """Recording income or an expense (quick add and ➕ Add share one draft card).

    `amount` is the typed amount step of ➕ Add, `note` the optional note, `card` the draft card
    and its pickers — a message typed there corrects the draft instead of starting a new one.
    """
    amount = State()
    note = State()
    card = State()


class Pay(StatesGroup):
    """Paying from a Home button: pick the account / wallet, or type another amount."""
    pick = State()
    amount = State()


class CheckIn(StatesGroup):
    """Check wallets: the intro, one typed balance per wallet, the review."""
    intro = State()
    balance = State()
    review = State()
