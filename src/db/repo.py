from __future__ import annotations

import json
from datetime import date, datetime, timezone

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import (
    AccessRequest,
    AnswerLog,
    DailyQuestion,
    DailyQuiz,
    Difficulty,
    GenerationMode,
    LessonType,
    LessonTypeDailyPack,
    LessonTypeMaterial,
    LessonTypeMaterialTopic,
    LessonTypeStudent,
    LessonTypeTopic,
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

    @staticmethod
    def _clean_topic(raw: str | None) -> str:
        topic = (raw or "").replace("`", " ").strip()
        topic = topic.lstrip("#> ").strip().strip("-•*")
        while "  " in topic:
            topic = topic.replace("  ", " ")
        return topic[:255]

    @staticmethod
    def _is_noise_topic(topic: str) -> bool:
        low = topic.lower().strip()
        if not low:
            return True
        if low in {"markdown", "md", "json", "yaml", "code", "text", "текст"}:
            return True
        if "```" in topic:
            return True
        return False

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

    async def ensure_default_lesson_types(self) -> None:
        defaults = [
            ("C++", "cpp"),
            ("Python", "python"),
            ("Математика", "math"),
        ]
        for name, slug in defaults:
            row = await self.session.scalar(select(LessonType).where(LessonType.slug == slug))
            if row:
                continue
            self.session.add(
                LessonType(
                    name=name,
                    slug=slug,
                    generation_mode=GenerationMode.MANUAL,
                    generate_hour=0,
                    generate_minute=0,
                )
            )
        await self.session.flush()

    async def list_lesson_types(self) -> list[LessonType]:
        result = await self.session.scalars(select(LessonType).order_by(LessonType.name.asc()))
        return list(result)

    async def get_lesson_type(self, lesson_type_id: int) -> LessonType | None:
        return await self.session.scalar(select(LessonType).where(LessonType.id == lesson_type_id))

    async def set_lesson_type_schedule(
        self, lesson_type_id: int, mode: GenerationMode, generate_hour: int, generate_minute: int
    ) -> LessonType | None:
        lesson_type = await self.get_lesson_type(lesson_type_id)
        if not lesson_type:
            return None
        lesson_type.generation_mode = mode
        lesson_type.generate_hour = max(0, min(23, int(generate_hour)))
        lesson_type.generate_minute = max(0, min(59, int(generate_minute)))
        await self.session.flush()
        return lesson_type

    async def list_auto_lesson_types_for_time(self, hour: int, minute: int) -> list[LessonType]:
        result = await self.session.scalars(
            select(LessonType).where(
                and_(
                    LessonType.generation_mode == GenerationMode.AUTO,
                    LessonType.generate_hour == int(hour),
                    LessonType.generate_minute == int(minute),
                )
            )
        )
        return list(result)

    async def list_students_by_lesson_type(self, lesson_type_id: int) -> list[User]:
        result = await self.session.scalars(
            select(User)
            .join(LessonTypeStudent, LessonTypeStudent.student_id == User.id)
            .where(and_(LessonTypeStudent.lesson_type_id == lesson_type_id, User.role == UserRole.STUDENT))
            .order_by(User.full_name.asc())
        )
        return list(result)

    async def get_student_lesson_types(self, student_id: int) -> list[LessonType]:
        result = await self.session.scalars(
            select(LessonType)
            .join(LessonTypeStudent, LessonTypeStudent.lesson_type_id == LessonType.id)
            .where(LessonTypeStudent.student_id == student_id)
            .order_by(LessonType.name.asc())
        )
        return list(result)

    async def replace_lesson_type_students(self, lesson_type_id: int, student_ids: list[int]) -> list[int]:
        cleaned = sorted({int(x) for x in student_ids if int(x) > 0})
        await self.session.execute(delete(LessonTypeStudent).where(LessonTypeStudent.lesson_type_id == lesson_type_id))
        for student_id in cleaned:
            self.session.add(LessonTypeStudent(lesson_type_id=lesson_type_id, student_id=student_id))
        await self.session.flush()
        return cleaned

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

    async def create_lesson_type_material(
        self,
        lesson_type_id: int,
        title: str,
        source_filename: str,
        content_hash: str,
        compact_context: str,
        tokens_estimate: int,
    ) -> LessonTypeMaterial | None:
        existing = await self.session.scalar(
            select(LessonTypeMaterial).where(
                and_(LessonTypeMaterial.lesson_type_id == lesson_type_id, LessonTypeMaterial.content_hash == content_hash)
            )
        )
        if existing:
            return None
        material = LessonTypeMaterial(
            lesson_type_id=lesson_type_id,
            title=title,
            source_filename=source_filename,
            content_hash=content_hash,
            compact_context=compact_context,
            tokens_estimate=tokens_estimate,
        )
        self.session.add(material)
        await self.session.flush()
        return material

    async def get_lesson_type_material_by_hash(self, lesson_type_id: int, content_hash: str) -> LessonTypeMaterial | None:
        return await self.session.scalar(
            select(LessonTypeMaterial).where(
                and_(LessonTypeMaterial.lesson_type_id == lesson_type_id, LessonTypeMaterial.content_hash == content_hash)
            )
        )

    async def get_lesson_type_material_by_id(self, lesson_type_id: int, material_id: int) -> LessonTypeMaterial | None:
        return await self.session.scalar(
            select(LessonTypeMaterial).where(
                and_(LessonTypeMaterial.lesson_type_id == lesson_type_id, LessonTypeMaterial.id == material_id)
            )
        )

    async def replace_lesson_type_material_topics(
        self, lesson_type_id: int, material_id: int, topics: list[str]
    ) -> list[str]:
        cleaned = []
        seen: set[str] = set()
        for raw in topics:
            topic = self._clean_topic(raw)
            if self._is_noise_topic(topic):
                continue
            key = topic.lower()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(topic)
        await self.session.execute(delete(LessonTypeMaterialTopic).where(LessonTypeMaterialTopic.material_id == material_id))
        for topic in cleaned:
            self.session.add(
                LessonTypeMaterialTopic(
                    lesson_type_id=lesson_type_id,
                    material_id=material_id,
                    topic=topic,
                )
            )
        await self.session.flush()
        return cleaned

    async def get_lesson_type_material_topics(self, material_id: int) -> list[str]:
        result = await self.session.scalars(
            select(LessonTypeMaterialTopic.topic)
            .where(LessonTypeMaterialTopic.material_id == material_id)
            .order_by(LessonTypeMaterialTopic.topic.asc())
        )
        topics: list[str] = []
        seen: set[str] = set()
        for raw in result:
            topic = self._clean_topic(raw)
            if self._is_noise_topic(topic):
                continue
            key = topic.lower()
            if key in seen:
                continue
            seen.add(key)
            topics.append(topic)
        return topics

    async def delete_lesson_type_material(self, lesson_type_id: int, material_id: int) -> bool:
        material = await self.get_lesson_type_material_by_id(lesson_type_id, material_id)
        if not material:
            return False
        await self.session.execute(delete(LessonTypeMaterialTopic).where(LessonTypeMaterialTopic.material_id == material_id))
        await self.session.delete(material)
        await self.session.flush()
        return True

    async def get_lesson_type_materials(self, lesson_type_id: int, limit: int = 30) -> list[LessonTypeMaterial]:
        result = await self.session.scalars(
            select(LessonTypeMaterial)
            .where(LessonTypeMaterial.lesson_type_id == lesson_type_id)
            .order_by(LessonTypeMaterial.created_at.desc())
            .limit(limit)
        )
        return list(result)

    async def get_lesson_type_materials_by_topics(
        self, lesson_type_id: int, topics: list[str], limit: int = 30
    ) -> list[LessonTypeMaterial]:
        cleaned = [t.strip() for t in topics if t and t.strip()]
        if not cleaned:
            return await self.get_lesson_type_materials(lesson_type_id, limit=limit)
        result = await self.session.scalars(
            select(LessonTypeMaterial)
            .join(
                LessonTypeMaterialTopic,
                LessonTypeMaterialTopic.material_id == LessonTypeMaterial.id,
                isouter=True,
            )
            .where(
                and_(
                    LessonTypeMaterial.lesson_type_id == lesson_type_id,
                    or_(
                        LessonTypeMaterialTopic.topic.in_(cleaned),
                        LessonTypeMaterial.title.in_(cleaned),
                    ),
                )
            )
            .distinct()
            .order_by(LessonTypeMaterial.created_at.desc())
            .limit(limit)
        )
        return list(result)

    async def list_lesson_type_material_topics(self, lesson_type_id: int, limit: int = 200) -> list[str]:
        result = await self.session.scalars(
            select(LessonTypeMaterialTopic.topic)
            .where(LessonTypeMaterialTopic.lesson_type_id == lesson_type_id)
            .order_by(LessonTypeMaterialTopic.topic.asc())
            .limit(limit)
        )
        topics: list[str] = []
        seen: set[str] = set()
        for raw in result:
            title = self._clean_topic(raw)
            if self._is_noise_topic(title):
                continue
            key = title.lower()
            if key in seen:
                continue
            topics.append(title)
            seen.add(key)
        if topics:
            return topics
        # Backward-compatible fallback for old materials where topic extraction was not stored.
        legacy = await self.session.scalars(
            select(LessonTypeMaterial.title)
            .where(LessonTypeMaterial.lesson_type_id == lesson_type_id)
            .order_by(LessonTypeMaterial.created_at.desc())
            .limit(limit)
        )
        for raw in legacy:
            title = self._clean_topic(raw)
            if self._is_noise_topic(title):
                continue
            key = title.lower()
            if key in seen:
                continue
            topics.append(title)
            seen.add(key)
        return topics

    async def get_lesson_type_topics(self, lesson_type_id: int) -> list[str]:
        result = await self.session.scalars(
            select(LessonTypeTopic.topic)
            .where(LessonTypeTopic.lesson_type_id == lesson_type_id)
            .order_by(LessonTypeTopic.topic.asc())
        )
        topics: list[str] = []
        seen: set[str] = set()
        for raw in result:
            topic = self._clean_topic(raw)
            if self._is_noise_topic(topic):
                continue
            key = topic.lower()
            if key in seen:
                continue
            seen.add(key)
            topics.append(topic)
        return topics

    async def replace_lesson_type_topics(self, lesson_type_id: int, topics: list[str]) -> list[str]:
        cleaned_set = set()
        for raw in topics:
            topic = self._clean_topic(raw)
            if self._is_noise_topic(topic):
                continue
            cleaned_set.add(topic)
        cleaned = sorted(cleaned_set)
        await self.session.execute(delete(LessonTypeTopic).where(LessonTypeTopic.lesson_type_id == lesson_type_id))
        for topic in cleaned:
            self.session.add(LessonTypeTopic(lesson_type_id=lesson_type_id, topic=topic))
        await self.session.flush()
        return cleaned

    async def get_lesson_type_daily_pack(
        self, lesson_type_id: int, quiz_date: date, difficulty: Difficulty
    ) -> LessonTypeDailyPack | None:
        return await self.session.scalar(
            select(LessonTypeDailyPack).where(
                and_(
                    LessonTypeDailyPack.lesson_type_id == lesson_type_id,
                    LessonTypeDailyPack.quiz_date == quiz_date,
                    LessonTypeDailyPack.difficulty == difficulty,
                )
            )
        )

    async def upsert_lesson_type_daily_pack(
        self, lesson_type_id: int, quiz_date: date, difficulty: Difficulty, questions: list[dict]
    ) -> LessonTypeDailyPack:
        pack = await self.get_lesson_type_daily_pack(lesson_type_id, quiz_date, difficulty)
        payload = json.dumps(questions, ensure_ascii=False)
        if not pack:
            pack = LessonTypeDailyPack(
                lesson_type_id=lesson_type_id,
                quiz_date=quiz_date,
                difficulty=difficulty,
                questions_json=payload,
            )
            self.session.add(pack)
            await self.session.flush()
            return pack
        pack.questions_json = payload
        pack.generated_at = datetime.now(timezone.utc)
        await self.session.flush()
        return pack

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

    async def list_quiz_questions(self, quiz_id: int) -> list[DailyQuestion]:
        result = await self.session.scalars(
            select(DailyQuestion).where(DailyQuestion.quiz_id == quiz_id).order_by(DailyQuestion.position.asc())
        )
        return list(result)

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

    async def list_answer_logs(self, quiz_id: int, student_id: int) -> list[AnswerLog]:
        result = await self.session.scalars(
            select(AnswerLog)
            .where(and_(AnswerLog.quiz_id == quiz_id, AnswerLog.student_id == student_id))
            .order_by(AnswerLog.answered_at.desc(), AnswerLog.id.desc())
        )
        return list(result)
