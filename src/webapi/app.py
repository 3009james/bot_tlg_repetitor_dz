from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qsl
from zoneinfo import ZoneInfo

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from pydantic import BaseModel, Field

from src.bot.services.notebook_ingest import build_notebook_digest
from src.bot.services.quiz_service import QuizService
from src.bot.services.routerai_client import RouterAIClient
from src.core.config import get_settings
from src.db.models import Difficulty, QuizStatus, RequestStatus, UserRole
from src.db.repo import BotRepo
from src.db.session import create_db, create_engine_and_factory, session_scope


class StartQuizPayload(BaseModel):
    difficulty: str


class AnswerPayload(BaseModel):
    quiz_id: int
    selected_index: int


class TopicsPayload(BaseModel):
    topics: list[str] = Field(default_factory=list)


class AccessRequestPayload(BaseModel):
    subject: str = ""
    message: str = ""


app = FastAPI(title="Tutor Bot Mini App API", version="2.0.0")


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
        }


async def _require_student(x_telegram_init_data: str | None) -> dict[str, Any]:
    user = await _resolve_user_record(x_telegram_init_data)
    if user["role"] != UserRole.STUDENT:
        raise HTTPException(status_code=403, detail="Student access required")
    return user


async def _require_admin(x_telegram_init_data: str | None) -> dict[str, Any]:
    user = await _resolve_user_record(x_telegram_init_data)
    if user["role"] != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


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


@app.on_event("shutdown")
async def shutdown() -> None:
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
    return {"status": "created", "request_id": req.id}


@app.post("/api/quiz/start")
async def quiz_start(payload: StartQuizPayload, x_telegram_init_data: str | None = Header(default=None)) -> dict[str, Any]:
    difficulty_map = {
        "easy": Difficulty.EASY,
        "medium": Difficulty.MEDIUM,
        "hard": Difficulty.HARD,
    }
    difficulty = difficulty_map.get(payload.difficulty.strip().lower())
    if not difficulty:
        raise HTTPException(status_code=400, detail="Invalid difficulty")

    student = await _require_student(x_telegram_init_data)
    settings = app.state.settings
    today = datetime.now(ZoneInfo(settings.timezone)).date()

    async with session_scope(app.state.session_factory) as session:
        repo = BotRepo(session)
        user = await repo.get_user_by_id(student["id"])
        quiz = await app.state.quiz_service.ensure_daily_quiz(repo, user, today, difficulty)
        progress = await repo.get_or_create_progress(quiz.id, student["id"])
        total = await repo.get_quiz_questions_count(quiz.id)
        if progress.current_position > total:
            quiz.status = QuizStatus.COMPLETED
            return {
                "status": "completed",
                "quiz_id": quiz.id,
                "result": {
                    "correct_answers": progress.correct_answers,
                    "total_questions": total,
                },
            }
        question = await repo.get_quiz_question(quiz.id, progress.current_position)
        if not question:
            raise HTTPException(status_code=404, detail="Question not found")
        return {
            "status": "in_progress",
            "quiz_id": quiz.id,
            "position": progress.current_position,
            "total": total,
            "question": {
                "id": question.id,
                "text": question.question_text,
                "options": json.loads(question.options_json),
            },
            "score": {
                "correct_answers": progress.correct_answers,
                "answered": progress.total_answered,
            },
        }


@app.post("/api/quiz/answer")
async def quiz_answer(payload: AnswerPayload, x_telegram_init_data: str | None = Header(default=None)) -> dict[str, Any]:
    student = await _require_student(x_telegram_init_data)

    async with session_scope(app.state.session_factory) as session:
        repo = BotRepo(session)
        quiz = await repo.get_quiz_by_id(payload.quiz_id)
        if not quiz or quiz.student_id != student["id"]:
            raise HTTPException(status_code=403, detail="No access to quiz")

        progress = await repo.get_or_create_progress(payload.quiz_id, student["id"])
        total = await repo.get_quiz_questions_count(payload.quiz_id)
        if progress.current_position > total:
            quiz.status = QuizStatus.COMPLETED
            return {
                "status": "completed",
                "result": {
                    "correct_answers": progress.correct_answers,
                    "total_questions": total,
                },
            }

        question = await repo.get_quiz_question(payload.quiz_id, progress.current_position)
        if not question:
            raise HTTPException(status_code=404, detail="Question not found")

        options = json.loads(question.options_json)
        if payload.selected_index < 0 or payload.selected_index >= len(options):
            raise HTTPException(status_code=400, detail="Invalid option")

        correct = payload.selected_index == question.correct_option_index
        progress.total_answered += 1
        if correct:
            progress.correct_answers += 1
        progress.current_position += 1
        await repo.log_answer(payload.quiz_id, question.id, student["id"], payload.selected_index, correct)

        response: dict[str, Any] = {
            "status": "next",
            "feedback": {
                "is_correct": correct,
                "correct_option_index": question.correct_option_index,
                "explanation": question.explanation or "",
            },
        }

        if progress.current_position > total:
            quiz.status = QuizStatus.COMPLETED
            progress.finished_at = datetime.now(timezone.utc)
            response["status"] = "completed"
            response["result"] = {
                "correct_answers": progress.correct_answers,
                "total_questions": total,
            }
            return response

        next_question = await repo.get_quiz_question(payload.quiz_id, progress.current_position)
        if not next_question:
            raise HTTPException(status_code=404, detail="Next question not found")
        response["next_question"] = {
            "quiz_id": payload.quiz_id,
            "position": progress.current_position,
            "total": total,
            "question": {
                "id": next_question.id,
                "text": next_question.question_text,
                "options": json.loads(next_question.options_json),
            },
        }
        return response


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
    settings = app.state.settings
    today = datetime.now(ZoneInfo(settings.timezone)).date()
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
        for difficulty in (Difficulty.EASY, Difficulty.MEDIUM, Difficulty.HARD):
            await app.state.quiz_service.ensure_daily_quiz(repo, user, today, difficulty, force_regenerate=True)
    return {"status": "approved", "request_id": request_id}


@app.post("/api/admin/requests/{request_id}/reject")
async def admin_request_reject(request_id: int, x_telegram_init_data: str | None = Header(default=None)) -> dict[str, Any]:
    admin = await _require_admin(x_telegram_init_data)
    async with session_scope(app.state.session_factory) as session:
        repo = BotRepo(session)
        req = await repo.handle_request(request_id, RequestStatus.REJECTED, admin["telegram_id"])
        if not req:
            raise HTTPException(status_code=404, detail="Request not found")
    return {"status": "rejected", "request_id": request_id}


@app.get("/api/admin/students")
async def admin_students(x_telegram_init_data: str | None = Header(default=None)) -> dict[str, Any]:
    await _require_admin(x_telegram_init_data)
    async with session_scope(app.state.session_factory) as session:
        repo = BotRepo(session)
        students = await repo.list_students()
        result = []
        for student in students:
            selected_topics = await repo.get_student_topics(student.id)
            result.append(
                {
                    "id": student.id,
                    "telegram_id": student.telegram_id,
                    "full_name": student.full_name,
                    "subject": student.subject,
                    "selected_topics": selected_topics,
                }
            )
    return {"items": result}


@app.get("/api/admin/students/{student_id}/topics")
async def admin_student_topics(student_id: int, x_telegram_init_data: str | None = Header(default=None)) -> dict[str, Any]:
    await _require_admin(x_telegram_init_data)
    async with session_scope(app.state.session_factory) as session:
        repo = BotRepo(session)
        student = await repo.get_user_by_id(student_id)
        if not student or student.role != UserRole.STUDENT:
            raise HTTPException(status_code=404, detail="Student not found")
        available = await repo.list_student_material_topics(student_id)
        selected = await repo.get_student_topics(student_id)
    return {
        "student_id": student_id,
        "available_topics": available,
        "selected_topics": selected,
    }


@app.post("/api/admin/students/{student_id}/topics")
async def admin_set_student_topics(
    student_id: int,
    payload: TopicsPayload,
    x_telegram_init_data: str | None = Header(default=None),
) -> dict[str, Any]:
    await _require_admin(x_telegram_init_data)
    async with session_scope(app.state.session_factory) as session:
        repo = BotRepo(session)
        student = await repo.get_user_by_id(student_id)
        if not student or student.role != UserRole.STUDENT:
            raise HTTPException(status_code=404, detail="Student not found")
        selected = await repo.replace_student_topics(student_id, payload.topics)
    return {"student_id": student_id, "selected_topics": selected}


@app.post("/api/admin/students/{student_id}/generate")
async def admin_generate_student(student_id: int, x_telegram_init_data: str | None = Header(default=None)) -> dict[str, Any]:
    await _require_admin(x_telegram_init_data)
    settings = app.state.settings
    today = datetime.now(ZoneInfo(settings.timezone)).date()
    async with session_scope(app.state.session_factory) as session:
        repo = BotRepo(session)
        student = await repo.get_user_by_id(student_id)
        if not student or student.role != UserRole.STUDENT:
            raise HTTPException(status_code=404, detail="Student not found")
        for difficulty in (Difficulty.EASY, Difficulty.MEDIUM, Difficulty.HARD):
            await app.state.quiz_service.ensure_daily_quiz(repo, student, today, difficulty, force_regenerate=True)
    return {"status": "ok", "student_id": student_id, "date": today.isoformat()}


@app.post("/api/admin/generate-all")
async def admin_generate_all(x_telegram_init_data: str | None = Header(default=None)) -> dict[str, Any]:
    await _require_admin(x_telegram_init_data)
    settings = app.state.settings
    today = datetime.now(ZoneInfo(settings.timezone)).date()
    async with session_scope(app.state.session_factory) as session:
        repo = BotRepo(session)
        students = await repo.list_students()
        for student in students:
            for difficulty in (Difficulty.EASY, Difficulty.MEDIUM, Difficulty.HARD):
                await app.state.quiz_service.ensure_daily_quiz(repo, student, today, difficulty, force_regenerate=True)
    return {"status": "ok", "date": today.isoformat()}


@app.post("/api/admin/material/upload")
async def admin_upload_material(
    student_id: int = Form(...),
    file: UploadFile = File(...),
    x_telegram_init_data: str | None = Header(default=None),
) -> dict[str, Any]:
    await _require_admin(x_telegram_init_data)
    if not file.filename or not file.filename.lower().endswith(".ipynb"):
        raise HTTPException(status_code=400, detail="Only .ipynb is supported")
    raw = await file.read()
    digest = await build_notebook_digest(raw, app.state.llm_client)
    async with session_scope(app.state.session_factory) as session:
        repo = BotRepo(session)
        student = await repo.get_user_by_id(student_id)
        if not student or student.role != UserRole.STUDENT:
            raise HTTPException(status_code=404, detail="Student not found")
        created = await repo.create_material(
            student_id=student_id,
            title=digest.title,
            source_filename=file.filename,
            content_hash=digest.content_hash,
            compact_context=digest.compact_context,
            tokens_estimate=digest.tokens_estimate,
        )
    return {
        "status": "created" if created else "duplicate",
        "title": digest.title,
        "filename": file.filename,
    }
