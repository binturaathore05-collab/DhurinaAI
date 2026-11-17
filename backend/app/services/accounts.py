"""OTP login, session tokens, demo quota and subscription status."""
import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass

import jwt

from ..db import Database
from ..i18n import t

OTP_TTL_SECONDS = 300
OTP_MAX_ATTEMPTS = 5


class AuthError(Exception):
    """Raised with a message already translated for the student."""


class WrongCode(AuthError):
    """The code typed does not match (counted towards the per-number lock)."""


def _hash_code(phone: str, code: str, secret: str) -> str:
    return hmac.new(secret.encode(), f"{phone}:{code}".encode(), hashlib.sha256).hexdigest()


def normalize_phone(phone: str) -> str:
    digits = "".join(ch for ch in phone if ch.isdigit())
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    if len(digits) != 10 or digits[0] not in "6789":
        raise ValueError("Enter a valid 10-digit Indian mobile number")
    return "+91" + digits


@dataclass
class OtpService:
    db: Database
    secret: str
    sms_sender: "callable"  # (phone, message) -> None

    def send(self, teacher_id: str, teacher_name: str, phone: str, template: str = "otp_sms") -> None:
        phone = normalize_phone(phone)
        code = f"{secrets.randbelow(10**6):06d}"
        self.db.execute("UPDATE otp_codes SET used = 1 WHERE teacher_id = ? AND phone = ? AND used = 0",
                        (teacher_id, phone))
        self.db.execute(
            "INSERT INTO otp_codes (teacher_id, phone, code_hash, expires_at) VALUES (?, ?, ?, ?)",
            (teacher_id, phone, _hash_code(phone, code, self.secret), time.time() + OTP_TTL_SECONDS))
        self.sms_sender(phone, t(template, "en", code=code, teacher=teacher_name))

    def verify(self, teacher_id: str, phone: str, code: str) -> str:
        """Check the code; return the normalized phone, or raise AuthError."""
        phone = normalize_phone(phone)
        row = self.db.one(
            "SELECT * FROM otp_codes WHERE teacher_id = ? AND phone = ? AND used = 0 ORDER BY id DESC LIMIT 1",
            (teacher_id, phone))
        if row is None or row["expires_at"] < time.time():
            raise AuthError(t("otp_expired", "en"))
        if row["attempts"] >= OTP_MAX_ATTEMPTS:
            raise AuthError(t("otp_too_many", "en"))
        if not hmac.compare_digest(row["code_hash"], _hash_code(phone, code.strip(), self.secret)):
            self.db.execute("UPDATE otp_codes SET attempts = attempts + 1 WHERE id = ?", (row["id"],))
            raise WrongCode(t("otp_invalid", "en"))
        self.db.execute("UPDATE otp_codes SET used = 1 WHERE id = ?", (row["id"],))
        return phone


def get_or_create_student(db: Database, teacher_id: str, phone: str) -> int:
    db.execute("INSERT OR IGNORE INTO students (teacher_id, phone, language) VALUES (?, ?, 'en')",
               (teacher_id, phone))
    row = db.one("SELECT id FROM students WHERE teacher_id = ? AND phone = ?", (teacher_id, phone))
    return row["id"]


def issue_token(student_id: int, teacher_id: str, secret: str, days: int) -> str:
    now = int(time.time())
    return jwt.encode({"sub": str(student_id), "tid": teacher_id, "iat": now, "exp": now + days * 86400},
                      secret, algorithm="HS256")


def read_token(token: str, secret: str) -> tuple[int, str]:
    try:
        data = jwt.decode(token, secret, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise AuthError("Session expired. Please log in again.") from exc
    return int(data["sub"]), data["tid"]


# ---------- access: demo → active → (renew soon) → grace → expired ----------

def active_subscription(db: Database, student_id: int, now: float | None = None):
    now = now or time.time()
    return db.one("SELECT * FROM subscriptions WHERE student_id = ? AND starts_at <= ? AND ends_at > ? "
                  "ORDER BY ends_at DESC LIMIT 1", (student_id, now, now))


FREE_PLAN = "free"   # a plan given by Dhurina without payment (testers, scholarships); never counted as money


def grant_free_plan(db: Database, student_id: int, days: int, now: float | None = None) -> float:
    """Super Admin: a plan without payment, from now (or from the end of a plan the student already has)."""
    if not 1 <= int(days) <= 366:
        raise ValueError("Give 1 to 366 days")
    now = now or time.time()
    start = max(now, _latest_end(db, student_id) or 0)
    end = start + int(days) * 86400
    db.execute("INSERT INTO subscriptions (student_id, plan_id, starts_at, ends_at) VALUES (?, ?, ?, ?)",
               (student_id, FREE_PLAN, start, end))
    return end


def end_free_plan(db: Database, student_id: int, now: float | None = None) -> None:
    """Stops free plans at once (paid plans are never touched)."""
    now = now or time.time()
    db.execute("UPDATE subscriptions SET ends_at = ? WHERE student_id = ? AND plan_id = ? AND ends_at > ?",
               (now, student_id, FREE_PLAN, now))
    db.execute("DELETE FROM subscriptions WHERE student_id = ? AND plan_id = ? AND starts_at >= ends_at",
               (student_id, FREE_PLAN))


def plan_summary(db: Database, student_id: int, now: float | None = None) -> dict:
    now = now or time.time()
    cur = active_subscription(db, student_id, now)
    free = db.one("SELECT MAX(ends_at) AS e FROM subscriptions WHERE student_id = ? AND plan_id = ? AND ends_at > ?",
                  (student_id, FREE_PLAN, now))["e"]
    return {"active": bool(cur), "ends_at": _latest_end(db, student_id) if cur else None, "free_until": free}


def _latest_end(db: Database, student_id: int) -> float | None:
    """When the student's paid time runs out (including plans bought in advance)."""
    row = db.one("SELECT MAX(ends_at) AS e FROM subscriptions WHERE student_id = ?", (student_id,))
    return row["e"] if row else None


def _questions_since(db: Database, student_id: int, since: float) -> int:
    row = db.one("SELECT COUNT(*) AS n FROM qa_history WHERE student_id = ? "
                 "AND created_at >= datetime(?, 'unixepoch')", (student_id, since))
    return row["n"]


def access_status(db: Database, student_id: int, demo_limit: int, grace_days: int = 0, grace_questions: int = 0,
                  reminder_days: int = 3, now: float | None = None) -> dict:
    """Everything the app needs to decide what to show:
    state = demo | active | grace | expired, plus days left, renew reminder, and questions left."""
    now = now or time.time()
    used = db.one("SELECT demo_questions_used FROM students WHERE id = ?", (student_id,))["demo_questions_used"]
    end = _latest_end(db, student_id)
    info = {"state": "demo", "subscribed": False, "subscription_ends_at": end, "days_left": None,
            "renew_soon": False, "plan_ended_at": None, "grace_questions_left": 0,
            "demo_questions_left": max(demo_limit - used, 0)}
    if end and active_subscription(db, student_id, now):
        days_left = int((end - now) // 86400)
        info.update(state="active", subscribed=True, days_left=days_left, renew_soon=days_left < reminder_days)
    elif end:  # had a plan, it has run out
        grace_left = 0
        if now < end + grace_days * 86400:
            grace_left = max(grace_questions - _questions_since(db, student_id, end), 0)
        info.update(state="grace" if grace_left > 0 else "expired", plan_ended_at=end,
                    grace_questions_left=grace_left, demo_questions_left=0)
    info["can_ask"] = (info["state"] in ("active", "grace")) or (info["state"] == "demo" and info["demo_questions_left"] > 0)
    return info


def consume_question(db: Database, student_id: int, demo_limit: int, grace_days: int = 0,
                     grace_questions: int = 0) -> bool:
    """Count one question. Subscribers are unlimited; demo users use free questions; a student whose plan
    just ended gets a few grace questions. Returns False when the student must pay first."""
    status = access_status(db, student_id, demo_limit, grace_days, grace_questions)
    if status["state"] in ("active", "grace"):
        return True  # grace questions are counted from the question history itself
    if status["state"] == "expired":
        return False
    cur = db.execute("UPDATE students SET demo_questions_used = demo_questions_used + 1 "
                     "WHERE id = ? AND demo_questions_used < ?", (student_id, demo_limit))
    return cur.rowcount == 1
