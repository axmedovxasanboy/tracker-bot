"""Auth: /start, typed login/signup (24h session), /lock, /menu, global /cancel."""
from aiogram import F, Router
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from .. import api, keyboards
from ..keyboards import esc
from ..session import store
from ..states import Auth

router = Router()


def _menu_or_login(chat_id: int):
    return keyboards.main_menu_kb() if store.is_active(chat_id) else keyboards.login_kb()


@router.message(CommandStart())
async def start(message: Message, state: FSMContext) -> None:
    await state.clear()
    if store.is_active(message.chat.id):
        await message.answer(keyboards.MENU_TEXT, reply_markup=keyboards.main_menu_kb())
    else:
        await message.answer(
            "👋 Welcome to <b>Tracker</b>.\nLog in to continue — first time? Just pick a username + password.",
            reply_markup=keyboards.login_kb())


@router.message(Command("menu"))
async def menu_cmd(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(keyboards.MENU_TEXT if store.is_active(message.chat.id) else "🔒 Please log in first.",
                         reply_markup=_menu_or_login(message.chat.id))


@router.message(Command("cancel"))
async def cancel_cmd(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Cancelled.", reply_markup=_menu_or_login(message.chat.id))


@router.callback_query(F.data == "auth:login")
async def login_cb(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    await state.set_state(Auth.username)
    await cb.message.answer("👤 Enter your <b>username</b>:")


@router.message(Command("login"))
async def login_cmd(message: Message, state: FSMContext) -> None:
    await state.set_state(Auth.username)
    await message.answer("👤 Enter your <b>username</b>:")


@router.message(StateFilter(Auth.username))
async def got_username(message: Message, state: FSMContext) -> None:
    await state.update_data(username=(message.text or "").strip())
    await state.set_state(Auth.password)
    await message.answer("🔑 Now enter your <b>password</b>:")


@router.message(StateFilter(Auth.password))
async def got_password(message: Message, state: FSMContext) -> None:
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
            verb = "Account created"
        else:
            tokens = await api.login(username, password)
            verb = "Logged in"
    except api.ApiError as exc:
        await state.clear()
        await message.answer(f"❌ {esc(exc.message)}\n\nTap /login to try again.")
        return
    except Exception:  # noqa: BLE001
        await state.clear()
        await message.answer("❌ Couldn't reach the server. Is the backend running?")
        return
    store.start(message.chat.id, username, tokens["accessToken"], tokens["refreshToken"])
    await state.clear()
    await message.answer(
        f"✅ {verb} as <b>{esc(username)}</b>. Session lasts 24h (or until /lock).",
        reply_markup=keyboards.main_menu_kb())


@router.message(Command("lock"))
async def lock_cmd(message: Message, state: FSMContext) -> None:
    store.lock(message.chat.id)
    await state.clear()
    await message.answer("🔒 Locked. You'll need to log in again.", reply_markup=keyboards.login_kb())


@router.callback_query(F.data == "lock")
async def lock_cb(cb: CallbackQuery, state: FSMContext) -> None:
    store.lock(cb.message.chat.id)
    await state.clear()
    await cb.answer("Locked")
    await cb.message.edit_text("🔒 Locked. You'll need to log in again.", reply_markup=keyboards.login_kb())
