"""LiveTeach API (FastAPI). Every request names the teacher app it comes from (X-Teacher-Id header).
The app's screens are in English; the AI teacher answers in whatever language the student asks in.

Run:  uvicorn app.main:app --reload
"""
import base64
import copy
import hmac
import os
import time

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from .config import settings
from .db import Database
from .i18n import t
from .services import accounts, admin, admin_auth, builds, notes_pdf, payments
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
            "brand_color": row["brand_color"], "plans": plans, "demo_questions": _limits(teacher.id)["demo"]}


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


def _limits(teacher_id: str) -> dict:
    """This teacher's demo/grace settings → admin Settings defaults → .env defaults."""
    d = admin.get_settings(db)["defaults"]
    t = db.one("SELECT demo_questions, grace_days, grace_questions FROM teachers WHERE id = ?", (teacher_id,))
    pick = lambda col, key, env: t[col] if t and t[col] is not None else d.get(key, env)  # noqa: E731
    return {"demo": int(pick("demo_questions", "demo_questions", settings.demo_question_limit)),
            "grace_days": int(pick("grace_days", "grace_days", settings.grace_days)),
            "grace_questions": int(pick("grace_questions", "grace_questions", settings.grace_questions)),
            "reminder": int(d.get("renew_reminder_days", settings.renew_reminder_days))}


def _access(student_id: int) -> dict:
    tid = db.one("SELECT teacher_id FROM students WHERE id = ?", (student_id,))["teacher_id"]
    lim = _limits(tid)
    return accounts.access_status(db, student_id, lim["demo"], lim["grace_days"], lim["grace_questions"], lim["reminder"])


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
    lim = _limits(teacher.id)
    if not accounts.consume_question(db, student["id"], lim["demo"], lim["grace_days"], lim["grace_questions"]):
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


def _pay_settings():
    """.env payment settings, overridden by the admin panel's Settings (linked account, default split)."""
    s = copy.copy(settings)
    ps = admin.get_settings(db)
    if ps["company"].get("linked_account"):
        s.platform_linked_account = ps["company"]["linked_account"]
    s.platform_commission_percent = float(ps["defaults"].get("platform_percent", s.platform_commission_percent))
    return s


@app.post("/pay/checkout")
def checkout(body: Checkout, student=Depends(current_student)):
    try:
        return payments.start_checkout(db, student["id"], body.plan_id, _pay_settings())
    except KeyError:
        raise HTTPException(404, "Plan not found")


@app.post("/pay/confirm")
def confirm(body: PaymentDone, student=Depends(current_student)):
    secret = payments.teacher_payment_settings(db, student["teacher_id"], _pay_settings())["key_secret"]
    if not payments.verify_payment_signature(body.razorpay_order_id, body.razorpay_payment_id,
                                             body.razorpay_signature, secret):
        raise HTTPException(400, "Payment could not be verified")
    return payments.mark_paid(db, body.razorpay_order_id, body.razorpay_payment_id)


@app.post("/pay/webhook/{teacher_id}")
async def razorpay_webhook(teacher_id: str, request: Request, x_razorpay_signature: str = Header(...)):
    """Each teacher's Razorpay account points its webhook at /pay/webhook/<teacher id>."""
    raw = await request.body()
    try:
        secret = payments.teacher_payment_settings(db, teacher_id, _pay_settings())["webhook_secret"]
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


# ---------- Durina admin panel ----------
# Open https://<server>/admin in a browser and log in with email + password.
# The first owner account comes from ADMIN_EMAIL / ADMIN_PASSWORD in .env.

admin_auth.ensure_first_admin(db, os.environ.get("ADMIN_EMAIL"), os.environ.get("ADMIN_PASSWORD"))

AVATAR_DIR = os.environ.get("AVATAR_DIR", "avatars")
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


def require_admin(authorization: str = Header("")):
    try:
        return admin_auth.read_session(db, authorization.removeprefix("Bearer ").strip(), settings.jwt_secret)
    except admin_auth.LoginError as exc:
        raise HTTPException(401, str(exc))


class AdminLogin(BaseModel):
    email: str
    password: str


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


@app.post("/admin/api/login")
def admin_login(body: AdminLogin, request: Request):
    try:
        return admin_auth.login(db, body.email, body.password, settings.jwt_secret,
                                request.client.host if request.client else "")
    except admin_auth.LoginError as exc:
        raise HTTPException(401, str(exc))


@app.get("/admin/api/me")
def admin_me(user=Depends(require_admin)):
    logins = [dict(r) for r in db.all("SELECT at, ip, success FROM admin_logins WHERE email = ? ORDER BY id DESC LIMIT 5",
                                      (user["email"],))]
    return {"email": user["email"], "name": user["name"], "role": user["role"], "recent_logins": logins}


@app.post("/admin/api/password")
def admin_password(body: PasswordChange, user=Depends(require_admin)):
    try:
        admin_auth.change_password(db, user["id"], body.current_password, body.new_password)
    except admin_auth.LoginError as exc:
        raise HTTPException(400, str(exc))
    return {"changed": True}


def _default_pct() -> float:
    return float(admin.get_settings(db)["defaults"]["platform_percent"])


@app.get("/admin", response_class=HTMLResponse)
def admin_page():
    with open(os.path.join(STATIC_DIR, "admin.html"), encoding="utf-8") as f:
        return f.read()


@app.get("/admin/api/overview", dependencies=[Depends(require_admin)])
def admin_overview():
    return {"overview": admin.overview(db, _default_pct()), "teachers": admin.list_teachers(db, _default_pct())}


@app.get("/admin/api/teachers/{tid}", dependencies=[Depends(require_admin)])
def admin_teacher(tid: str):
    try:
        return admin.teacher_detail(db, tid, _default_pct())
    except KeyError:
        raise HTTPException(404, "Teacher not found")


@app.post("/admin/api/teachers", dependencies=[Depends(require_admin)])
async def admin_create_teacher(request: Request):
    return _save_teacher(await request.json(), creating=True)


@app.put("/admin/api/teachers/{tid}", dependencies=[Depends(require_admin)])
async def admin_update_teacher(tid: str, request: Request):
    data = await request.json()
    data["id"] = tid
    return _save_teacher(data, creating=False)


def _save_teacher(data: dict, creating: bool):
    try:
        out = admin.save_teacher(db, data, creating)
    except admin.AdminError as exc:
        raise HTTPException(400, str(exc))
    except KeyError:
        raise HTTPException(404, "Teacher not found")
    photo = data.get("photo_base64")
    if photo:
        os.makedirs(AVATAR_DIR, exist_ok=True)
        raw = base64.b64decode(photo.split(",", 1)[-1])
        if len(raw) > 5_000_000:
            raise HTTPException(400, "Photo must be under 5 MB")
        with open(os.path.join(AVATAR_DIR, f"{out['id']}.jpg"), "wb") as f:
            f.write(raw)
        db.execute("UPDATE teachers SET avatar_url = ? WHERE id = ?", (f"/teachers/{out['id']}/avatar", out["id"]))
        out["has_avatar"] = True
    return out


@app.post("/admin/api/teachers/{tid}/checklist", dependencies=[Depends(require_admin)])
async def admin_checklist(tid: str, request: Request):
    body = await request.json()
    try:
        return admin.set_checklist(db, tid, body.get("item", ""), bool(body.get("done")))
    except (KeyError, admin.AdminError) as exc:
        raise HTTPException(400, str(exc))


@app.post("/admin/api/teachers/{tid}/build", dependencies=[Depends(require_admin)])
def admin_build(tid: str, request: Request):
    t = db.one("SELECT * FROM teachers WHERE id = ?", (tid,))
    if t is None:
        raise HTTPException(404, "Teacher not found")
    base = os.environ.get("PUBLIC_BASE_URL") or str(request.base_url).rstrip("/")
    avatar = f"{base}/teachers/{tid}/avatar" if t["avatar_url"] else ""
    try:
        builds.trigger_build(dict(t), avatar, base)
    except builds.BuildError as exc:
        raise HTTPException(400, str(exc))
    if t["status"] == "draft":
        admin.set_status(db, tid, "building")
    return {"started": True}


@app.get("/admin/api/teachers/{tid}/builds", dependencies=[Depends(require_admin)])
def admin_builds(tid: str):
    try:
        return builds.list_builds(tid)
    except builds.BuildError as exc:
        return {"error": str(exc), "builds": []}


@app.get("/admin/api/settings", dependencies=[Depends(require_admin)])
def admin_get_settings():
    return admin.get_settings(db)


@app.put("/admin/api/settings", dependencies=[Depends(require_admin)])
async def admin_put_settings(request: Request):
    try:
        return admin.save_settings(db, await request.json())
    except admin.AdminError as exc:
        raise HTTPException(400, str(exc))


@app.get("/teachers/{tid}/avatar")
def teacher_avatar(tid: str):
    path = os.path.join(AVATAR_DIR, f"{os.path.basename(tid)}.jpg")
    if not os.path.exists(path):
        raise HTTPException(404, "No photo")
    return FileResponse(path, media_type="image/jpeg")


@app.get("/health")
def health():
    return {"ok": True, "time": time.time()}
