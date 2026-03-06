from __future__ import annotations

import json
from datetime import date

from src.bot.services.routerai_client import RouterAIClient
from src.db.models import Difficulty, LessonType, QuizStatus, User
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

    async def ensure_lesson_type_daily_quizzes(
        self,
        repo: BotRepo,
        lesson_type: LessonType,
        quiz_date: date,
        force_regenerate: bool = False,
    ) -> int:
        students = await repo.list_students_by_lesson_type(lesson_type.id)

        for difficulty in (Difficulty.EASY, Difficulty.MEDIUM, Difficulty.HARD):
            questions = await self._get_or_generate_lesson_type_questions(
                repo=repo,
                lesson_type=lesson_type,
                quiz_date=quiz_date,
                difficulty=difficulty,
                force_regenerate=force_regenerate,
            )
            for student in students:
                quiz = await repo.get_quiz(student.id, quiz_date, difficulty)
                if not quiz:
                    quiz = await repo.create_quiz(student.id, quiz_date, difficulty)
                await repo.replace_quiz_questions(quiz.id, questions)
                quiz.status = QuizStatus.READY
                await repo.reset_progress(quiz.id, student.id)
        return len(students)

    async def _get_or_generate_lesson_type_questions(
        self,
        repo: BotRepo,
        lesson_type: LessonType,
        quiz_date: date,
        difficulty: Difficulty,
        force_regenerate: bool,
    ) -> list[dict]:
        pack = await repo.get_lesson_type_daily_pack(lesson_type.id, quiz_date, difficulty)
        if pack and not force_regenerate:
            return json.loads(pack.questions_json)

        selected_topics = await repo.get_lesson_type_topics(lesson_type.id)
        if selected_topics:
            materials = await repo.get_lesson_type_materials_by_topics(lesson_type.id, selected_topics, limit=40)
        else:
            materials = await repo.get_lesson_type_materials(lesson_type.id, limit=40)
        context = self._build_lesson_type_context(lesson_type.name, materials, selected_topics)
        questions = await self.llm.generate_questions(context, difficulty.value, count=10)
        await repo.upsert_lesson_type_daily_pack(lesson_type.id, quiz_date, difficulty, questions)
        return questions

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

    @staticmethod
    def _build_lesson_type_context(lesson_type_name: str, materials, selected_topics: list[str]) -> str:
        chunks = [m.compact_context for m in materials if m.compact_context]
        topics_hint = ""
        if selected_topics:
            topics_hint = "Выбранные темы: " + "; ".join(selected_topics[:20]) + "\n\n"
        if not chunks:
            return (
                f"Предмет: {lesson_type_name}\n"
                f"{topics_hint}"
                "Материалы не загружены. Сгенерируй базовые тренировочные задания по выбранному предмету."
            )
        return f"Предмет: {lesson_type_name}\n{topics_hint}" + "\n\n---\n\n".join(chunks[:25])[:30000]
