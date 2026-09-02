"""Auth: /start, typed login/signup (24h session), /lock, /menu, global /cancel."""
from aiogram import F, Router
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from .. import api, keyboards
from ..i18n import t
from ..keyboards import esc
from ..session import store
from ..states import Auth

router = Router()


def _menu_or_login(chat_id: int):
    return keyboards.main_menu_kb(chat_id) if store.is_active(chat_id) else keyboards.login_kb(chat_id)


@router.message(CommandStart())
async def start(message: Message, state: FSMContext) -> None:
    await state.clear()
    chat_id = message.chat.id
    if store.is_active(chat_id):
        await message.answer(keyboards.menu_text(chat_id), reply_markup=keyboards.main_menu_kb(chat_id))
    else:
        await message.answer(t(chat_id, "auth.welcome"), reply_markup=keyboards.login_kb(chat_id))


@router.message(Command("menu"))
async def menu_cmd(message: Message, state: FSMContext) -> None:
    await state.clear()
    chat_id = message.chat.id
    text = keyboards.menu_text(chat_id) if store.is_active(chat_id) else t(chat_id, "auth.pleaseLoginFirst")
    await message.answer(text, reply_markup=_menu_or_login(chat_id))


@router.message(Command("cancel"))
async def cancel_cmd(message: Message, state: FSMContext) -> None:
    await state.clear()
    chat_id = message.chat.id
    await message.answer(t(chat_id, "common.cancelled"), reply_markup=_menu_or_login(chat_id))


@router.callback_query(F.data == "auth:login")
async def login_cb(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    await state.set_state(Auth.username)
    await cb.message.answer(t(cb.message.chat.id, "auth.enterUsername"))


@router.message(Command("login"))
async def login_cmd(message: Message, state: FSMContext) -> None:
    await state.set_state(Auth.username)
    await message.answer(t(message.chat.id, "auth.enterUsername"))


@router.message(StateFilter(Auth.username))
async def got_username(message: Message, state: FSMContext) -> None:
    await state.update_data(username=(message.text or "").strip())
    await state.set_state(Auth.password)
    await message.answer(t(message.chat.id, "auth.enterPassword"))


@router.message(StateFilter(Auth.password))
async def got_password(message: Message, state: FSMContext) -> None:
    chat_id = message.chat.id
    data = await state.get_data()
    username = data.get("username", "")
    password = message.text or ""
    try:
        await message.delete()  # don't leave the password in chat history
    except Exception:  # noqa: BLE001
        pass
    try:
        status = await api.auth_status()
        if status.get("needsSignup"):
            tokens = await api.signup(username, password)
            verb_key = "auth.accountCreated"
        else:
            tokens = await api.login(username, password)
            verb_key = "auth.loggedIn"
    except api.ApiError as exc:
        await state.clear()
        await message.answer(f"❌ {esc(exc.message)}\n\n{t(chat_id, 'auth.tryAgain')}")
        return
    except Exception:  # noqa: BLE001
        await state.clear()
        await message.answer(t(chat_id, "auth.serverUnreachable"))
        return
    store.start(chat_id, username, tokens["accessToken"], tokens["refreshToken"])
    await state.clear()
    await message.answer(
        t(chat_id, "auth.loginSuccess", verb=t(chat_id, verb_key), username=esc(username)),
        reply_markup=keyboards.main_menu_kb(chat_id))


@router.message(Command("lock"))
async def lock_cmd(message: Message, state: FSMContext) -> None:
    chat_id = message.chat.id
    store.lock(chat_id)
    await state.clear()
    await message.answer(t(chat_id, "auth.locked"), reply_markup=keyboards.login_kb(chat_id))


@router.callback_query(F.data == "lock")
async def lock_cb(cb: CallbackQuery, state: FSMContext) -> None:
    chat_id = cb.message.chat.id
    store.lock(chat_id)
    await state.clear()
    await cb.answer(t(chat_id, "auth.lockedToast"))
    await cb.message.edit_text(t(chat_id, "auth.locked"), reply_markup=keyboards.login_kb(chat_id))
