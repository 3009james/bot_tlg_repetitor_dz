from __future__ import annotations

from contextlib import asynccontextmanager

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.core.config import Settings
from src.db.base import Base


def create_engine_and_factory(settings: Settings) -> tuple:
    engine = create_async_engine(
        settings.db_url,
        echo=False,
        future=True,
        connect_args={"timeout": 30},
    )
    if settings.db_url.startswith("sqlite"):
        # Reduce "database is locked" in concurrent bot/api writes.
        @event.listens_for(engine.sync_engine, "connect")
        def _set_sqlite_pragma(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL;")
            cursor.execute("PRAGMA synchronous=NORMAL;")
            cursor.execute("PRAGMA busy_timeout=30000;")
            cursor.close()
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    return engine, session_factory


async def create_db(engine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_run_sqlite_migrations)


def _run_sqlite_migrations(sync_conn) -> None:
    if sync_conn.dialect.name != "sqlite":
        return

    def _table_exists(name: str) -> bool:
        row = sync_conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=:name",
            {"name": name},
        ).fetchone()
        return row is not None

    if _table_exists("dailyquiz"):
        cols = {row[1] for row in sync_conn.exec_driver_sql("PRAGMA table_info('dailyquiz')").fetchall()}
        if "lesson_type_id" not in cols:
            # Rebuild table to change unique constraint and add lesson_type_id.
            sync_conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
            sync_conn.exec_driver_sql(
                """
                CREATE TABLE IF NOT EXISTS dailyquiz_new (
                    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                    student_id BIGINT NOT NULL,
                    lesson_type_id INTEGER NOT NULL DEFAULT 1,
                    quiz_date DATE NOT NULL,
                    difficulty VARCHAR(6) NOT NULL,
                    status VARCHAR(9) NOT NULL,
                    generated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    CONSTRAINT uq_daily_quiz UNIQUE (student_id, lesson_type_id, quiz_date, difficulty),
                    FOREIGN KEY(student_id) REFERENCES user (id) ON DELETE CASCADE,
                    FOREIGN KEY(lesson_type_id) REFERENCES lessontype (id) ON DELETE CASCADE
                )
                """
            )
            sync_conn.exec_driver_sql(
                """
                INSERT INTO dailyquiz_new (id, student_id, lesson_type_id, quiz_date, difficulty, status, generated_at)
                SELECT id, student_id, 1, quiz_date, difficulty, status, generated_at FROM dailyquiz
                """
            )
            sync_conn.exec_driver_sql("DROP TABLE dailyquiz")
            sync_conn.exec_driver_sql("ALTER TABLE dailyquiz_new RENAME TO dailyquiz")
            sync_conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_dailyquiz_student_id ON dailyquiz(student_id)")
            sync_conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_dailyquiz_lesson_type_id ON dailyquiz(lesson_type_id)")
            sync_conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_dailyquiz_quiz_date ON dailyquiz(quiz_date)")
            sync_conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_dailyquiz_difficulty ON dailyquiz(difficulty)")
            sync_conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_dailyquiz_status ON dailyquiz(status)")
            sync_conn.exec_driver_sql("PRAGMA foreign_keys=ON")

    if _table_exists("dailyquestion"):
        cols = {row[1] for row in sync_conn.exec_driver_sql("PRAGMA table_info('dailyquestion')").fetchall()}
        if "question_type" not in cols:
            sync_conn.exec_driver_sql("ALTER TABLE dailyquestion ADD COLUMN question_type VARCHAR(8) DEFAULT 'MCQ'")
        if "meta_json" not in cols:
            sync_conn.exec_driver_sql("ALTER TABLE dailyquestion ADD COLUMN meta_json TEXT")

    if _table_exists("answerlog"):
        cols = {row[1] for row in sync_conn.exec_driver_sql("PRAGMA table_info('answerlog')").fetchall()}
        if "code_text" not in cols:
            sync_conn.exec_driver_sql("ALTER TABLE answerlog ADD COLUMN code_text TEXT")
        if "feedback_text" not in cols:
            sync_conn.exec_driver_sql("ALTER TABLE answerlog ADD COLUMN feedback_text TEXT")
        if "suggested_code" not in cols:
            sync_conn.exec_driver_sql("ALTER TABLE answerlog ADD COLUMN suggested_code TEXT")


@asynccontextmanager
async def session_scope(session_factory):
    session: AsyncSession = session_factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
