"""LiveTeach API (FastAPI). Every request names the teacher app it comes from (X-Teacher-Id header).
The app's screens are in English; the AI teacher answers in whatever language the student asks in.

Run:  uvicorn app.main:app --reload
"""
import base64
import copy
import hmac
import os
import re
import time

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from .config import settings
from .db import Database
from .i18n import t
from .services import accounts, admin, admin_auth, builds, notes_pdf, payments
from .services import style as style_mod
from .services import teacher_data
from .services import classroom, quiz, share
from .services import admin_reports
from .services import limits
from .services import student_safety
from .services import moderation
from .services import switches
from .languages import detect_language
from fastapi.responses import Response
from .services.knowledge import KnowledgeBase
from .services.llm import FakeLLM, OpenAICompatibleLLM
from .services.tutor import TeacherProfile, Tutor, approve_answer, is_save_command, review_queue


def sms_console(phone: str, message: str) -> None:
    print(f"[SMS to {phone}] {message}")  # replace with a real SMS provider in production


db = Database(settings.database_path)
kb = KnowledgeBase(db)


def _client(model: str, timeout: float = 60):
    if not settings.llm_api_key:
        return None
    return OpenAICompatibleLLM(settings.llm_base_url, settings.llm_api_key, model, timeout) if model else None


_fake = None if settings.llm_api_key else FakeLLM()   # local development / tests without an AI key
_main, _small, _backup = settings.llm_model, settings.llm_small_model, settings.llm_backup_model
# A4: every job goes to the first model in line that is not switched off in admin → Emergency
raw_llm = switches.ModelRouter(db, [(_main, _client(_main) or _fake), (_backup, _client(_backup))])
# optional cheaper model for small helper jobs (search keywords, safety check); answers, notes and tests use the
# main model. Search keywords are never shown to the student, so they skip the output check.
side_llm = switches.ModelRouter(db, [(_small, _client(_small)), (_main, _client(_main) or _fake), (_backup, _client(_backup))])

# A2: independent safety check on every student message and every AI text before a student sees it
_provider = settings.moderation_provider
if _provider == "auto":
    _provider = "llm" if settings.llm_api_key else "rules"
if _provider == "rules":
    print("[safety] WARNING: safety model is OFF (rules only). Set LLM_API_KEY or MODERATION_PROVIDER before launch.")
_mod_model = settings.llm_small_model or settings.llm_model
moderator = moderation.Moderator(
    db, _provider,
    switches.ModelRouter(db, [(_small, _client(_small, 12)), (_main, _client(_main, 12) or FakeLLM()), (_backup, _client(_backup, 12))]),
    settings.llm_base_url, settings.llm_api_key,
    model_name="omni-moderation-latest" if _provider == "openai" else (_mod_model if _provider == "llm" else "rules"))
llm = moderation.ModeratedLLM(raw_llm, moderator)
tutor = Tutor(db, kb, llm, side_llm)
otp = accounts.OtpService(db, settings.jwt_secret, sms_console)

app = FastAPI(title="LiveTeach API", version="0.1.0")


@app.exception_handler(switches.AIPaused)
def _ai_paused(request: Request, exc: switches.AIPaused):
    from fastapi.responses import JSONResponse
    return JSONResponse({"detail": t("ai_paused", "en")}, status_code=503)


@app.exception_handler(moderation.Unavailable)
def _moderation_down(request: Request, exc: moderation.Unavailable):
    from fastapi.responses import JSONResponse
    return JSONResponse({"detail": t("safety_retry", "en")}, status_code=503)


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
    if row["status"] == "disabled":   # A3: a disabled account can do nothing, even with an old login
        raise HTTPException(403, student_safety.account(db, student_id)["account_message"])
    return {"id": student_id, "teacher_id": teacher_id}


def teacher_admin(x_teacher_id: str = Header(...), x_teacher_key: str = Header(...)) -> str:
    expected = os.environ.get(f"TEACHER_KEY_{x_teacher_id.upper()}", "")
    if not expected or not hmac.compare_digest(expected, x_teacher_key):
        raise HTTPException(403, "Not allowed")
    return x_teacher_id


# ---------- app config & languages ----------

@app.get("/teacher")
def teacher_info(request: Request, teacher: TeacherProfile = Depends(teacher_from_header)):
    row = db.one("SELECT * FROM teachers WHERE id = ?", (teacher.id,))
    plans = [dict(p) for p in db.all("SELECT id, name, amount_paise, duration_days FROM plans "
                                     "WHERE teacher_id = ? AND active = 1", (teacher.id,))]
    return {"id": row["id"], "name": row["name"], "subject": row["subject"], "avatar_url": row["avatar_url"],
            "brand_color": row["brand_color"], "plans": plans, "demo_questions": _limits(teacher.id)["demo"],
            "share_url": share.share_url(settings.public_base_url, row["id"], str(request.base_url)),
            "features": {"ai_chat": not switches.ai_paused_for(db, teacher.id), "voice": not switches.is_off(db, "voice"),
                         "photo": not switches.is_off(db, "photo")}}


# ---------- rate limits (A6) ----------

def _limit_settings() -> dict:
    return limits.settings(admin.get_settings(db))


def _client_ip(request: Request) -> str:
    if settings.trust_proxy:   # only behind our own proxy / load balancer, which sets this header
        fwd = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        if fwd:
            return fwd
    return request.client.host if request.client else ""


def _too_many(exc: limits.Limited) -> HTTPException:
    return HTTPException(429, str(exc), headers={"Retry-After": str(exc.retry_after)})


def _gate(student_id: int) -> None:
    """A3: a suspended / under-review / disabled student can't use Sir's AI (checked on the server every time,
    so logging out, reinstalling or a new class doesn't help). Notes, library and payments keep working."""
    row = db.one("SELECT teacher_id FROM students WHERE id = ?", (student_id,))
    moderation.request_ctx.set({"student_id": student_id, "teacher_id": row["teacher_id"] if row else None})
    if switches.ai_paused_for(db, row["teacher_id"] if row else None) or not raw_llm.available():   # A4 kill switch
        raise HTTPException(503, t("ai_paused", "en"))
    blocked = student_safety.can_use_ai(db, student_id)
    if blocked:
        raise HTTPException(403, blocked["account_message"])


def _limit_questions(student_id: int) -> None:
    """Every action that makes Sir's AI work counts: questions, class notes, new tests, written/oral answers."""
    _gate(student_id)
    try:
        limits.check_and_record(db, limits.question_rules(student_id, _limit_settings()))
    except limits.Limited as exc:
        raise _too_many(exc)


# ---------- login ----------

class OtpRequest(BaseModel):
    phone: str


class OtpVerify(BaseModel):
    phone: str
    code: str


@app.post("/auth/otp")
def send_otp(body: OtpRequest, request: Request, teacher: TeacherProfile = Depends(teacher_from_header),
             x_device_id: str = Header("")):
    try:
        phone = accounts.normalize_phone(body.phone)
        lim = _limit_settings()
        limits.check_and_record(db, [limits.wrong_code_rule(teacher.id, phone, lim)], record=False)  # locked number
        limits.check_and_record(db, limits.otp_send_rules(teacher.id, phone, x_device_id.strip(),
                                                          _client_ip(request), lim))
        otp.send(teacher.id, teacher.name, phone)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except limits.Limited as exc:
        raise _too_many(exc)
    return {"sent": True}


@app.post("/auth/verify")
def verify_otp(body: OtpVerify, teacher: TeacherProfile = Depends(teacher_from_header)):
    try:
        phone = accounts.normalize_phone(body.phone)
        wrong = limits.wrong_code_rule(teacher.id, phone, _limit_settings())
        limits.check_and_record(db, [wrong], record=False)   # too many wrong codes today: number is locked
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except limits.Limited as exc:
        raise _too_many(exc)
    try:
        phone = otp.verify(teacher.id, phone, body.code)
    except accounts.WrongCode as exc:
        limits.record(db, wrong.key)
        raise HTTPException(400, str(exc))
    except (accounts.AuthError, ValueError) as exc:
        raise HTTPException(400, str(exc))
    student_id = accounts.get_or_create_student(db, teacher.id, phone)
    if student_safety.status(db, student_id) == "disabled":
        raise HTTPException(403, student_safety.account(db, student_id)["account_message"])
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
    return {**accounts.access_status(db, student_id, lim["demo"], lim["grace_days"], lim["grace_questions"], lim["reminder"]),
            **student_safety.account(db, student_id),
            "service_message": t("ai_paused", "en") if switches.ai_paused_for(db, tid) or not raw_llm.available() else None}


def _after_answer(student_id: int, teacher_id: str, question: str, result) -> None:
    """A3: a blocked topic is a minor violation, a clearly harmful request a serious one (off-topic chat is neither)."""
    if result.scope not in ("blocked", "unsafe"):
        return
    row = db.one("SELECT blocked_topic FROM qa_history WHERE id = ?", (result.qa_id,))
    sev = "minor" if result.scope == "blocked" else "serious"
    student_safety.record_violation(db, student_id, teacher_id, sev, (row["blocked_topic"] if row else "") or result.scope,
                                    question, result.qa_id, student_safety.safety_settings(admin.get_settings(db)))


class StudentName(BaseModel):
    name: str


@app.put("/me/name")
def set_my_name(body: StudentName, student=Depends(current_student)):
    """'What should Sir call you?' — the AI teacher uses it now and then."""
    name = body.name.strip()[:40]
    if name:   # the name goes into Sir's instructions, so it is checked like a message
        moderation.request_ctx.set({"student_id": student["id"], "teacher_id": student["teacher_id"]})
        if not _check_input(name).safe:
            raise HTTPException(400, "Please choose a different name.")
    db.execute("UPDATE students SET name = ? WHERE id = ?", (name or None, student["id"]))
    return {"name": name}


@app.get("/me/access")
def my_access(student=Depends(current_student)):
    return _access(student["id"])


# ---------- live class ----------

class Ask(BaseModel):
    question: str
    last_qa_id: int | None = None  # the answer on screen, used when the student says "save this"


def _consume(student_id: int, teacher: TeacherProfile) -> None:
    lim = _limits(teacher.id)
    if not accounts.consume_question(db, student_id, lim["demo"], lim["grace_days"], lim["grace_questions"]):
        ended = _access(student_id)["state"] == "expired"
        raise HTTPException(402, t("plan_ended" if ended else "demo_over", "en", teacher=teacher.name))


def _class_notes(student_id: int, teacher: TeacherProfile, session_id: int | None, topics: list[str] | None):
    try:
        return classroom.save_class_notes(db, llm, student_id, teacher.name, settings.notes_dir, session_id, topics)
    except classroom.ClassError as exc:
        raise HTTPException(400, str(exc))


def _retry() -> HTTPException:
    return HTTPException(503, t("safety_retry", "en"))


def _check_input(text: str) -> moderation.Verdict:
    """A2 stage 1. If the check can't run, the student is asked to try again (nothing unchecked goes through)."""
    try:
        return moderator.check_input(text)
    except moderation.Unavailable:
        raise _retry()


def _safe_reply(student_id: int, teacher: TeacherProfile, question: str, v: moderation.Verdict, session_id):
    """A message the input check stopped: no AI call. Care for a student in distress; a kind refusal for a harmful
    request (serious, counts in A3); a study redirect for a small problem (minor, counts in A3)."""
    lang = detect_language(question)
    level = style_mod.get_level(db, student_id)
    if v.severity == "care":
        result = tutor._redirect(student_id, question, lang, "care", None, level, session_id, "care_message")
    elif v.severity == "serious":
        result = tutor._redirect(student_id, question, lang, "unsafe", v.category, level, session_id, "safety_refusal")
    else:
        result = tutor._redirect(student_id, question, lang, "blocked", v.category, level, session_id)
    _after_answer(student_id, teacher.id, question, result)
    return result


def _refund(student_id: int) -> None:
    """The safety check failed after a demo question was counted: give it back."""
    if _access(student_id)["state"] == "demo":
        db.execute("UPDATE students SET demo_questions_used = MAX(demo_questions_used - 1, 0) WHERE id = ?", (student_id,))


def _answer_safely(student_id: int, teacher: TeacherProfile, question: str, session_id):
    """A2 stage 2 happens inside the model wrapper: an unsafe AI answer is never stored or shown."""
    try:
        result = tutor.answer(student_id, teacher, question, session_id)
    except moderation.UnsafeOutput:
        lang = detect_language(question)
        return tutor._redirect(student_id, question, lang, "stopped", None, style_mod.get_level(db, student_id),
                               session_id, "safety_replaced")
    except moderation.Unavailable:
        _refund(student_id)
        raise _retry()
    except switches.AIPaused:   # switched off while this question was on its way
        _refund(student_id)
        raise HTTPException(503, t("ai_paused", "en"))
    _after_answer(student_id, teacher.id, question, result)
    return result


@app.post("/class/ask")
def ask(body: Ask, student=Depends(current_student), teacher: TeacherProfile = Depends(teacher_from_header)):
    _limit_questions(student["id"])
    session_id = classroom.current_session(db, student["id"], teacher.id)
    if is_save_command(body.question):   # "Sir, save this" = notes of the whole class so far
        return {"type": "note_saved", "note": _class_notes(student["id"], teacher, session_id, None)}
    if quiz.is_test_command(body.question):   # "Sir, test lo" → the app asks MCQ / written / oral
        return {"type": "test_offer", "mode": quiz.mode_in(body.question), **classroom.class_summary(
            db, student["id"], classroom.latest_session_with_content(db, student["id"], session_id))}
    verdict = _check_input(body.question)
    if not verdict.safe:
        result = _safe_reply(student["id"], teacher, body.question, verdict, session_id)
        return {"type": "answer", **result.__dict__, **_access(student["id"])}
    _consume(student["id"], teacher)
    result = _answer_safely(student["id"], teacher, body.question, session_id)
    return {"type": "answer", **result.__dict__, **_access(student["id"])}


@app.get("/class/current")
def class_current(student=Depends(current_student)):
    """Topics of the class in progress (for 'choose topics' and the end-of-class test offer)."""
    return classroom.class_summary(db, student["id"], classroom.open_session(db, student["id"]))


@app.post("/class/end")
def class_end(student=Depends(current_student)):
    sid = classroom.end_session(db, student["id"])
    return classroom.class_summary(db, student["id"], sid)


class ClassNotes(BaseModel):
    topics: list[str] | None = None     # None = every topic of the class
    session_id: int | None = None       # None = the class in progress (or the last one)


@app.post("/class/notes")
def class_notes(body: ClassNotes, student=Depends(current_student),
                teacher: TeacherProfile = Depends(teacher_from_header)):
    sid = body.session_id or classroom.open_session(db, student["id"])
    if body.session_id and not db.one("SELECT 1 FROM class_sessions WHERE id = ? AND student_id = ?",
                                      (body.session_id, student["id"])):
        raise HTTPException(404, "Class not found")
    _limit_questions(student["id"])
    return _class_notes(student["id"], teacher, sid, body.topics)


# ---------- test series ----------

class NewTest(BaseModel):
    mode: str                            # mcq | written | oral
    topics: list[str] | None = None
    session_id: int | None = None


class TestAnswer(BaseModel):
    answer: int | str | None = None      # MCQ: option index (or "B"); written / oral: the student's answer


class Reteach(BaseModel):
    yes: bool


@app.post("/tests")
def new_test(body: NewTest, student=Depends(current_student), teacher: TeacherProfile = Depends(teacher_from_header)):
    sid = body.session_id or classroom.open_session(db, student["id"])
    if body.session_id and not db.one("SELECT 1 FROM class_sessions WHERE id = ? AND student_id = ?",
                                      (body.session_id, student["id"])):
        raise HTTPException(404, "Class not found")
    if body.mode not in quiz.MODES:
        raise HTTPException(400, "Choose MCQ, written or oral")
    _limit_questions(student["id"])
    _consume(student["id"], teacher)   # a test counts as one question of the plan / demo
    try:
        return quiz.create_test(db, llm, student["id"], teacher.id, teacher.name, body.mode, sid, body.topics)
    except quiz.TestError as exc:
        raise HTTPException(400, str(exc))


@app.get("/tests")
def my_tests(student=Depends(current_student)):
    return {"items": quiz.history(db, student["id"])}


@app.get("/tests/{test_id}")
def get_test(test_id: int, student=Depends(current_student)):
    try:
        return quiz.public_view(quiz._load(db, student["id"], test_id))
    except KeyError:
        raise HTTPException(404, "Test not found")


@app.post("/tests/{test_id}/answer")
def answer_test(test_id: int, body: TestAnswer, student=Depends(current_student),
                teacher: TeacherProfile = Depends(teacher_from_header)):
    _gate(student["id"])
    row = db.one("SELECT mode FROM tests WHERE id = ? AND student_id = ?", (test_id, student["id"]))
    if row is not None and row["mode"] != "mcq":   # MCQ is checked without AI, so it is not limited
        _limit_questions(student["id"])
        if isinstance(body.answer, str):
            v = _check_input(body.answer)
            if not v.safe:
                if v.severity in ("serious", "minor"):
                    student_safety.record_violation(db, student["id"], teacher.id, v.severity, v.category, body.answer,
                                                    None, student_safety.safety_settings(admin.get_settings(db)))
                raise HTTPException(400, t("care_message" if v.severity == "care" else "safety_refusal", "en"))
    try:
        return quiz.answer_question(db, llm, student["id"], test_id, body.answer, teacher.name)
    except KeyError:
        raise HTTPException(404, "Test not found")
    except quiz.TestError as exc:
        raise HTTPException(400, str(exc))


@app.post("/tests/{test_id}/reteach")
def test_reteach(test_id: int, body: Reteach, student=Depends(current_student),
                 teacher: TeacherProfile = Depends(teacher_from_header)):
    """'Shall I teach it again?' — yes: Sir teaches the weak topics again right away (counts as one question)."""
    if body.yes:
        _limit_questions(student["id"])
    try:
        request_text = quiz.reteach(db, student["id"], test_id, body.yes)
    except KeyError:
        raise HTTPException(404, "Test not found")
    except quiz.TestError as exc:
        raise HTTPException(400, str(exc))
    if request_text is None:
        return {"type": "none"}
    _consume(student["id"], teacher)
    session_id = classroom.current_session(db, student["id"], teacher.id)
    result = _answer_safely(student["id"], teacher, request_text, session_id)
    return {"type": "answer", "question": request_text, **result.__dict__, **_access(student["id"])}


@app.post("/notes/{qa_id}")
def save_note(qa_id: int, student=Depends(current_student), teacher: TeacherProfile = Depends(teacher_from_header)):
    try:
        return notes_pdf.save_note(db, student["id"], qa_id, teacher.name, settings.notes_dir)
    except KeyError:
        raise HTTPException(404, "Answer not found")


@app.get("/t/{teacher_id}", response_class=HTMLResponse)
def share_page(teacher_id: str):
    """The link that goes with everything a student shares: teacher's name and photo + 'Get the app'."""
    row = db.one("SELECT * FROM teachers WHERE id = ?", (teacher_id,))
    if row is None:
        raise HTTPException(404, "Not found")
    return HTMLResponse(share.share_page_html(dict(row)), headers={"Cache-Control": "public, max-age=300"})


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
    if student_safety.status(db, student["id"]) == "review":   # no new payments while the team reviews the account
        raise HTTPException(403, student_safety.account(db, student["id"])["account_message"])
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


@app.get("/teacher/style")
def teacher_style(teacher_id: str = Depends(teacher_admin)):
    return {"style": style_mod.get_style(db, teacher_id), "personalities": style_mod.PERSONALITIES,
            "interaction": {k: t for k, (t, _) in style_mod.INTERACTION.items()},
            "avatar": {k: t for k, (t, _) in style_mod.AVATAR.items()}}


@app.put("/teacher/style")
async def teacher_style_save(request: Request, teacher_id: str = Depends(teacher_admin)):
    return style_mod.save_style(db, teacher_id, await request.json())


@app.get("/teacher/review")
def teacher_review(offset: int = 0, limit: int = 20, q: str = "", origin: str = "", sort: str = "most_asked",
                   status: str = "pending", teacher_id: str = Depends(teacher_admin)):
    return teacher_data.review_page(db, teacher_id, offset, limit, q, origin, sort, status)


@app.post("/teacher/review/undo")
async def teacher_review_undo(request: Request, teacher_id: str = Depends(teacher_admin)):
    """Approved or rejected by mistake → back to Waiting (an approved answer stops being used at once)."""
    return teacher_data.review_undo(db, teacher_id, (await request.json()).get("ids", []))


@app.put("/teacher/verified/{verified_id}")
async def teacher_edit_verified(verified_id: int, request: Request, teacher_id: str = Depends(teacher_admin)):
    try:
        return teacher_data.edit_verified(db, teacher_id, verified_id, (await request.json()).get("answer", ""))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except KeyError:
        raise HTTPException(404, "Approved answer not found")


@app.post("/teacher/review/bulk")
async def teacher_review_bulk(request: Request, teacher_id: str = Depends(teacher_admin)):
    body = await request.json()
    return teacher_data.review_decide(db, teacher_id, body.get("decisions", []))


@app.get("/teacher/students")
def teacher_students(offset: int = 0, limit: int = 25, q: str = "", status: str = "",
                     teacher_id: str = Depends(teacher_admin)):
    return teacher_data.students_page(db, teacher_id, offset, limit, q, status)


def _report_response(tid: str, month: str, fmt: str, audience: str, date_from: str = "", date_to: str = ""):
    """month=2026-11, or any period: date_from/date_to (a year, a financial year, custom dates)."""
    if date_from or date_to:
        try:
            start, end, p_from, p_to = teacher_data.parse_period(date_from, date_to)
        except teacher_data.ReportError as exc:
            raise HTTPException(400, str(exc))
        rep = teacher_data.period_report(db, tid, start, end, p_from, p_to, _default_pct(), audience)
        name = f"liveteach-{tid}-{date_from}-to-{date_to}"
    else:
        if not re.fullmatch(r"\d{4}-\d{2}", month or ""):
            raise HTTPException(400, "month must look like 2026-11")
        rep = teacher_data.monthly_report(db, tid, month, _default_pct(), audience)
        name = f"liveteach-{tid}-{month}"
    if fmt == "xlsx":
        return Response(teacher_data.report_xlsx(rep), headers={"Content-Disposition": f'attachment; filename="{name}.xlsx"'},
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    if fmt == "pdf":
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            path = notes_pdf.render_pdf(teacher_data.report_html(rep), os.path.join(d, "r.pdf"))
            with open(path, "rb") as f:
                data = f.read()
        return Response(data, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{name}.pdf"'})
    return rep


@app.get("/teacher/report")
def teacher_report(month: str = "", format: str = "json", date_from: str = "", date_to: str = "",
                   teacher_id: str = Depends(teacher_admin)):
    return _report_response(teacher_id, month, format, "teacher", date_from, date_to)   # never shows Dhurina's share


@app.post("/teacher/review/{qa_id}/approve")
def teacher_approve(qa_id: int, body: Approval, teacher_id: str = Depends(teacher_admin)):
    try:
        approve_answer(db, teacher_id, qa_id, body.corrected_answer)
    except KeyError:
        raise HTTPException(404, "Not found")
    return {"approved": True}


# ---------- Dhurina admin panel ----------
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


@app.get("/admin/api/teachers/{tid}/report", dependencies=[Depends(require_admin)])
def admin_teacher_report(tid: str, month: str = "", format: str = "json", view: str = "admin", date_from: str = "", date_to: str = ""):
    """view=teacher gives exactly what the teacher sees (to send it to them)."""
    return _report_response(tid, month, format, "teacher" if view == "teacher" else "admin", date_from, date_to)


# ---- Reports: all teachers' sales for any period ----

def _rep_err(fn):
    try:
        return fn()
    except admin_reports.ReportError as exc:
        raise HTTPException(400, str(exc))


@app.get("/admin/api/reports", dependencies=[Depends(require_admin)])
def admin_reports_view(date_from: str, date_to: str, teacher: str = "", sort: str = "sales"):
    return _rep_err(lambda: admin_reports.full_report(db, date_from, date_to, _default_pct(), teacher or None, sort))


@app.get("/admin/api/reports/payments", dependencies=[Depends(require_admin)])
def admin_reports_payments(date_from: str, date_to: str, teacher: str = "", q: str = "", offset: int = 0, limit: int = 50):
    def run():
        start, end, _, _ = admin_reports.parse_period(date_from, date_to)
        return admin_reports.payments(db, start, end, _default_pct(), teacher or None, q, offset, limit)
    return _rep_err(run)


@app.get("/admin/api/reports/export", dependencies=[Depends(require_admin)])
def admin_reports_export(date_from: str, date_to: str, format: str = "xlsx", teacher: str = ""):
    rep = _rep_err(lambda: admin_reports.full_report(db, date_from, date_to, _default_pct(), teacher or None))
    name = f"liveteach-sales-{date_from}-to-{date_to}" + (f"-{teacher}" if teacher else "")
    if format == "pdf":
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            path = notes_pdf.render_pdf(admin_reports.export_html(rep), os.path.join(d, "r.pdf"))
            with open(path, "rb") as f:
                data = f.read()
        return Response(data, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{name}.pdf"'})
    return Response(admin_reports.export_xlsx(db, rep, _default_pct()),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}.xlsx"'})


@app.get("/admin/api/teachers/{tid}/students", dependencies=[Depends(require_admin)])
def admin_teacher_students(tid: str, offset: int = 0, limit: int = 25, q: str = "", status: str = ""):
    return teacher_data.students_page(db, tid, offset, limit, q, status)


@app.get("/admin/api/settings", dependencies=[Depends(require_admin)])
def admin_get_settings():
    return admin.get_settings(db)


@app.put("/admin/api/settings", dependencies=[Depends(require_admin)])
async def admin_put_settings(request: Request):
    try:
        return admin.save_settings(db, await request.json())
    except admin.AdminError as exc:
        raise HTTPException(400, str(exc))


# ---------- A3: student safety (block / unblock) ----------

class StudentAction(BaseModel):
    action: str                 # warn | suspend | review | disable | unblock
    reason: str
    remarks: str = ""
    hours: int | None = None    # for suspend


@app.get("/admin/api/students", dependencies=[Depends(require_admin)])
def admin_safety_students(status: str = "", q: str = "", teacher: str = "", offset: int = 0, limit: int = 25):
    return student_safety.list_students(db, status, q, teacher, offset, limit)


# ---------- A4: emergency kill switches ----------

def _models_in_use() -> list[dict]:
    rows = [("Main model (answers, notes, tests)", _main), ("Backup model (used when the main one is off)", _backup),
            ("Small helper model (keywords, safety check)", _small)]
    seen, out = set(), []
    for role, name in rows:
        if name and name not in seen:
            seen.add(name)
            out.append({"role": role, "name": name})
    return out


class SwitchChange(BaseModel):
    key: str
    off: bool
    reason: str


@app.get("/admin/api/emergency", dependencies=[Depends(require_admin)])
def admin_emergency():
    return {**switches.overview(db, _models_in_use()), "ai_available": raw_llm.available()}


@app.post("/admin/api/emergency")
def admin_emergency_set(body: SwitchChange, user=Depends(require_admin)):
    try:
        switches.set_switch(db, body.key, body.off, body.reason, user["email"])
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return admin_emergency()


@app.get("/admin/api/safety-events", dependencies=[Depends(require_admin)])
def admin_safety_events(limit: int = 30):
    """A2: what the safety check stopped (student messages and AI answers) and when it could not run."""
    return {**moderation.recent_events(db, max(1, min(limit, 100))), "provider": moderator.provider,
            "policy_version": moderation.POLICY_VERSION}


@app.get("/admin/api/students/{sid}", dependencies=[Depends(require_admin)])
def admin_safety_student(sid: int):
    try:
        return student_safety.detail(db, sid)
    except KeyError:
        raise HTTPException(404, "Student not found")


@app.post("/admin/api/students/{sid}/status")
def admin_safety_action(sid: int, body: StudentAction, user=Depends(require_admin)):
    try:
        return student_safety.admin_action(db, sid, body.action, body.reason, body.remarks, user["email"], body.hours)
    except KeyError:
        raise HTTPException(404, "Student not found")
    except student_safety.SafetyError as exc:
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
