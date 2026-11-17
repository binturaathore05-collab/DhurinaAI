"""B9 · Parent notifications (brief §9): a short SMS to the parent who gave consent (B1) when

  block   the student's AI teacher access is suspended, stopped for review or disabled (automatically or by an admin)
          → on by default (admin Safety Center → Parents)
  care    a student seemed upset or talked about hurting themselves (care case, B4)
          → by default a person in the Review Center decides and sends it with one button ("Inform parent"),
            because sometimes the trouble is at home; the admin can switch it to automatic.

The SMS never contains what the child wrote — only that something happened and what to do. Adults (18+) and
students without a parent's number are never notified. The same kind of SMS goes at most once a day per student.
Every attempt (sent or why not) is recorded and shown on the student's page.
"""
import time

from ..db import Database
from ..i18n import t

DEFAULT_PARENTS = {"notify_block": True, "notify_care": "manual", "language": "hi"}
CARE_MODES = ("off", "manual", "auto")
REPEAT_SECONDS = 86400

sender = {"sms": None}   # set by the API: (phone, message) -> None


def parent_settings(admin_settings: dict) -> dict:
    out = dict(DEFAULT_PARENTS)
    out.update({k: v for k, v in (admin_settings.get("parents") or {}).items() if k in out})
    return out


def validate(values: dict) -> dict:
    out = dict(values or {})
    if "notify_block" in out:
        v = out["notify_block"]
        out["notify_block"] = v if isinstance(v, bool) else str(v).lower() in ("true", "1", "on", "yes")
    if out.get("notify_care", "manual") not in CARE_MODES:
        raise ValueError("Care SMS must be off, sent by a person, or automatic")
    if out.get("language", "hi") not in ("hi", "en"):
        raise ValueError("Parent SMS language must be Hindi or English")
    return out


def _record(db: Database, student_id: int, kind: str, phone, status: str, by: str, now: float) -> dict:
    db.execute("INSERT INTO parent_notices (at, student_id, kind, phone, status, by_who) VALUES (?, ?, ?, ?, ?, ?)",
               (now, student_id, kind, phone, status, by))
    return {"status": status}


def notify(db: Database, student_id: int, kind: str, by: str = "system", now: float | None = None,
           force: bool = False) -> dict:
    """Send (or explain why not). `force` = a person pressed the button (ignores on/off, not the once-a-day rule).
    Never raises into the caller."""
    try:
        now = now or time.time()
        from . import admin as admin_mod
        s = parent_settings(admin_mod.get_settings(db))
        if not force:
            on = s["notify_block"] if kind == "block" else s["notify_care"] == "auto"
            if not on:
                return {"status": "off"}
        st = db.one("SELECT s.name, s.is_adult, s.parent_phone, s.consent_status, t.name AS teacher FROM students s "
                    "LEFT JOIN teachers t ON t.id = s.teacher_id WHERE s.id = ?", (student_id,))
        if st is None:
            return {"status": "no_student"}
        if st["is_adult"]:
            return _record(db, student_id, kind, None, "adult", by, now)
        phone = st["parent_phone"] if st["consent_status"] == "given" else None
        if not phone:
            return _record(db, student_id, kind, None, "no_phone", by, now)
        recent = db.one("SELECT id FROM parent_notices WHERE student_id = ? AND kind = ? AND status = 'sent' AND at > ?",
                        (student_id, kind, now - REPEAT_SECONDS))
        if recent:
            return _record(db, student_id, kind, phone, "repeat", by, now)
        name = (st["name"] or "").strip() or ("आपके बच्चे" if s["language"] == "hi" else "your child")
        text = t(f"parent_{kind}", s["language"], name=name, teacher=st["teacher"] or "LiveTeach")
        if not sender["sms"]:
            return _record(db, student_id, kind, phone, "failed", by, now)
        try:
            sender["sms"](phone, text)
        except Exception as exc:
            print(f"[parent sms] failed: {exc}")
            return _record(db, student_id, kind, phone, "failed", by, now)
        return _record(db, student_id, kind, phone, "sent", by, now)
    except Exception as exc:   # a notice must never break blocking or the care reply
        print(f"[parent sms] error: {exc}")
        return {"status": "failed"}


def history(db: Database, student_id: int, limit: int = 20) -> list[dict]:
    out = []
    for r in db.all("SELECT at, kind, phone, status, by_who FROM parent_notices WHERE student_id = ? "
                    "ORDER BY at DESC, id DESC LIMIT ?", (student_id, limit)):
        d = dict(r)
        p = d.get("phone") or ""
        d["phone"] = ("•" * max(len(p) - 4, 0) + p[-4:]) if p else ""
        out.append(d)
    return out
