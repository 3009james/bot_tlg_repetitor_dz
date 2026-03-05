from __future__ import annotations

import json
from datetime import date, datetime, timezone

from sqlalchemy import and_, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import (
    AccessRequest,
    AnswerLog,
    DailyQuestion,
    DailyQuiz,
    Difficulty,
    LessonMaterial,
    RequestStatus,
    StudentTopic,
    StudentProgress,
    User,
    UserRole,
)


class BotRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def upsert_user(self, telegram_id: int, full_name: str, username: str | None, role: UserRole) -> User:
        stmt = select(User).where(User.telegram_id == telegram_id)
        user = await self.session.scalar(stmt)
        if user:
            user.full_name = full_name or user.full_name
            user.username = username
            if user.role != UserRole.ADMIN:
                user.role = role
            return user
        user = User(telegram_id=telegram_id, full_name=full_name, username=username, role=role)
        self.session.add(user)
        await self.session.flush()
        return user

    async def set_user_role(self, telegram_id: int, role: UserRole, subject: str | None = None) -> User | None:
        user = await self.get_user_by_telegram(telegram_id)
        if not user:
            return None
        user.role = role
        if subject is not None:
            user.subject = subject
        await self.session.flush()
        return user

    async def get_user_by_telegram(self, telegram_id: int) -> User | None:
        return await self.session.scalar(select(User).where(User.telegram_id == telegram_id))

    async def get_user_by_id(self, user_id: int) -> User | None:
        return await self.session.scalar(select(User).where(User.id == user_id))

    async def list_students(self) -> list[User]:
        result = await self.session.scalars(select(User).where(User.role == UserRole.STUDENT).order_by(User.full_name))
        return list(result)

    async def create_access_request(
        self, telegram_id: int, full_name: str, username: str | None, subject: str | None, message: str | None
    ) -> AccessRequest:
        req = AccessRequest(
            telegram_id=telegram_id,
            full_name=full_name,
            username=username,
            subject=subject,
            message=message,
            status=RequestStatus.PENDING,
        )
        self.session.add(req)
        await self.session.flush()
        return req

    async def get_pending_request(self, telegram_id: int) -> AccessRequest | None:
        stmt = (
            select(AccessRequest)
            .where(and_(AccessRequest.telegram_id == telegram_id, AccessRequest.status == RequestStatus.PENDING))
            .order_by(AccessRequest.created_at.desc())
            .limit(1)
        )
        return await self.session.scalar(stmt)

    async def list_pending_requests(self) -> list[AccessRequest]:
        result = await self.session.scalars(
            select(AccessRequest).where(AccessRequest.status == RequestStatus.PENDING).order_by(AccessRequest.created_at)
        )
        return list(result)

    async def handle_request(self, request_id: int, status: RequestStatus, admin_telegram_id: int) -> AccessRequest | None:
        req = await self.session.scalar(select(AccessRequest).where(AccessRequest.id == request_id))
        if not req:
            return None
        req.status = status
        req.handled_by = admin_telegram_id
        req.handled_at = datetime.now(timezone.utc)
        await self.session.flush()
        return req

    async def create_material(
        self,
        student_id: int,
        title: str,
        source_filename: str,
        content_hash: str,
        compact_context: str,
        tokens_estimate: int,
    ) -> LessonMaterial | None:
        existing = await self.session.scalar(
            select(LessonMaterial).where(
                and_(LessonMaterial.student_id == student_id, LessonMaterial.content_hash == content_hash)
            )
        )
        if existing:
            return None
        material = LessonMaterial(
            student_id=student_id,
            title=title,
            source_filename=source_filename,
            content_hash=content_hash,
            compact_context=compact_context,
            tokens_estimate=tokens_estimate,
        )
        self.session.add(material)
        await self.session.flush()
        return material

    async def get_student_materials(self, student_id: int, limit: int = 30) -> list[LessonMaterial]:
        result = await self.session.scalars(
            select(LessonMaterial)
            .where(LessonMaterial.student_id == student_id)
            .order_by(LessonMaterial.created_at.desc())
            .limit(limit)
        )
        return list(result)

    async def get_student_materials_by_topics(
        self, student_id: int, topics: list[str], limit: int = 30
    ) -> list[LessonMaterial]:
        cleaned = [t.strip() for t in topics if t and t.strip()]
        if not cleaned:
            return await self.get_student_materials(student_id, limit=limit)
        result = await self.session.scalars(
            select(LessonMaterial)
            .where(and_(LessonMaterial.student_id == student_id, LessonMaterial.title.in_(cleaned)))
            .order_by(LessonMaterial.created_at.desc())
            .limit(limit)
        )
        return list(result)

    async def list_student_material_topics(self, student_id: int, limit: int = 200) -> list[str]:
        result = await self.session.scalars(
            select(LessonMaterial.title)
            .where(LessonMaterial.student_id == student_id)
            .order_by(LessonMaterial.created_at.desc())
            .limit(limit)
        )
        topics: list[str] = []
        seen: set[str] = set()
        for raw in result:
            title = (raw or "").strip()
            if not title or title in seen:
                continue
            topics.append(title)
            seen.add(title)
        return topics

    async def get_student_topics(self, student_id: int) -> list[str]:
        result = await self.session.scalars(
            select(StudentTopic.topic)
            .where(StudentTopic.student_id == student_id)
            .order_by(StudentTopic.topic.asc())
        )
        return [x for x in result]

    async def replace_student_topics(self, student_id: int, topics: list[str]) -> list[str]:
        cleaned = sorted({t.strip() for t in topics if t and t.strip()})
        await self.session.execute(delete(StudentTopic).where(StudentTopic.student_id == student_id))
        for topic in cleaned:
            self.session.add(StudentTopic(student_id=student_id, topic=topic))
        await self.session.flush()
        return cleaned

    async def get_quiz(self, student_id: int, quiz_date: date, difficulty: Difficulty) -> DailyQuiz | None:
        stmt = select(DailyQuiz).where(
            and_(DailyQuiz.student_id == student_id, DailyQuiz.quiz_date == quiz_date, DailyQuiz.difficulty == difficulty)
        )
        return await self.session.scalar(stmt)

    async def get_quiz_by_id(self, quiz_id: int) -> DailyQuiz | None:
        return await self.session.scalar(select(DailyQuiz).where(DailyQuiz.id == quiz_id))

    async def create_quiz(self, student_id: int, quiz_date: date, difficulty: Difficulty) -> DailyQuiz:
        quiz = DailyQuiz(student_id=student_id, quiz_date=quiz_date, difficulty=difficulty)
        self.session.add(quiz)
        await self.session.flush()
        return quiz

    async def replace_quiz_questions(self, quiz_id: int, questions: list[dict]) -> None:
        await self.session.execute(delete(DailyQuestion).where(DailyQuestion.quiz_id == quiz_id))
        for i, q in enumerate(questions, start=1):
            row = DailyQuestion(
                quiz_id=quiz_id,
                position=i,
                question_text=q["question"],
                options_json=json.dumps(q["options"], ensure_ascii=False),
                correct_option_index=q["correct_index"],
                explanation=q.get("explanation", ""),
            )
            self.session.add(row)
        await self.session.flush()

    async def get_quiz_question(self, quiz_id: int, position: int) -> DailyQuestion | None:
        stmt = select(DailyQuestion).where(and_(DailyQuestion.quiz_id == quiz_id, DailyQuestion.position == position))
        return await self.session.scalar(stmt)

    async def get_quiz_questions_count(self, quiz_id: int) -> int:
        stmt = select(func.count()).select_from(DailyQuestion).where(DailyQuestion.quiz_id == quiz_id)
        count = await self.session.scalar(stmt)
        return int(count or 0)

    async def get_or_create_progress(self, quiz_id: int, student_id: int) -> StudentProgress:
        progress = await self.session.scalar(
            select(StudentProgress).where(and_(StudentProgress.quiz_id == quiz_id, StudentProgress.student_id == student_id))
        )
        if progress:
            return progress
        progress = StudentProgress(quiz_id=quiz_id, student_id=student_id)
        self.session.add(progress)
        await self.session.flush()
        return progress

    async def reset_progress(self, quiz_id: int, student_id: int) -> StudentProgress:
        progress = await self.get_or_create_progress(quiz_id, student_id)
        progress.current_position = 1
        progress.total_answered = 0
        progress.correct_answers = 0
        progress.finished_at = None
        await self.session.execute(
            delete(AnswerLog).where(and_(AnswerLog.quiz_id == quiz_id, AnswerLog.student_id == student_id))
        )
        await self.session.flush()
        return progress

    async def log_answer(
        self, quiz_id: int, question_id: int, student_id: int, selected_index: int, is_correct: bool
    ) -> AnswerLog:
        row = AnswerLog(
            quiz_id=quiz_id,
            question_id=question_id,
            student_id=student_id,
            selected_option_index=selected_index,
            is_correct=1 if is_correct else 0,
        )
        self.session.add(row)
        await self.session.flush()
        return row
