from __future__ import annotations

import asyncio
import logging

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties

from src.bot.app import build_dispatcher
from src.bot.services.quiz_service import QuizService
from src.bot.services.routerai_client import RouterAIClient
from src.bot.services.scheduler import build_scheduler
from src.core.config import get_settings
from src.core.logging import setup_logging
from src.db.repo import BotRepo
from src.db.session import create_db, create_engine_and_factory
from src.db.session import session_scope

log = logging.getLogger(__name__)


async def main() -> None:
    setup_logging()
    settings = get_settings()

    engine, session_factory = create_engine_and_factory(settings)
    await create_db(engine)
    async with session_scope(session_factory) as session:
        repo = BotRepo(session)
        await repo.ensure_default_lesson_types()

    bot = Bot(token=settings.bot_token, default=DefaultBotProperties(parse_mode="HTML"))
    dp = build_dispatcher()

    llm_client = RouterAIClient(
        api_key=settings.routerai_api_key,
        base_url=settings.routerai_base_url,
        model=settings.routerai_model,
    )
    quiz_service = QuizService(llm=llm_client)
    scheduler = build_scheduler(settings, session_factory, quiz_service, bot)
    scheduler.start()

    log.info("Bot started")
    try:
        await dp.start_polling(
            bot,
            settings=settings,
            session_factory=session_factory,
            llm_client=llm_client,
            quiz_service=quiz_service,
        )
    finally:
        scheduler.shutdown(wait=False)
        await bot.session.close()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
