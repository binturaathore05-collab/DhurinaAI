"""B3 · Safety dashboard: the numbers behind everything A1–A8 / B1–B2 do, for a date range and (optionally) one teacher.

Most important metric: how many times the AI tried to give a student an unsafe answer, and how many of those the
safety check stopped before the student saw them (every AI text is checked, so stopped = tried, unless a student or
reviewer later reports one that got through — "reported failures", filled by the review center, B4).
"""
import json
import time
from datetime import datetime, timedelta, timezone

from ..db import Database

CATEGORY_LABELS = {
    "sexual": "Sexual / adult content", "adult": "Sexual / adult content",
    "violence": "Violence & crime", "crime": "Violence & crime", "threat": "Violence & crime",
    "weapons": "Weapons & explosives", "explosives": "Weapons & explosives",
    "drugs": "Drugs & alcohol", "jailbreak": "Trying to break the rules",
    "harassment": "Bullying & insults", "bullying": "Bullying & insults",
    "personal_info": "Private details", "privacy": "Private details",
    "dangerous_advice": "Dangerous advice", "self_harm": "Sadness / self-harm (care given)",
    "unsafe": "Harmful (AI's own judgement)", "blocked": "Blocked topic",
}


def _label(cat: str | None) -> str:
    c = (cat or "").strip().lower()
    return CATEGORY_LABELS.get(c) or (f"Blocked topic: {cat}" if cat else "Other")


def _day(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")


def build(db: Database, days: int = 30, teacher_id: str = "", now: float | None = None) -> dict:
    now = now or time.time()
    days = max(1, min(int(days), 365))
    # the window is whole days (UTC): today and the days before it, so the daily chart adds up to the totals
    today = datetime.fromtimestamp(now, timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    since = (today - timedelta(days=days - 1)).timestamp()
    since_txt = datetime.fromtimestamp(since, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    tq, targs = ("AND s.teacher_id = ?", (teacher_id,)) if teacher_id else ("", ())

    def one(sql, args=()):
        return db.one(sql, args)["n"] or 0

    # ---- conversations and what happened to the questions (qa_history: one row per question answered) ----
    qa = lambda extra="": one(f"SELECT COUNT(*) AS n FROM qa_history q JOIN students s ON s.id = q.student_id "  # noqa: E731
                              f"WHERE q.created_at >= ? {tq} {extra}", (since_txt, *targs))
    questions = qa()
    blocked = qa("AND q.scope IN ('blocked', 'unsafe')")
    care = qa("AND q.scope = 'care'")
    off_topic = qa("AND q.scope = 'off_topic'")
    students = one(f"SELECT COUNT(DISTINCT q.student_id) AS n FROM qa_history q JOIN students s ON s.id = q.student_id "
                   f"WHERE q.created_at >= ? {tq}", (since_txt, *targs))

    # ---- the AI's own answers that the safety check stopped (A2 output stage) ----
    ev_t = "AND e.teacher_id = ?" if teacher_id else ""
    ev = lambda extra: one(f"SELECT COUNT(*) AS n FROM safety_events e WHERE e.at >= ? {ev_t} {extra}",  # noqa: E731
                           (since, *targs))
    ai_tried = ev("AND e.stage = 'output' AND e.action = 'replaced'")
    check_failed = ev("AND e.action = 'retry'")
    reported = 0   # filled by the review center (B4): unsafe answers someone reported after they reached a student

    # ---- students: flags, blocks, unblocks ----
    flagged = one(f"SELECT COUNT(*) AS n FROM student_violations v JOIN students s ON s.id = v.student_id "
                  f"WHERE v.at >= ? {tq}", (since, *targs))
    log = lambda extra: one(f"SELECT COUNT(*) AS n FROM student_status_log l JOIN students s ON s.id = l.student_id "  # noqa: E731
                            f"WHERE l.at >= ? {tq} {extra}", (since, *targs))
    auto_blocks = log("AND l.by_who = 'auto' AND l.new_status IN ('suspended', 'review')")
    admin_blocks = log("AND l.by_who NOT IN ('auto', 'system') AND l.new_status IN ('suspended', 'review', 'disabled')")
    unblocks = log("AND l.by_who NOT IN ('auto', 'system') AND l.new_status = 'active'")
    warnings = log("AND l.new_status = 'warning'")
    review_pending = one(f"SELECT COUNT(*) AS n FROM students s WHERE s.status = 'review' {tq}", targs)

    # ---- category-wise: everything stopped on the way in, plus AI answers stopped ----
    cats: dict[str, dict] = {}
    for r in db.all(f"SELECT v.category AS c, v.severity AS sev, COUNT(*) AS n FROM student_violations v "
                    f"JOIN students s ON s.id = v.student_id WHERE v.at >= ? {tq} GROUP BY v.category, v.severity",
                    (since, *targs)):
        d = cats.setdefault(_label(r["c"]), {"students": 0, "serious": 0, "ai": 0})
        d["students"] += r["n"]
        d["serious"] += r["n"] if r["sev"] == "serious" else 0
    for r in db.all(f"SELECT e.category AS c, e.stage AS st, e.action AS a, COUNT(*) AS n FROM safety_events e "
                    f"WHERE e.at >= ? {ev_t} AND (e.stage = 'output' AND e.action = 'replaced' OR e.action = 'care_reply') "
                    f"GROUP BY e.category, e.stage, e.action", (since, *targs)):
        d = cats.setdefault(_label(r["c"]), {"students": 0, "serious": 0, "ai": 0})
        if r["st"] == "output":
            d["ai"] += r["n"]
        else:
            d["students"] += r["n"]
    categories = sorted(({"label": k, **v, "total": v["students"] + v["ai"]} for k, v in cats.items()),
                        key=lambda x: -x["total"])

    # ---- AI-model-wise ----
    models: dict[str, dict] = {}
    for r in db.all(f"SELECT COALESCE(q.model, 'before sealing') AS m, COUNT(*) AS n FROM qa_history q "
                    f"JOIN students s ON s.id = q.student_id WHERE q.created_at >= ? {tq} AND q.model NOT LIKE 'none%' "
                    f"GROUP BY m", (since_txt, *targs)):
        models.setdefault(r["m"], {"answers": 0, "stopped": 0})["answers"] += r["n"]
    for r in db.all(f"SELECT COALESCE(e.answer_model, 'unknown') AS m, COUNT(*) AS n FROM safety_events e "
                    f"WHERE e.at >= ? {ev_t} AND e.stage = 'output' AND e.action = 'replaced' GROUP BY m", (since, *targs)):
        models.setdefault(r["m"], {"answers": 0, "stopped": 0})["stopped"] += r["n"]
    model_rows = sorted(({"model": k, **v, "tried": v["stopped"]} for k, v in models.items()),
                        key=lambda x: -(x["answers"] + x["stopped"]))

    # ---- date-wise ----
    daily = {(datetime.fromtimestamp(since, timezone.utc) + timedelta(days=i)).strftime("%Y-%m-%d"):
             {"questions": 0, "blocked": 0, "ai_stopped": 0} for i in range(days)}
    for r in db.all(f"SELECT substr(q.created_at, 1, 10) AS d, COUNT(*) AS n, "
                    f"SUM(CASE WHEN q.scope IN ('blocked', 'unsafe') THEN 1 ELSE 0 END) AS b FROM qa_history q "
                    f"JOIN students s ON s.id = q.student_id WHERE q.created_at >= ? {tq} GROUP BY d", (since_txt, *targs)):
        if r["d"] in daily:
            daily[r["d"]].update(questions=r["n"], blocked=r["b"] or 0)
    for r in db.all(f"SELECT e.at FROM safety_events e WHERE e.at >= ? {ev_t} AND e.stage = 'output' "
                    f"AND e.action = 'replaced'", (since, *targs)):
        d = _day(r["at"])
        if d in daily:
            daily[d]["ai_stopped"] += 1

    last = db.one("SELECT at, passed, total, failed, groups FROM safety_test_runs WHERE mode = 'live' "
                  "ORDER BY at DESC LIMIT 1")
    tests = {"at": last["at"], "passed": bool(last["passed"]), "total": last["total"], "failed": last["failed"],
             "groups": json.loads(last["groups"] or "{}")} if last else None

    return {
        "days": days, "teacher_id": teacher_id,
        "conversations": {"questions": questions, "students": students, "blocked": blocked, "care": care,
                          "off_topic": off_topic},
        "ai": {"tried": ai_tried + reported, "stopped": ai_tried, "reported_failures": reported,
               "check_failed": check_failed},
        "students": {"flagged": flagged, "warnings": warnings, "auto_blocks": auto_blocks, "admin_blocks": admin_blocks,
                     "unblocks": unblocks, "review_pending": review_pending},
        "categories": categories, "models": model_rows,
        "daily": [{"day": k, **v} for k, v in daily.items()],
        "tests": tests,
        "teachers": [dict(r) for r in db.all("SELECT id, name FROM teachers ORDER BY name")],
    }
