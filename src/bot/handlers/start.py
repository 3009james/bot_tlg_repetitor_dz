from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from src.bot.keyboards.common import admin_home_kb, open_app_kb, student_home_kb, student_webapp_kb, unknown_user_kb
from src.bot.states import RequestAccessState
from src.db.models import UserRole
from src.db.repo import BotRepo
from src.db.session import session_scope

router = Router()


@router.message(CommandStart())
async def start_handler(message: Message, settings, session_factory) -> None:
    tg_id = message.from_user.id
    full_name = message.from_user.full_name
    username = message.from_user.username

    async with session_scope(session_factory) as session:
        repo = BotRepo(session)
        if tg_id in settings.admins:
            user = await repo.upsert_user(tg_id, full_name, username, UserRole.ADMIN)
            user.role = UserRole.ADMIN
        else:
            user = await repo.get_user_by_telegram(tg_id)
            if not user:
                user = await repo.upsert_user(tg_id, full_name, username, UserRole.PENDING)

    if tg_id in settings.admins:
        if settings.webapp_url:
            await message.answer("Админ-панель доступна в приложении.", reply_markup=open_app_kb(settings.webapp_url))
        else:
            await message.answer("Админ-панель активна.", reply_markup=admin_home_kb())
        return

    if user.role == UserRole.STUDENT:
        greeting = f"Здравствуйте, {user.full_name}.\nОткройте приложение."
        reply_markup = student_home_kb()
        if settings.webapp_url:
            reply_markup = student_webapp_kb(settings.webapp_url)
        if user.photo_file_id:
            await message.answer_photo(user.photo_file_id, caption=greeting, reply_markup=reply_markup)
        else:
            await message.answer(greeting, reply_markup=reply_markup)
        return

    if settings.webapp_url:
        await message.answer(
            "Откройте приложение и отправьте заявку на доступ.",
            reply_markup=open_app_kb(settings.webapp_url),
        )
        return
    await message.answer("Доступ пока не выдан. Отправьте заявку, и администратор добавит вас в систему.", reply_markup=unknown_user_kb())


@router.message(F.text == "Отправить заявку")
async def request_start_handler(message: Message, state: FSMContext) -> None:
    await state.set_state(RequestAccessState.waiting_subject)
    await message.answer("Укажите предмет/направление (например: Python, C++, Математика).")


@router.message(RequestAccessState.waiting_subject)
async def request_subject_handler(message: Message, state: FSMContext) -> None:
    await state.update_data(subject=message.text.strip())
    await state.set_state(RequestAccessState.waiting_message)
    await message.answer("Добавьте короткий комментарий о текущем уровне или целях.")


@router.message(RequestAccessState.waiting_message)
async def request_message_handler(message: Message, state: FSMContext, session_factory) -> None:
    data = await state.get_data()
    subject = data.get("subject", "").strip() or None
    note = message.text.strip() or None

    async with session_scope(session_factory) as session:
        repo = BotRepo(session)
        existing = await repo.get_pending_request(message.from_user.id)
        if existing:
            await state.clear()
            await message.answer("У вас уже есть активная заявка. Ожидайте решения администратора.")
            return
        await repo.upsert_user(
            telegram_id=message.from_user.id,
            full_name=message.from_user.full_name,
            username=message.from_user.username,
            role=UserRole.PENDING,
        )
        await repo.create_access_request(
            telegram_id=message.from_user.id,
            full_name=message.from_user.full_name,
            username=message.from_user.username,
            subject=subject,
            message=note,
        )
    await state.clear()
    await message.answer("Заявка отправлена. Как только вас добавят, задания появятся автоматически.")
