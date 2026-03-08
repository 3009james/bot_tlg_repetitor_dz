from __future__ import annotations

import enum
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base


class Difficulty(str, enum.Enum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class QuizStatus(str, enum.Enum):
    READY = "ready"
    COMPLETED = "completed"


class QuestionType(str, enum.Enum):
    MCQ = "mcq"
    CODE = "code"


class DailyQuiz(Base):
    __table_args__ = (
        UniqueConstraint("student_id", "lesson_type_id", "quiz_date", "difficulty", name="uq_daily_quiz"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), index=True)
    lesson_type_id: Mapped[int] = mapped_column(ForeignKey("lessontype.id", ondelete="CASCADE"), index=True)
    quiz_date: Mapped[date] = mapped_column(Date, index=True)
    difficulty: Mapped[Difficulty] = mapped_column(Enum(Difficulty), index=True)
    status: Mapped[QuizStatus] = mapped_column(Enum(QuizStatus), default=QuizStatus.READY, index=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DailyQuestion(Base):
    __table_args__ = (UniqueConstraint("quiz_id", "position", name="uq_quiz_question_position"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    quiz_id: Mapped[int] = mapped_column(ForeignKey("dailyquiz.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    question_text: Mapped[str] = mapped_column(Text)
    options_json: Mapped[str] = mapped_column(Text)
    correct_option_index: Mapped[int] = mapped_column(Integer)
    question_type: Mapped[QuestionType] = mapped_column(Enum(QuestionType), default=QuestionType.MCQ, index=True)
    meta_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)


class StudentProgress(Base):
    __table_args__ = (UniqueConstraint("quiz_id", "student_id", name="uq_progress_quiz_student"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    quiz_id: Mapped[int] = mapped_column(ForeignKey("dailyquiz.id", ondelete="CASCADE"), index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), index=True)
    current_position: Mapped[int] = mapped_column(Integer, default=1)
    total_answered: Mapped[int] = mapped_column(Integer, default=0)
    correct_answers: Mapped[int] = mapped_column(Integer, default=0)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AnswerLog(Base):
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    quiz_id: Mapped[int] = mapped_column(ForeignKey("dailyquiz.id", ondelete="CASCADE"), index=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("dailyquestion.id", ondelete="CASCADE"), index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), index=True)
    selected_option_index: Mapped[int] = mapped_column(Integer)
    is_correct: Mapped[int] = mapped_column(Integer)
    code_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    feedback_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    suggested_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    answered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
