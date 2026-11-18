"""B8 · Safety policy versions: every change of the safety rules is a numbered version (who, when, why), any two
versions can be compared, and an earlier version — ideally one the safety tests verified — can be brought back.

The safety policy = these admin settings: topics Sir must not answer and trusted sites (ai), the warnings ladder
(safety), rate limits (limits), age-group rules (age_groups) and the lowest class (students); since B9 also the
content filters, the messages students see and parent SMS settings (filters, messages, parents) once changed.
A version is "verified" when a live safety-test run (A8) passed while it was the current version.
Rolling back writes the old rules as a new version ("Rolled back to v3"), so the history is never rewritten.
"""
import hashlib
import json
import time

from ..db import Database

POLICY_SECTIONS = ("ai", "safety", "limits", "age_groups", "students")

LABELS = {
    "ai.blocked_topics": "Topics Sir must not answer", "ai.trusted_sites": "Trusted websites",
    "safety.auto_block": "Auto-block", "safety.minor_warn": "Blocked topics in 7 days → warning",
    "safety.minor_suspend": "Blocked topics in 7 days → suspension", "safety.serious_suspend": "Serious requests → suspension",
    "safety.serious_review": "Serious requests → stopped for review", "safety.suspend_hours": "Suspension length (hours)",
    "limits.questions_per_minute": "Questions per minute", "limits.questions_per_day": "Questions per day", "limits.photos_per_day": "Photo questions per day", "limits.requests_per_ip_minute": "Requests per minute per IP",
    "limits.otp_per_phone_10min": "Codes per number in 10 min", "limits.otp_per_phone_day": "Codes per number per day",
    "limits.otp_gap_seconds": "Seconds between two codes", "limits.otp_per_device_day": "Codes per device per day",
    "limits.otp_per_ip_hour": "Codes per internet address per hour",
    "limits.otp_wrong_per_phone_day": "Wrong codes before a number is locked", "students.min_class": "Lowest class allowed",
}
MESSAGE_NAMES = {
    "safety_refusal": "Harmful request refused", "redirect_study": "Blocked topic / off-topic", "safety_replaced": "AI answer stopped",
    "safety_warning": "Warning", "safety_suspended": "Suspended", "safety_review": "Stopped for review",
    "safety_disabled": "Account disabled", "care_message": "Upset student (helpline)",
}
GROUP_NAMES = {"primary": "Class 1–5", "junior": "Class 6–8", "middle": "Class 9–10", "senior": "Class 11–12", "adult": "18+"}


# B9 sections: only part of a version once changed from the defaults (older versions keep their fingerprint)
OPTIONAL_SECTIONS = ("filters", "messages", "parents")


def _defaults() -> dict:
    from .admin import DEFAULT_SETTINGS
    return DEFAULT_SETTINGS


def snapshot(settings: dict) -> dict:
    snap = {s: settings.get(s) for s in POLICY_SECTIONS}
    d = _defaults()
    for s in OPTIONAL_SECTIONS:
        if settings.get(s) is not None and settings.get(s) != d[s]:
            snap[s] = settings.get(s)
    return snap


def rules_to_restore(snap: dict) -> dict:
    """An old version's rules as settings to save: B9 sections it doesn't have go back to their defaults."""
    import copy
    out = copy.deepcopy(snap)
    for s in OPTIONAL_SECTIONS:
        out.setdefault(s, copy.deepcopy(_defaults()[s]))
    return out


def fingerprint(snap: dict) -> str:
    return hashlib.sha256(json.dumps(snap, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def _flat(d, prefix="") -> dict:
    out = {}
    for k, v in (d or {}).items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(_flat(v, key + "."))
        else:
            out[key] = v
    return out


def label(key: str) -> str:
    if key in LABELS:
        return LABELS[key]
    parts = key.split(".")
    if parts[0] == "filters" and len(parts) == 3:
        from .content_filters import FILTERS
        what = {"on": "on/off", "level": "strictness", "severity": "counts as", "review": "human review"}.get(parts[2], parts[2])
        return f"Filter “{FILTERS.get(parts[1], parts[1])}”: {what}"
    if parts[0] == "messages" and len(parts) == 3:
        return f"Message “{MESSAGE_NAMES.get(parts[1], parts[1])}” ({parts[2]})"
    if parts[0] == "parents" and len(parts) == 2:
        return {"notify_block": "SMS to parent when a student is blocked", "notify_care": "SMS to parent when a student seems upset",
                "language": "Parent SMS language"}.get(parts[1], key)
    if parts[0] == "age_groups" and len(parts) == 3:
        what = {"strictness": "strictness", "blocked_topics": "extra topics Sir must not answer"}.get(parts[2], parts[2])
        return f"{GROUP_NAMES.get(parts[1], parts[1])}: {what}"
    return key


def diff(old: dict, new: dict) -> list[dict]:
    a, b = _flat(old), _flat(new)
    out = []
    for key in sorted(set(a) | set(b)):
        if a.get(key) == b.get(key):
            continue
        row = {"key": key, "label": label(key), "old": a.get(key), "new": b.get(key)}
        if isinstance(a.get(key), list) or isinstance(b.get(key), list):
            oa, nb = list(a.get(key) or []), list(b.get(key) or [])
            row["added"] = [x for x in nb if x not in oa]
            row["removed"] = [x for x in oa if x not in nb]
        out.append(row)
    return out


def _latest(db: Database):
    return db.one("SELECT * FROM policy_versions ORDER BY id DESC LIMIT 1")


def ensure_initial(db: Database, settings: dict) -> None:
    if _latest(db) is None:
        snap = snapshot(settings)
        db.execute("INSERT INTO policy_versions (created_at, created_by, note, rules, fingerprint) VALUES (?, ?, ?, ?, ?)",
                   (time.time(), "system", "First version (the rules in place when versions started)",
                    json.dumps(snap, ensure_ascii=False), fingerprint(snap)))


def record_if_changed(db: Database, settings: dict, by: str, note: str = "", rolled_back_from: int | None = None) -> int | None:
    """Called after every settings save: a new version only when the safety rules really changed."""
    ensure_initial(db, settings)
    snap = snapshot(settings)
    fp = fingerprint(snap)
    last = _latest(db)
    if last and last["fingerprint"] == fp and rolled_back_from is None:
        return None
    cur = db.execute("INSERT INTO policy_versions (created_at, created_by, note, rules, fingerprint, rolled_back_from) "
                     "VALUES (?, ?, ?, ?, ?, ?)", (time.time(), by, (note or "").strip()[:500] or "(no note)",
                                                   json.dumps(snap, ensure_ascii=False), fp, rolled_back_from))
    return cur.lastrowid


def mark_verified(db: Database, settings: dict, run_id: int) -> None:
    """A live safety-test run passed: the current version is verified."""
    ensure_initial(db, settings)
    last = _latest(db)
    if last and last["fingerprint"] == fingerprint(snapshot(settings)) and not last["verified_run"]:
        db.execute("UPDATE policy_versions SET verified_run = ?, verified_at = ? WHERE id = ?", (run_id, time.time(), last["id"]))


def _row(r) -> dict:
    d = dict(r)
    d["rules"] = json.loads(d["rules"])
    return d


def versions(db: Database, settings: dict) -> dict:
    ensure_initial(db, settings)
    rows = [_row(r) for r in db.all("SELECT * FROM policy_versions ORDER BY id DESC")]
    for i, r in enumerate(rows):
        prev = rows[i + 1]["rules"] if i + 1 < len(rows) else None
        r["changes"] = len(diff(prev, r["rules"])) if prev is not None else None
        r["current"] = i == 0
        r.pop("rules")
    return {"items": rows, "current": rows[0]["id"] if rows else None}


def get(db: Database, vid: int) -> dict:
    r = db.one("SELECT * FROM policy_versions WHERE id = ?", (vid,))
    if r is None:
        raise KeyError(vid)
    return _row(r)


def compare(db: Database, a: int, b: int) -> dict:
    va, vb = get(db, a), get(db, b)
    return {"a": {k: va[k] for k in ("id", "created_at", "created_by", "note")},
            "b": {k: vb[k] for k in ("id", "created_at", "created_by", "note")},
            "changes": diff(va["rules"], vb["rules"])}


def number_for(db: Database, settings_fp: str) -> int | None:
    r = db.one("SELECT id FROM policy_versions WHERE fingerprint = ? ORDER BY id DESC LIMIT 1", (settings_fp,))
    return r["id"] if r else None
