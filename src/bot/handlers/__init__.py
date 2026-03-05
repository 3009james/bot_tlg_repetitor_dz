from src.bot.handlers.admin import router as admin_router
from src.bot.handlers.start import router as start_router
from src.bot.handlers.student import router as student_router

__all__ = ["admin_router", "start_router", "student_router"]
