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
from .services import audit
from . import ai_setup
from . import safety_lab
from .services import consent
from .services import safety_dashboard
from .services import incidents
from .services import roles
from .services import data_protection
from .services import alerts
from .services import photo as photo_mod
from .services import security
from .services import institute_status
from .services import parents
from .services import age_policy, content_filters, parent_notify
from . import i18n
from .services import policy
from .services.tutor import is_delete_command, is_photo_command, is_profile_command
from .services import faculty as faculty_mod, library, institute_auth
import threading
import hashlib
from .languages import detect_language
from fastapi.responses import Response
from .services.knowledge import KnowledgeBase
from .services.llm import FakeLLM, OpenAICompatibleLLM
from .services.tutor import TeacherProfile, Tutor, approve_answer, is_save_command, review_queue


def sms_console(phone: str, message: str) -> None:
    print(f"[SMS to {phone}] {message}")  # replace with a real SMS provider in production


db = Database(settings.database_path, settings.db_encryption_key or None)   # B6: encrypted at rest when keyed
kb = KnowledgeBase(db)


# the AI side (model router A4, safety check A2, AI teacher) — the safety test lab (A8) builds the very same pipeline
_ai = ai_setup.build(db, settings)
raw_llm, side_llm, moderator, llm, tutor = _ai.raw_llm, _ai.side_llm, _ai.moderator, _ai.llm, _ai.tutor
_main, _small, _backup, _provider = _ai.main, _ai.small, _ai.backup, _ai.provider
if _provider == "rules":
    print("[safety] WARNING: safety model is OFF (rules only). Set LLM_API_KEY or MODERATION_PROVIDER before launch.")
elif os.environ.get("SAFETY_LAB_AUTORUN", "1") == "1":
    safety_lab.start_background(settings, db, "startup")   # A8: new model / instructions on the server → test them
otp = accounts.OtpService(db, settings.jwt_secret, sms_console)
faculty_mod.ensure_all(db)   # multi-teacher migration: every existing app gets its one teacher as faculty
parent_notify.sender["sms"] = sms_console   # B9: parent SMS goes through the same SMS service as login codes
i18n.overrides["get"] = lambda: admin.get_settings(db).get("messages")   # B9: messages changed by the admin
AUDIT_SECRET = settings.audit_secret or hashlib.sha256(f"audit|{settings.jwt_secret}".encode()).hexdigest()

app = FastAPI(title="LiveTeach API", version="0.1.0")


# ---------- A5: admin / teacher audit log ----------

_WATCH_GET = re.compile(r"^/admin/api/(students/\d+|verify|incidents/\d+)$")
_TEACHER_WATCH_GET = re.compile(r"^/teacher/safety/\d+$")   # a teacher looking at a student's flagged messages


@app.middleware("http")
async def _audit_middleware(request: Request, call_next):
    path, method = request.url.path, request.method
    watched = (path.startswith("/admin/api/") and (method != "GET" or _WATCH_GET.match(path))) or \
              (path.startswith("/teacher/") and (method != "GET" or _TEACHER_WATCH_GET.match(path)))
    if not watched:
        return await call_next(request)
    body = await request.body() if method != "GET" else b""
    if path.startswith("/teacher/"):   # who it is, read before the action (a password change ends the old login)
        role, token = "teacher", request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        who = f"teacher:{request.headers.get('x-teacher-id', '?')}"
        if token:
            try:
                who = f"teacher:{institute_auth.read(db, token, settings.jwt_secret)}"
            except Exception:
                who = "teacher:invalid login"
        elif path == "/teacher/login":
            try:
                import json as _json
                who = "teacher-login:" + str(_json.loads(body).get("login", "?"))[:80]
            except Exception:
                pass
    else:
        role, who = "admin", "?"
        token = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        if token and path != "/admin/api/login":
            try:
                who = admin_auth.read_session(db, token, settings.jwt_secret)["email"]
            except Exception:
                who = "invalid login"
        elif path == "/admin/api/login":
            try:
                import json as _json
                who = str(_json.loads(body).get("email", "?"))[:120]
            except Exception:
                pass
    response = await call_next(request)
    try:
        details = audit.details_from_body(body) if body else (str(request.url.query)[:500] if method == "GET" else "")
        audit.log_action(db, AUDIT_SECRET, who, role, method, path, response.status_code, _client_ip(request), details)
    except Exception as exc:   # the log must never break the panel; but say so loudly
        print(f"[audit] could not log {method} {path}: {exc}")
    return response


_ip_limiter = security.IpLimiter(limits.DEFAULT_LIMITS["requests_per_ip_minute"])
_ip_limit_read = {"at": 0.0}


@app.middleware("http")
async def _security_middleware(request: Request, call_next):
    """S3: blocked IP addresses, a per-IP request ceiling, and browser security headers on every reply."""
    from fastapi.responses import JSONResponse
    ip = _client_ip(request)
    if time.time() - _ip_limit_read["at"] > 60:   # the ceiling from admin → Settings → Limits, read once a minute
        _ip_limit_read["at"] = time.time()
        try:
            _ip_limiter.per_minute = _limit_settings()["requests_per_ip_minute"]
        except Exception:
            pass
    if request.url.path != "/health":
        if security.is_blocked(db, "ip", ip):
            security.note(db, "sec:blocked:ip")
            response = JSONResponse({"detail": "Access from this network is blocked. Please contact support."}, 403)
        elif not _ip_limiter.allow(ip):
            security.note(db, "sec:ip_limit")
            response = JSONResponse({"detail": "Too many requests. Please wait a minute."}, 429, {"Retry-After": "60"})
        else:
            response = await call_next(request)
    else:
        response = await call_next(request)
    https = request.url.scheme == "https" or (settings.trust_proxy and request.headers.get("x-forwarded-proto") == "https")
    for k, v in security.headers(response.headers.get("content-type", ""), https).items():
        response.headers.setdefault(k, v)
    return response


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
        student_id, teacher_id, tv = accounts.read_token(authorization.removeprefix("Bearer ").strip(),
                                                         settings.jwt_secret, with_version=True)
    except accounts.AuthError as exc:
        raise HTTPException(401, str(exc))
    row = db.one("SELECT * FROM students WHERE id = ?", (student_id,))
    if row is None:
        raise HTTPException(401, "Unknown student")
    if tv != (row["token_version"] or 0):   # S3: "log out every other phone" / number changed
        raise HTTPException(401, "You were logged out. Please log in again.")
    if row["status"] == "disabled":   # A3: a disabled account can do nothing, even with an old login
        raise HTTPException(403, student_safety.account(db, student_id)["account_message"])
    return {"id": student_id, "teacher_id": teacher_id}


def teacher_admin(authorization: str = Header(""), x_teacher_id: str = Header(""), x_teacher_key: str = Header("")) -> str:
    """The institute panel: its own login (Bearer token from /teacher/login), or the older teacher key from .env."""
    token = authorization.removeprefix("Bearer ").strip()
    if token:
        try:
            tid = institute_auth.read(db, token, settings.jwt_secret)
        except institute_auth.InstituteAuthError as exc:
            raise HTTPException(401, str(exc))
    else:
        expected = os.environ.get(f"TEACHER_KEY_{x_teacher_id.upper()}", "") if x_teacher_id else ""
        if not expected or not x_teacher_key or not hmac.compare_digest(expected, x_teacher_key):
            raise HTTPException(403, "Not allowed")
        tid = x_teacher_id
    _panel_open(tid)
    return tid


def _panel_open(tid: str) -> None:
    if institute_status.state(db, tid) == "blocked":   # Dhurina blocked this institute: the panel is closed
        raise HTTPException(403, "This institute account is blocked by Dhurina. Please contact Dhurina support.")


# ---------- app config & languages ----------

@app.get("/teacher")
def teacher_info(request: Request, teacher: TeacherProfile = Depends(teacher_from_header)):
    row = db.one("SELECT * FROM teachers WHERE id = ?", (teacher.id,))
    plans = [dict(p) for p in db.all("SELECT id, name, amount_paise, duration_days FROM plans "
                                     "WHERE teacher_id = ? AND active = 1", (teacher.id,))]
    return {"id": row["id"], "name": row["name"], "subject": row["subject"], "avatar_url": row["avatar_url"],
            "brand_color": row["brand_color"], "plans": plans, "demo_questions": _limits(teacher.id)["demo"],
            "share_url": share.share_url(settings.public_base_url, row["id"], str(request.base_url)),
            "faculty": [f.public() for f in faculty_mod.list_faculty(db, teacher.id)],
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


def _institute_message(teacher_id: str | None, lang: str = "en") -> str | None:
    """Paused / blocked institute: the message its students see (None when active)."""
    st = institute_status.state(db, teacher_id)
    if st == "active":
        return None
    name = (db.one("SELECT name FROM teachers WHERE id = ?", (teacher_id,)) or {"name": "Sir"})["name"]
    return t("institute_paused" if st == "paused" else "institute_blocked", lang, teacher=name)


def _gate(student_id: int) -> None:
    """A3: a suspended / under-review / disabled student can't use Sir's AI (checked on the server every time,
    so logging out, reinstalling or a new class doesn't help). Notes, library and payments keep working."""
    row = db.one("SELECT teacher_id FROM students WHERE id = ?", (student_id,))
    moderation.request_ctx.set({"student_id": student_id, "teacher_id": row["teacher_id"] if row else None})
    stopped = _institute_message(row["teacher_id"] if row else None)
    if stopped:   # the institute is paused / blocked by Dhurina
        raise HTTPException(403, stopped)
    if switches.ai_paused_for(db, row["teacher_id"] if row else None) or not raw_llm.available():   # A4 kill switch
        raise HTTPException(503, t("ai_paused", "en"))
    blocked = student_safety.can_use_ai(db, student_id)
    if blocked:
        raise HTTPException(403, blocked["account_message"])
    # B1: class first; under 18 → a parent's OK first (428 = the app opens the right screen)
    wait = consent.gate_message(consent.state(db, student_id, consent.min_class(admin.get_settings(db))))
    if wait:
        raise HTTPException(428, wait)


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


def _new_students_allowed(teacher_id: str, phone: str) -> None:
    """A blocked institute takes no new students (its own students can still log in for notes and library)."""
    if institute_status.state(db, teacher_id) == "blocked" and \
            not db.one("SELECT 1 FROM students WHERE teacher_id = ? AND phone = ?", (teacher_id, phone)):
        raise HTTPException(403, _institute_message(teacher_id))


def _not_blocked_phone(phone: str) -> None:
    if security.is_blocked(db, "phone", phone):   # S3: admin → Security → blocked numbers
        security.note(db, "sec:blocked:phone")
        raise HTTPException(403, "This number can't use the app. Please contact support.")


@app.post("/auth/otp")
def send_otp(body: OtpRequest, request: Request, teacher: TeacherProfile = Depends(teacher_from_header),
             x_device_id: str = Header("")):
    try:
        phone = accounts.normalize_phone(body.phone)
        _not_blocked_phone(phone)
        _new_students_allowed(teacher.id, phone)
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
        _not_blocked_phone(phone)
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
    return {"token": _student_token(student_id, teacher.id), **_access(student_id)}


def _student_token(student_id: int, teacher_id: str) -> str:
    tv = db.one("SELECT token_version FROM students WHERE id = ?", (student_id,))["token_version"] or 0
    return accounts.issue_token(student_id, teacher_id, settings.jwt_secret, settings.jwt_days, tv)


def _logout_everywhere(student_id: int) -> None:
    db.execute("UPDATE students SET token_version = COALESCE(token_version, 0) + 1 WHERE id = ?", (student_id,))


@app.post("/me/logout-all")
def logout_all(student=Depends(current_student)):
    """S3: log out every other phone. This phone gets a fresh login and stays in."""
    _logout_everywhere(student["id"])
    return {"token": _student_token(student["id"], student["teacher_id"])}


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
            **consent.state(db, student_id, consent.min_class(admin.get_settings(db))),
            "service_message": _institute_message(tid) or (
                t("ai_paused", "en") if switches.ai_paused_for(db, tid) or not raw_llm.available() else None)}


def _after_answer(student_id: int, teacher_id: str, question: str, result) -> None:
    """A3: a blocked topic is a minor violation, a clearly harmful request a serious one (off-topic chat is neither)."""
    if result.scope not in ("blocked", "unsafe"):
        return
    row = db.one("SELECT blocked_topic FROM qa_history WHERE id = ?", (result.qa_id,))
    sev = "minor" if result.scope == "blocked" else "serious"
    student_safety.record_violation(db, student_id, teacher_id, sev, (row["blocked_topic"] if row else "") or result.scope,
                                    question, result.qa_id, student_safety.safety_settings(admin.get_settings(db)))


# ---------- B6: delete my data ----------

class DeleteConfirm(BaseModel):
    confirm: str


@app.post("/me/delete")
def delete_my_data(body: DeleteConfirm, student=Depends(current_student)):
    """The student deletes their account and learning data (type DELETE to confirm). Can't be undone."""
    if body.confirm.strip().upper() != "DELETE":
        raise HTTPException(400, "Type DELETE to confirm")
    try:
        done = data_protection.delete_student(db, student["id"], "student", "Student asked in the app",
                                              settings.notes_dir)
    except data_protection.DataError as exc:
        raise HTTPException(400, str(exc))
    return {"deleted": True, **done}


# ---------- B1: class + parent consent ----------

class Profile(BaseModel):
    class_level: str
    is_adult: bool


class ParentPhone(BaseModel):
    phone: str


class ParentCode(BaseModel):
    phone: str
    code: str


@app.put("/me/profile")
def set_profile(body: Profile, student=Depends(current_student)):
    try:
        consent.set_profile(db, student["id"], body.class_level, body.is_adult, consent.min_class(admin.get_settings(db)))
    except consent.ConsentError as exc:
        raise HTTPException(400, str(exc))
    return _access(student["id"])


def _needs_parent(student_id: int) -> None:
    if not consent.state(db, student_id)["consent_needed"]:
        raise HTTPException(400, "No parent permission is needed for this account.")


@app.post("/me/parent/otp")
def parent_otp(body: ParentPhone, request: Request, student=Depends(current_student),
               teacher: TeacherProfile = Depends(teacher_from_header), x_device_id: str = Header("")):
    """Send the parent a code by SMS (same limits as login codes)."""
    _needs_parent(student["id"])
    ns = consent.namespace(student["id"])
    try:
        phone = accounts.normalize_phone(body.phone)
        consent.check_parent_phone(db, student["id"], phone)
        lim = _limit_settings()
        limits.check_and_record(db, [limits.wrong_code_rule(ns, phone, lim)], record=False)
        limits.check_and_record(db, limits.otp_send_rules(ns, phone, x_device_id.strip(), _client_ip(request), lim))
        otp.send(ns, teacher.name, phone, "parent_sms")
    except (ValueError, consent.ConsentError) as exc:
        raise HTTPException(400, str(exc))
    except limits.Limited as exc:
        raise _too_many(exc)
    return {"sent": True}


@app.post("/me/parent/verify")
def parent_verify(body: ParentCode, request: Request, student=Depends(current_student)):
    _needs_parent(student["id"])
    ns = consent.namespace(student["id"])
    try:
        phone = accounts.normalize_phone(body.phone)
        wrong = limits.wrong_code_rule(ns, phone, _limit_settings())
        limits.check_and_record(db, [wrong], record=False)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except limits.Limited as exc:
        raise _too_many(exc)
    try:
        phone = otp.verify(ns, phone, body.code)
    except accounts.WrongCode as exc:
        limits.record(db, wrong.key)
        raise HTTPException(400, str(exc))
    except (accounts.AuthError, ValueError) as exc:
        raise HTTPException(400, str(exc))
    consent.record(db, student["id"], student["teacher_id"], phone, _client_ip(request))
    return _access(student["id"])


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


# ---------- the student's profile (app → My Library → Profile) ----------

@app.get("/me")
def my_profile(request: Request, student=Depends(current_student)):
    """Name, number, class, plan and the app's legal links, for the Profile screen."""
    row = db.one("SELECT name, phone, class_level, is_adult, created_at FROM students WHERE id = ?", (student["id"],))
    legal = admin.get_settings(db).get("legal", {})
    return {"name": row["name"] or "", "phone": row["phone"], "class_level": row["class_level"],
            "is_adult": None if row["is_adult"] is None else bool(row["is_adult"]),
            "joined": row["created_at"], "consent": consent.state(db, student["id"])["consent"],
            "plan": accounts.plan_summary(db, student["id"]),
            "privacy_url": legal.get("privacy_url", ""), "terms_url": legal.get("terms_url", ""),
            "parent_url": _parent_url(request) if not row["is_adult"] else "",
            **_access(student["id"])}


def _parent_url(request: Request) -> str:
    return (settings.public_base_url or str(request.base_url)).rstrip("/") + "/parent"


class NewPhone(BaseModel):
    phone: str


class NewPhoneCode(BaseModel):
    phone: str
    code: str


def _new_phone(student: dict, phone: str) -> str:
    phone = accounts.normalize_phone(phone)
    if phone == db.one("SELECT phone FROM students WHERE id = ?", (student["id"],))["phone"]:
        raise ValueError("This is already your number")
    if db.one("SELECT 1 FROM students WHERE teacher_id = ? AND phone = ?", (student["teacher_id"], phone)):
        raise ValueError("This number already has an account in this app")
    return phone


@app.post("/me/phone/otp")
def change_phone_otp(body: NewPhone, request: Request, student=Depends(current_student), x_device_id: str = Header("")):
    """Change my number, step 1: a code is sent to the NEW number (it must belong to the student)."""
    try:
        phone = _new_phone(student, body.phone)
        lim = _limit_settings()
        limits.check_and_record(db, [limits.wrong_code_rule(student["teacher_id"], phone, lim)], record=False)
        limits.check_and_record(db, limits.otp_send_rules(student["teacher_id"], phone, x_device_id.strip(),
                                                          _client_ip(request), lim))
        t = db.one("SELECT name FROM teachers WHERE id = ?", (student["teacher_id"],))
        otp.send(student["teacher_id"], t["name"] if t else "", phone)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except limits.Limited as exc:
        raise _too_many(exc)
    return {"sent": True}


@app.post("/me/phone/verify")
def change_phone_verify(body: NewPhoneCode, student=Depends(current_student)):
    """Change my number, step 2: the code from the new number. Classes, notes and plan stay with the account."""
    try:
        phone = _new_phone(student, body.phone)
        wrong = limits.wrong_code_rule(student["teacher_id"], phone, _limit_settings())
        limits.check_and_record(db, [wrong], record=False)
        try:
            phone = otp.verify(student["teacher_id"], phone, body.code)
        except accounts.WrongCode:
            limits.record(db, wrong.key)
            raise
        db.execute("UPDATE students SET phone = ? WHERE id = ?", (phone, student["id"]))
    except (ValueError, accounts.AuthError) as exc:
        raise HTTPException(400, str(exc))
    except limits.Limited as exc:
        raise _too_many(exc)
    _logout_everywhere(student["id"])   # S3: a new number ends the logins on every other phone
    return {"phone": phone, "token": _student_token(student["id"], student["teacher_id"])}


@app.get("/me/access")
def my_access(student=Depends(current_student)):
    """Plan / safety state, plus the teacher the student is with now (the app shows that face and name on open)."""
    f = _active_faculty(student["teacher_id"], student["id"])
    return {**_access(student["id"]), "active_faculty": f.public() if f else None, "ai_intro": _ai_intro(student, f)}


def _ai_intro(student, f) -> dict | None:
    """A7 / Phase C: Sir says once that he is an AI teacher, at the student's very first class (before the first
    question). After that the class is just a class (owner: no AI labels everywhere)."""
    if db.one("SELECT 1 FROM qa_history WHERE student_id = ? LIMIT 1", (student["id"],)):
        return None
    name = f.name if f else (db.one("SELECT name FROM teachers WHERE id = ?", (student["teacher_id"],)) or {"name": "Sir"})["name"]
    return {lang: t("ai_intro", lang, teacher=name) for lang in ("en", "hi", "pa")}


# ---------- live class ----------

class Ask(BaseModel):
    question: str
    voice: bool = False             # spoken: the phone turned speech into text (a word may be misheard)
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


def _seal(result, model: str):
    """A5: stamp the delivered answer with model + policy version + a tamper-evident seal; give it a reference code."""
    policy = audit.policy_version(db, moderation.POLICY_VERSION, admin.get_settings(db))
    result.verify_code = audit.stamp_answer(db, AUDIT_SECRET, result.qa_id, model, policy)
    return result


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
    return _seal(result, "none (fixed reply, no AI)")


def _refund(student_id: int) -> None:
    """The safety check failed after a demo question was counted: give it back."""
    if _access(student_id)["state"] == "demo":
        db.execute("UPDATE students SET demo_questions_used = MAX(demo_questions_used - 1, 0) WHERE id = ?", (student_id,))


def _answer_safely(student_id: int, teacher: TeacherProfile, question: str, session_id, spoken: bool = False):
    """A2 stage 2 happens inside the model wrapper: an unsafe AI answer is never stored or shown."""
    audit.used_model.set("")
    try:
        result = tutor.answer(student_id, teacher, question, session_id, spoken)
    except moderation.UnsafeOutput:
        lang = detect_language(question)
        result = tutor._redirect(student_id, question, lang, "stopped", None, style_mod.get_level(db, student_id),
                                 session_id, "safety_replaced")
        return _seal(result, f"none (fixed reply; answer of {audit.used_model.get() or 'AI'} stopped)")
    except moderation.Unavailable:
        _refund(student_id)
        raise _retry()
    except switches.AIPaused:   # switched off while this question was on its way
        _refund(student_id)
        raise HTTPException(503, t("ai_paused", "en"))
    _after_answer(student_id, teacher.id, question, result)
    return _seal(result, audit.used_model.get() or "none (fixed reply, no AI)")


@app.post("/class/ask")
def ask(body: Ask, student=Depends(current_student), teacher: TeacherProfile = Depends(teacher_from_header)):
    _limit_questions(student["id"])
    session_id = classroom.current_session(db, student["id"], teacher.id)
    if is_delete_command(body.question):   # B6: "delete my data" → the app asks to confirm; nothing is deleted yet
        return {"type": "delete_offer", **_access(student["id"])}
    if is_profile_command(body.question):   # "mera profile", "logout", "number badlo" → the app opens Profile
        return {"type": "profile", **_access(student["id"])}
    if is_save_command(body.question):   # "Sir, save this" = notes of the whole class so far
        return {"type": "note_saved", "note": _class_notes(student["id"], teacher, session_id, None)}
    if quiz.is_test_command(body.question):   # "Sir, test lo" → the app asks MCQ / written / oral
        return {"type": "test_offer", "mode": quiz.mode_in(body.question), **classroom.class_summary(
            db, student["id"], classroom.latest_session_with_content(db, student["id"], session_id))}
    if is_photo_command(body.question):   # "photo se poochna hai" → the app opens the camera
        return {"type": "photo", **_access(student["id"])}
    return _ask_question(student, teacher, body.question, session_id, body.voice)


def _ask_question(student, teacher: TeacherProfile, question: str, session_id, voice: bool = False,
                  extra: dict | None = None) -> dict:
    """Input check → (counts one question) → the right teacher → answer → answer check."""
    verdict = _check_input(question)
    if not verdict.safe:
        return _stopped(student, teacher, question, verdict, session_id, extra)
    _consume(student["id"], teacher)
    # multi-teacher: subject from the safety check (our own checker) or the free keyword match, else from the search
    # keyword call the teacher makes anyway (no extra AI call); sticky; "Maths wale sir ko bulao"
    r = faculty_mod.route(db, teacher.id, student["id"], question, verdict.subject, tutor.subject_of)
    result = _answer_safely(student["id"], teacher.as_faculty(r.faculty, r.previous.name if r.switched else None),
                            question, session_id, voice)
    _tag(result, r.faculty, session_id)
    result.switched, result.handover = r.switched, faculty_mod.handover_line(r, result.language)
    return {"type": "answer", **result.__dict__, **(extra or {}), **_access(student["id"])}


def _stopped(student, teacher: TeacherProfile, question: str, verdict, session_id, extra: dict | None = None) -> dict:
    result = _safe_reply(student["id"], teacher, question, verdict, session_id)
    _tag(result, _active_faculty(teacher.id, student["id"]), session_id)
    return {"type": "answer", **result.__dict__, **(extra or {}), **_access(student["id"])}


class PhotoAsk(BaseModel):
    photo_base64: str
    caption: str = ""               # optional: "Q3 samjhao" (typed or spoken)
    voice: bool = False


@app.post("/class/ask-photo")
def ask_photo(body: PhotoAsk, student=Depends(current_student), teacher: TeacherProfile = Depends(teacher_from_header)):
    """Phase C: a photo of a question. Photo safety check → read the question from it → the normal question path.
    The photo is never stored."""
    if switches.is_off(db, "photo"):   # A4: admin → Emergency → Photo questions
        raise HTTPException(503, t("photo_off", "en"))
    _limit_questions(student["id"])
    try:
        limits.check_and_record(db, limits.photo_rules(student["id"], _limit_settings()))
    except limits.Limited as exc:
        raise _too_many(exc)
    caption = " ".join((body.caption or "").split())[:300]
    try:
        jpeg = photo_mod.prepare(_b64(body.photo_base64))
    except photo_mod.PhotoError as exc:
        raise HTTPException(400, str(exc))
    session_id = classroom.current_session(db, student["id"], teacher.id)
    shown = f"📷 {caption}".strip()
    if caption:   # the note is the student's own words: the normal text check first (free, cached)
        v = _check_input(caption)
        if not v.safe:
            return _stopped(student, teacher, shown, v, session_id, {"photo_text": ""})
    url = photo_mod.data_url(jpeg)
    try:
        v = photo_mod.check(moderator, url, caption)
    except moderation.Unavailable:
        moderator.log("input", moderation.Verdict("check_failed", "none", "model"), f"[photo] {caption}", "retry")
        raise _retry()
    try:
        reading = photo_mod.read(raw_llm, url, caption) if v.safe else None
    except switches.AIPaused:
        raise HTTPException(503, t("ai_paused", "en"))
    except Exception:
        raise _retry()
    if reading is not None and not reading.safe:
        v = photo_mod.verdict_of(reading)
    if not v.safe:
        moderator.log("input", v, f"[photo] {caption}", {"care": "care_reply", "serious": "refused"}.get(v.severity, "redirected"))
        return _stopped(student, teacher, shown, v, session_id, {"photo_text": ""})
    if not reading.question:
        lang = detect_language(caption) if caption else "hi"
        return {"type": "photo_unclear", "message": t("photo_unclear", lang), **_access(student["id"])}
    question = reading.question + (f"\n({caption})" if caption else "")
    return _ask_question(student, teacher, question, session_id, body.voice, {"photo_text": reading.question})


def _active_faculty(institute: str, student_id: int):
    facs = faculty_mod.list_faculty(db, institute)
    st = db.one("SELECT active_faculty_id FROM students WHERE id = ?", (student_id,))
    return next((f for f in facs if st and f.id == st["active_faculty_id"]), facs[0] if facs else None)


def _tag(result, f, session_id) -> None:
    """Who answered: on the answer (app shows name / photo / voice), in the history, on the class."""
    if f is None:
        return
    result.faculty = f.public()
    db.execute("UPDATE qa_history SET faculty_id = ? WHERE id = ?", (f.id, result.qa_id))
    if session_id:
        db.execute("UPDATE class_sessions SET faculty_id = ? WHERE id = ? AND faculty_id IS NULL", (f.id, session_id))


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
    f = _session_faculty(teacher.id, student["id"], classroom.latest_session_with_content(db, student["id"], sid))
    try:
        out = quiz.create_test(db, llm, student["id"], teacher.id, f.name if f else teacher.name, body.mode, sid, body.topics)
    except quiz.TestError as exc:
        raise HTTPException(400, str(exc))
    if f:   # subject-wise tests and progress
        db.execute("UPDATE tests SET faculty_id = ? WHERE id = ?", (f.id, out["id"]))
        out["faculty"] = f.public()
    return out


def _session_faculty(institute: str, student_id: int, session_id: int | None):
    """The teacher who taught most of this class (a test is that teacher's test)."""
    row = db.one("SELECT faculty_id FROM qa_history WHERE session_id = ? AND student_id = ? AND faculty_id IS NOT NULL "
                 "GROUP BY faculty_id ORDER BY COUNT(*) DESC, MAX(id) DESC LIMIT 1", (session_id, student_id)) \
        if session_id else None
    return (faculty_mod.get(db, institute, row["faculty_id"]) if row else None) or _active_faculty(institute, student_id)


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
    frow = db.one("SELECT faculty_id FROM tests WHERE id = ? AND student_id = ?", (test_id, student["id"]))
    f = faculty_mod.get(db, teacher.id, frow["faculty_id"]) if frow and frow["faculty_id"] else None
    try:
        return quiz.answer_question(db, llm, student["id"], test_id, body.answer, f.name if f else teacher.name)
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
    if institute_status.state(db, student["teacher_id"]) != "active":   # no new plans while the institute is stopped
        raise HTTPException(403, "New plans can't be bought right now. " + (_institute_message(student["teacher_id"]) or ""))
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


@app.get("/teacher/safety")
def teacher_safety(status: str = "", q: str = "", offset: int = 0, limit: int = 25,
                   teacher_id: str = Depends(teacher_admin)):
    """Owner (17 Nov 2026): the teacher also sees flagged students — only their own app's students; can't block."""
    out = student_safety.list_students(db, status, q, teacher_id, offset, limit)
    out.pop("counts", None)   # the platform-wide counts are Dhurina's
    for x in out.get("items", []):   # numbers stay hidden from the institute, as on its Students page
        x["phone"] = teacher_data.mask_phone(x.get("phone") or "")
    return out


@app.get("/teacher/safety/{sid}")
def teacher_safety_student(sid: int, teacher_id: str = Depends(teacher_admin)):
    """A student's flagged messages (what they wrote) — own students only; every look is in the audit log."""
    row = db.one("SELECT teacher_id FROM students WHERE id = ?", (sid,))
    if row is None or row["teacher_id"] != teacher_id:
        raise HTTPException(404, "Student not found")
    d = student_safety.detail(db, sid)
    d["phone"] = teacher_data.mask_phone(d.get("phone") or "")
    return {k: d[k] for k in ("id", "name", "phone", "status", "status_until", "status_reason", "joined", "questions",
                              "violations", "history", "class_level")}


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


_FIRST_LOGIN_OK = {"/admin/api/me", "/admin/api/password", "/admin/api/logout"}
_SETUP_2STEP_OK = _FIRST_LOGIN_OK | {"/admin/api/2step/start", "/admin/api/2step/confirm"}


def require_admin(request: Request, authorization: str = Header("")):
    try:
        user = admin_auth.read_session(db, authorization.removeprefix("Bearer ").strip(), settings.jwt_secret)
    except admin_auth.LoginError as exc:
        raise HTTPException(401, str(exc))
    if user["must_change"] and request.url.path not in _FIRST_LOGIN_OK:   # B5: one-time password → own password first
        raise HTTPException(403, "Please set your own password first.")
    if not user["totp_on"] and security.require_2step(db) and request.url.path not in _SETUP_2STEP_OK:
        raise HTTPException(403, "Turn on 2-step login first.")   # S3: Super Admin made it required
    return user


def need(cap: str):
    """B5: this request needs a permission (see services/roles.py). Checked on the server, every time."""
    def dep(user=Depends(require_admin)):
        if not roles.has(user["role"], cap):
            raise HTTPException(403, f"Your role ({roles.label(user['role'])}) can't do this.")
        return user
    return dep


require_safety = need("evidence")   # B4: conversations and flagged messages only for the safety team


class AdminLogin(BaseModel):
    email: str
    password: str


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


@app.post("/admin/api/login")
def admin_login(body: AdminLogin, request: Request):
    try:
        return admin_auth.login(db, body.email, body.password, settings.jwt_secret, _client_ip(request),
                                request.headers.get("user-agent", ""))
    except admin_auth.LoginError as exc:
        raise HTTPException(401, str(exc))


class LoginCode(BaseModel):
    ticket: str
    code: str


@app.post("/admin/api/login/code")
def admin_login_code(body: LoginCode, request: Request):
    """S3: step 2 of the login — the code from the authenticator app (or a backup code)."""
    try:
        return admin_auth.login_code(db, body.ticket, body.code, settings.jwt_secret, _client_ip(request),
                                     request.headers.get("user-agent", ""))
    except admin_auth.LoginError as exc:
        raise HTTPException(401, str(exc))


@app.post("/admin/api/logout")
def admin_logout(authorization: str = Header(""), user=Depends(require_admin)):
    """Ends this login on the server too (the token stops working at once)."""
    sid = admin_auth.session_id(authorization.removeprefix("Bearer ").strip(), settings.jwt_secret)
    if sid:
        security.end_session(db, sid, user["id"])
    return {"ok": True}


@app.get("/admin/api/me")
def admin_me(user=Depends(require_admin)):
    logins = [dict(r) for r in db.all("SELECT at, ip, success FROM admin_logins WHERE email = ? ORDER BY id DESC LIMIT 5",
                                      (user["email"],))]
    required = security.require_2step(db)
    return {"email": user["email"], "name": user["name"], "role": user["role"], "role_label": roles.label(user["role"]),
            "caps": roles.caps(user["role"]), "must_change": bool(user["must_change"]), "recent_logins": logins,
            "two_step": bool(user["totp_on"]), "backup_left": security.backup_left(user),
            "require_2step": required, "needs_2step": required and not user["totp_on"]}


# ---------- S3: 2-step login, sessions, block list ----------

class TwoStepCode(BaseModel):
    code: str


class TwoStepOff(BaseModel):
    password: str


@app.post("/admin/api/2step/start")
def two_step_start(user=Depends(require_admin)):
    """A new secret for the authenticator app (QR code + the key to type). Not on until a code is confirmed."""
    return security.start_2step(db, user["id"], user["email"])


@app.post("/admin/api/2step/confirm")
def two_step_confirm(body: TwoStepCode, user=Depends(require_admin)):
    try:
        codes = security.confirm_2step(db, user["id"], body.code)
    except security.SecurityError as exc:
        raise HTTPException(400, str(exc))
    return {"on": True, "backup_codes": codes}   # shown once; only hashes are kept


@app.post("/admin/api/2step/off")
def two_step_off(body: TwoStepOff, user=Depends(require_admin)):
    if security.require_2step(db):
        raise HTTPException(400, "2-step login is required for the whole team (Security page)")
    if not admin_auth.check_password(body.password or "", user["password_hash"]):
        raise HTTPException(400, "Password is wrong")
    security.turn_off_2step(db, user["id"])
    return {"on": False}


@app.post("/admin/api/2step/backup-codes")
def two_step_new_codes(body: TwoStepCode, user=Depends(require_admin)):
    """New backup codes (the old ones stop working); needs a code from the app."""
    try:
        security.check_2step(db, user, body.code)
    except security.SecurityError as exc:
        raise HTTPException(400, str(exc))
    plain, hashed = security.new_backup_codes()
    db.execute("UPDATE admin_users SET backup_codes = ? WHERE id = ?", (hashed, user["id"]))
    return {"backup_codes": plain}


@app.post("/admin/api/team/{uid}/2step-off")
def team_two_step_off(uid: int, user=Depends(need("team"))):
    """Super Admin: a team member lost their phone and backup codes → 2-step off and every login of theirs ends."""
    if not db.one("SELECT 1 FROM admin_users WHERE id = ?", (uid,)):
        raise HTTPException(404, "Team member not found")
    security.turn_off_2step(db, uid)
    security.end_all_sessions(db, uid)
    return admin_team()


@app.get("/admin/api/security")
def security_page(request: Request, authorization: str = Header(""), user=Depends(need("security_view"))):
    me_sid = admin_auth.session_id(authorization.removeprefix("Bearer ").strip(), settings.jwt_secret)
    team = roles.has(user["role"], "team")
    mine = security.sessions(db, user["id"])
    everyone = security.sessions(db) if team else None
    for x in mine + (everyone or []):
        x["this"] = x["id"] == me_sid
    return {"require_2step": security.require_2step(db), "my_sessions": mine,
            "team_sessions": everyone,
            "team_2step": [{"email": m["email"], "name": m["name"], "role": roles.label(m["role"]), "on": bool(m["totp_on"])}
                           for m in db.all("SELECT email, name, role, totp_on FROM admin_users WHERE active = 1")] if team else None,
            "blocks": security.blocks(db), "recent": security.recent(db),
            "can_edit": roles.has(user["role"], "security_edit"), "can_team": team,
            "ip_block_hours": security.IP_BLOCK_HOURS, "your_ip": _client_ip(request)}


class RequireTwoStep(BaseModel):
    on: bool


@app.put("/admin/api/security/require-2step")
def security_require(body: RequireTwoStep, user=Depends(need("team"))):
    if body.on and not user["totp_on"]:
        raise HTTPException(400, "Turn on your own 2-step login first")
    security.set_require_2step(db, body.on)
    return {"require_2step": body.on}


@app.post("/admin/api/sessions/end-others")
def sessions_end_others(authorization: str = Header(""), user=Depends(require_admin)):
    sid = admin_auth.session_id(authorization.removeprefix("Bearer ").strip(), settings.jwt_secret)
    return {"ended": security.end_other_sessions(db, user["id"], sid)}


@app.post("/admin/api/sessions/{sid}/end")
def sessions_end(sid: str, user=Depends(require_admin)):
    """Your own session, or (Super Admin) anyone's."""
    ok = security.end_session(db, sid, None if roles.has(user["role"], "team") else user["id"])
    if not ok:
        raise HTTPException(404, "Session not found or already ended")
    return {"ended": True}


class BlockAdd(BaseModel):
    kind: str           # phone | ip
    value: str
    reason: str
    hours: float | None = None   # None: phone = until removed, IP = 24 hours


@app.post("/admin/api/security/block")
def security_block(body: BlockAdd, request: Request, user=Depends(need("security_edit"))):
    value = body.value
    try:
        if body.kind == "phone":
            value = accounts.normalize_phone(value)
        security.block(db, body.kind, value, body.reason, user["email"], body.hours, _client_ip(request))
    except (security.SecurityError, ValueError) as exc:
        raise HTTPException(400, str(exc))
    return {"blocks": security.blocks(db)}


@app.delete("/admin/api/security/block/{bid}")
def security_unblock(bid: int, user=Depends(need("security_edit"))):
    try:
        security.unblock(db, bid)
    except KeyError:
        raise HTTPException(404, "Not in the block list")
    return {"blocks": security.blocks(db)}


@app.post("/admin/api/students/{sid}/logout-all")
def admin_student_logout_all(sid: int, user=Depends(need("students"))):
    """S3: e.g. a student's phone was lost — every login of this student ends."""
    if not db.one("SELECT 1 FROM students WHERE id = ?", (sid,)):
        raise HTTPException(404, "Student not found")
    _logout_everywhere(sid)
    return {"ok": True}


# ---------- B8: safety policy versions ----------

class Rollback(BaseModel):
    note: str = ""


@app.get("/admin/api/policy", dependencies=[Depends(need("settings_view"))])
def admin_policy():
    return policy.versions(db, admin.get_settings(db))


@app.get("/admin/api/policy/compare", dependencies=[Depends(need("settings_view"))])
def admin_policy_compare(a: int, b: int):
    try:
        return policy.compare(db, a, b)
    except KeyError:
        raise HTTPException(404, "Version not found")


@app.post("/admin/api/policy/{vid}/rollback")
def admin_policy_rollback(vid: int, body: Rollback, user=Depends(need("settings_safety"))):
    """Bring back an earlier version: its rules become a new version (history is never rewritten)."""
    try:
        old = policy.get(db, vid)
    except KeyError:
        raise HTTPException(404, "Version not found")
    current = admin.get_settings(db)
    if policy.fingerprint(policy.snapshot(current)) == old["fingerprint"]:
        raise HTTPException(400, "These rules are already in use")
    try:
        saved = admin.save_settings(db, policy.rules_to_restore(old["rules"]))
    except admin.AdminError as exc:
        raise HTTPException(400, str(exc))
    why = (body.note or "").strip()
    policy.record_if_changed(db, saved, user["email"], f"Rolled back to v{vid}" + (f": {why}" if why else ""), vid)
    safety_lab.start_background(settings, db, "settings")   # the old rules are tested again with today's model
    return policy.versions(db, saved)


# ---------- B6: data protection (admin) ----------

class StudentDelete(BaseModel):
    reason: str


@app.post("/admin/api/students/{sid}/delete")
def admin_delete_student(sid: int, body: StudentDelete, user=Depends(need("delete_data"))):
    if not body.reason.strip():
        raise HTTPException(400, "Write why (e.g. the parent asked by phone)")
    try:
        return data_protection.delete_student(db, sid, user["email"], body.reason, settings.notes_dir)
    except KeyError:
        raise HTTPException(404, "Student not found")
    except data_protection.DataError as exc:
        raise HTTPException(400, str(exc))


@app.get("/admin/api/data", dependencies=[Depends(need("data_admin"))])
def admin_data():
    return {"encrypted": db.encrypted, "backup_dir": settings.backup_dir,
            "backups": data_protection.list_backups(settings.backup_dir),
            "last_backup": data_protection.last_job(db, "backup"), "last_cleanup": data_protection.last_job(db, "retention"),
            "last_restore_test": data_protection.last_job(db, "restore_test"),
            "settings": data_protection.data_settings(admin.get_settings(db)),
            "requests": data_protection.requests_log(db)}


@app.post("/admin/api/data/backup", dependencies=[Depends(need("data_admin"))])
def admin_data_backup():
    data_protection.backup_now(db, settings.backup_dir, data_protection.data_settings(admin.get_settings(db))["backup_keep"])
    return admin_data()


class RestoreTest(BaseModel):
    file: str = ""


@app.post("/admin/api/data/restore-test", dependencies=[Depends(need("data_admin"))])
def admin_data_restore_test(body: RestoreTest):
    """B9: open a copy of a backup the way a restore would and check it (nothing live is changed)."""
    try:
        result = data_protection.restore_test(db, settings.backup_dir, settings.db_encryption_key or None,
                                              AUDIT_SECRET, body.file)
    except data_protection.DataError as exc:
        raise HTTPException(400, str(exc))
    return {**admin_data(), "result": result}


@app.post("/admin/api/data/cleanup", dependencies=[Depends(need("data_admin"))])
def admin_data_cleanup():
    data_protection.run_retention(db, admin.get_settings(db))
    return admin_data()


def _data_jobs_loop():
    """B6: every hour, run what is due — the daily encrypted backup and the daily clean-up of old data."""
    while True:
        time.sleep(60)
        try:
            data_protection.daily(db, lambda: admin.get_settings(db), settings.backup_dir,
                                  key=settings.db_encryption_key or None, audit_secret=AUDIT_SECRET)
        except Exception as exc:   # never take the server down; say so in the logs
            print(f"[data] daily job failed: {exc}")
        time.sleep(3600 - 60)


if os.environ.get("DATA_JOBS", "1") == "1":
    threading.Thread(target=_data_jobs_loop, daemon=True, name="data-jobs").start()


# ---------- B7: alerts ----------

alerts.mailer["base_url"] = settings.public_base_url
if settings.smtp_host:
    alerts.mailer["send"] = alerts.smtp_sender(settings.smtp_host, settings.smtp_port, settings.smtp_user,
                                               settings.smtp_password, settings.smtp_from or settings.smtp_user)


def _alerts_loop():
    """Every 5 minutes: cases waiting too long, unusual spikes, the safety check failing again and again."""
    while True:
        time.sleep(300)
        try:
            alerts.periodic(db, admin.get_settings(db))
        except Exception as exc:
            print(f"[alerts] check failed: {exc}")


if os.environ.get("DATA_JOBS", "1") == "1":
    threading.Thread(target=_alerts_loop, daemon=True, name="alerts").start()


class AlertAck(BaseModel):
    id: int | None = None      # None = all open alerts
    note: str = ""


@app.get("/admin/api/alerts", dependencies=[Depends(need("dashboard"))])
def admin_alerts(all: bool = False):
    return {**alerts.listing(db, not all), "email_ready": bool(alerts.mailer["send"]),
            "settings": alerts.alert_settings(admin.get_settings(db))}


@app.post("/admin/api/alerts/ack")
def admin_alerts_ack(body: AlertAck, user=Depends(need("dashboard"))):
    try:
        alerts.acknowledge(db, body.id, user["email"], body.note)
    except KeyError:
        raise HTTPException(404, "Alert not found")
    return admin_alerts()
if not db.encrypted:
    print("[data] WARNING: the database is NOT encrypted. Set DB_ENCRYPTION_KEY before launch.")


# ---------- B5: team ----------

class TeamAdd(BaseModel):
    email: str
    name: str = ""
    role: str


class TeamUpdate(BaseModel):
    role: str | None = None
    active: bool | None = None
    name: str | None = None


@app.get("/admin/api/team", dependencies=[Depends(need("team"))])
def admin_team():
    return {"members": admin_auth.team(db), "roles": roles.catalog()}


@app.post("/admin/api/team")
def admin_team_add(body: TeamAdd, user=Depends(need("team"))):
    try:
        uid, pw = admin_auth.add_member(db, body.email, body.name, body.role, user["email"], roles.ROLES)
    except admin_auth.LoginError as exc:
        raise HTTPException(400, str(exc))
    return {"id": uid, "temp_password": pw, **admin_team()}   # shown once; never stored in plain text


@app.put("/admin/api/team/{uid}")
def admin_team_update(uid: int, body: TeamUpdate, user=Depends(need("team"))):
    try:
        admin_auth.update_member(db, uid, user["id"], roles.ROLES, body.role, body.active, body.name)
    except KeyError:
        raise HTTPException(404, "Team member not found")
    except admin_auth.LoginError as exc:
        raise HTTPException(400, str(exc))
    return admin_team()


@app.post("/admin/api/team/{uid}/reset")
def admin_team_reset(uid: int, user=Depends(need("team"))):
    if uid == user["id"]:
        raise HTTPException(400, "Change your own password in Settings")
    try:
        pw = admin_auth.reset_password(db, uid)
    except KeyError:
        raise HTTPException(404, "Team member not found")
    return {"temp_password": pw, **admin_team()}


@app.post("/admin/api/password")
def admin_password(body: PasswordChange, user=Depends(require_admin)):
    try:
        admin_auth.change_password(db, user["id"], body.current_password, body.new_password)
    except admin_auth.LoginError as exc:
        raise HTTPException(400, str(exc))
    return {"changed": True}


def _default_pct() -> float:
    return float(admin.get_settings(db)["defaults"]["platform_percent"])


# ---------- parent dashboard (brief §14) ----------

@app.get("/parent", response_class=HTMLResponse)
def parent_page():
    """Parents open this on any phone browser: their number + SMS code → their child's progress."""
    with open(os.path.join(STATIC_DIR, "parent.html"), encoding="utf-8") as f:
        return HTMLResponse(f.read())


class ParentPhone(BaseModel):
    phone: str


class ParentCode(BaseModel):
    phone: str
    code: str


class ParentDelete(BaseModel):
    confirm: str


def current_parent(authorization: str = Header("")) -> str:
    try:
        return parents.read(authorization.removeprefix("Bearer ").strip(), settings.jwt_secret)
    except parents.ParentError as exc:
        raise HTTPException(401, str(exc))


@app.post("/parent/api/otp")
def parent_otp(body: ParentPhone, request: Request, x_device_id: str = Header("")):
    try:
        phone = accounts.normalize_phone(body.phone)
        _not_blocked_phone(phone)
        lim = _limit_settings()
        limits.check_and_record(db, [limits.wrong_code_rule(parents.OTP_NAMESPACE, phone, lim)], record=False)
        limits.check_and_record(db, limits.otp_send_rules(parents.OTP_NAMESPACE, phone, x_device_id.strip(),
                                                          _client_ip(request), lim))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except limits.Limited as exc:
        raise _too_many(exc)
    if parents.is_parent(db, phone):   # no SMS (and no cost) for numbers that aren't a parent's; same reply either way
        otp.send(parents.OTP_NAMESPACE, "LiveTeach", phone, "parent_login_sms")
    return {"sent": True}


@app.post("/parent/api/verify")
def parent_verify(body: ParentCode):
    try:
        phone = accounts.normalize_phone(body.phone)
        wrong = limits.wrong_code_rule(parents.OTP_NAMESPACE, phone, _limit_settings())
        limits.check_and_record(db, [wrong], record=False)
        try:
            phone = otp.verify(parents.OTP_NAMESPACE, phone, body.code)
        except accounts.WrongCode:
            limits.record(db, wrong.key)
            raise
    except (ValueError, accounts.AuthError) as exc:
        raise HTTPException(400, str(exc))
    except limits.Limited as exc:
        raise _too_many(exc)
    if not parents.is_parent(db, phone):
        raise HTTPException(400, "This number is not a parent's number in LiveTeach")
    parents.log(db, phone, "login")
    return {"token": parents.token(phone, settings.jwt_secret)}


@app.get("/parent/api/children")
def parent_children(phone: str = Depends(current_parent)):
    return {"children": parents.children(db, phone)}


@app.post("/parent/api/children/{sid}/withdraw")
def parent_withdraw(sid: int, phone: str = Depends(current_parent)):
    try:
        parents.withdraw(db, phone, sid)
    except KeyError:
        raise HTTPException(404, "Not found")
    except parents.ParentError as exc:
        raise HTTPException(400, str(exc))
    parents.log(db, phone, f"withdrew consent for student {sid}")
    return {"children": parents.children(db, phone)}


@app.post("/parent/api/children/{sid}/delete")
def parent_delete(sid: int, body: ParentDelete, phone: str = Depends(current_parent)):
    try:
        parents.delete(db, phone, sid, body.confirm, settings.notes_dir)
    except KeyError:
        raise HTTPException(404, "Not found")
    except parents.ParentError as exc:
        raise HTTPException(400, str(exc))
    parents.log(db, phone, f"deleted the data of student {sid}")
    return {"children": parents.children(db, phone)}


@app.get("/teacher-panel", response_class=HTMLResponse)
def teacher_panel_page():
    """The teacher dashboard (log in with the teacher id + teacher key)."""
    with open(os.path.join(STATIC_DIR, "teacher.html"), encoding="utf-8") as f:
        return HTMLResponse(f.read())


@app.get("/admin", response_class=HTMLResponse)
def admin_page():
    with open(os.path.join(STATIC_DIR, "admin.html"), encoding="utf-8") as f:
        return f.read()


@app.get("/admin/api/overview", dependencies=[Depends(need("teachers_view"))])
def admin_overview():
    states = institute_status.all_states(db)
    teachers = [{**t, "account_status": states.get(t["id"], "active")} for t in admin.list_teachers(db, _default_pct())]
    return {"overview": admin.overview(db, _default_pct()), "teachers": teachers}


@app.get("/admin/api/teachers/{tid}")
def admin_teacher(tid: str, user=Depends(need("teachers_view"))):
    try:
        out = admin.teacher_detail(db, tid, _default_pct())
    except KeyError:
        raise HTTPException(404, "Teacher not found")
    return {**out, "account": institute_status.get(db, tid), "account_history": institute_status.history(db, tid),
            "can_account": roles.has(user["role"], "institute_status")}


class InstituteState(BaseModel):
    state: str                     # active | paused | blocked
    reason: str
    until_days: int | None = None  # pause only: ends by itself after this many days


@app.post("/admin/api/teachers/{tid}/account")
def admin_institute_state(tid: str, body: InstituteState, user=Depends(need("institute_status"))):
    """Super Admin: pause, block or make active a whole institute."""
    if not db.one("SELECT 1 FROM teachers WHERE id = ?", (tid,)):
        raise HTTPException(404, "Teacher not found")
    if body.until_days is not None and not 1 <= body.until_days <= 365:
        raise HTTPException(400, "A pause can be 1 to 365 days")
    until = time.time() + body.until_days * 86400 if body.until_days else None
    try:
        acc = institute_status.change(db, tid, body.state, body.reason, user["email"], until)
    except institute_status.StatusError as exc:
        raise HTTPException(400, str(exc))
    return {"account": acc, "account_history": institute_status.history(db, tid)}


@app.post("/admin/api/teachers", dependencies=[Depends(need("teachers_edit"))])
async def admin_create_teacher(request: Request):
    return _save_teacher(await request.json(), creating=True)


@app.put("/admin/api/teachers/{tid}", dependencies=[Depends(need("teachers_edit"))])
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


@app.post("/admin/api/teachers/{tid}/checklist", dependencies=[Depends(need("teachers_edit"))])
async def admin_checklist(tid: str, request: Request):
    body = await request.json()
    try:
        return admin.set_checklist(db, tid, body.get("item", ""), bool(body.get("done")))
    except (KeyError, admin.AdminError) as exc:
        raise HTTPException(400, str(exc))


@app.post("/admin/api/teachers/{tid}/build", dependencies=[Depends(need("teachers_edit"))])
def admin_build(tid: str, request: Request):
    t = db.one("SELECT * FROM teachers WHERE id = ?", (tid,))
    if t is None:
        raise HTTPException(404, "Teacher not found")
    if institute_status.state(db, tid) == "blocked":
        raise HTTPException(400, "This institute is blocked — make it active first")
    base = os.environ.get("PUBLIC_BASE_URL") or str(request.base_url).rstrip("/")
    avatar = f"{base}/teachers/{tid}/avatar" if t["avatar_url"] else ""
    try:
        builds.trigger_build(dict(t), avatar, base)
    except builds.BuildError as exc:
        raise HTTPException(400, str(exc))
    if t["status"] == "draft":
        admin.set_status(db, tid, "building")
    return {"started": True}


@app.get("/admin/api/teachers/{tid}/builds", dependencies=[Depends(need("teachers_view"))])
def admin_builds(tid: str):
    try:
        return builds.list_builds(tid)
    except builds.BuildError as exc:
        return {"error": str(exc), "builds": []}


@app.get("/admin/api/teachers/{tid}/report", dependencies=[Depends(need("money"))])
def admin_teacher_report(tid: str, month: str = "", format: str = "json", view: str = "admin", date_from: str = "", date_to: str = ""):
    """view=teacher gives exactly what the teacher sees (to send it to them)."""
    return _report_response(tid, month, format, "teacher" if view == "teacher" else "admin", date_from, date_to)


# ---- Reports: all teachers' sales for any period ----

def _rep_err(fn):
    try:
        return fn()
    except admin_reports.ReportError as exc:
        raise HTTPException(400, str(exc))


@app.get("/admin/api/reports", dependencies=[Depends(need("money"))])
def admin_reports_view(date_from: str, date_to: str, teacher: str = "", sort: str = "sales"):
    return _rep_err(lambda: admin_reports.full_report(db, date_from, date_to, _default_pct(), teacher or None, sort))


@app.get("/admin/api/reports/payments", dependencies=[Depends(need("money"))])
def admin_reports_payments(date_from: str, date_to: str, teacher: str = "", q: str = "", offset: int = 0, limit: int = 50):
    def run():
        start, end, _, _ = admin_reports.parse_period(date_from, date_to)
        return admin_reports.payments(db, start, end, _default_pct(), teacher or None, q, offset, limit)
    return _rep_err(run)


@app.get("/admin/api/reports/export", dependencies=[Depends(need("money"))])
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


@app.get("/admin/api/teachers/{tid}/students", dependencies=[Depends(need("teachers_view"))])
def admin_teacher_students(tid: str, offset: int = 0, limit: int = 25, q: str = "", status: str = ""):
    return teacher_data.students_page(db, tid, offset, limit, q, status)


@app.get("/admin/api/settings", dependencies=[Depends(need("settings_view"))])
def admin_get_settings():
    return admin.get_settings(db)


@app.put("/admin/api/settings")
async def admin_put_settings(request: Request, user=Depends(need("settings_view"))):
    data = await request.json()
    note = str((data or {}).pop("_note", "") or "")   # B8: why the safety rules were changed
    # B5: only sections whose values really change are checked (the page sends the whole form)
    current = admin.get_settings(db)
    changed = [sec for sec, vals in (data or {}).items() if isinstance(vals, dict) and sec in current
               and any(current[sec].get(k) != v for k, v in vals.items() if k in current[sec])]
    for sec in changed:
        cap = "settings_safety" if sec in roles.SAFETY_SECTIONS else "settings_all"
        if not roles.has(user["role"], cap):
            raise HTTPException(403, f"Your role ({roles.label(user['role'])}) can't change these settings.")
    policy.ensure_initial(db, current)   # B8: the rules before the first versioned change are v1
    try:
        saved = admin.save_settings(db, data)
    except admin.AdminError as exc:
        raise HTTPException(400, str(exc))
    policy.record_if_changed(db, saved, user["email"], note)
    safety_lab.start_background(settings, db, "settings")   # A8: safety rules changed → run the safety tests again
    return saved


# ---------- A3: student safety (block / unblock) ----------

class StudentAction(BaseModel):
    action: str                 # warn | suspend | review | disable | unblock
    reason: str
    remarks: str = ""
    hours: int | None = None    # for suspend


@app.get("/admin/api/students", dependencies=[Depends(need("students"))])
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


@app.get("/admin/api/emergency", dependencies=[Depends(need("emergency_view"))])
def admin_emergency():
    return {**switches.overview(db, _models_in_use()), "ai_available": raw_llm.available()}


@app.post("/admin/api/emergency")
def admin_emergency_set(body: SwitchChange, user=Depends(need("emergency"))):
    try:
        switches.set_switch(db, body.key, body.off, body.reason, user["email"])
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if body.key.startswith("model:"):
        safety_lab.start_background(settings, db, "emergency")   # A8: another model now answers → test it
    return admin_emergency()


# ---------- A8: safety test lab ----------

@app.get("/admin/api/safety-tests", dependencies=[Depends(need("tests_view"))])
def admin_safety_tests():
    cases = safety_lab.load_cases()["cases"]
    return {"launch": safety_lab.launch_status(settings, db), "runs": safety_lab.runs(db),
            "cases": len(cases), "languages": sorted({c["lang"] for c in cases})}


@app.post("/admin/api/safety-tests/run", dependencies=[Depends(need("tests_run"))])
def admin_safety_tests_run():
    if _provider == "rules":
        raise HTTPException(400, "The server has no AI key yet, so the real safety check can't be tested.")
    if not safety_lab.start_background(settings, db, "admin", force=True):
        raise HTTPException(409, "Safety tests are already running.")
    return admin_safety_tests()


@app.get("/admin/api/verify", dependencies=[Depends(require_safety)])
def admin_verify(q: str = ""):
    """A5: look up a reported conversation by its reference code (LT-XXXX-XXXX) or by its words."""
    return audit.find(db, AUDIT_SECRET, q)


@app.get("/admin/api/audit", dependencies=[Depends(need("audit"))])
def admin_audit_log(q: str = "", offset: int = 0, limit: int = 50):
    return {**audit.audit_log(db, AUDIT_SECRET, q, offset, limit), "chain": audit.check_audit_chain(db, AUDIT_SECRET)}


# ---------- B4: Human Review Center ----------

class IncidentAction(BaseModel):
    action: str                 # escalate | note | resolve | reopen | stop_class | pause_teacher | notify_parent
    note: str = ""
    resolution: str = ""


class IncidentFlag(BaseModel):
    note: str
    qa_id: int | None = None
    student_id: int | None = None


@app.get("/admin/api/incidents", dependencies=[Depends(require_safety)])
def admin_incidents(status: str = "", q: str = "", offset: int = 0):
    return incidents.list_incidents(db, status, q, offset)


@app.get("/admin/api/incidents/{iid}")
def admin_incident(iid: int, user=Depends(require_safety)):
    try:
        return incidents.detail(db, iid, user["email"])
    except KeyError:
        raise HTTPException(404, "Case not found")


@app.post("/admin/api/incidents/flag")
def admin_incident_flag(body: IncidentFlag, user=Depends(require_safety)):
    try:
        iid = incidents.flag(db, user["email"], body.note, body.qa_id, body.student_id)
    except KeyError:
        raise HTTPException(404, "Conversation not found")
    except incidents.IncidentError as exc:
        raise HTTPException(400, str(exc))
    return incidents.detail(db, iid)


@app.post("/admin/api/incidents/{iid}/act")
def admin_incident_act(iid: int, body: IncidentAction, user=Depends(require_safety)):
    who = user["email"]
    row = db.one("SELECT student_id, teacher_id, kind FROM incidents WHERE id = ?", (iid,))
    if row is None:
        raise HTTPException(404, "Case not found")
    try:
        if body.action == "stop_class":   # end the student's class now (to keep them out: suspend them)
            if not row["student_id"]:
                raise incidents.IncidentError("This case has no student")
            ended = classroom.end_session(db, row["student_id"])
            incidents.record(db, iid, who, "stopped the class" if ended else "no class was running", body.note)
        elif body.action == "pause_teacher":   # A4 switch for this teacher's AI
            if not row["teacher_id"]:
                raise incidents.IncidentError("This case has no teacher")
            reason = (body.note or "").strip() or f"Review case #{iid}"
            try:
                switches.set_switch(db, f"teacher:{row['teacher_id']}", True, reason, who)
            except ValueError as exc:
                raise incidents.IncidentError(str(exc))
            incidents.record(db, iid, who, "paused this teacher's AI (turn back on in Emergency)", reason)
        elif body.action == "notify_parent":   # B9: a person decided the parent should know (care cases)
            if not row["student_id"]:
                raise incidents.IncidentError("This case has no student")
            kind = row["kind"] if row["kind"] == "care" else "block"
            res = parent_notify.notify(db, row["student_id"], "care" if kind == "care" else "block", who, force=True)
            msg = {"sent": "SMS sent to the parent", "adult": "not sent — the student is 18 or older",
                   "no_phone": "not sent — no parent number (no parent consent)",
                   "repeat": "not sent — the parent already got this SMS today",
                   "failed": "SMS could not be sent (SMS service)"}.get(res["status"], res["status"])
            incidents.record(db, iid, who, "inform parent: " + msg, body.note)
        else:
            incidents.act(db, iid, who, body.action, body.note, body.resolution)
    except incidents.IncidentError as exc:
        raise HTTPException(400, str(exc))
    return incidents.detail(db, iid)


# ---------- B9: AI Teacher Safety Center (one place for the 12 safety modules of the brief) ----------

@app.get("/admin/api/safety-center", dependencies=[Depends(need("dashboard"))])
def admin_safety_center():
    """A short live status of every safety module (no personal data), with where to open it."""
    s = admin.get_settings(db)
    f = content_filters.settings_of(s)
    off = switches.off_keys(db)
    since = time.time() - 86400
    lab = safety_lab.launch_status(settings, db)
    last_run = db.one("SELECT at, passed, total, failed FROM safety_test_runs ORDER BY at DESC LIMIT 1")
    ss = student_safety.safety_settings(s)
    p = parent_notify.parent_settings(s)
    restore = data_protection.last_job(db, "restore_test")
    return {
        "filters": {"on": sum(1 for v in f.values() if v["on"]), "total": len(f), "locked": len(content_filters.LOCKED),
                    "custom_messages": sum(1 for v in (s.get("messages") or {}).values() if any(v.values()))},
        "age_groups": {g: v["strictness"] for g, v in age_policy.settings_of(s).items()},
        "education_only": {"blocked_topics": len(s["ai"]["blocked_topics"])},
        "moderation": {"provider": moderator.provider,
                       "stopped_24h": db.one("SELECT COUNT(*) AS n FROM safety_events WHERE at > ? AND action != 'retry'", (since,))["n"],
                       "failed_24h": db.one("SELECT COUNT(*) AS n FROM safety_events WHERE at > ? AND action = 'retry'", (since,))["n"]},
        "students": {"auto_block": ss["auto_block"], **{st: db.one("SELECT COUNT(*) AS n FROM students WHERE status = ?", (st,))["n"]
                                                        for st in ("warning", "suspended", "review")}},
        "review": {"open": db.one("SELECT COUNT(*) AS n FROM incidents WHERE status != 'resolved'")["n"],
                   "high": db.one("SELECT COUNT(*) AS n FROM incidents WHERE status != 'resolved' AND severity = 'high'")["n"]},
        "identity": {"sealed_answers": db.one("SELECT COUNT(*) AS n FROM qa_history WHERE record_hash IS NOT NULL")["n"]},
        "privacy": {"encrypted": db.encrypted, "parent_block_sms": p["notify_block"], "parent_care_sms": p["notify_care"],
                    "consents": db.one("SELECT COUNT(*) AS n FROM parent_consents WHERE revoked_at IS NULL")["n"],
                    "restore_test": restore},
        "tests": {"state": lab["state"], "why": lab["why"], "last": dict(last_run) if last_run else None},
        "emergency": {"off": [{"key": k, "reason": v.get("reason")} for k, v in off.items()]},
        "alerts_open": db.one("SELECT COUNT(*) AS n FROM alerts WHERE ack_at IS NULL")["n"],
    }


@app.get("/admin/api/filters", dependencies=[Depends(need("settings_view"))])
def admin_filters():
    """B9: the Content filters page — filters, the messages students see (built-in text for blank fields), parent SMS."""
    s = admin.get_settings(db)
    return {"catalog": content_filters.catalog(), "filters": content_filters.settings_of(s),
            "messages": {k: {"name": policy.MESSAGE_NAMES[k], "must": list(i18n.EDITABLE[k]),
                             "default": {lang: i18n.MESSAGES[k].get(lang, "") for lang in i18n.EDIT_LANGS},
                             "custom": (s.get("messages") or {}).get(k) or {}} for k in i18n.EDITABLE},
            "parents": parent_notify.parent_settings(s), "sms_ready": settings.sms_provider != "console"}


@app.get("/admin/api/safety-dashboard", dependencies=[Depends(need("dashboard"))])
def admin_safety_dashboard(days: int = 30, teacher: str = ""):
    """B3: safety numbers for a date range (and optionally one teacher)."""
    return safety_dashboard.build(db, days, teacher)


@app.get("/admin/api/safety-events", dependencies=[Depends(require_safety)])
def admin_safety_events(limit: int = 30):
    """A2: what the safety check stopped (student messages and AI answers) and when it could not run."""
    return {**moderation.recent_events(db, max(1, min(limit, 100))), "provider": moderator.provider,
            "policy_version": moderation.POLICY_VERSION}


@app.get("/admin/api/students/{sid}")
def admin_safety_student(sid: int, user=Depends(need("students"))):
    try:
        d = student_safety.detail(db, sid)
    except KeyError:
        raise HTTPException(404, "Student not found")
    if not roles.has(user["role"], "evidence"):   # B5: support sees the account, not what the student wrote
        for v in d["violations"]:
            v["question"] = "(hidden — safety team only)"
    d["can"] = {"block": roles.has(user["role"], "block"), "consent": roles.has(user["role"], "consent"),
                "evidence": roles.has(user["role"], "evidence"), "delete": roles.has(user["role"], "delete_data")}
    d["parent_notices"] = parent_notify.history(db, sid)   # B9: SMS sent to the parent (or why not)
    d["plan"] = accounts.plan_summary(db, sid)
    d["can"]["free_plan"] = roles.has(user["role"], "free_plan")
    return d


class FreePlan(BaseModel):
    days: int
    reason: str


@app.post("/admin/api/students/{sid}/free-plan")
def admin_free_plan(sid: int, body: FreePlan, user=Depends(need("free_plan"))):
    """Super Admin: a plan without payment for a tester (or a scholarship). Written to the audit log with the reason."""
    if not db.one("SELECT 1 FROM students WHERE id = ?", (sid,)):
        raise HTTPException(404, "Student not found")
    if len(body.reason.strip()) < 3:
        raise HTTPException(400, "Write why (e.g. testing)")
    try:
        end = accounts.grant_free_plan(db, sid, body.days)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True, "until": end, **accounts.plan_summary(db, sid)}


@app.post("/admin/api/students/{sid}/free-plan/end")
def admin_free_plan_end(sid: int, user=Depends(need("free_plan"))):
    accounts.end_free_plan(db, sid)
    return {"ok": True, **accounts.plan_summary(db, sid)}


class ConsentRevoke(BaseModel):
    reason: str


@app.post("/admin/api/students/{sid}/consent/revoke")
def admin_consent_revoke(sid: int, body: ConsentRevoke, user=Depends(need("consent"))):
    """B1: a parent withdraws consent (e.g. by calling support) → Sir's AI stops until a parent allows again."""
    try:
        consent.revoke(db, sid, user["email"], body.reason)
    except KeyError:
        raise HTTPException(404, "Student not found")
    except consent.ConsentError as exc:
        raise HTTPException(400, str(exc))
    return student_safety.detail(db, sid)


@app.post("/admin/api/students/{sid}/status")
def admin_safety_action(sid: int, body: StudentAction, user=Depends(need("block"))):
    try:
        return student_safety.admin_action(db, sid, body.action, body.reason, body.remarks, user["email"], body.hours)
    except KeyError:
        raise HTTPException(404, "Student not found")
    except student_safety.SafetyError as exc:
        raise HTTPException(400, str(exc))


# ---------- multi-teacher: AI teachers (faculty) and the content library ----------

def _b64(data: str) -> bytes:
    try:
        return base64.b64decode((data or "").split(",", 1)[-1], validate=False)
    except Exception:
        raise HTTPException(400, "Could not read the file")


def _lib(fn):
    try:
        return fn()
    except KeyError:
        raise HTTPException(404, "Not found")
    except (library.LibraryError, faculty_mod.FacultyError) as exc:
        raise HTTPException(400, str(exc))


def _faculty_list(tid: str) -> dict:
    if not db.one("SELECT 1 FROM teachers WHERE id = ?", (tid,)):
        raise HTTPException(404, "Teacher not found")
    files = library.faculty_stats(db, tid)
    att = library.attachments(db, tid)
    items = [{**f.__dict__, "files": files.get(f.id, 0),
              "subject_labels": [faculty_mod.subject_label(x) for x in f.subjects],
              "common": [a for a in att if a["faculty_id"] == f.id]}
             for f in faculty_mod.list_faculty(db, tid, active_only=False)]
    return {"items": items, "subjects": _subjects()}


def _subjects() -> list[dict]:
    return [{"key": k, "label": v[0]} for k, v in faculty_mod.SUBJECTS.items()] + \
           [{"key": faculty_mod.GENERAL, "label": "General (every teacher)"}]


def _save_faculty(tid: str, data: dict, fid: int | None):
    f = _lib(lambda: faculty_mod.save(db, tid, data, fid))
    photo = data.get("photo_base64")
    if photo:
        raw = _b64(photo)
        if len(raw) > 5_000_000:
            raise HTTPException(400, "Photo must be under 5 MB")
        os.makedirs(AVATAR_DIR, exist_ok=True)
        with open(os.path.join(AVATAR_DIR, f"faculty-{f.id}.jpg"), "wb") as fh:
            fh.write(raw)
        faculty_mod.set_avatar(db, tid, f.id, f"/faculty/{f.id}/avatar?v={int(time.time())}")
        f = faculty_mod.get(db, tid, f.id)
    return {**f.__dict__}


def _upload(owner: str, data: dict, by: str):
    return _lib(lambda: library.upload(
        db, owner, str(data.get("filename", "")), _b64(data.get("data_base64", "")),
        subject=data.get("subject") or None, faculty_id=data.get("faculty_id") or None,
        allow_common=bool(data.get("allow_common")), by=by, side_llm=side_llm, moderator=moderator))


def _kw():
    return {"side_llm": side_llm, "moderator": moderator}


@app.get("/admin/api/subjects", dependencies=[Depends(need("teachers_view"))])
def admin_subjects():
    return {"items": _subjects()}


@app.get("/admin/api/teachers/{tid}/faculty", dependencies=[Depends(need("teachers_view"))])
def admin_faculty(tid: str):
    return _faculty_list(tid)


@app.post("/admin/api/teachers/{tid}/faculty", dependencies=[Depends(need("teachers_edit"))])
async def admin_faculty_add(tid: str, request: Request):
    return _save_faculty(tid, await request.json(), None)


@app.put("/admin/api/teachers/{tid}/faculty/{fid}", dependencies=[Depends(need("teachers_edit"))])
async def admin_faculty_edit(tid: str, fid: int, request: Request):
    return _save_faculty(tid, await request.json(), fid)


@app.delete("/admin/api/teachers/{tid}/faculty/{fid}", dependencies=[Depends(need("teachers_edit"))])
def admin_faculty_delete(tid: str, fid: int):
    _lib(lambda: faculty_mod.delete(db, tid, fid))
    return {"ok": True}


@app.get("/faculty/{fid}/avatar")
def faculty_avatar(fid: int):
    path = os.path.join(AVATAR_DIR, f"faculty-{int(fid)}.jpg")
    if not os.path.exists(path):
        raise HTTPException(404, "No photo")
    return FileResponse(path, media_type="image/jpeg")


@app.get("/admin/api/teachers/{tid}/library", dependencies=[Depends(need("teachers_view"))])
def admin_library(tid: str, status: str = "", subject: str = "", q: str = ""):
    return library.list_links(db, tid, status, subject, q)


@app.post("/admin/api/teachers/{tid}/library")
async def admin_library_upload(tid: str, request: Request, user=Depends(need("teachers_edit"))):
    return _upload(tid, await request.json(), user["email"])


@app.get("/admin/api/teachers/{tid}/library/{lid}", dependencies=[Depends(need("teachers_view"))])
def admin_library_preview(tid: str, lid: int, offset: int = 0):
    return _lib(lambda: library.preview(db, tid, lid, offset))


@app.post("/admin/api/teachers/{tid}/library/{lid}/accept", dependencies=[Depends(need("teachers_edit"))])
def admin_library_accept(tid: str, lid: int):
    return _lib(lambda: library.accept(db, tid, lid))


@app.put("/admin/api/teachers/{tid}/library/{lid}", dependencies=[Depends(need("teachers_edit"))])
async def admin_library_assign(tid: str, lid: int, request: Request):
    d = await request.json()
    return _lib(lambda: library.assign(db, tid, lid, d.get("subject") or None, d.get("faculty_id") or None))


@app.put("/admin/api/teachers/{tid}/library/{lid}/text", dependencies=[Depends(need("teachers_edit"))])
async def admin_library_edit(tid: str, lid: int, request: Request):
    d = await request.json()
    return _lib(lambda: library.edit_text(db, tid, lid, str(d.get("text", "")), **_kw()))


@app.post("/admin/api/teachers/{tid}/library/{lid}/replace", dependencies=[Depends(need("teachers_edit"))])
async def admin_library_replace(tid: str, lid: int, request: Request):
    d = await request.json()
    return _lib(lambda: library.replace(db, tid, lid, str(d.get("filename", "")), _b64(d.get("data_base64", "")), **_kw()))


@app.post("/admin/api/teachers/{tid}/library/{lid}/recheck", dependencies=[Depends(need("teachers_edit"))])
def admin_library_recheck(tid: str, lid: int):
    _lib(lambda: library.preview(db, tid, lid))   # belongs to this institute
    return library.recheck(db, lid, moderator)


@app.delete("/admin/api/teachers/{tid}/library/{lid}", dependencies=[Depends(need("teachers_edit"))])
def admin_library_delete(tid: str, lid: int):
    _lib(lambda: library.remove(db, tid, lid))
    return {"ok": True}


@app.post("/admin/api/teachers/{tid}/library/{lid}/promote")
def admin_library_promote(tid: str, lid: int, user=Depends(need("library_common"))):
    return _lib(lambda: library.promote(db, tid, lid, user["email"]))


# Common Library (Super Admin): Dhurina's shared content by subject, linked (not copied) to institute teachers

@app.get("/admin/api/common", dependencies=[Depends(need("library_common"))])
def admin_common(status: str = "", subject: str = "", q: str = ""):
    return {**library.list_links(db, library.COMMON, status, subject, q), "subjects": library.common_subjects(db)}


@app.post("/admin/api/common")
async def admin_common_upload(request: Request, user=Depends(need("library_common"))):
    return _upload(library.COMMON, await request.json(), user["email"])


@app.get("/admin/api/common/{lid}", dependencies=[Depends(need("library_common"))])
def admin_common_preview(lid: int, offset: int = 0):
    return _lib(lambda: library.preview(db, library.COMMON, lid, offset))


@app.put("/admin/api/common/{lid}/text", dependencies=[Depends(need("library_common"))])
async def admin_common_edit(lid: int, request: Request):
    d = await request.json()
    return _lib(lambda: library.edit_text(db, library.COMMON, lid, str(d.get("text", "")), **_kw()))


@app.post("/admin/api/common/{lid}/accept", dependencies=[Depends(need("library_common"))])
def admin_common_accept(lid: int):
    return _lib(lambda: library.accept(db, library.COMMON, lid))


@app.put("/admin/api/common/{lid}", dependencies=[Depends(need("library_common"))])
async def admin_common_assign(lid: int, request: Request):
    d = await request.json()
    return _lib(lambda: library.assign(db, library.COMMON, lid, d.get("subject") or None, None))


@app.delete("/admin/api/common/{lid}", dependencies=[Depends(need("library_common"))])
def admin_common_delete(lid: int):
    _lib(lambda: library.remove(db, library.COMMON, lid))
    return {"ok": True}


@app.post("/admin/api/teachers/{tid}/faculty/{fid}/common")
async def admin_common_attach(tid: str, fid: int, request: Request, user=Depends(need("library_common"))):
    d = await request.json()
    _lib(lambda: library.attach(db, tid, fid, str(d.get("subject", "")), user["email"]))
    return {"ok": True}


@app.delete("/admin/api/teachers/{tid}/faculty/{fid}/common/{subject}", dependencies=[Depends(need("library_common"))])
def admin_common_detach(tid: str, fid: int, subject: str):
    _lib(lambda: library.detach(db, tid, fid, subject))
    return {"ok": True}


# the institute's own panel (teacher.html, teacher id + key): teachers and the content library

@app.get("/teacher/faculty")
def institute_faculty(teacher_id: str = Depends(teacher_admin)):
    return _faculty_list(teacher_id)


@app.get("/teacher/library")
def institute_library(status: str = "", subject: str = "", q: str = "", teacher_id: str = Depends(teacher_admin)):
    return library.list_links(db, teacher_id, status, subject, q)


@app.post("/teacher/library")
async def institute_library_upload(request: Request, teacher_id: str = Depends(teacher_admin)):
    return _upload(teacher_id, await request.json(), f"teacher:{teacher_id}")


@app.put("/teacher/library/{lid}")
async def institute_library_assign(lid: int, request: Request, teacher_id: str = Depends(teacher_admin)):
    d = await request.json()
    return _lib(lambda: library.assign(db, teacher_id, lid, d.get("subject") or None, d.get("faculty_id") or None))


@app.delete("/teacher/library/{lid}")
def institute_library_delete(lid: int, teacher_id: str = Depends(teacher_admin)):
    _lib(lambda: library.remove(db, teacher_id, lid))
    return {"ok": True}


# ---------- Step 3: the institute's own panel (login, home, teachers, content) ----------

class InstituteLogin(BaseModel):
    login: str
    password: str


@app.post("/teacher/login")
def institute_login(body: InstituteLogin, request: Request):
    try:
        limits.check_and_record(db, [limits.Rule(f"inst-login:{_client_ip(request)}", 20, 900, "limit_otp")])   # 20 / 15 min / IP
        out = institute_auth.login(db, body.login, body.password, settings.jwt_secret)
        _panel_open(institute_auth.read(db, out["token"], settings.jwt_secret))
        return out
    except institute_auth.InstituteAuthError as exc:
        raise HTTPException(400, str(exc))
    except limits.Limited as exc:
        raise _too_many(exc)


class InstitutePassword(BaseModel):
    current_password: str
    new_password: str


@app.post("/teacher/password")
def institute_password(body: InstitutePassword, teacher_id: str = Depends(teacher_admin)):
    try:
        token = institute_auth.change_password(db, teacher_id, body.current_password, body.new_password,
                                               settings.jwt_secret)
    except institute_auth.InstituteAuthError as exc:
        raise HTTPException(400, str(exc))
    return {"changed": True, "token": token}   # older logins (other devices) end; this one goes on


@app.get("/teacher/home")
def institute_home(teacher_id: str = Depends(teacher_admin)):
    """Everything the panel's Home and menu need, in one call (only this institute's numbers, never Dhurina's share)."""
    t = db.one("SELECT * FROM teachers WHERE id = ?", (teacher_id,))
    if t is None:
        raise HTTPException(404, "Not found")
    now = time.time()
    pct = t["platform_commission_percent"] if t["platform_commission_percent"] is not None else _default_pct()
    split = 100 - pct
    lt = time.localtime(now)
    months = []   # the institute's own earnings, last 6 months (never Dhurina's share)
    for k in range(5, -1, -1):
        y, m = lt.tm_year, lt.tm_mon - k
        while m <= 0:
            y, m = y - 1, m + 12
        a = time.mktime((y, m, 1, 0, 0, 0, 0, 0, -1))
        b = time.mktime((y + (m == 12), m % 12 + 1, 1, 0, 0, 0, 0, 0, -1))
        rows = db.all("SELECT p.amount_paise, COALESCE(p.platform_percent, ?) AS pct FROM payments p "
                      "JOIN plans pl ON pl.id = p.plan_id WHERE pl.teacher_id = ? AND p.status = 'paid' "
                      "AND p.created_at >= datetime(?, 'unixepoch') AND p.created_at < datetime(?, 'unixepoch')",
                      (pct, teacher_id, a, b))
        months.append({"label": time.strftime("%b", time.localtime(a)),
                       "paise": sum(r["amount_paise"] - round(r["amount_paise"] * r["pct"] / 100) for r in rows)})
    week = db.one("SELECT COUNT(*) AS n, SUM(CASE WHEN q.origin = 'teacher_notes' THEN 1 ELSE 0 END) AS own "
                  "FROM qa_history q JOIN students s ON s.id = q.student_id WHERE s.teacher_id = ? "
                  "AND q.created_at >= datetime(?, 'unixepoch')", (teacher_id, now - 7 * 86400))
    rv = teacher_data.review_page(db, teacher_id, 0, 3, status="pending")
    lib = library.list_links(db, teacher_id)
    students = teacher_data.students_page(db, teacher_id, 0, 1)["counts"]
    return {"me": {"name": t["name"], "app": t["name"], "login": t["panel_login"] or "", "avatar": t["avatar_url"] or "",
                   "subjects": t["subject"] or "", "split": round(split, 2), "must_change": bool(t["panel_must_change"])},
            "faculty": len(faculty_mod.list_faculty(db, teacher_id)),
            "review": {"waiting": rv["total_answers"], "questions": rv["total"], "top": rv["items"]},
            "files": {"total": lib["total"], **lib["counts"]},
            "students": students, "months": months,
            "week_questions": week["n"] or 0, "from_notes": round((week["own"] or 0) / week["n"], 2) if week["n"] else 0,
            "account": _panel_account(teacher_id)}


def _panel_account(teacher_id: str) -> dict:
    """What the institute sees about its own status (a banner when Dhurina paused it)."""
    a = institute_status.get(db, teacher_id)
    return {"state": a["state"], "reason": a["reason"], "until": a["until"]}


@app.post("/teacher/faculty")
async def institute_faculty_add(request: Request, teacher_id: str = Depends(teacher_admin)):
    return _save_faculty(teacher_id, await request.json(), None)


@app.put("/teacher/faculty/{fid}")
async def institute_faculty_edit(fid: int, request: Request, teacher_id: str = Depends(teacher_admin)):
    return _save_faculty(teacher_id, await request.json(), fid)


@app.delete("/teacher/faculty/{fid}")
def institute_faculty_delete(fid: int, teacher_id: str = Depends(teacher_admin)):
    _lib(lambda: faculty_mod.delete(db, teacher_id, fid))
    return {"ok": True}


@app.get("/teacher/library/{lid}")
def institute_library_preview(lid: int, offset: int = 0, teacher_id: str = Depends(teacher_admin)):
    return _lib(lambda: library.preview(db, teacher_id, lid, offset))


@app.put("/teacher/library/{lid}/text")
async def institute_library_edit(lid: int, request: Request, teacher_id: str = Depends(teacher_admin)):
    d = await request.json()
    return _lib(lambda: library.edit_text(db, teacher_id, lid, str(d.get("text", "")), **_kw()))


@app.post("/teacher/library/{lid}/replace")
async def institute_library_replace(lid: int, request: Request, teacher_id: str = Depends(teacher_admin)):
    d = await request.json()
    return _lib(lambda: library.replace(db, teacher_id, lid, str(d.get("filename", "")), _b64(d.get("data_base64", "")), **_kw()))


@app.post("/teacher/library/{lid}/accept")
def institute_library_accept(lid: int, teacher_id: str = Depends(teacher_admin)):
    return _lib(lambda: library.accept(db, teacher_id, lid))


@app.post("/teacher/library/{lid}/recheck")
def institute_library_recheck(lid: int, teacher_id: str = Depends(teacher_admin)):
    _lib(lambda: library.preview(db, teacher_id, lid))
    return library.recheck(db, lid, moderator)


class PanelLogin(BaseModel):
    login: str


@app.put("/admin/api/teachers/{tid}/panel-login", dependencies=[Depends(need("teachers_edit"))])
def admin_panel_login(tid: str, body: PanelLogin):
    """Set or reset the institute's own panel login. The one-time password is shown here once."""
    if not db.one("SELECT 1 FROM teachers WHERE id = ?", (tid,)):
        raise HTTPException(404, "Teacher not found")
    try:
        temp = institute_auth.set_login(db, tid, body.login)
    except institute_auth.InstituteAuthError as exc:
        raise HTTPException(400, str(exc))
    return {"login": institute_auth.clean_login(body.login), "password": temp}


# test lab for the brief's 7 checks (5 prototype teachers, a throw-away database; no AI cost)

@app.get("/admin/api/teacher-lab", dependencies=[Depends(need("tests_view"))])
def admin_teacher_lab():
    from . import teacher_lab
    return teacher_lab.last(db)


@app.post("/admin/api/teacher-lab/run")
def admin_teacher_lab_run(mode: str = "free", user=Depends(need("tests_run"))):
    from . import teacher_lab
    try:
        return teacher_lab.run_and_save(db, user["email"], "ai" if mode == "ai" else "free", settings)
    except RuntimeError as exc:
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
