"""LiveTeach API (FastAPI). Every request names the teacher app it comes from (X-Teacher-Id header).
The app's screens are in English; the AI teacher answers in whatever language the student asks in.

Run:  uvicorn app.main:app --reload
"""
import hmac
import os
import time

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .config import settings
from .db import Database
from .i18n import t
from .services import accounts, notes_pdf, payments
from .services.knowledge import KnowledgeBase
from .services.llm import FakeLLM, OpenAICompatibleLLM
from .services.tutor import TeacherProfile, Tutor, approve_answer, is_save_command, review_queue


def sms_console(phone: str, message: str) -> None:
    print(f"[SMS to {phone}] {message}")  # replace with a real SMS provider in production


db = Database(settings.database_path)
kb = KnowledgeBase(db)
llm = (OpenAICompatibleLLM(settings.llm_base_url, settings.llm_api_key, settings.llm_model)
       if settings.llm_api_key else FakeLLM())
tutor = Tutor(db, kb, llm)
otp = accounts.OtpService(db, settings.jwt_secret, sms_console)

app = FastAPI(title="LiveTeach API", version="0.1.0")


# ---------- dependencies ----------

def teacher_from_header(x_teacher_id: str = Header(...)) -> TeacherProfile:
    row = db.one("SELECT * FROM teachers WHERE id = ?", (x_teacher_id,))
    if row is None:
        raise HTTPException(404, "Unknown teacher app")
    return TeacherProfile(row["id"], row["name"], row["subject"] or "")


def current_student(authorization: str = Header(...)):
    try:
        student_id, teacher_id = accounts.read_token(authorization.removeprefix("Bearer ").strip(), settings.jwt_secret)
    except accounts.AuthError as exc:
        raise HTTPException(401, str(exc))
    row = db.one("SELECT * FROM students WHERE id = ?", (student_id,))
    if row is None:
        raise HTTPException(401, "Unknown student")
    return {"id": student_id, "teacher_id": teacher_id}


def teacher_admin(x_teacher_id: str = Header(...), x_teacher_key: str = Header(...)) -> str:
    expected = os.environ.get(f"TEACHER_KEY_{x_teacher_id.upper()}", "")
    if not expected or not hmac.compare_digest(expected, x_teacher_key):
        raise HTTPException(403, "Not allowed")
    return x_teacher_id


# ---------- app config & languages ----------

@app.get("/teacher")
def teacher_info(teacher: TeacherProfile = Depends(teacher_from_header)):
    row = db.one("SELECT * FROM teachers WHERE id = ?", (teacher.id,))
    plans = [dict(p) for p in db.all("SELECT id, name, amount_paise, duration_days FROM plans "
                                     "WHERE teacher_id = ? AND active = 1", (teacher.id,))]
    return {"id": row["id"], "name": row["name"], "subject": row["subject"], "avatar_url": row["avatar_url"],
            "brand_color": row["brand_color"], "plans": plans, "demo_questions": settings.demo_question_limit}


# ---------- login ----------

class OtpRequest(BaseModel):
    phone: str


class OtpVerify(BaseModel):
    phone: str
    code: str


@app.post("/auth/otp")
def send_otp(body: OtpRequest, teacher: TeacherProfile = Depends(teacher_from_header)):
    try:
        otp.send(teacher.id, teacher.name, body.phone)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"sent": True}


@app.post("/auth/verify")
def verify_otp(body: OtpVerify, teacher: TeacherProfile = Depends(teacher_from_header)):
    try:
        phone = otp.verify(teacher.id, body.phone, body.code)
    except (accounts.AuthError, ValueError) as exc:
        raise HTTPException(400, str(exc))
    student_id = accounts.get_or_create_student(db, teacher.id, phone)
    token = accounts.issue_token(student_id, teacher.id, settings.jwt_secret, settings.jwt_days)
    return {"token": token, **_access(student_id)}


def _access(student_id: int) -> dict:
    return accounts.access_status(db, student_id, settings.demo_question_limit, settings.grace_days,
                                  settings.grace_questions, settings.renew_reminder_days)


@app.get("/me/access")
def my_access(student=Depends(current_student)):
    return _access(student["id"])


# ---------- live class ----------

class Ask(BaseModel):
    question: str
    last_qa_id: int | None = None  # the answer on screen, used when the student says "save this"


@app.post("/class/ask")
def ask(body: Ask, student=Depends(current_student), teacher: TeacherProfile = Depends(teacher_from_header)):
    if body.last_qa_id and is_save_command(body.question):
        note = notes_pdf.save_note(db, student["id"], body.last_qa_id, teacher.name, settings.notes_dir)
        return {"type": "note_saved", "note": note}
    if not accounts.consume_question(db, student["id"], settings.demo_question_limit,
                                     settings.grace_days, settings.grace_questions):
        ended = _access(student["id"])["state"] == "expired"
        raise HTTPException(402, t("plan_ended" if ended else "demo_over", "en", teacher=teacher.name))
    result = tutor.answer(student["id"], teacher, body.question)
    return {"type": "answer", **result.__dict__, **_access(student["id"])}


@app.post("/notes/{qa_id}")
def save_note(qa_id: int, student=Depends(current_student), teacher: TeacherProfile = Depends(teacher_from_header)):
    try:
        return notes_pdf.save_note(db, student["id"], qa_id, teacher.name, settings.notes_dir)
    except KeyError:
        raise HTTPException(404, "Answer not found")


@app.get("/library")
def my_library(q: str | None = None, history_offset: int = 0, student=Depends(current_student)):
    return notes_pdf.library(db, student["id"], q=q, history_offset=history_offset)


@app.get("/notes")
def my_notes(offset: int = 0, limit: int = 20, q: str | None = None, student=Depends(current_student)):
    return notes_pdf.list_notes(db, student["id"], offset, limit, q)


@app.get("/notes/{note_id}/pdf")
def download_note(note_id: int, student=Depends(current_student)):
    row = db.one("SELECT * FROM saved_notes WHERE id = ? AND student_id = ?", (note_id, student["id"]))
    if row is None:
        raise HTTPException(404, "Note not found")
    return FileResponse(row["pdf_path"], media_type="application/pdf", filename=f"{row['title'][:40]}.pdf")


# ---------- payments ----------

class Checkout(BaseModel):
    plan_id: str


class PaymentDone(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


@app.post("/pay/checkout")
def checkout(body: Checkout, student=Depends(current_student)):
    try:
        return payments.start_checkout(db, student["id"], body.plan_id, settings)
    except KeyError:
        raise HTTPException(404, "Plan not found")


@app.post("/pay/confirm")
def confirm(body: PaymentDone, student=Depends(current_student)):
    secret = payments.teacher_payment_settings(db, student["teacher_id"], settings)["key_secret"]
    if not payments.verify_payment_signature(body.razorpay_order_id, body.razorpay_payment_id,
                                             body.razorpay_signature, secret):
        raise HTTPException(400, "Payment could not be verified")
    return payments.mark_paid(db, body.razorpay_order_id, body.razorpay_payment_id)


@app.post("/pay/webhook/{teacher_id}")
async def razorpay_webhook(teacher_id: str, request: Request, x_razorpay_signature: str = Header(...)):
    """Each teacher's Razorpay account points its webhook at /pay/webhook/<teacher id>."""
    raw = await request.body()
    try:
        secret = payments.teacher_payment_settings(db, teacher_id, settings)["webhook_secret"]
    except KeyError:
        raise HTTPException(404, "Unknown teacher")
    if not payments.verify_webhook_signature(raw, x_razorpay_signature, secret):
        raise HTTPException(400, "Bad signature")
    event = await request.json()
    if event.get("event") in ("payment.captured", "order.paid"):
        entity = event["payload"]["payment"]["entity"]
        try:
            payments.mark_paid(db, entity["order_id"], entity["id"])
        except KeyError:
            pass  # order not created by us
    return {"ok": True}


# ---------- teacher dashboard ----------

class Document(BaseModel):
    title: str
    text: str
    source_ref: str | None = None
    language: str | None = None


class Approval(BaseModel):
    corrected_answer: str | None = None


@app.post("/teacher/documents")
def add_document(body: Document, teacher_id: str = Depends(teacher_admin)):
    n = kb.add_document(teacher_id, body.title, body.text, body.source_ref, body.language)
    return {"chunks": n}


@app.get("/teacher/review")
def teacher_review(teacher_id: str = Depends(teacher_admin)):
    return review_queue(db, teacher_id)


@app.post("/teacher/review/{qa_id}/approve")
def teacher_approve(qa_id: int, body: Approval, teacher_id: str = Depends(teacher_admin)):
    try:
        approve_answer(db, teacher_id, qa_id, body.corrected_answer)
    except KeyError:
        raise HTTPException(404, "Not found")
    return {"approved": True}


@app.get("/health")
def health():
    return {"ok": True, "time": time.time()}
