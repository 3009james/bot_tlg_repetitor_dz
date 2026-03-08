from __future__ import annotations

import hashlib
import hmac
import json
from datetime import date, datetime, time, timezone, timedelta
from typing import Any
from urllib.parse import parse_qsl
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from fastapi import FastAPI, File, Header, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from src.bot.services.notebook_ingest import build_material_digest
from src.bot.services.quiz_service import QuizService
from src.bot.services.routerai_client import RouterAIClient
from src.core.config import get_settings
from src.db.models import Difficulty, RequestStatus, UserRole, QuestionType
from src.db.repo import BotRepo
from src.db.session import create_db, create_engine_and_factory, session_scope


class AccessRequestPayload(BaseModel):
    subject: str = ""
    message: str = ""


class LessonTypeTopicsPayload(BaseModel):
    topics: list[str] = Field(default_factory=list)


class LessonTypeStudentsPayload(BaseModel):
    student_ids: list[int] = Field(default_factory=list)


class DifficultyPayload(BaseModel):
    difficulty: str


class StartTestPayload(BaseModel):
    lesson_type_id: int
    difficulty: str
    restart: bool = True


class AnswerAtPositionPayload(BaseModel):
    quiz_id: int
    position: int
    selected_index: int


class CodeCheckPayload(BaseModel):
    quiz_id: int
    position: int
    code: str


app = FastAPI(title="Tutor Bot Mini App API", version="3.0.0")


def _validate_init_data(init_data: str, bot_token: str) -> dict[str, Any]:
    if not init_data:
        raise HTTPException(status_code=401, detail="Missing init data")
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    provided_hash = pairs.pop("hash", "")
    if not provided_hash:
        raise HTTPException(status_code=401, detail="Invalid init data")

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    computed_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(computed_hash, provided_hash):
        raise HTTPException(status_code=401, detail="Init data signature mismatch")

    try:
        auth_date = int(pairs.get("auth_date", "0"))
    except ValueError:
        auth_date = 0
    if auth_date:
        age = datetime.now(timezone.utc).timestamp() - auth_date
        if age > 60 * 60 * 24:
            raise HTTPException(status_code=401, detail="Init data expired")

    user_raw = pairs.get("user")
    if not user_raw:
        raise HTTPException(status_code=401, detail="Missing user")
    try:
        user = json.loads(user_raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=401, detail="Invalid user in init data") from exc
    return user


async def _resolve_user_record(x_telegram_init_data: str | None):
    init_data = (x_telegram_init_data or "").strip()
    settings = app.state.settings
    tg_user = _validate_init_data(init_data, settings.bot_token)
    tg_id = int(tg_user["id"])
    full_name = " ".join([x for x in [tg_user.get("first_name", ""), tg_user.get("last_name", "")] if x]).strip()
    username = tg_user.get("username")

    async with session_scope(app.state.session_factory) as session:
        repo = BotRepo(session)
        if tg_id in settings.admins:
            user = await repo.upsert_user(tg_id, full_name, username, UserRole.ADMIN)
            user.role = UserRole.ADMIN
        else:
            user = await repo.get_user_by_telegram(tg_id)
            if not user:
                user = await repo.upsert_user(tg_id, full_name, username, UserRole.PENDING)
        return {
            "id": user.id,
            "telegram_id": user.telegram_id,
            "full_name": user.full_name,
            "username": user.username,
            "role": user.role,
            "subject": user.subject,
            "photo_file_id": user.photo_file_id,
        }


async def _require_admin(x_telegram_init_data: str | None) -> dict[str, Any]:
    user = await _resolve_user_record(x_telegram_init_data)
    if user["role"] != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


async def _require_student(x_telegram_init_data: str | None) -> dict[str, Any]:
    user = await _resolve_user_record(x_telegram_init_data)
    if user["role"] != UserRole.STUDENT:
        raise HTTPException(status_code=403, detail="Student access required")
    return user


def _parse_difficulty(raw: str) -> Difficulty:
    mapping = {
        "low": Difficulty.EASY,
        "easy": Difficulty.EASY,
        "medium": Difficulty.MEDIUM,
        "mid": Difficulty.MEDIUM,
        "high": Difficulty.HARD,
        "hard": Difficulty.HARD,
    }
    difficulty = mapping.get(raw.strip().lower())
    if not difficulty:
        raise HTTPException(status_code=400, detail="Invalid difficulty")
    return difficulty


def _now_msk() -> datetime:
    return datetime.now(ZoneInfo("Europe/Moscow"))


def _next_generation_at(last_generated_at: datetime | None) -> datetime | None:
    if not last_generated_at:
        return None
    if last_generated_at.tzinfo is None:
        last_generated_at = last_generated_at.replace(tzinfo=timezone.utc)
    msk_dt = last_generated_at.astimezone(ZoneInfo("Europe/Moscow"))
    next_day = msk_dt.date() + timedelta(days=1)
    return datetime.combine(next_day, time(7, 0), tzinfo=ZoneInfo("Europe/Moscow"))


@app.on_event("startup")
async def startup() -> None:
    settings = get_settings()
    engine, session_factory = create_engine_and_factory(settings)
    await create_db(engine)
    llm_client = RouterAIClient(
        api_key=settings.routerai_api_key,
        base_url=settings.routerai_base_url,
        model=settings.routerai_model,
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.quiz_service = QuizService(llm=llm_client)
    app.state.llm_client = llm_client
    app.state.bot = Bot(token=settings.bot_token, default=DefaultBotProperties(parse_mode="HTML"))
    async with session_scope(session_factory) as session:
        repo = BotRepo(session)
        await repo.ensure_default_lesson_types()


@app.on_event("shutdown")
async def shutdown() -> None:
    await app.state.bot.session.close()
    await app.state.engine.dispose()


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/me")
async def me(x_telegram_init_data: str | None = Header(default=None)) -> dict[str, Any]:
    user = await _resolve_user_record(x_telegram_init_data)
    return {
        "telegram_id": user["telegram_id"],
        "full_name": user["full_name"],
        "username": user["username"],
        "role": user["role"].value,
        "subject": user["subject"],
        "photo_file_id": user["photo_file_id"],
    }


@app.get("/api/access/status")
async def access_status(x_telegram_init_data: str | None = Header(default=None)) -> dict[str, Any]:
    user = await _resolve_user_record(x_telegram_init_data)
    async with session_scope(app.state.session_factory) as session:
        repo = BotRepo(session)
        pending = await repo.get_pending_request(user["telegram_id"])
    return {
        "role": user["role"].value,
        "has_pending_request": bool(pending),
        "pending_request": (
            {
                "id": pending.id,
                "subject": pending.subject,
                "message": pending.message,
                "created_at": pending.created_at.isoformat() if pending.created_at else None,
            }
            if pending
            else None
        ),
    }


@app.post("/api/access/request")
async def access_request(payload: AccessRequestPayload, x_telegram_init_data: str | None = Header(default=None)) -> dict[str, Any]:
    user = await _resolve_user_record(x_telegram_init_data)
    if user["role"] == UserRole.STUDENT:
        raise HTTPException(status_code=400, detail="Student already approved")
    if user["role"] == UserRole.ADMIN:
        raise HTTPException(status_code=400, detail="Admin does not need request")

    subject = payload.subject.strip() or None
    message = payload.message.strip() or None
    async with session_scope(app.state.session_factory) as session:
        repo = BotRepo(session)
        existing = await repo.get_pending_request(user["telegram_id"])
        if existing:
            return {"status": "already_pending", "request_id": existing.id}
        req = await repo.create_access_request(
            telegram_id=user["telegram_id"],
            full_name=user["full_name"],
            username=user["username"],
            subject=subject,
            message=message,
        )
    for admin_id in app.state.settings.admins:
        try:
            await app.state.bot.send_message(
                admin_id,
                (
                    "Новая заявка на доступ\n"
                    f"Пользователь: {user['full_name']} (@{user['username'] or '-'})\n"
                    f"tg_id: {user['telegram_id']}\n"
                    f"Предмет: {subject or '-'}\n"
                    f"Комментарий: {message or '-'}"
                ),
            )
        except Exception:
            # Уведомления не должны ломать основной flow создания заявки.
            pass
    return {"status": "created", "request_id": req.id}


@app.get("/api/admin/requests")
async def admin_requests(x_telegram_init_data: str | None = Header(default=None)) -> dict[str, Any]:
    await _require_admin(x_telegram_init_data)
    async with session_scope(app.state.session_factory) as session:
        repo = BotRepo(session)
        rows = await repo.list_pending_requests()
    return {
        "items": [
            {
                "id": row.id,
                "telegram_id": row.telegram_id,
                "full_name": row.full_name,
                "username": row.username,
                "subject": row.subject,
                "message": row.message,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]
    }


@app.post("/api/admin/requests/{request_id}/approve")
async def admin_request_approve(request_id: int, x_telegram_init_data: str | None = Header(default=None)) -> dict[str, Any]:
    admin = await _require_admin(x_telegram_init_data)
    async with session_scope(app.state.session_factory) as session:
        repo = BotRepo(session)
        req = await repo.handle_request(request_id, RequestStatus.APPROVED, admin["telegram_id"])
        if not req:
            raise HTTPException(status_code=404, detail="Request not found")
        user = await repo.get_user_by_telegram(req.telegram_id)
        if not user:
            user = await repo.upsert_user(req.telegram_id, req.full_name, req.username, UserRole.STUDENT)
        user.role = UserRole.STUDENT
        user.subject = req.subject
    try:
        await app.state.bot.send_message(
            req.telegram_id,
            "Ваша заявка одобрена. Откройте бота и нажмите «Открыть приложение».",
        )
    except Exception:
        pass
    return {"status": "approved", "request_id": request_id}


@app.post("/api/admin/requests/{request_id}/reject")
async def admin_request_reject(request_id: int, x_telegram_init_data: str | None = Header(default=None)) -> dict[str, Any]:
    admin = await _require_admin(x_telegram_init_data)
    async with session_scope(app.state.session_factory) as session:
        repo = BotRepo(session)
        req = await repo.handle_request(request_id, RequestStatus.REJECTED, admin["telegram_id"])
        if not req:
            raise HTTPException(status_code=404, detail="Request not found")
    try:
        await app.state.bot.send_message(req.telegram_id, "Заявка отклонена. Можно отправить новую позже.")
    except Exception:
        pass
    return {"status": "rejected", "request_id": request_id}


@app.get("/api/admin/students")
async def admin_students(x_telegram_init_data: str | None = Header(default=None)) -> dict[str, Any]:
    await _require_admin(x_telegram_init_data)
    async with session_scope(app.state.session_factory) as session:
        repo = BotRepo(session)
        students = await repo.list_students()
    return {
        "items": [
            {
                "id": row.id,
                "telegram_id": row.telegram_id,
                "full_name": row.full_name,
                "subject": row.subject,
            }
            for row in students
        ]
    }


@app.get("/api/admin/lesson-types")
async def admin_lesson_types(x_telegram_init_data: str | None = Header(default=None)) -> dict[str, Any]:
    await _require_admin(x_telegram_init_data)
    async with session_scope(app.state.session_factory) as session:
        repo = BotRepo(session)
        lesson_types = await repo.list_lesson_types()
        rows = []
        for row in lesson_types:
            students = await repo.list_students_by_lesson_type(row.id)
            topics = await repo.get_lesson_type_topics(row.id)
            materials = await repo.get_lesson_type_materials(row.id, limit=500)
            rows.append(
                {
                    "id": row.id,
                    "name": row.name,
                    "slug": row.slug,
                    "students_count": len(students),
                    "topics_count": len(topics),
                    "materials_count": len(materials),
                }
            )
    return {"items": rows}


@app.get("/api/admin/lesson-types/{lesson_type_id}")
async def admin_lesson_type_details(lesson_type_id: int, x_telegram_init_data: str | None = Header(default=None)) -> dict[str, Any]:
    await _require_admin(x_telegram_init_data)
    async with session_scope(app.state.session_factory) as session:
        repo = BotRepo(session)
        lesson_type = await repo.get_lesson_type(lesson_type_id)
        if not lesson_type:
            raise HTTPException(status_code=404, detail="Lesson type not found")
        students = await repo.list_students_by_lesson_type(lesson_type_id)
        material_topics = await repo.list_lesson_type_material_topics(lesson_type_id)
        selected_topics = await repo.get_lesson_type_topics(lesson_type_id)
        materials = await repo.get_lesson_type_materials(lesson_type_id, limit=300)
        material_items = []
        for m in materials:
            material_items.append(
                {
                    "id": m.id,
                    "title": m.title,
                    "source_filename": m.source_filename,
                    "tokens_estimate": m.tokens_estimate,
                    "created_at": m.created_at.isoformat() if m.created_at else None,
                    "topics": await repo.get_lesson_type_material_topics(m.id),
                }
            )
    return {
        "id": lesson_type.id,
        "name": lesson_type.name,
        "slug": lesson_type.slug,
        "students": [
            {"id": s.id, "full_name": s.full_name, "telegram_id": s.telegram_id, "subject": s.subject} for s in students
        ],
        "available_topics": material_topics,
        "selected_topics": selected_topics,
        "materials": material_items,
    }


@app.post("/api/admin/lesson-types/{lesson_type_id}/materials/upload")
async def admin_upload_lesson_type_material(
    lesson_type_id: int,
    file: UploadFile = File(...),
    x_telegram_init_data: str | None = Header(default=None),
) -> dict[str, Any]:
    await _require_admin(x_telegram_init_data)
    allowed = (".txt", ".docx", ".pdf")
    if not file.filename or not file.filename.lower().endswith(allowed):
        raise HTTPException(status_code=400, detail="Only .txt, .docx, .pdf are supported")
    raw = await file.read()
    content_hash = hashlib.sha256(raw).hexdigest()

    # Fast path: duplicate with topics already extracted.
    async with session_scope(app.state.session_factory) as session:
        repo = BotRepo(session)
        lesson_type = await repo.get_lesson_type(lesson_type_id)
        if not lesson_type:
            raise HTTPException(status_code=404, detail="Lesson type not found")
        existing = await repo.get_lesson_type_material_by_hash(lesson_type_id, content_hash)
        if existing:
            existing_topics = await repo.get_lesson_type_material_topics(existing.id)
            if existing_topics:
                available = await repo.list_lesson_type_material_topics(lesson_type_id)
                current_topics = await repo.get_lesson_type_topics(lesson_type_id)
                if not current_topics and available:
                    await repo.replace_lesson_type_topics(lesson_type_id, available)
                return {"status": "duplicate", "title": existing.title, "topics": existing_topics}

    try:
        digest = await build_material_digest(file.filename, raw, app.state.llm_client)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    extracted_topics = await app.state.llm_client.extract_topics(digest.compact_context, max_topics=5)
    if not extracted_topics:
        extracted_topics = [digest.title]
    response_topics: list[str] = []
    async with session_scope(app.state.session_factory) as session:
        repo = BotRepo(session)
        lesson_type = await repo.get_lesson_type(lesson_type_id)
        if not lesson_type:
            raise HTTPException(status_code=404, detail="Lesson type not found")
        existing = await repo.get_lesson_type_material_by_hash(lesson_type_id, content_hash)
        if existing:
            # Legacy duplicate without topics: refresh digest and backfill topics.
            existing.title = digest.title
            existing.source_filename = file.filename
            existing.compact_context = digest.compact_context
            existing.tokens_estimate = digest.tokens_estimate
            response_topics = await repo.replace_lesson_type_material_topics(
                lesson_type_id=lesson_type_id,
                material_id=existing.id,
                topics=extracted_topics,
            )
            created = None
        else:
            created = await repo.create_lesson_type_material(
                lesson_type_id=lesson_type_id,
                title=digest.title,
                source_filename=file.filename,
                content_hash=digest.content_hash,
                compact_context=digest.compact_context,
                tokens_estimate=digest.tokens_estimate,
            )
            if created:
                response_topics = await repo.replace_lesson_type_material_topics(
                    lesson_type_id=lesson_type_id,
                    material_id=created.id,
                    topics=extracted_topics,
                )
        # Автоматически обновляем выбранные темы только при первом заполнении.
        current_topics = await repo.get_lesson_type_topics(lesson_type_id)
        available = await repo.list_lesson_type_material_topics(lesson_type_id)
        if not current_topics and available:
            await repo.replace_lesson_type_topics(lesson_type_id, available)
    return {
        "status": "created" if created else "duplicate",
        "title": digest.title,
        "topics": response_topics,
    }


@app.post("/api/admin/lesson-types/{lesson_type_id}/topics")
async def admin_set_lesson_type_topics(
    lesson_type_id: int,
    payload: LessonTypeTopicsPayload,
    x_telegram_init_data: str | None = Header(default=None),
) -> dict[str, Any]:
    await _require_admin(x_telegram_init_data)
    async with session_scope(app.state.session_factory) as session:
        repo = BotRepo(session)
        lesson_type = await repo.get_lesson_type(lesson_type_id)
        if not lesson_type:
            raise HTTPException(status_code=404, detail="Lesson type not found")
        selected = await repo.replace_lesson_type_topics(lesson_type_id, payload.topics)
    return {"lesson_type_id": lesson_type_id, "selected_topics": selected}


@app.delete("/api/admin/lesson-types/{lesson_type_id}/materials/{material_id}")
async def admin_delete_lesson_type_material(
    lesson_type_id: int,
    material_id: int,
    x_telegram_init_data: str | None = Header(default=None),
) -> dict[str, Any]:
    await _require_admin(x_telegram_init_data)
    async with session_scope(app.state.session_factory) as session:
        repo = BotRepo(session)
        lesson_type = await repo.get_lesson_type(lesson_type_id)
        if not lesson_type:
            raise HTTPException(status_code=404, detail="Lesson type not found")
        deleted = await repo.delete_lesson_type_material(lesson_type_id, material_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Material not found")
        available = await repo.list_lesson_type_material_topics(lesson_type_id)
        selected = await repo.get_lesson_type_topics(lesson_type_id)
        selected_filtered = [t for t in selected if t in set(available)]
        if selected != selected_filtered:
            await repo.replace_lesson_type_topics(lesson_type_id, selected_filtered)
    return {"status": "deleted", "material_id": material_id}


@app.post("/api/admin/lesson-types/{lesson_type_id}/students")
async def admin_set_lesson_type_students(
    lesson_type_id: int,
    payload: LessonTypeStudentsPayload,
    x_telegram_init_data: str | None = Header(default=None),
) -> dict[str, Any]:
    await _require_admin(x_telegram_init_data)
    async with session_scope(app.state.session_factory) as session:
        repo = BotRepo(session)
        lesson_type = await repo.get_lesson_type(lesson_type_id)
        if not lesson_type:
            raise HTTPException(status_code=404, detail="Lesson type not found")
        updated = await repo.replace_lesson_type_students(lesson_type_id, payload.student_ids)
    return {"lesson_type_id": lesson_type_id, "student_ids": updated}


@app.post("/api/admin/lesson-types/{lesson_type_id}/generate")
async def admin_generate_for_lesson_type(
    lesson_type_id: int,
    payload: DifficultyPayload,
    x_telegram_init_data: str | None = Header(default=None),
) -> dict[str, Any]:
    await _require_admin(x_telegram_init_data)
    difficulty = _parse_difficulty(payload.difficulty)
    settings = app.state.settings
    today = datetime.now(ZoneInfo(settings.timezone)).date()
    async with session_scope(app.state.session_factory) as session:
        repo = BotRepo(session)
        lesson_type = await repo.get_lesson_type(lesson_type_id)
        if not lesson_type:
            raise HTTPException(status_code=404, detail="Lesson type not found")
        students_count = await app.state.quiz_service.ensure_lesson_type_daily_quizzes(
            repo=repo,
            lesson_type=lesson_type,
            quiz_date=today,
            force_regenerate=True,
            difficulties=[difficulty],
        )
    return {
        "status": "ok",
        "lesson_type_id": lesson_type_id,
        "date": today.isoformat(),
        "students_count": students_count,
        "difficulty": difficulty.value,
    }


@app.get("/api/admin/lesson-types/{lesson_type_id}/daily-pack")
async def admin_daily_pack(
    lesson_type_id: int,
    difficulty: str = Query(...),
    quiz_date: str | None = Query(default=None),
    x_telegram_init_data: str | None = Header(default=None),
) -> dict[str, Any]:
    await _require_admin(x_telegram_init_data)
    parsed_difficulty = _parse_difficulty(difficulty)
    if quiz_date:
        try:
            day = date.fromisoformat(quiz_date)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid date format") from exc
    else:
        day = datetime.now(ZoneInfo(app.state.settings.timezone)).date()

    async with session_scope(app.state.session_factory) as session:
        repo = BotRepo(session)
        pack = await repo.get_lesson_type_daily_pack(lesson_type_id, day, parsed_difficulty)
        if not pack:
            raise HTTPException(status_code=404, detail="No generated pack for this day and difficulty")
        questions = json.loads(pack.questions_json)
    return {
        "lesson_type_id": lesson_type_id,
        "quiz_date": day.isoformat(),
        "difficulty": parsed_difficulty.value,
        "generated_at": pack.generated_at.isoformat() if pack.generated_at else None,
        "questions": questions,
    }


@app.get("/api/student/dashboard")
async def student_dashboard(x_telegram_init_data: str | None = Header(default=None)) -> dict[str, Any]:
    student = await _require_student(x_telegram_init_data)
    now_msk = _now_msk()
    async with session_scope(app.state.session_factory) as session:
        repo = BotRepo(session)
        lesson_types = await repo.get_student_lesson_types(student["id"])
        items = []
        for row in lesson_types:
            latest_generated_at = await repo.get_lesson_type_latest_generated_at_for_student(student["id"], row.id)
            generation_state = await repo.get_lesson_type_student_generation_state(row.id, student["id"])
            next_allowed_at = _next_generation_at(
                generation_state.last_generated_at if generation_state else None
            )
            can_generate_now = (next_allowed_at is None) or (now_msk >= next_allowed_at)
            items.append(
                {
                    "id": row.id,
                    "name": row.name,
                    "slug": row.slug,
                    "updated_at": latest_generated_at.isoformat() if latest_generated_at else None,
                    "can_generate_now": bool(can_generate_now),
                    "next_generation_at": next_allowed_at.isoformat() if next_allowed_at else None,
                }
            )
    return {
        "student": {
            "id": student["id"],
            "full_name": student["full_name"],
            "photo_file_id": student["photo_file_id"],
        },
        "lesson_types": items,
    }


@app.post("/api/student/tests/start")
async def student_start_test(payload: StartTestPayload, x_telegram_init_data: str | None = Header(default=None)) -> dict[str, Any]:
    student = await _require_student(x_telegram_init_data)
    difficulty = _parse_difficulty(payload.difficulty)

    async with session_scope(app.state.session_factory) as session:
        repo = BotRepo(session)
        lesson_type = await repo.get_lesson_type(payload.lesson_type_id)
        if not lesson_type:
            raise HTTPException(status_code=404, detail="Lesson type not found")
        assigned_types = await repo.get_student_lesson_types(student["id"])
        if payload.lesson_type_id not in {x.id for x in assigned_types}:
            raise HTTPException(status_code=403, detail="You are not assigned to this lesson type")
        quiz = await repo.get_latest_quiz(student["id"], lesson_type.id, difficulty)
        if not quiz:
            raise HTTPException(status_code=404, detail="No tasks yet. Generate new tasks first.")
        if payload.restart:
            await repo.reset_progress(quiz.id, student["id"])
        questions = await repo.list_quiz_questions(quiz.id)
    return {
        "quiz_id": quiz.id,
        "lesson_type_id": lesson_type.id,
        "lesson_type_name": lesson_type.name,
        "difficulty": difficulty.value,
        "questions": [
            {
                "position": q.position,
                "question": q.question_text,
                "type": q.question_type.value if q.question_type else QuestionType.MCQ.value,
                "options": json.loads(q.options_json),
                "meta": json.loads(q.meta_json) if q.meta_json else {},
            }
            for q in questions
        ],
    }


@app.post("/api/student/lesson-types/{lesson_type_id}/generate")
async def student_generate_new_tasks(
    lesson_type_id: int,
    payload: DifficultyPayload,
    x_telegram_init_data: str | None = Header(default=None),
) -> dict[str, Any]:
    student = await _require_student(x_telegram_init_data)
    difficulty = _parse_difficulty(payload.difficulty)
    now_msk = _now_msk()
    quiz_date = now_msk.date()

    async with session_scope(app.state.session_factory) as session:
        repo = BotRepo(session)
        lesson_type = await repo.get_lesson_type(lesson_type_id)
        if not lesson_type:
            raise HTTPException(status_code=404, detail="Lesson type not found")
        assigned_types = await repo.get_student_lesson_types(student["id"])
        if lesson_type_id not in {x.id for x in assigned_types}:
            raise HTTPException(status_code=403, detail="You are not assigned to this lesson type")

        generation_state = await repo.get_lesson_type_student_generation_state(lesson_type_id, student["id"])
        next_allowed_at = _next_generation_at(generation_state.last_generated_at if generation_state else None)
        if next_allowed_at and now_msk < next_allowed_at:
            raise HTTPException(
                status_code=403,
                detail=f"New tasks will be available after {next_allowed_at.strftime('%d.%m.%Y %H:%M')} (MSK)",
            )

        student_row = await repo.get_user_by_id(student["id"])
        if not student_row:
            raise HTTPException(status_code=404, detail="Student not found")
        quiz = await app.state.quiz_service.generate_student_lesson_type_quiz(
            repo=repo,
            student=student_row,
            lesson_type=lesson_type,
            quiz_date=quiz_date,
            difficulty=difficulty,
        )
        questions = await repo.list_quiz_questions(quiz.id)

    return {
        "status": "ok",
        "quiz_id": quiz.id,
        "lesson_type_id": lesson_type.id,
        "difficulty": difficulty.value,
        "generated_at": now_msk.isoformat(),
        "questions": [
            {
                "position": q.position,
                "question": q.question_text,
                "type": q.question_type.value if q.question_type else QuestionType.MCQ.value,
                "options": json.loads(q.options_json),
                "meta": json.loads(q.meta_json) if q.meta_json else {},
            }
            for q in questions
        ],
    }


@app.get("/api/student/tests/{quiz_id}")
async def student_get_quiz(quiz_id: int, x_telegram_init_data: str | None = Header(default=None)) -> dict[str, Any]:
    student = await _require_student(x_telegram_init_data)
    async with session_scope(app.state.session_factory) as session:
        repo = BotRepo(session)
        quiz = await repo.get_quiz_by_id(quiz_id)
        if not quiz or quiz.student_id != student["id"]:
            raise HTTPException(status_code=403, detail="No access to quiz")
        questions = await repo.list_quiz_questions(quiz_id)
        logs = await repo.list_answer_logs(quiz_id, student["id"])

    latest_by_question: dict[int, Any] = {}
    for log in logs:
        if log.question_id in latest_by_question:
            continue
        latest_by_question[log.question_id] = log

    answers_by_position: dict[str, Any] = {}
    for q in questions:
        log = latest_by_question.get(q.id)
        if not log:
            continue
        answers_by_position[str(q.position)] = {
            "selected_index": log.selected_option_index,
            "is_correct": bool(log.is_correct),
            "code_text": log.code_text or "",
            "feedback_text": log.feedback_text or "",
            "suggested_code": log.suggested_code or "",
            "answered_at": log.answered_at.isoformat() if log.answered_at else None,
        }

    return {
        "quiz_id": quiz_id,
        "difficulty": quiz.difficulty.value,
        "questions": [
            {
                "position": q.position,
                "question": q.question_text,
                "type": q.question_type.value if q.question_type else QuestionType.MCQ.value,
                "options": json.loads(q.options_json),
                "meta": json.loads(q.meta_json) if q.meta_json else {},
                "solution": q.explanation or "",
            }
            for q in questions
        ],
        "answers_by_position": answers_by_position,
    }


@app.post("/api/student/tests/answer")
async def student_answer_test(payload: AnswerAtPositionPayload, x_telegram_init_data: str | None = Header(default=None)) -> dict[str, Any]:
    student = await _require_student(x_telegram_init_data)
    async with session_scope(app.state.session_factory) as session:
        repo = BotRepo(session)
        quiz = await repo.get_quiz_by_id(payload.quiz_id)
        if not quiz or quiz.student_id != student["id"]:
            raise HTTPException(status_code=403, detail="No access to quiz")
        question = await repo.get_quiz_question(payload.quiz_id, payload.position)
        if not question:
            raise HTTPException(status_code=404, detail="Question not found")
        if question.question_type == QuestionType.CODE:
            raise HTTPException(status_code=400, detail="Use code-check endpoint for practical code tasks")
        options = json.loads(question.options_json)
        if payload.selected_index < 0 or payload.selected_index >= len(options):
            raise HTTPException(status_code=400, detail="Invalid option index")
        correct = payload.selected_index == question.correct_option_index
        await repo.log_answer(payload.quiz_id, question.id, student["id"], payload.selected_index, correct)
    return {
        "is_correct": correct,
        "correct_option_index": question.correct_option_index,
        "solution": question.explanation or "",
    }


@app.post("/api/student/tests/code-check")
async def student_code_check(
    payload: CodeCheckPayload,
    x_telegram_init_data: str | None = Header(default=None),
) -> dict[str, Any]:
    student = await _require_student(x_telegram_init_data)
    async with session_scope(app.state.session_factory) as session:
        repo = BotRepo(session)
        quiz = await repo.get_quiz_by_id(payload.quiz_id)
        if not quiz or quiz.student_id != student["id"]:
            raise HTTPException(status_code=403, detail="No access to quiz")
        question = await repo.get_quiz_question(payload.quiz_id, payload.position)
        if not question:
            raise HTTPException(status_code=404, detail="Question not found")
        if question.question_type != QuestionType.CODE:
            raise HTTPException(status_code=400, detail="Question is not practical code task")

        meta = json.loads(question.meta_json) if question.meta_json else {}
        language = str(meta.get("language", "python"))
        reference_solution = str(meta.get("reference_solution", "")).strip()
        review = await app.state.llm_client.evaluate_code_solution(
            question_text=question.question_text,
            student_code=payload.code,
            reference_solution=reference_solution,
            language=language,
            difficulty=quiz.difficulty.value,
        )
        await repo.log_answer(
            payload.quiz_id,
            question.id,
            student["id"],
            selected_index=-1,
            is_correct=bool(review.get("is_correct", False)),
            code_text=payload.code,
            feedback_text=str(review.get("feedback", "")),
            suggested_code=str(review.get("suggested_code", "")),
        )

    return {
        "is_correct": bool(review.get("is_correct", False)),
        "feedback": str(review.get("feedback", "")),
        "suggested_code": str(review.get("suggested_code", "")),
        "solution": question.explanation or "",
    }


@app.get("/api/student/tests/{quiz_id}/result")
async def student_test_result(quiz_id: int, x_telegram_init_data: str | None = Header(default=None)) -> dict[str, Any]:
    student = await _require_student(x_telegram_init_data)
    async with session_scope(app.state.session_factory) as session:
        repo = BotRepo(session)
        quiz = await repo.get_quiz_by_id(quiz_id)
        if not quiz or quiz.student_id != student["id"]:
            raise HTTPException(status_code=403, detail="No access to quiz")
        questions = await repo.list_quiz_questions(quiz_id)
        logs = await repo.list_answer_logs(quiz_id, student["id"])

    latest_by_question: dict[int, Any] = {}
    for log in logs:
        if log.question_id in latest_by_question:
            continue
        latest_by_question[log.question_id] = log

    total = len(questions)
    answered = 0
    correct = 0
    for q in questions:
        log = latest_by_question.get(q.id)
        if not log:
            continue
        answered += 1
        if bool(log.is_correct):
            correct += 1

    return {
        "quiz_id": quiz_id,
        "answered": answered,
        "total": total,
        "correct": correct,
    }
