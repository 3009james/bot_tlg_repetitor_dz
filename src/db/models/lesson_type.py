from __future__ import annotations

import enum
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base
from src.db.models.quiz import Difficulty


class GenerationMode(str, enum.Enum):
    MANUAL = "manual"
    AUTO = "auto"


class LessonType(Base):
    __table_args__ = (UniqueConstraint("name", name="uq_lesson_type_name"), UniqueConstraint("slug", name="uq_lesson_type_slug"))

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100))
    slug: Mapped[str] = mapped_column(String(100), index=True)
    generation_mode: Mapped[GenerationMode] = mapped_column(Enum(GenerationMode), default=GenerationMode.MANUAL)
    generate_hour: Mapped[int] = mapped_column(Integer, default=0)
    generate_minute: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class LessonTypeMaterial(Base):
    __table_args__ = (UniqueConstraint("lesson_type_id", "content_hash", name="uq_lesson_type_material_hash"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    lesson_type_id: Mapped[int] = mapped_column(ForeignKey("lessontype.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    source_filename: Mapped[str] = mapped_column(String(255))
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    compact_context: Mapped[str] = mapped_column(Text)
    tokens_estimate: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LessonTypeMaterialTopic(Base):
    __table_args__ = (UniqueConstraint("material_id", "topic", name="uq_lesson_type_material_topic"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    lesson_type_id: Mapped[int] = mapped_column(ForeignKey("lessontype.id", ondelete="CASCADE"), index=True)
    material_id: Mapped[int] = mapped_column(ForeignKey("lessontypematerial.id", ondelete="CASCADE"), index=True)
    topic: Mapped[str] = mapped_column(String(255), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LessonTypeTopic(Base):
    __table_args__ = (UniqueConstraint("lesson_type_id", "topic", name="uq_lesson_type_topic"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    lesson_type_id: Mapped[int] = mapped_column(ForeignKey("lessontype.id", ondelete="CASCADE"), index=True)
    topic: Mapped[str] = mapped_column(String(255), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LessonTypeStudent(Base):
    __table_args__ = (UniqueConstraint("lesson_type_id", "student_id", name="uq_lesson_type_student"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    lesson_type_id: Mapped[int] = mapped_column(ForeignKey("lessontype.id", ondelete="CASCADE"), index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LessonTypeDailyPack(Base):
    __table_args__ = (
        UniqueConstraint("lesson_type_id", "quiz_date", "difficulty", name="uq_lesson_type_daily_pack"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    lesson_type_id: Mapped[int] = mapped_column(ForeignKey("lessontype.id", ondelete="CASCADE"), index=True)
    quiz_date: Mapped[date] = mapped_column(Date, index=True)
    difficulty: Mapped[Difficulty] = mapped_column(Enum(Difficulty), index=True)
    questions_json: Mapped[str] = mapped_column(Text)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LessonTypeStudentGeneration(Base):
    __table_args__ = (
        UniqueConstraint("lesson_type_id", "student_id", name="uq_lesson_type_student_generation"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    lesson_type_id: Mapped[int] = mapped_column(ForeignKey("lessontype.id", ondelete="CASCADE"), index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), index=True)
    last_generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
