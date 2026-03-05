from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from src.bot.keyboards.common import difficulty_kb, mode_kb, next_question_kb, question_options_kb, student_home_kb
from src.bot.states import StudentFlowState
from src.db.models import Difficulty, QuizStatus, UserRole
from src.db.repo import BotRepo
from src.db.session import session_scope

router = Router()


DIFFICULTY_MAP = {
    "Легко": Difficulty.EASY,
    "Средне": Difficulty.MEDIUM,
    "Сложно": Difficulty.HARD,
    "easy": Difficulty.EASY,
    "medium": Difficulty.MEDIUM,
    "hard": Difficulty.HARD,
}


async def _get_student(repo: BotRepo, telegram_id: int):
    user = await repo.get_user_by_telegram(telegram_id)
    if not user or user.role != UserRole.STUDENT:
        return None
    return user


@router.message(F.text == "Пройти обучение")
async def start_learning(message: Message, state: FSMContext, session_factory) -> None:
    async with session_scope(session_factory) as session:
        repo = BotRepo(session)
        student = await _get_student(repo, message.from_user.id)
    if not student:
        await message.answer("Доступ к обучению пока недоступен.", reply_markup=student_home_kb())
        return
    await state.set_state(StudentFlowState.waiting_mode)
    await message.answer("Выберите режим:", reply_markup=mode_kb())


@router.message(StudentFlowState.waiting_mode, F.text == "Тестирование")
async def choose_test_mode(message: Message, state: FSMContext) -> None:
    await state.set_state(StudentFlowState.waiting_difficulty)
    await message.answer("Выберите сложность:", reply_markup=difficulty_kb())


@router.message(StudentFlowState.waiting_mode, F.text == "Вручную (скоро)")
async def manual_mode_placeholder(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Режим вручную добавим следующим этапом.")


@router.message(StudentFlowState.waiting_difficulty)
async def run_test(message: Message, state: FSMContext, settings, session_factory, quiz_service) -> None:
    difficulty = DIFFICULTY_MAP.get(message.text)
    if difficulty is None:
        await message.answer("Выберите кнопку сложности.")
        return

    await _run_test_for_difficulty(message, state, settings, session_factory, quiz_service, difficulty)


async def _run_test_for_difficulty(message: Message, state: FSMContext, settings, session_factory, quiz_service, difficulty):
    today = datetime.now(ZoneInfo(settings.timezone)).date()
    async with session_scope(session_factory) as session:
        repo = BotRepo(session)
        student = await _get_student(repo, message.from_user.id)
        if not student:
            await message.answer("Доступ к обучению пока недоступен.")
            return
        quiz = await quiz_service.ensure_daily_quiz(repo, student, today, difficulty)
        await repo.get_or_create_progress(quiz.id, student.id)
    await state.clear()
    await send_question(message, session_factory, quiz.id, 1)


@router.message(F.web_app_data)
async def handle_webapp_data(message: Message, state: FSMContext, settings, session_factory, quiz_service) -> None:
    if not message.web_app_data or not message.web_app_data.data:
        return
    try:
        payload = json.loads(message.web_app_data.data)
    except json.JSONDecodeError:
        await message.answer("Некорректные данные из приложения.")
        return

    action = str(payload.get("action", "")).strip().lower()
    if action == "manual":
        await state.clear()
        await message.answer("Режим вручную добавим следующим этапом.")
        return
    if action != "start_quiz":
        await message.answer("Неизвестная команда приложения.")
        return

    difficulty_raw = str(payload.get("difficulty", "")).strip().lower()
    difficulty = DIFFICULTY_MAP.get(difficulty_raw)
    if difficulty is None:
        await message.answer("Не выбрана сложность.")
        return

    await _run_test_for_difficulty(message, state, settings, session_factory, quiz_service, difficulty)


async def send_question(target, session_factory, quiz_id: int, position: int) -> None:
    async with session_scope(session_factory) as session:
        repo = BotRepo(session)
        question = await repo.get_quiz_question(quiz_id, position)
        total = await repo.get_quiz_questions_count(quiz_id)
    if not question:
        await target.answer("Вопрос не найден.")
        return
    options = json.loads(question.options_json)
    text = f"Задание {position}/{total}\n\n{question.question_text}"
    await target.answer(text, reply_markup=question_options_kb(quiz_id, position, options))


@router.callback_query(F.data.startswith("ans:"))
async def answer_question(callback: CallbackQuery, session_factory) -> None:
    _, quiz_id_raw, position_raw, selected_raw = callback.data.split(":")
    quiz_id = int(quiz_id_raw)
    position = int(position_raw)
    selected = int(selected_raw)

    async with session_scope(session_factory) as session:
        repo = BotRepo(session)
        user = await repo.get_user_by_telegram(callback.from_user.id)
        if not user or user.role != UserRole.STUDENT:
            await callback.answer("Нет доступа", show_alert=True)
            return
        quiz = await repo.get_quiz_by_id(quiz_id)
        if not quiz or quiz.student_id != user.id:
            await callback.answer("Нет доступа к этому тесту", show_alert=True)
            return
        progress = await repo.get_or_create_progress(quiz_id, user.id)
        question = await repo.get_quiz_question(quiz_id, position)
        if not question:
            await callback.answer("Вопрос не найден", show_alert=True)
            return

        if position != progress.current_position:
            await callback.answer("Этот вопрос уже обработан.")
            return

        correct = selected == question.correct_option_index
        progress.total_answered += 1
        if correct:
            progress.correct_answers += 1
        progress.current_position += 1
        await repo.log_answer(quiz_id, question.id, user.id, selected, correct)

        total = await repo.get_quiz_questions_count(quiz_id)
        explanation = question.explanation or "Пояснение не указано."
        if progress.current_position > total:
            quiz = await repo.get_quiz_by_id(quiz_id)
            if quiz:
                quiz.status = QuizStatus.COMPLETED
            msg = (
                f"{'Верно' if correct else 'Неверно'}.\n"
                f"Правильный ответ: {question.correct_option_index + 1}\n"
                f"{explanation}\n\n"
                f"Тест завершен.\nРезультат: {progress.correct_answers}/{total}"
            )
            await callback.message.answer(msg)
            await callback.answer()
            return

    msg = (
        f"{'Верно' if correct else 'Неверно'}.\n"
        f"Правильный ответ: {question.correct_option_index + 1}\n"
        f"{question.explanation or ''}"
    )
    await callback.message.answer(msg, reply_markup=next_question_kb(quiz_id, position + 1))
    await callback.answer()


@router.callback_query(F.data.startswith("next:"))
async def next_question(callback: CallbackQuery, session_factory) -> None:
    _, quiz_id_raw, position_raw = callback.data.split(":")
    quiz_id = int(quiz_id_raw)
    async with session_scope(session_factory) as session:
        repo = BotRepo(session)
        user = await repo.get_user_by_telegram(callback.from_user.id)
        quiz = await repo.get_quiz_by_id(quiz_id)
        if not user or user.role != UserRole.STUDENT or not quiz or quiz.student_id != user.id:
            await callback.answer("Нет доступа к этому тесту", show_alert=True)
            return
    await send_question(callback.message, session_factory, quiz_id, int(position_raw))
    await callback.answer()
