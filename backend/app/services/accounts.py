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

    def send(self, teacher_id: str, teacher_name: str, phone: str) -> None:
        phone = normalize_phone(phone)
        code = f"{secrets.randbelow(10**6):06d}"
        self.db.execute("UPDATE otp_codes SET used = 1 WHERE teacher_id = ? AND phone = ? AND used = 0",
                        (teacher_id, phone))
        self.db.execute(
            "INSERT INTO otp_codes (teacher_id, phone, code_hash, expires_at) VALUES (?, ?, ?, ?)",
            (teacher_id, phone, _hash_code(phone, code, self.secret), time.time() + OTP_TTL_SECONDS))
        self.sms_sender(phone, t("otp_sms", "en", code=code, teacher=teacher_name))

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
            raise AuthError(t("otp_invalid", "en"))
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


# ---------- access: demo quota + subscription ----------

def active_subscription(db: Database, student_id: int, now: float | None = None):
    now = now or time.time()
    return db.one("SELECT * FROM subscriptions WHERE student_id = ? AND starts_at <= ? AND ends_at > ? "
                  "ORDER BY ends_at DESC LIMIT 1", (student_id, now, now))


def access_status(db: Database, student_id: int, demo_limit: int) -> dict:
    sub = active_subscription(db, student_id)
    used = db.one("SELECT demo_questions_used FROM students WHERE id = ?", (student_id,))["demo_questions_used"]
    return {
        "subscribed": sub is not None,
        "subscription_ends_at": sub["ends_at"] if sub else None,
        "demo_questions_left": max(demo_limit - used, 0),
        "can_ask": sub is not None or used < demo_limit,
    }


def consume_question(db: Database, student_id: int, demo_limit: int) -> bool:
    """Count one question. Subscribers are unlimited; demo users use up their free questions.
    Returns False if the student may not ask (demo over and no subscription)."""
    if active_subscription(db, student_id):
        return True
    cur = db.execute("UPDATE students SET demo_questions_used = demo_questions_used + 1 "
                     "WHERE id = ? AND demo_questions_used < ?", (student_id, demo_limit))
    return cur.rowcount == 1
