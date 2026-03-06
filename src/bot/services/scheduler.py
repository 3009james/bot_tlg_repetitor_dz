from __future__ import annotations

import logging
from datetime import datetime

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from zoneinfo import ZoneInfo

from src.bot.services.quiz_service import QuizService
from src.db.repo import BotRepo
from src.db.session import session_scope

log = logging.getLogger(__name__)


def build_scheduler(settings, session_factory, quiz_service: QuizService, bot: Bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=ZoneInfo(settings.timezone))

    async def generate_auto_lesson_type_jobs() -> None:
        now_dt = datetime.now(ZoneInfo(settings.timezone))
        now = now_dt.date()
        async with session_scope(session_factory) as session:
            repo = BotRepo(session)
            lesson_types = await repo.list_auto_lesson_types_for_time(hour=now_dt.hour, minute=now_dt.minute)
            if not lesson_types:
                return
            for lesson_type in lesson_types:
                students_count = await quiz_service.ensure_lesson_type_daily_quizzes(
                    repo=repo,
                    lesson_type=lesson_type,
                    quiz_date=now,
                    force_regenerate=True,
                )
                log.info(
                    "Generated daily quizzes for lesson_type=%s date=%s students=%s",
                    lesson_type.name,
                    now,
                    students_count,
                )

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
                        f"Занятия обновлены: {now_msk.strftime('%d.%m.%Y %H:%M')} (МСК).\n"
                        f"Новые задания на {quiz_date} уже доступны в приложении."
                    ),
                )
            except Exception:
                log.exception("Failed to send reminder to student telegram_id=%s", student.telegram_id)

        log.info("Sent morning reminders for %s to %s students", quiz_date, len(students))

    scheduler.add_job(generate_auto_lesson_type_jobs, CronTrigger(minute="*"), id="auto_lesson_type_generation")
    scheduler.add_job(
        send_morning_reminders,
        CronTrigger(hour=9, minute=0, timezone=ZoneInfo("Europe/Moscow")),
        id="daily_student_reminders",
    )
    return scheduler
