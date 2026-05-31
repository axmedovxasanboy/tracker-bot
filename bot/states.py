"""FSM state groups for the multi-step flows."""
from aiogram.fsm.state import State, StatesGroup


class Auth(StatesGroup):
    username = State()
    password = State()


class AddTx(StatesGroup):
    type = State()
    amount = State()
    category = State()
    source = State()
    date = State()
    desc = State()
    confirm = State()


class Exchange(StatesGroup):
    src = State()
    src_amt = State()
    dst = State()
    dst_amt = State()
    confirm = State()


class Bulk(StatesGroup):
    type = State()
    source = State()
    lines = State()


class FinAction(StatesGroup):
    amount = State()
    source = State()
    confirm = State()


class Wizard(StatesGroup):
    step = State()


class CatCreate(StatesGroup):
    mode = State()
    root_name = State()
    root_type = State()
    parent = State()
    sub_name = State()
    bonus = State()
