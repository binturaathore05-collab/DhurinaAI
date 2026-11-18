"""Parent dashboard (brief §14). A parent opens <server>/parent on any phone browser, types their own mobile number
and the SMS code, and sees each child who gave that number for parent consent (any institute's app):

  - how much the child studied (questions and study days, last 14 days), topics learnt, test results, plan, account
    status — never the child's own words or Sir's answers (the same rule as the parent SMS);
  - "Withdraw my consent" (DPDP): Sir's AI stops for the child until a parent agrees again;
  - "Delete my child's data" (DPDP), after typing DELETE.

No app is needed. The code is sent only to numbers that are a parent's number on record (no SMS cost for others,
and the reply is the same either way, so nobody can find out whose number is registered).
"""
import time

import jwt

from ..db import Database
from . import consent as consent_mod
from . import quiz, student_safety

OTP_NAMESPACE = "parent"     # parent codes are kept apart from the students' login codes
SESSION_DAYS = 7
DAY = 86400


class ParentError(ValueError):
    pass


def is_parent(db: Database, phone: str) -> bool:
    return db.one("SELECT 1 FROM students WHERE parent_phone = ? AND phone NOT LIKE 'deleted:%' LIMIT 1", (phone,)) is not None


def token(phone: str, secret: str, now: float | None = None) -> str:
    now = int(now or time.time())
    return jwt.encode({"sub": phone, "aud": "parent", "iat": now, "exp": now + SESSION_DAYS * DAY}, secret, algorithm="HS256")


def read(tok: str, secret: str) -> str:
    try:
        return jwt.decode(tok, secret, algorithms=["HS256"], audience="parent")["sub"]
    except jwt.PyJWTError:
        raise ParentError("Please log in again")


def _child(db: Database, phone: str, student_id: int):
    row = db.one("SELECT s.*, t.name AS teacher_name, t.app_name FROM students s JOIN teachers t ON t.id = s.teacher_id "
                 "WHERE s.id = ? AND s.parent_phone = ? AND s.phone NOT LIKE 'deleted:%'", (student_id, phone))
    if row is None:
        raise KeyError(student_id)   # not this parent's child (or already deleted)
    return row


def children(db: Database, phone: str, now: float | None = None) -> list[dict]:
    rows = db.all("SELECT id FROM students WHERE parent_phone = ? AND phone NOT LIKE 'deleted:%' ORDER BY id", (phone,))
    return [child(db, phone, r["id"], now) for r in rows]


def child(db: Database, phone: str, student_id: int, now: float | None = None) -> dict:
    from . import accounts
    now = now or time.time()
    s = _child(db, phone, student_id)
    since = now - 14 * DAY
    per_day = {r["d"]: r["n"] for r in db.all(
        "SELECT date(created_at, '+5 hours', '+30 minutes') AS d, COUNT(*) AS n FROM qa_history WHERE student_id = ? "
        "AND created_at >= datetime(?, 'unixepoch') AND COALESCE(scope, 'study') NOT IN ('blocked', 'unsafe', 'care', 'stopped') "
        "GROUP BY d", (student_id, since))}
    days = []
    for k in range(13, -1, -1):
        d = time.strftime("%Y-%m-%d", time.gmtime(now + 5.5 * 3600 - k * DAY))
        days.append({"date": d, "questions": per_day.get(d, 0)})
    week = days[-7:]
    topics = [dict(r) for r in db.all(
        "SELECT topic, MAX(created_at) AS last, COUNT(*) AS n FROM qa_history WHERE student_id = ? AND topic IS NOT NULL "
        "AND topic != '' AND COALESCE(scope, 'study') NOT IN ('blocked', 'unsafe', 'care', 'stopped') "
        "GROUP BY topic ORDER BY last DESC LIMIT 12", (student_id,))]
    tests = [t for t in quiz.history(db, student_id, 10) if t["status"] == "done"]
    plan = accounts.plan_summary(db, student_id, now)
    safety = student_safety.status(db, student_id)
    return {
        "id": s["id"], "name": s["name"] or "", "class_level": s["class_level"], "institute": s["app_name"] or s["teacher_name"],
        "consent": s["consent_status"] or "", "consent_at": s["consent_at"],
        "week": {"questions": sum(d["questions"] for d in week), "study_days": sum(1 for d in week if d["questions"])},
        "days": days, "streak": s["streak"] or 0,
        "topics": [{"topic": x["topic"], "questions": x["n"], "last": x["last"]} for x in topics],
        "tests": [{"mode": t["mode"], "topics": t["topics"][:4], "percent": t["percent"], "at": t["created_at"]} for t in tests],
        "plan": _plan(plan),
        "status": {"active": "ok", "warning": "warning"}.get(safety, "paused") if safety else "ok",
    }


def _plan(p) -> dict | None:
    if not p:
        return None
    return {"active": bool(p.get("active")), "ends_at": p.get("ends_at")}


def withdraw(db: Database, phone: str, student_id: int) -> None:
    _child(db, phone, student_id)
    try:
        consent_mod.revoke(db, student_id, "parent", "The parent withdrew consent in the parent dashboard")
    except consent_mod.ConsentError as exc:
        raise ParentError(str(exc))


def delete(db: Database, phone: str, student_id: int, confirm: str, notes_dir: str) -> dict:
    from . import data_protection
    _child(db, phone, student_id)
    if (confirm or "").strip().upper() != "DELETE":
        raise ParentError("Type DELETE to confirm")
    try:
        return data_protection.delete_student(db, student_id, "parent", "The parent asked in the parent dashboard", notes_dir)
    except data_protection.DataError as exc:
        raise ParentError(str(exc))


def log(db: Database, phone: str, action: str) -> None:
    """Every parent login and action is kept (number masked) for the consent records."""
    masked = phone[:-6] + "••••" + phone[-2:] if len(phone) > 6 else phone
    db.execute("INSERT INTO parent_events (at, phone, action) VALUES (?, ?, ?)", (time.time(), masked, action[:200]))
