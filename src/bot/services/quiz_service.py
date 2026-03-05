from __future__ import annotations

from datetime import date

from src.bot.services.routerai_client import RouterAIClient
from src.db.models import Difficulty, QuizStatus, User
from src.db.repo import BotRepo


class QuizService:
    def __init__(self, llm: RouterAIClient):
        self.llm = llm

    async def ensure_daily_quiz(
        self,
        repo: BotRepo,
        student: User,
        quiz_date: date,
        difficulty: Difficulty,
        force_regenerate: bool = False,
    ):
        quiz = await repo.get_quiz(student.id, quiz_date, difficulty)
        if quiz and not force_regenerate:
            return quiz
        if not quiz:
            quiz = await repo.create_quiz(student.id, quiz_date, difficulty)

        selected_topics = await repo.get_student_topics(student.id)
        if selected_topics:
            materials = await repo.get_student_materials_by_topics(student.id, selected_topics, limit=40)
        else:
            materials = await repo.get_student_materials(student.id, limit=40)
        context = self._build_context(materials, selected_topics)
        questions = await self.llm.generate_questions(context, difficulty.value, count=10)
        await repo.replace_quiz_questions(quiz.id, questions)
        quiz.status = QuizStatus.READY
        await repo.reset_progress(quiz.id, student.id)
        return quiz

    @staticmethod
    def _build_context(materials, selected_topics: list[str]) -> str:
        chunks = [m.compact_context for m in materials if m.compact_context]
        topics_hint = ""
        if selected_topics:
            topics_hint = "Приоритетные темы: " + "; ".join(selected_topics[:20]) + "\n\n"
        if not chunks:
            return (
                f"{topics_hint}База уроков пока пустая. "
                "Сгенерируй общий тренировочный тест по предмету и отмеченным темам."
            )
        return f"{topics_hint}" + "\n\n---\n\n".join(chunks[:25])[:30000]
