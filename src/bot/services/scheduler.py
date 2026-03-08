from __future__ import annotations

import logging
from datetime import datetime

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from zoneinfo import ZoneInfo

from src.db.repo import BotRepo
from src.db.session import session_scope

log = logging.getLogger(__name__)


def build_scheduler(settings, session_factory, quiz_service, bot: Bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=ZoneInfo(settings.timezone))

    async def send_morning_reminders() -> None:
        now_msk = datetime.now(ZoneInfo("Europe/Moscow"))
        async with session_scope(session_factory) as session:
            repo = BotRepo(session)
            students = await repo.list_students()

        for student in students:
            try:
                await bot.send_message(
                    student.telegram_id,
                    (
                        f"Доброе утро, {student.full_name}!\n"
                        f"Проверьте задания в Mini App: {now_msk.strftime('%d.%m.%Y %H:%M')} (МСК).\n"
                        "Можно пройти текущие задания или сгенерировать новые, если доступно."
                    ),
                )
            except Exception:
                log.exception("Failed to send reminder to student telegram_id=%s", student.telegram_id)

        log.info("Sent morning reminders to %s students", len(students))

    scheduler.add_job(
        send_morning_reminders,
        CronTrigger(hour=9, minute=0, timezone=ZoneInfo("Europe/Moscow")),
        id="daily_student_reminders",
    )
    return scheduler
