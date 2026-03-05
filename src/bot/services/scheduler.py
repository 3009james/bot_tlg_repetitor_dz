from __future__ import annotations

import logging
from datetime import datetime

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from zoneinfo import ZoneInfo

from src.bot.services.quiz_service import QuizService
from src.db.models import Difficulty
from src.db.repo import BotRepo
from src.db.session import session_scope

log = logging.getLogger(__name__)


def build_scheduler(settings, session_factory, quiz_service: QuizService, bot: Bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=ZoneInfo(settings.timezone))

    async def generate_daily_jobs() -> None:
        now = datetime.now(ZoneInfo(settings.timezone)).date()
        async with session_scope(session_factory) as session:
            repo = BotRepo(session)
            students = await repo.list_students()
            for student in students:
                for difficulty in (Difficulty.EASY, Difficulty.MEDIUM, Difficulty.HARD):
                    await quiz_service.ensure_daily_quiz(repo, student, now, difficulty, force_regenerate=True)
        log.info("Generated daily quizzes for %s", now)

    async def send_morning_reminders() -> None:
        now_msk = datetime.now(ZoneInfo("Europe/Moscow"))
        quiz_date = now_msk.date()
        async with session_scope(session_factory) as session:
            repo = BotRepo(session)
            students = await repo.list_students()

        for student in students:
            try:
                await bot.send_message(
                    student.telegram_id,
                    (
                        f"Доброе утро, {student.full_name}!\n"
                        f"Новые задания на {quiz_date} уже доступны. "
                        "Откройте бота и нажмите «Пройти обучение»."
                    ),
                )
            except Exception:
                log.exception("Failed to send reminder to student telegram_id=%s", student.telegram_id)

        log.info("Sent morning reminders for %s to %s students", quiz_date, len(students))

    scheduler.add_job(generate_daily_jobs, CronTrigger(hour=0, minute=0), id="daily_quiz_generation")
    scheduler.add_job(
        send_morning_reminders,
        CronTrigger(hour=9, minute=0, timezone=ZoneInfo("Europe/Moscow")),
        id="daily_student_reminders",
    )
    return scheduler
