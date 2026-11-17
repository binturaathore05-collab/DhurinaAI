"""Dhurina admin: add/edit teachers, platform settings, and earnings reports."""
import json
import re
import time

from ..db import Database
from ..secrets_box import mask, seal
from .limits import DEFAULT_LIMITS
from . import student_safety
from . import age_policy
from . import data_protection
from . import alerts
from . import content_filters
from . import parent_notify
from .. import i18n
import copy

CHECKLIST = [
    ("consent", "Teacher consent form signed"),
    ("play_console", "Play Console account (teacher’s own)"),
    ("razorpay", "Razorpay account + Route linked"),
    ("content", "Notes & YouTube connected (teacher dashboard)"),
    ("published", "Closed testing → production"),
]

DEFAULT_SETTINGS = {
    "company": {"name": "Dhurina Ventures Pvt. Ltd.", "address": "", "gstin": "", "pan": "",
                "linked_account": ""},
    "defaults": {"platform_percent": 20, "demo_questions": 3, "grace_days": 2, "grace_questions": 3,
                 "renew_reminder_days": 3},
    "students": {"min_class": 6},    # B1: lowest class allowed at signup
    "age_groups": copy.deepcopy(age_policy.DEFAULT_AGE_GROUPS),   # B2: rules per age group
    "data": dict(data_protection.DEFAULT_DATA),   # B6: how long data is kept, backups kept
    "alerts": dict(alerts.DEFAULT_ALERTS),        # B7: who gets emails, thresholds
    "filters": copy.deepcopy(content_filters.DEFAULT_FILTERS),   # B9: content filters (Safety Center)
    "messages": {k: {} for k in i18n.EDITABLE},   # B9: student messages changed by the admin (blank = default)
    "parents": dict(parent_notify.DEFAULT_PARENTS),   # B9: SMS to parents on block / care
    "limits": dict(DEFAULT_LIMITS),
    "safety": dict(student_safety.DEFAULT_SAFETY),   # A3 warnings ladder (see services/student_safety.py)   # A6 rate limits (see services/limits.py)
    "ai": {"trusted_sites": ["pib.gov.in", "india.gov.in", "ncert.nic.in"],
           "blocked_topics": ["politics", "adult content"]},
    "legal": {"privacy_url": "", "terms_url": ""},
    # Test series: questions per test; below reteach_below % Sir offers to teach again; from praise_from % shabash
    "tests": {"questions": 10, "reteach_below": 50, "praise_from": 80},
}

_ID = re.compile(r"^[a-z][a-z0-9-]{1,30}$")


class AdminError(ValueError):
    pass


# ---------- platform settings ----------

def get_settings(db: Database) -> dict:
    row = db.one("SELECT value FROM platform_settings WHERE key = 'all'")
    saved = json.loads(row["value"]) if row else {}
    out = json.loads(json.dumps(DEFAULT_SETTINGS))
    for section, values in saved.items():
        if section in out and isinstance(values, dict):
            out[section].update(values)
    return out


def save_settings(db: Database, data: dict) -> dict:
    current = get_settings(db)
    for section, values in data.items():
        if section in current and isinstance(values, dict):
            current[section].update({k: v for k, v in values.items() if k in current[section]})
    try:
        current["safety"].update(student_safety.validate_settings(current["safety"]))
    except student_safety.SafetyError as exc:
        raise AdminError(str(exc))
    try:
        current["alerts"].update(alerts.validate(current["alerts"]))
    except ValueError as exc:
        raise AdminError(str(exc))
    try:
        current["data"].update(data_protection.validate(current["data"]))
    except data_protection.DataError as exc:
        raise AdminError(str(exc))
    try:
        current["filters"] = {**current["filters"], **content_filters.validate(current["filters"])}
        current["messages"] = {**current["messages"], **i18n.validate_messages(current["messages"])}
        current["parents"].update(parent_notify.validate(current["parents"]))
    except ValueError as exc:
        raise AdminError(str(exc))
    try:
        current["age_groups"] = age_policy.validate(current["age_groups"])
    except age_policy.AgePolicyError as exc:
        raise AdminError(str(exc))
    try:
        mc = int(current["students"]["min_class"])
        ok = 1 <= mc <= 12 and float(current["students"]["min_class"]) == mc
    except (TypeError, ValueError):
        ok = False
    if not ok:
        raise AdminError("Lowest class must be a whole number from 1 to 12")
    current["students"]["min_class"] = mc
    for k, v in current["limits"].items():
        try:
            ok = int(v) >= 1 and float(v) == int(v)
        except (TypeError, ValueError):
            ok = False
        if not ok:
            raise AdminError("Every limit must be a whole number, 1 or more")
        current["limits"][k] = int(v)
    p = current["defaults"]["platform_percent"]
    if not 0 <= float(p) <= 100:
        raise AdminError("Default split must be between 0 and 100")
    db.execute("INSERT INTO platform_settings (key, value) VALUES ('all', ?) "
               "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (json.dumps(current, ensure_ascii=False),))
    return current


# ---------- teachers ----------

def _play_store(value) -> str:
    from .share import clean_play_store_url
    try:
        return clean_play_store_url(value)
    except ValueError as exc:
        raise AdminError(str(exc))


def _rupees_to_paise(v) -> int:
    try:
        return int(round(float(v) * 100))
    except (TypeError, ValueError):
        raise AdminError("Prices must be numbers")


def save_teacher(db: Database, data: dict, creating: bool) -> dict:
    """Create or update a teacher from the admin form. Secrets left blank keep their old value."""
    tid = str(data.get("id", "")).strip().lower()
    if not _ID.match(tid):
        raise AdminError("Teacher id: lower-case letters, numbers and '-' only, starting with a letter")
    if tid == "common":   # reserved for Dhurina's Common Library (multi-teacher content library)
        raise AdminError("This id is reserved; please choose another")
    exists = db.one("SELECT * FROM teachers WHERE id = ?", (tid,))
    if creating and exists:
        raise AdminError(f"A teacher with id '{tid}' already exists")
    if not creating and not exists:
        raise KeyError(tid)
    name = str(data.get("name", "")).strip()
    if not name:
        raise AdminError("Teacher name is required")
    split = data.get("platform_percent")
    if split is not None and split != "":
        split = float(split)
        if not 0 <= split <= 100:
            raise AdminError("Dhurina share must be between 0 and 100")
    else:
        split = None

    def keep(field, new):  # blank secret = keep the stored one
        return seal(new) if new else (exists[field] if exists else None)

    subjects = data.get("subjects")
    if isinstance(subjects, list):
        subject = ", ".join(dict.fromkeys(x.strip() for x in subjects if str(x).strip()))
    else:
        subject = str(data.get("subject") or "").strip()
    values = {
        "name": name,
        "subject": subject,                 # several subjects stored as "History, Geography, Polity"
        "app_name": data.get("app_name") or f"{name} AI",
        "brand_color": data.get("brand_color") or "#2DD4BF",
        "platform_commission_percent": split,
        "demo_questions": data.get("demo_questions"),
        "grace_days": data.get("grace_days"),
        "grace_questions": data.get("grace_questions"),
        "razorpay_key_id": data.get("razorpay_key_id") or (exists["razorpay_key_id"] if exists else None),
        "razorpay_key_secret": keep("razorpay_key_secret", data.get("razorpay_key_secret")),
        "razorpay_webhook_secret": keep("razorpay_webhook_secret", data.get("razorpay_webhook_secret")),
        "teacher_phone": data.get("teacher_phone") or "",
        "teacher_email": data.get("teacher_email") or "",
        "play_store_url": _play_store(data.get("play_store_url")),
    }
    for k in ("demo_questions", "grace_days", "grace_questions"):
        if values[k] in ("", None):
            values[k] = None
        else:
            values[k] = int(values[k])
    if creating:
        cols = ", ".join(["id", *values])
        db.execute(f"INSERT INTO teachers ({cols}) VALUES ({', '.join('?' * (len(values) + 1))})",
                   (tid, *values.values()))
    else:
        db.execute(f"UPDATE teachers SET {', '.join(f'{k} = ?' for k in values)} WHERE id = ?",
                   (*values.values(), tid))

    for plan_key, name_, days in (("monthly", "Monthly", 30), ("yearly", "Yearly", 365)):
        price = data.get(f"{plan_key}_price")
        if price in (None, ""):
            continue
        pid = f"{tid}-{plan_key}"
        db.execute("INSERT INTO plans (id, teacher_id, name, amount_paise, duration_days) VALUES (?, ?, ?, ?, ?) "
                   "ON CONFLICT(id) DO UPDATE SET amount_paise = excluded.amount_paise, active = 1",
                   (pid, tid, name_, _rupees_to_paise(price), days))
    return teacher_detail(db, tid)


def set_checklist(db: Database, tid: str, item: str, done: bool) -> dict:
    row = db.one("SELECT checklist FROM teachers WHERE id = ?", (tid,))
    if row is None:
        raise KeyError(tid)
    if item not in dict(CHECKLIST):
        raise AdminError("Unknown checklist item")
    state = json.loads(row["checklist"] or "{}")
    state[item] = bool(done)
    status = "live" if state.get("published") else None
    db.execute("UPDATE teachers SET checklist = ?" + (", status = 'live'" if status else "") + " WHERE id = ?",
               (json.dumps(state), tid))
    return teacher_detail(db, tid)


def set_status(db: Database, tid: str, status: str) -> None:
    db.execute("UPDATE teachers SET status = ? WHERE id = ?", (status, tid))


# ---------- reports ----------

def _month_start(now: float) -> float:
    t = time.localtime(now)
    return time.mktime((t.tm_year, t.tm_mon, 1, 0, 0, 0, 0, 0, -1))


def _money(db: Database, tid: str | None, since: float | None, default_percent: float) -> dict:
    where, args = ["p.status = 'paid'"], []
    if tid:
        where.append("pl.teacher_id = ?")
        args.append(tid)
    if since:
        where.append("p.created_at >= datetime(?, 'unixepoch')")
        args.append(since)
    rows = db.all("SELECT p.amount_paise, COALESCE(p.platform_percent, t.platform_commission_percent, ?) AS pct "
                  "FROM payments p JOIN plans pl ON pl.id = p.plan_id JOIN teachers t ON t.id = pl.teacher_id "
                  f"WHERE {' AND '.join(where)}", (default_percent, *args))
    total = sum(r["amount_paise"] for r in rows)
    platform = sum(round(r["amount_paise"] * r["pct"] / 100) for r in rows)
    return {"total_paise": total, "platform_paise": platform, "teacher_paise": total - platform}


def _counts(db: Database, tid: str, now: float) -> dict:
    students = db.one("SELECT COUNT(*) AS n FROM students WHERE teacher_id = ?", (tid,))["n"]
    active = db.one("SELECT COUNT(DISTINCT s.student_id) AS n FROM subscriptions s JOIN students st ON st.id = s.student_id "
                    "WHERE st.teacher_id = ? AND s.starts_at <= ? AND s.ends_at > ?", (tid, now, now))["n"]
    return {"students": students, "active_plans": active}


def list_teachers(db: Database, default_percent: float) -> list[dict]:
    now = time.time()
    out = []
    for t in db.all("SELECT * FROM teachers ORDER BY created_at DESC, id"):
        pct = t["platform_commission_percent"]
        pct = default_percent if pct is None else pct
        out.append({
            "id": t["id"], "name": t["name"], "subject": t["subject"], "status": t["status"],
            "has_avatar": bool(t["avatar_url"]), "platform_percent": pct, "teacher_percent": 100 - pct,
            **_counts(db, t["id"], now),
            "this_month": _money(db, t["id"], _month_start(now), default_percent),
        })
    return out


def overview(db: Database, default_percent: float) -> dict:
    now = time.time()
    return {
        "teachers": db.one("SELECT COUNT(*) AS n FROM teachers")["n"],
        "live": db.one("SELECT COUNT(*) AS n FROM teachers WHERE status = 'live'")["n"],
        "students": db.one("SELECT COUNT(*) AS n FROM students")["n"],
        "active_plans": db.one("SELECT COUNT(DISTINCT student_id) AS n FROM subscriptions WHERE starts_at <= ? AND ends_at > ?",
                               (now, now))["n"],
        "this_month": _money(db, None, _month_start(now), default_percent),
    }


def teacher_detail(db: Database, tid: str, default_percent: float = 20) -> dict:
    t = db.one("SELECT * FROM teachers WHERE id = ?", (tid,))
    if t is None:
        raise KeyError(tid)
    now = time.time()
    pct = t["platform_commission_percent"]
    pct_eff = default_percent if pct is None else pct
    plans = {p["id"].rsplit("-", 1)[-1]: p["amount_paise"] / 100
             for p in db.all("SELECT * FROM plans WHERE teacher_id = ? AND active = 1", (tid,))}
    months = []
    lt = time.localtime(now)
    for back in range(5, -1, -1):
        y, m = lt.tm_year, lt.tm_mon - back
        while m <= 0:
            y, m = y - 1, m + 12
        start = time.mktime((y, m, 1, 0, 0, 0, 0, 0, -1))
        ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
        end = time.mktime((ny, nm, 1, 0, 0, 0, 0, 0, -1))
        rows = db.all("SELECT p.amount_paise FROM payments p JOIN plans pl ON pl.id = p.plan_id WHERE pl.teacher_id = ? "
                      "AND p.status = 'paid' AND p.created_at >= datetime(?, 'unixepoch') AND p.created_at < datetime(?, 'unixepoch')",
                      (tid, start, end))
        months.append({"label": time.strftime("%b", time.localtime(start)), "total_paise": sum(r["amount_paise"] for r in rows)})
    state = json.loads(t["checklist"] or "{}")
    return {
        "id": t["id"], "name": t["name"], "subject": t["subject"], "app_name": t["app_name"],
        "subjects": [x.strip() for x in (t["subject"] or "").split(",") if x.strip()],
        "brand_color": t["brand_color"], "status": t["status"], "has_avatar": bool(t["avatar_url"]),
        "platform_percent": pct, "effective_platform_percent": pct_eff, "teacher_percent": 100 - pct_eff,
        "demo_questions": t["demo_questions"], "grace_days": t["grace_days"], "grace_questions": t["grace_questions"],
        "monthly_price": plans.get("monthly"), "yearly_price": plans.get("yearly"),
        "razorpay_key_id": t["razorpay_key_id"], "razorpay_key_secret": mask(t["razorpay_key_secret"]),
        "razorpay_webhook_secret": mask(t["razorpay_webhook_secret"]),
        "teacher_phone": t["teacher_phone"], "teacher_email": t["teacher_email"],
        "play_store_url": t["play_store_url"] or "",
        "checklist": [{"key": k, "label": label, "done": bool(state.get(k))} for k, label in CHECKLIST],
        **_counts(db, tid, now),
        "this_month": _money(db, tid, _month_start(now), pct_eff),
        "months": months,
    }
