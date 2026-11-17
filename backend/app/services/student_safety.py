"""A3 · Student status, warnings ladder, auto-block and admin Block / Unblock with history.

Status (stored on the student, checked on the server for every AI action):
  active    – normal
  warning   – still learns normally; the app shows a gentle warning (clears itself after a quiet week)
  suspended – temporary: no AI actions until `status_until`; notes, library and payments still work
  review    – no AI actions until an admin decides (no end time)
  disabled  – permanently disabled by an admin: no login, nothing works

Violations come from the AI's own decision today (A1 scope); A2 adds an independent moderation check.
  minor   = a topic the admin has blocked (scope "blocked")
  serious = clearly harmful requests (scope "unsafe": sexual content, weapons, dangerous crime, safety bypass,
            threats). Ordinary off-topic chat is NOT a violation: a harmless question never leads to a block.
"""
import time

from ..db import Database
from ..i18n import t

DAY = 86400
MINOR_WINDOW_DAYS = 7
SERIOUS_WINDOW_DAYS = 30
STATUSES = ("active", "warning", "suspended", "review", "disabled")
NO_AI = ("suspended", "review", "disabled")   # these students can't use Sir's AI

DEFAULT_SAFETY = {
    "auto_block": True,
    "minor_warn": 3,        # blocked-topic questions in 7 days → warning
    "minor_suspend": 6,     # … → temporary suspension
    "serious_suspend": 1,   # serious requests in 30 days → temporary suspension at once
    "serious_review": 2,    # … → access stopped until an admin reviews
    "suspend_hours": 24,
}

REASONS = ["Blocked topics again and again", "Harmful or unsafe request", "Trying to bypass safety rules",
           "Harassment or threats", "Sharing account / misuse", "Parent or school request", "Other"]


class SafetyError(Exception):
    pass


def safety_settings(admin_settings: dict) -> dict:
    out = dict(DEFAULT_SAFETY)
    saved = admin_settings.get("safety") or {}
    for k in out:
        if k in saved:
            out[k] = bool(saved[k]) if k == "auto_block" else max(int(saved[k]), 1)
    return out


def validate_settings(values: dict) -> dict:
    out = {}
    for k, v in values.items():
        if k == "auto_block":
            out[k] = v in (True, "true", "1", 1, "on")
            continue
        try:
            n = int(v)
            ok = n >= 1 and float(v) == n
        except (TypeError, ValueError):
            ok = False
        if not ok:
            raise SafetyError("Every student safety number must be a whole number, 1 or more")
        out[k] = n
    if out.get("minor_suspend", 2) <= out.get("minor_warn", 1):
        raise SafetyError("Suspension must need more blocked-topic questions than the warning")
    if out.get("serious_review", 2) < out.get("serious_suspend", 1):
        raise SafetyError("Admin review must need at least as many serious requests as the suspension")
    return out


# ---------- reading the status ----------

def _row(db: Database, student_id: int):
    return db.one("SELECT id, status, status_until, status_reason FROM students WHERE id = ?", (student_id,))


def _log(db: Database, student_id: int, old: str, new: str, by: str, reason: str, remarks: str = "",
         until: float | None = None, now: float | None = None) -> None:
    db.execute("INSERT INTO student_status_log (student_id, old_status, new_status, by_who, reason, remarks, until, at) "
               "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (student_id, old, new, by, reason[:200], remarks[:1000], until,
                                                   now or time.time()))


def _set(db: Database, student_id: int, new: str, by: str, reason: str, remarks: str = "",
         until: float | None = None, now: float | None = None) -> None:
    old = (_row(db, student_id)["status"] or "active")
    db.execute("UPDATE students SET status = ?, status_until = ?, status_reason = ? WHERE id = ?",
               (new, until, reason[:200], student_id))
    _log(db, student_id, old, new, by, reason, remarks, until, now)
    if new in ("suspended", "review", "disabled") and old != new and reason != "Data deleted on request":
        from . import parent_notify   # B9: tell the parent (if on; never the child's words)
        parent_notify.notify(db, student_id, "block", "system" if by == "auto" else by, now)
    if by == "auto" and new in ("suspended", "review"):   # B7
        from . import alerts
        alerts.raise_alert(db, "auto_block", "high",
                           f"Student {'stopped until review' if new == 'review' else 'suspended'} automatically",
                           f"Reason: {reason}.", f"#/s/{student_id}", f"auto_block:{student_id}:{new}", student_id, now=now)


def _count(db: Database, student_id: int, severity: str, days: int, now: float) -> int:
    return db.one("SELECT COUNT(*) AS n FROM student_violations WHERE student_id = ? AND severity = ? AND at > ?",
                  (student_id, severity, now - days * DAY))["n"]


def status(db: Database, student_id: int, now: float | None = None) -> str:
    """The student's status right now (a finished suspension or a quiet week clears itself here)."""
    now = now or time.time()
    row = _row(db, student_id)
    if row is None:
        raise KeyError(student_id)
    st = row["status"] or "active"
    if st == "suspended" and row["status_until"] and row["status_until"] <= now:
        _set(db, student_id, "active", "system", "Suspension ended", now=now)
        st = "active"
    if st == "warning" and _count(db, student_id, "minor", MINOR_WINDOW_DAYS, now) == 0 \
            and _count(db, student_id, "serious", MINOR_WINDOW_DAYS, now) == 0:
        _set(db, student_id, "active", "system", "No problems for a week", now=now)
        st = "active"
    return st


def account(db: Database, student_id: int, now: float | None = None) -> dict:
    """What the app shows: status + a ready message (None when all is well)."""
    st = status(db, student_id, now)
    row = _row(db, student_id)
    until = row["status_until"] if st == "suspended" else None
    msg = None
    if st == "warning":
        msg = t("safety_warning", "en")
    elif st == "suspended":
        hours = max(int(((until or 0) - (now or time.time()) + 3599) // 3600), 1)
        msg = t("safety_suspended", "en", wait=f"{hours} hour{'s' if hours > 1 else ''}")
    elif st == "review":
        msg = t("safety_review", "en")
    elif st == "disabled":
        msg = t("safety_disabled", "en")
    return {"account_status": st, "account_message": msg, "account_until": until}


def can_use_ai(db: Database, student_id: int) -> dict | None:
    """None if the student may use Sir's AI, else the account info with the message to show."""
    info = account(db, student_id)
    return info if info["account_status"] in NO_AI else None


# ---------- violations → ladder ----------

def record_violation(db: Database, student_id: int, teacher_id: str, severity: str, category: str,
                     question: str, qa_id: int | None, settings: dict, now: float | None = None) -> str:
    """Store one violation and move the student up the ladder if needed. Returns the new status."""
    now = now or time.time()
    db.execute("INSERT INTO student_violations (student_id, teacher_id, qa_id, severity, category, question, at) "
               "VALUES (?, ?, ?, ?, ?, ?, ?)", (student_id, teacher_id, qa_id, severity, (category or "")[:80],
                                                question[:1000], now))
    if severity == "serious":   # B4: a person should look at every clearly harmful request
        from . import incidents
        incidents.open_auto(db, "serious_request", student_id, teacher_id, f"{category}: {question[:300]}", qa_id, now)
    elif severity == "minor":   # B9: the admin asked for a person to look at this filter's hits
        from . import admin as admin_mod, content_filters, incidents
        if content_filters.needs_review(category, admin_mod.get_settings(db)):
            incidents.open_auto(db, "filter_review", student_id, teacher_id, f"{category}: {question[:300]}", qa_id, now)
    st = status(db, student_id, now)
    if not settings["auto_block"] or st in ("review", "disabled"):
        return st
    minor = _count(db, student_id, "minor", MINOR_WINDOW_DAYS, now)
    serious = _count(db, student_id, "serious", SERIOUS_WINDOW_DAYS, now)
    until = now + settings["suspend_hours"] * 3600
    if serious >= settings["serious_review"]:
        _set(db, student_id, "review", "auto", "Repeated harmful or unsafe requests", now=now)
        from . import incidents   # B4: an admin must decide → a high-priority case
        incidents.open_auto(db, "student_review", student_id, teacher_id,
                            "Stopped after repeated harmful requests — decide: unblock, keep stopped or disable", qa_id, now)
        return "review"
    if severity == "serious" and serious >= settings["serious_suspend"]:
        _set(db, student_id, "suspended", "auto", "Harmful or unsafe request", until=until, now=now)
        return "suspended"
    if severity == "minor" and minor >= settings["minor_suspend"] and st != "suspended":
        _set(db, student_id, "suspended", "auto", "Blocked topics again and again", until=until, now=now)
        return "suspended"
    if severity == "minor" and minor >= settings["minor_warn"] and st == "active":
        _set(db, student_id, "warning", "auto", "Blocked topics again and again", now=now)
        return "warning"
    return st


# ---------- admin ----------

ACTIONS = {"warn": "warning", "suspend": "suspended", "review": "review", "disable": "disabled", "unblock": "active"}


def admin_action(db: Database, student_id: int, action: str, reason: str, remarks: str, by: str,
                 hours: int | None = None, now: float | None = None) -> dict:
    now = now or time.time()
    if action not in ACTIONS:
        raise SafetyError("Unknown action")
    if _row(db, student_id) is None:
        raise KeyError(student_id)
    reason = (reason or "").strip()
    if not reason:
        raise SafetyError("Choose a reason")
    until = None
    if action == "suspend":
        try:
            hours = int(hours or 0)
        except (TypeError, ValueError):
            hours = 0
        if not 1 <= hours <= 24 * 90:
            raise SafetyError("Suspension must be between 1 hour and 90 days")
        until = now + hours * 3600
    _set(db, student_id, ACTIONS[action], by, reason, remarks or "", until, now)
    return detail(db, student_id)


def _student_dict(r) -> dict:
    return {"id": r["id"], "name": r["name"], "phone": r["phone"], "teacher_id": r["teacher_id"],
            "teacher_name": r["teacher_name"], "status": r["status"] or "active", "status_until": r["status_until"],
            "status_reason": r["status_reason"], "joined": r["created_at"]}


def list_students(db: Database, status_filter: str = "", q: str = "", teacher_id: str = "",
                  offset: int = 0, limit: int = 25) -> dict:
    """Default view: everyone who is not simply 'active'. A search looks at all students."""
    where, args = [], []
    if status_filter in STATUSES:
        where.append("COALESCE(s.status, 'active') = ?")
        args.append(status_filter)
    elif status_filter != "all" and not q:
        where.append("COALESCE(s.status, 'active') != 'active'")
    if teacher_id:
        where.append("s.teacher_id = ?")
        args.append(teacher_id)
    if q:
        like = f"%{q.strip()}%"
        where.append("(s.name LIKE ? OR s.phone LIKE ? OR CAST(s.id AS TEXT) = ?)")
        args += [like, like, q.strip()]
    sql_where = ("WHERE " + " AND ".join(where)) if where else ""
    limit = max(1, min(int(limit), 100))
    rows = db.all(f"""SELECT s.*, t.name AS teacher_name,
            (SELECT COUNT(*) FROM student_violations v WHERE v.student_id = s.id) AS violations,
            (SELECT MAX(at) FROM student_violations v WHERE v.student_id = s.id) AS last_violation
        FROM students s JOIN teachers t ON t.id = s.teacher_id {sql_where}
        ORDER BY CASE COALESCE(s.status, 'active') WHEN 'review' THEN 0 WHEN 'suspended' THEN 1 WHEN 'warning' THEN 2
                 WHEN 'disabled' THEN 3 ELSE 4 END, last_violation DESC, s.id DESC
        LIMIT ? OFFSET ?""", (*args, limit, max(int(offset), 0)))
    total = db.one(f"SELECT COUNT(*) AS n FROM students s {sql_where}", tuple(args))["n"]
    counts = {r["st"]: r["n"] for r in db.all("SELECT COALESCE(status, 'active') AS st, COUNT(*) AS n FROM students "
                                               "GROUP BY st")}
    items = []
    for r in rows:
        status(db, r["id"])   # let finished suspensions clear before showing them
    for r in rows:
        fresh = _row(db, r["id"])
        d = _student_dict(r)
        d.update(status=fresh["status"] or "active", status_until=fresh["status_until"],
                 status_reason=fresh["status_reason"], violations=r["violations"], last_violation=r["last_violation"])
        items.append(d)
    return {"items": items, "total": total, "counts": {s: counts.get(s, 0) for s in STATUSES}, "reasons": REASONS}


def detail(db: Database, student_id: int) -> dict:
    status(db, student_id)
    r = db.one("SELECT s.*, t.name AS teacher_name FROM students s JOIN teachers t ON t.id = s.teacher_id "
               "WHERE s.id = ?", (student_id,))
    if r is None:
        raise KeyError(student_id)
    out = _student_dict(r)
    out["questions"] = db.one("SELECT COUNT(*) AS n FROM qa_history WHERE student_id = ?", (student_id,))["n"]
    out["violations"] = [dict(v) for v in db.all(
        "SELECT id, severity, category, question, qa_id, at FROM student_violations WHERE student_id = ? "
        "ORDER BY at DESC LIMIT 50", (student_id,))]
    out["history"] = [dict(h) for h in db.all(
        "SELECT old_status, new_status, by_who, reason, remarks, until, at FROM student_status_log "
        "WHERE student_id = ? ORDER BY at DESC, id DESC LIMIT 100", (student_id,))]
    out["reasons"] = REASONS
    from . import consent   # B1
    out["class_level"], out["is_adult"] = r["class_level"], r["is_adult"]
    out["consent_status"] = "not needed (18+)" if r["is_adult"] else (r["consent_status"] or "not given yet")
    out["consents"] = consent.history(db, student_id)
    return out
