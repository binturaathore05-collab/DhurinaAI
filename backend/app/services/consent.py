"""B1 · Class at signup + parent consent by OTP for students under 18 (India's DPDP Act 2023).

After the student's own OTP login the app asks two things on one screen: the class (from the admin's lowest class,
default class 6, up to class 12, or "College / exam preparation") and "Are you 18 or older?". A student under 18 then
gives a parent's phone number; the parent gets a code by SMS and the student types it in. Only then does Sir's AI
work for that student (checked on the server for every AI action). Library, notes and payments are not affected.
Every consent is recorded (who, which number, when, from where, which notice) and can be withdrawn by an admin
when a parent asks.
"""
import time

from ..db import Database
from ..i18n import t

NOTICE_VERSION = "parent-consent-2026-11-17"
COLLEGE = "college"
DEFAULT_MIN_CLASS = 6


class ConsentError(Exception):
    pass


def class_options(min_class: int) -> list[dict]:
    opts = [{"value": str(c), "label": f"Class {c}"} for c in range(max(1, min(min_class, 12)), 13)]
    return opts + [{"value": COLLEGE, "label": "College / exam preparation"}]


def min_class(admin_settings: dict) -> int:
    try:
        return max(1, min(12, int((admin_settings.get("students") or {}).get("min_class", DEFAULT_MIN_CLASS))))
    except (TypeError, ValueError):
        return DEFAULT_MIN_CLASS


def _mask(phone: str | None) -> str | None:
    return (phone[:3] + "•••••" + phone[-3:]) if phone and len(phone) > 6 else phone


def state(db: Database, student_id: int, min_cls: int = DEFAULT_MIN_CLASS) -> dict:
    """What the app needs: is the class known, is a parent's OK still needed."""
    r = db.one("SELECT class_level, is_adult, consent_status, parent_phone, consent_at FROM students WHERE id = ?",
               (student_id,))
    profile_needed = not r["class_level"]
    consent_needed = (not profile_needed) and not r["is_adult"] and r["consent_status"] != "given"
    return {"class_level": r["class_level"], "is_adult": bool(r["is_adult"]) if r["is_adult"] is not None else None,
            "consent": "not_needed" if r["is_adult"] else (r["consent_status"] or "needed"),
            "profile_needed": profile_needed, "consent_needed": consent_needed,
            "parent_phone": _mask(r["parent_phone"]), "class_options": class_options(min_cls)}


def gate_message(st: dict) -> str | None:
    """None if Sir's AI may work for this student, else the message to show."""
    if st["profile_needed"]:
        return t("profile_needed", "en")
    if st["consent_needed"]:
        return t("consent_needed", "en")
    return None


def set_profile(db: Database, student_id: int, class_level: str, is_adult: bool, min_cls: int) -> None:
    class_level = str(class_level or "").strip().lower()
    allowed = {o["value"] for o in class_options(min_cls)}
    if class_level not in allowed:
        raise ConsentError(f"LiveTeach is for class {min_cls} and above. Please choose your class.")
    db.execute("UPDATE students SET class_level = ?, is_adult = ? WHERE id = ?", (class_level, int(bool(is_adult)), student_id))


def namespace(student_id: int) -> str:
    """Parent codes live apart from login codes."""
    return f"consent:{student_id}"


def check_parent_phone(db: Database, student_id: int, parent_phone: str) -> None:
    me = db.one("SELECT phone FROM students WHERE id = ?", (student_id,))["phone"]
    if parent_phone == me:
        raise ConsentError("Please enter your mother's or father's number, not your own.")


def record(db: Database, student_id: int, teacher_id: str, parent_phone: str, ip: str, now: float | None = None) -> None:
    now = now or time.time()
    db.execute("INSERT INTO parent_consents (student_id, teacher_id, parent_phone, given_at, ip, notice_version) "
               "VALUES (?, ?, ?, ?, ?, ?)", (student_id, teacher_id, parent_phone, now, ip, NOTICE_VERSION))
    db.execute("UPDATE students SET consent_status = 'given', parent_phone = ?, consent_at = ? WHERE id = ?",
               (parent_phone, now, student_id))


def revoke(db: Database, student_id: int, by: str, reason: str, now: float | None = None) -> None:
    reason = (reason or "").strip()
    if not reason:
        raise ConsentError("Write why (e.g. the parent called to withdraw consent)")
    row = db.one("SELECT consent_status FROM students WHERE id = ?", (student_id,))
    if row is None:
        raise KeyError(student_id)
    if row["consent_status"] != "given":
        raise ConsentError("There is no parent consent to withdraw")
    now = now or time.time()
    db.execute("UPDATE parent_consents SET revoked_at = ?, revoked_by = ?, revoke_reason = ? "
               "WHERE student_id = ? AND revoked_at IS NULL", (now, by, reason[:300], student_id))
    db.execute("UPDATE students SET consent_status = 'withdrawn', consent_at = NULL WHERE id = ?", (student_id,))


def history(db: Database, student_id: int) -> list[dict]:
    return [{**dict(r), "parent_phone": _mask(r["parent_phone"])} for r in db.all(
        "SELECT parent_phone, given_at, ip, notice_version, revoked_at, revoked_by, revoke_reason FROM parent_consents "
        "WHERE student_id = ? ORDER BY given_at DESC", (student_id,))]


def class_for_prompt(class_level: str | None) -> str:
    """One line for Sir's instructions so explanations fit the student's level."""
    if not class_level:
        return ""
    if class_level == COLLEGE:
        return "The student is in college or preparing for a competitive exam: explain at that level."
    return (f"The student is in class {class_level} (Indian school). Explain at that level, with examples a "
            f"class {class_level} student knows, and keep everything suitable for their age.")
