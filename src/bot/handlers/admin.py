from __future__ import annotations

import io
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from src.bot.keyboards.common import (
    admin_home_kb,
    request_actions_kb,
    student_select_kb,
    topic_manage_kb,
    topic_select_student_kb,
)
from src.bot.services.notebook_ingest import build_notebook_digest
from src.bot.states import UploadNotebookState
from src.db.models import Difficulty, RequestStatus, UserRole
from src.db.repo import BotRepo
from src.db.session import session_scope

router = Router()


def _is_admin(user_id: int, settings) -> bool:
    return user_id in settings.admins


async def _build_topic_editor(session_factory, student_id: int) -> tuple[str, object | None]:
    async with session_scope(session_factory) as session:
        repo = BotRepo(session)
        student = await repo.get_user_by_id(student_id)
        if not student or student.role != UserRole.STUDENT:
            return "Ученик не найден или еще не одобрен.", None
        available_topics = await repo.list_student_material_topics(student_id)
        selected_topics = set(await repo.get_student_topics(student_id))

    if not available_topics:
        return (
            f"У ученика {student.full_name} пока нет тем из блокнотов.\n"
            "Сначала загрузите `.ipynb` в разделе «Загрузить блокнот»."
        ), None

    selected_count = len([topic for topic in available_topics if topic in selected_topics])
    text = (
        f"Ученик: {student.full_name}\n"
        "Отметьте темы для генерации тестов.\n"
        f"Доступно тем: {len(available_topics)}\n"
        f"Выбрано: {selected_count}"
    )
    return text, topic_manage_kb(student_id, available_topics, selected_topics)


@router.message(Command("admin"))
async def admin_cmd(message: Message, settings) -> None:
    if not _is_admin(message.from_user.id, settings):
        await message.answer("Нет доступа.")
        return
    await message.answer("Админ-панель.", reply_markup=admin_home_kb())


@router.message(F.text == "Заявки")
async def list_requests(message: Message, settings, session_factory) -> None:
    if not _is_admin(message.from_user.id, settings):
        return
    async with session_scope(session_factory) as session:
        repo = BotRepo(session)
        requests = await repo.list_pending_requests()
    if not requests:
        await message.answer("Новых заявок нет.")
        return
    for req in requests:
        txt = (
            f"Заявка #{req.id}\n"
            f"Пользователь: {req.full_name} (@{req.username or '-'})\n"
            f"Telegram ID: {req.telegram_id}\n"
            f"Предмет: {req.subject or '-'}\n"
            f"Комментарий: {req.message or '-'}"
        )
        await message.answer(txt, reply_markup=request_actions_kb(req.id))


@router.callback_query(F.data.startswith("req:"))
async def handle_request_callback(callback: CallbackQuery, settings, session_factory, quiz_service) -> None:
    if not _is_admin(callback.from_user.id, settings):
        await callback.answer("Нет доступа", show_alert=True)
        return
    _, action, request_id_raw = callback.data.split(":")
    request_id = int(request_id_raw)
    status = RequestStatus.APPROVED if action == "approve" else RequestStatus.REJECTED

    async with session_scope(session_factory) as session:
        repo = BotRepo(session)
        req = await repo.handle_request(request_id, status, callback.from_user.id)
        if not req:
            await callback.answer("Заявка не найдена", show_alert=True)
            return
        if status == RequestStatus.APPROVED:
            user = await repo.get_user_by_telegram(req.telegram_id)
            if not user:
                user = await repo.upsert_user(req.telegram_id, req.full_name, req.username, UserRole.STUDENT)
            user.role = UserRole.STUDENT
            user.subject = req.subject
            await session.flush()
            today = datetime.now(ZoneInfo(settings.timezone)).date()
            for difficulty in (Difficulty.EASY, Difficulty.MEDIUM, Difficulty.HARD):
                await quiz_service.ensure_daily_quiz(repo, user, today, difficulty, force_regenerate=True)
    if status == RequestStatus.APPROVED:
        await callback.bot.send_message(
            req.telegram_id,
            "Ваша заявка одобрена. Нажмите /start, чтобы начать обучение.",
        )
    else:
        await callback.bot.send_message(req.telegram_id, "Заявка отклонена. Можно подать новую позже.")
    await callback.message.edit_text(f"Заявка #{request_id}: {status.value}")
    await callback.answer("Готово")


@router.message(F.text == "Ученики")
async def list_students(message: Message, settings, session_factory) -> None:
    if not _is_admin(message.from_user.id, settings):
        return
    async with session_scope(session_factory) as session:
        repo = BotRepo(session)
        students = await repo.list_students()
    if not students:
        await message.answer("Учеников пока нет.")
        return
    rows = [f"{s.full_name} | tg_id={s.telegram_id} | предмет: {s.subject or '-'}" for s in students]
    await message.answer("Ученики:\n" + "\n".join(rows))


@router.message(F.text == "Загрузить блокнот")
async def upload_notebook_start(message: Message, state: FSMContext, settings, session_factory) -> None:
    if not _is_admin(message.from_user.id, settings):
        return
    async with session_scope(session_factory) as session:
        repo = BotRepo(session)
        students = await repo.list_students()
    if not students:
        await message.answer("Сначала добавьте ученика.")
        return
    await state.set_state(UploadNotebookState.waiting_student)
    pairs = [(s.id, f"{s.full_name} ({s.subject or '-'})") for s in students]
    await message.answer("Выберите ученика для привязки блокнота:", reply_markup=student_select_kb(pairs))


@router.callback_query(UploadNotebookState.waiting_student, F.data.startswith("pick_student:"))
async def pick_student(callback: CallbackQuery, state: FSMContext, settings) -> None:
    if not _is_admin(callback.from_user.id, settings):
        await callback.answer("Нет доступа", show_alert=True)
        return
    student_id = int(callback.data.split(":")[1])
    await state.update_data(student_id=student_id)
    await state.set_state(UploadNotebookState.waiting_file)
    await callback.message.answer("Теперь отправьте `.ipynb` файлом.")
    await callback.answer()


@router.message(UploadNotebookState.waiting_file, F.document)
async def upload_notebook_file(
    message: Message,
    state: FSMContext,
    settings,
    session_factory,
    llm_client,
) -> None:
    if not _is_admin(message.from_user.id, settings):
        return
    doc = message.document
    if not doc.file_name.lower().endswith(".ipynb"):
        await message.answer("Нужен файл формата `.ipynb`.")
        return
    data = await state.get_data()
    student_id = data.get("student_id")
    if not student_id:
        await message.answer("Сначала выберите ученика.")
        return

    buffer = io.BytesIO()
    await message.bot.download(doc, destination=buffer)
    raw_bytes = buffer.getvalue()

    digest = await build_notebook_digest(raw_bytes, llm_client)

    async with session_scope(session_factory) as session:
        repo = BotRepo(session)
        created = await repo.create_material(
            student_id=student_id,
            title=digest.title,
            source_filename=doc.file_name,
            content_hash=digest.content_hash,
            compact_context=digest.compact_context,
            tokens_estimate=digest.tokens_estimate,
        )
    if created is None:
        await message.answer("Этот блокнот уже загружен для ученика (дубликат по hash).")
    else:
        await message.answer("Блокнот сохранен и сжат в базу знаний.")
    await state.clear()


@router.message(F.text == "Темы ученика")
async def choose_student_for_topics(message: Message, settings, session_factory) -> None:
    if not _is_admin(message.from_user.id, settings):
        return
    async with session_scope(session_factory) as session:
        repo = BotRepo(session)
        students = await repo.list_students()
    if not students:
        await message.answer("Сначала добавьте ученика.")
        return
    pairs = [(s.id, f"{s.full_name} ({s.subject or '-'})") for s in students]
    await message.answer("Выберите ученика для настройки тем:", reply_markup=topic_select_student_kb(pairs))


@router.callback_query(F.data.startswith("topic_student:"))
async def topic_student_selected(callback: CallbackQuery, settings, session_factory) -> None:
    if not _is_admin(callback.from_user.id, settings):
        await callback.answer("Нет доступа", show_alert=True)
        return
    student_id = int(callback.data.split(":")[1])
    text, kb = await _build_topic_editor(session_factory, student_id)
    if kb is None:
        await callback.message.edit_text(text)
    else:
        await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("topic_toggle:"))
async def topic_toggle(callback: CallbackQuery, settings, session_factory) -> None:
    if not _is_admin(callback.from_user.id, settings):
        await callback.answer("Нет доступа", show_alert=True)
        return
    _, _, student_id_raw, idx_raw = callback.data.split(":")
    student_id = int(student_id_raw)
    idx = int(idx_raw)

    async with session_scope(session_factory) as session:
        repo = BotRepo(session)
        available_topics = await repo.list_student_material_topics(student_id)
        if idx < 0 or idx >= len(available_topics):
            await callback.answer("Тема не найдена", show_alert=True)
            return
        selected_topics = set(await repo.get_student_topics(student_id))
        topic = available_topics[idx]
        if topic in selected_topics:
            selected_topics.remove(topic)
            status_txt = "выключена"
        else:
            selected_topics.add(topic)
            status_txt = "включена"
        await repo.replace_student_topics(student_id, list(selected_topics))

    text, kb = await _build_topic_editor(session_factory, student_id)
    if kb is None:
        await callback.message.edit_text(text)
    else:
        await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer(f"Тема {status_txt}")


@router.callback_query(F.data.startswith("topic_clear:"))
async def topic_clear(callback: CallbackQuery, settings, session_factory) -> None:
    if not _is_admin(callback.from_user.id, settings):
        await callback.answer("Нет доступа", show_alert=True)
        return
    student_id = int(callback.data.split(":")[1])
    async with session_scope(session_factory) as session:
        repo = BotRepo(session)
        await repo.replace_student_topics(student_id, [])
    text, kb = await _build_topic_editor(session_factory, student_id)
    if kb is None:
        await callback.message.edit_text(text)
    else:
        await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer("Выбор очищен")


@router.callback_query(F.data.startswith("topic_generate:"))
async def topic_generate(callback: CallbackQuery, settings, session_factory, quiz_service) -> None:
    if not _is_admin(callback.from_user.id, settings):
        await callback.answer("Нет доступа", show_alert=True)
        return
    student_id = int(callback.data.split(":")[1])
    await callback.answer("Генерирую...")

    today = datetime.now(ZoneInfo(settings.timezone)).date()
    async with session_scope(session_factory) as session:
        repo = BotRepo(session)
        student = await repo.get_user_by_id(student_id)
        if not student or student.role != UserRole.STUDENT:
            await callback.message.answer("Ученик не найден.")
            return
        for difficulty in (Difficulty.EASY, Difficulty.MEDIUM, Difficulty.HARD):
            await quiz_service.ensure_daily_quiz(repo, student, today, difficulty, force_regenerate=True)
        selected_topics = await repo.get_student_topics(student_id)
    await callback.message.answer(
        f"Готово: {student.full_name}, дата {today}, по 10 заданий на каждую сложность.\n"
        f"Темы: {', '.join(selected_topics) if selected_topics else 'все доступные материалы'}."
    )


@router.message(F.text == "Сгенерировать задания")
async def generate_for_today(message: Message, settings, session_factory, quiz_service) -> None:
    if not _is_admin(message.from_user.id, settings):
        return
    today = datetime.now(ZoneInfo(settings.timezone)).date()
    async with session_scope(session_factory) as session:
        repo = BotRepo(session)
        students = await repo.list_students()
        for student in students:
            for difficulty in (Difficulty.EASY, Difficulty.MEDIUM, Difficulty.HARD):
                await quiz_service.ensure_daily_quiz(repo, student, today, difficulty, force_regenerate=True)
    await message.answer(f"Готово. Сгенерированы задания на {today}.")
