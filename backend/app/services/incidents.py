"""B4 · Human Review Center: safety incidents ("cases") that people review, act on and close.

Cases open by themselves (escalation) for:
  care            a student seemed upset / talked about self-harm → HIGH, top of the list (a person should look)
  student_review  a student was stopped until an admin reviews (A3 ladder) → HIGH
  serious_request a clearly harmful request (A2 / A3) → MEDIUM
  ai_stopped      the AI wrote something unsafe and the safety check stopped it → LOW (quality review)
  filter_review   a small problem caught by a content filter with "human review" on (B9) → LOW
and by hand: an admin flags a conversation (e.g. after a parent's complaint, found by its LT- code in Audit).

Repeats are folded: while a case of the same kind for the same student is still open, a new event is added to its
timeline instead of opening another case. Every step (seen, escalated, class stopped, teacher AI paused, resolved)
is written to the case timeline with who and when; the audit log (A5) records every look.

Only roles with the "evidence" permission may see cases (services/roles.py: Super Admin, Safety Admin).
"""
import time

from ..db import Database

KINDS = {
    "care": ("high", "Student may need help (sadness / self-harm)"),
    "student_review": ("high", "Student stopped until an admin reviews"),
    "serious_request": ("medium", "Harmful request by a student"),
    "ai_stopped": ("low", "AI tried to give an unsafe answer (stopped)"),
    "filter_review": ("low", "Caught by a content filter (human review on)"),
    "report": ("high", "Reported conversation"),
}
STATUSES = ("open", "in_review", "escalated", "resolved")
RESOLUTIONS = {
    "no_issue": "Checked — no problem",
    "action_taken": "Action taken (student / teacher / content)",
    "false_alarm": "False alarm (safety check was too strict)",
    "ai_failure": "AI failure — something unsafe reached the student",
    "referred": "Referred to parents / authorities",
}
SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


class IncidentError(Exception):
    pass


def _note(db: Database, incident_id: int, by: str, action: str, note: str = "", now: float | None = None) -> None:
    db.execute("INSERT INTO incident_notes (incident_id, at, by_who, action, note) VALUES (?, ?, ?, ?, ?)",
               (incident_id, now or time.time(), by, action, (note or "")[:2000]))


def open_auto(db: Database, kind: str, student_id: int | None, teacher_id: str | None, summary: str,
              qa_id: int | None = None, now: float | None = None) -> int:
    """Open a case (or add to the open one of the same kind for this student). Never raises into the caller."""
    now = now or time.time()
    severity, title = KINDS[kind]
    existing = db.one("SELECT id FROM incidents WHERE kind = ? AND student_id IS ? AND status != 'resolved' "
                      "ORDER BY id DESC LIMIT 1", (kind, student_id)) if student_id else None
    if existing:
        db.execute("UPDATE incidents SET events = events + 1, last_at = ?, qa_id = COALESCE(?, qa_id) WHERE id = ?",
                   (now, qa_id, existing["id"]))
        _note(db, existing["id"], "system", "happened again", summary, now)
        n = db.one("SELECT events FROM incidents WHERE id = ?", (existing["id"],))["events"]
        if kind == "serious_request" and n >= 3:   # B7: the same student keeps trying
            from . import alerts
            alerts.raise_alert(db, "repeated", "high", f"Student made {n} harmful requests (case #{existing['id']})",
                               "The same student keeps asking for harmful things.", f"#/case/{existing['id']}",
                               f"repeated:{existing['id']}", student_id, teacher_id, now)
        return existing["id"]
    cur = db.execute(
        "INSERT INTO incidents (created_at, last_at, source, kind, severity, status, student_id, teacher_id, qa_id, "
        "title, summary, events) VALUES (?, ?, 'auto', ?, ?, 'open', ?, ?, ?, ?, ?, 1)",
        (now, now, kind, severity, student_id, teacher_id, qa_id, title, (summary or "")[:1000]))
    _note(db, cur.lastrowid, "system", "opened", summary, now)
    if kind == "care":   # B7: a person should look now
        from . import alerts
        alerts.raise_alert(db, "care", "critical", f"A student may need help (case #{cur.lastrowid})",
                           "A student seemed upset or talked about hurting themselves. Sir gave the helpline. "
                           "Please look at the case now.", f"#/case/{cur.lastrowid}", f"care:{cur.lastrowid}",
                           student_id, teacher_id, now)
        if student_id:   # B9: only when the admin chose "automatic" (default: a person decides in the case)
            from . import parent_notify
            if parent_notify.notify(db, student_id, "care", now=now).get("status") == "sent":
                _note(db, cur.lastrowid, "system", "inform parent: SMS sent to the parent (automatic)", "", now)
    return cur.lastrowid


def flag(db: Database, by: str, note: str, qa_id: int | None = None, student_id: int | None = None) -> int:
    """An admin flags a conversation by hand (e.g. after a complaint)."""
    note = (note or "").strip()
    if not note:
        raise IncidentError("Write what was reported")
    teacher_id = None
    if qa_id:
        r = db.one("SELECT q.student_id, s.teacher_id FROM qa_history q JOIN students s ON s.id = q.student_id "
                   "WHERE q.id = ?", (qa_id,))
        if r is None:
            raise KeyError(qa_id)
        student_id, teacher_id = r["student_id"], r["teacher_id"]
    elif student_id:
        r = db.one("SELECT teacher_id FROM students WHERE id = ?", (student_id,))
        if r is None:
            raise KeyError(student_id)
        teacher_id = r["teacher_id"]
    else:
        raise IncidentError("Choose a conversation or a student")
    now = time.time()
    severity, title = KINDS["report"]
    cur = db.execute(
        "INSERT INTO incidents (created_at, last_at, source, kind, severity, status, student_id, teacher_id, qa_id, "
        "title, summary, events, flagged_by) VALUES (?, ?, 'admin', 'report', ?, 'open', ?, ?, ?, ?, ?, 1, ?)",
        (now, now, severity, student_id, teacher_id, qa_id, title, note[:1000], by))
    _note(db, cur.lastrowid, by, "flagged", note, now)
    return cur.lastrowid


def list_incidents(db: Database, status: str = "", q: str = "", offset: int = 0, limit: int = 30) -> dict:
    where, args = [], []
    if status == "active" or not status:
        where.append("i.status != 'resolved'")
    elif status in STATUSES:
        where.append("i.status = ?")
        args.append(status)
    if q:
        where.append("(i.title LIKE ? OR i.summary LIKE ? OR s.name LIKE ? OR s.phone LIKE ? OR CAST(i.id AS TEXT) = ?)")
        like = f"%{q}%"
        args += [like, like, like, like, q.strip()]
    w = ("WHERE " + " AND ".join(where)) if where else ""
    rows = db.all(f"""SELECT i.*, s.name AS student_name, s.phone AS student_phone, t.name AS teacher_name
        FROM incidents i LEFT JOIN students s ON s.id = i.student_id LEFT JOIN teachers t ON t.id = i.teacher_id {w}
        ORDER BY CASE i.status WHEN 'resolved' THEN 1 ELSE 0 END,
                 CASE i.severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, i.last_at DESC
        LIMIT ? OFFSET ?""", (*args, max(1, min(int(limit), 100)), max(int(offset), 0)))
    total = db.one(f"SELECT COUNT(*) AS n FROM incidents i LEFT JOIN students s ON s.id = i.student_id {w}", tuple(args))["n"]
    counts = {r["status"]: r["n"] for r in db.all("SELECT status, COUNT(*) AS n FROM incidents GROUP BY status")}
    high_open = db.one("SELECT COUNT(*) AS n FROM incidents WHERE status != 'resolved' AND severity = 'high'")["n"]
    return {"items": [_mask_row(dict(r)) for r in rows], "total": total,
            "counts": {s: counts.get(s, 0) for s in STATUSES}, "high_open": high_open}


def _mask_row(r: dict) -> dict:
    p = r.pop("student_phone", None)
    r["student_phone"] = (p[:3] + "•••••" + p[-3:]) if p and len(p) > 6 else p
    return r


def detail(db: Database, incident_id: int, viewer: str | None = None) -> dict:
    r = db.one("""SELECT i.*, s.name AS student_name, s.phone AS student_phone, s.status AS student_status,
                  s.class_level, s.is_adult, t.name AS teacher_name
                  FROM incidents i LEFT JOIN students s ON s.id = i.student_id LEFT JOIN teachers t ON t.id = i.teacher_id
                  WHERE i.id = ?""", (incident_id,))
    if r is None:
        raise KeyError(incident_id)
    out = _mask_row(dict(r))
    if viewer and r["status"] == "open":   # someone looked at it: it is now in review
        db.execute("UPDATE incidents SET status = 'in_review', assigned_to = COALESCE(assigned_to, ?) WHERE id = ?",
                   (viewer, incident_id))
        _note(db, incident_id, viewer, "started review")
        out["status"], out["assigned_to"] = "in_review", out["assigned_to"] or viewer
    out["conversation"] = conversation(db, r["student_id"], r["qa_id"])
    out["timeline"] = [dict(n) for n in db.all("SELECT at, by_who, action, note FROM incident_notes WHERE incident_id = ? "
                                               "ORDER BY at, id", (incident_id,))]
    out["resolutions"] = RESOLUTIONS
    return out


def conversation(db: Database, student_id: int | None, qa_id: int | None, limit: int = 40) -> list[dict]:
    """The class around the incident: the same class session as the flagged answer, else the student's latest."""
    if not student_id:
        return []
    session = None
    if qa_id:
        row = db.one("SELECT session_id FROM qa_history WHERE id = ?", (qa_id,))
        session = row["session_id"] if row else None
    if session:
        rows = db.all("SELECT id, question, answer, follow_up, scope, origin, created_at, verify_code, model "
                      "FROM qa_history WHERE session_id = ? ORDER BY id LIMIT ?", (session, limit))
    else:
        rows = list(reversed(db.all("SELECT id, question, answer, follow_up, scope, origin, created_at, verify_code, model "
                                    "FROM qa_history WHERE student_id = ? ORDER BY id DESC LIMIT ?", (student_id, limit))))
    return [{**dict(x), "flagged": x["id"] == qa_id} for x in rows]


def act(db: Database, incident_id: int, by: str, action: str, note: str = "", resolution: str = "") -> None:
    """escalate | note | resolve | reopen (actions with side effects — stop class, pause teacher — are done by the API
    and recorded here with record())."""
    r = db.one("SELECT status FROM incidents WHERE id = ?", (incident_id,))
    if r is None:
        raise KeyError(incident_id)
    note = (note or "").strip()
    now = time.time()
    if action == "escalate":
        db.execute("UPDATE incidents SET status = 'escalated', escalated_at = ?, severity = 'high' WHERE id = ?",
                   (now, incident_id))
        _note(db, incident_id, by, "escalated to safety team", note, now)
    elif action == "note":
        if not note:
            raise IncidentError("Write a note")
        _note(db, incident_id, by, "note", note, now)
    elif action == "resolve":
        if resolution not in RESOLUTIONS:
            raise IncidentError("Choose how it was resolved")
        if not note:
            raise IncidentError("Write resolution remarks")
        db.execute("UPDATE incidents SET status = 'resolved', resolution = ?, resolution_note = ?, resolved_by = ?, "
                   "resolved_at = ?, ai_failure = ? WHERE id = ?",
                   (resolution, note[:2000], by, now, int(resolution == "ai_failure"), incident_id))
        _note(db, incident_id, by, "resolved: " + RESOLUTIONS[resolution], note, now)
        if resolution == "ai_failure":   # B7: something unsafe reached a student
            from . import alerts
            alerts.raise_alert(db, "ai_failure", "critical", f"AI failure confirmed in case #{incident_id}",
                               f"{by} found that something unsafe reached a student. Consider Emergency and the safety "
                               f"tests.", f"#/case/{incident_id}", f"ai_failure:{incident_id}", now=now)
    elif action == "reopen":
        if r["status"] != "resolved":
            raise IncidentError("This case is not closed")
        db.execute("UPDATE incidents SET status = 'in_review', resolved_at = NULL, ai_failure = 0 WHERE id = ?", (incident_id,))
        _note(db, incident_id, by, "reopened", note, now)
    else:
        raise IncidentError("Unknown action")


def record(db: Database, incident_id: int, by: str, action: str, note: str = "") -> None:
    _note(db, incident_id, by, action, note)


def counts(db: Database, since: float, teacher_id: str = "") -> dict:
    """For the safety dashboard (B3)."""
    t, a = ("AND teacher_id = ?", (teacher_id,)) if teacher_id else ("", ())
    one = lambda sql, args: db.one(sql, args)["n"]  # noqa: E731
    return {
        "open": one(f"SELECT COUNT(*) AS n FROM incidents WHERE status != 'resolved' {t}", a),
        "resolved": one(f"SELECT COUNT(*) AS n FROM incidents WHERE status = 'resolved' AND resolved_at >= ? {t}", (since, *a)),
        "ai_failures": one(f"SELECT COUNT(*) AS n FROM incidents WHERE ai_failure = 1 AND resolved_at >= ? {t}", (since, *a)),
    }
