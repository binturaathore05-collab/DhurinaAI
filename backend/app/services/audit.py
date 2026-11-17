"""A5 · Proof of what the AI really said, and who changed what in the admin / teacher panels.

Answers: every answer row is stamped with the AI model that wrote it, the safety-policy version in force, and a
tamper-evident seal (HMAC over the delivered text + time + class session + the previous seal, so the records form a
chain). Each answer also gets a short reference code (LT-XXXX-XXXX) shown under it in the app. If a recording goes
viral, an admin pastes the code (or searches the words) in admin → Audit and sees the genuine record, and whether it
was changed in the database since.

Admin audit log: every change made in the admin panel or a teacher dashboard (and every look at a student's flagged
messages) is recorded — who, when, from where, what — in a chained, append-only log. Secrets are never stored.
"""
import base64
import contextvars
import hashlib
import hmac
import json
import re
import time

from ..db import Database

GENESIS = "genesis"
# which AI model wrote the reply in this request (set by the model router)
used_model: contextvars.ContextVar[str] = contextvars.ContextVar("used_model", default="")


def _mac(secret: str, text: str) -> str:
    return hmac.new(secret.encode(), text.encode(), hashlib.sha256).hexdigest()


# ---------- safety-policy version ----------

def policy_version(db: Database, base: str, admin_settings: dict) -> str:
    """The base policy name + a short fingerprint of the admin's AI and safety settings at this moment.
    Every distinct set of rules is kept, so a verification can show exactly which rules applied."""
    rules = {k: admin_settings.get(k) for k in ("ai", "safety", "limits", "age_groups")}
    from .admin import DEFAULT_SETTINGS   # B9: filters count once changed (older fingerprints stay the same)
    if admin_settings.get("filters") not in (None, DEFAULT_SETTINGS["filters"]):
        rules["filters"] = admin_settings["filters"]
    blob = json.dumps(rules, sort_keys=True, ensure_ascii=False)
    version = f"{base}+{hashlib.sha256(blob.encode()).hexdigest()[:8]}"
    db.execute("INSERT OR IGNORE INTO policy_snapshots (version, rules, first_seen) VALUES (?, ?, ?)",
               (version, blob, time.time()))
    return version


# ---------- answers ----------

def _canonical(r, model: str, policy: str, prev: str) -> str:
    return json.dumps([r["id"], r["student_id"], r["session_id"], r["question"], r["answer"], r["follow_up"] or "",
                       r["origin"], r["created_at"], model, policy, prev], ensure_ascii=False)


def verify_code(secret: str, qa_id: int) -> str:
    raw = base64.b32encode(bytes.fromhex(_mac(secret, f"code|{qa_id}"))[:5]).decode()   # 8 letters/digits
    return f"LT-{raw[:4]}-{raw[4:8]}"


def stamp_answer(db: Database, secret: str, qa_id: int, model: str, policy: str) -> str:
    """Seal one answer row (once). Returns its reference code."""
    with db.tx() as conn:
        r = conn.execute("SELECT * FROM qa_history WHERE id = ?", (qa_id,)).fetchone()
        if r is None:
            raise KeyError(qa_id)
        if r["record_hash"]:
            return r["verify_code"]
        last = conn.execute("SELECT record_hash FROM qa_history WHERE record_hash IS NOT NULL "
                            "ORDER BY sealed_at DESC, id DESC LIMIT 1").fetchone()
        prev = last["record_hash"] if last else GENESIS
        seal = _mac(secret, _canonical(r, model, policy, prev))
        code = verify_code(secret, qa_id)
        conn.execute("UPDATE qa_history SET model = ?, policy_version = ?, prev_hash = ?, record_hash = ?, "
                     "verify_code = ?, sealed_at = ? WHERE id = ?", (model, policy, prev, seal, code, time.time(), qa_id))
    return code


def _norm_code(text: str) -> str | None:
    t = re.sub(r"[^A-Z0-9]", "", (text or "").upper())
    if t.startswith("LT"):
        t = t[2:]
    return f"LT-{t[:4]}-{t[4:8]}" if len(t) == 8 else None


def check_record(db: Database, secret: str, r) -> dict:
    if not r["record_hash"]:
        return {"sealed": False, "untouched": None, "chain_ok": None}
    untouched = hmac.compare_digest(r["record_hash"], _mac(secret, _canonical(r, r["model"], r["policy_version"],
                                                                                r["prev_hash"])))
    chain_ok = r["prev_hash"] == GENESIS or db.one("SELECT 1 FROM qa_history WHERE record_hash = ?",
                                                   (r["prev_hash"],)) is not None \
        or db.one("SELECT 1 FROM retention_tombstones WHERE record_hash = ?", (r["prev_hash"],)) is not None
    return {"sealed": True, "untouched": untouched, "chain_ok": chain_ok}


def _mask(phone: str | None) -> str:
    return (phone[:3] + "•••••" + phone[-3:]) if phone and len(phone) > 6 else (phone or "")


def find(db: Database, secret: str, query: str, limit: int = 20) -> dict:
    """Look up a reported interaction by its reference code, or by words from the question / answer."""
    query = (query or "").strip()
    if not query:
        return {"items": [], "by": None}
    code = _norm_code(query)
    sql = ("SELECT q.*, s.phone, s.name AS student_name, s.teacher_id, t.name AS teacher_name FROM qa_history q "
           "JOIN students s ON s.id = q.student_id JOIN teachers t ON t.id = s.teacher_id ")
    rows = db.all(sql + "WHERE q.verify_code = ?", (code,)) if code else []
    by = "code"
    if not rows:
        like = f"%{query[:200]}%"
        rows = db.all(sql + "WHERE q.question LIKE ? OR q.answer LIKE ? ORDER BY q.id DESC LIMIT ?", (like, like, limit))
        by = "text"
    items = []
    for r in rows:
        snap = db.one("SELECT rules FROM policy_snapshots WHERE version = ?", (r["policy_version"],)) if r["policy_version"] else None
        items.append({"id": r["id"], "code": r["verify_code"], "at": r["created_at"], "session_id": r["session_id"],
                      "teacher": r["teacher_name"], "student": r["student_name"] or "", "phone": _mask(r["phone"]),
                      "student_id": r["student_id"], "question": r["question"], "answer": r["answer"],
                      "follow_up": r["follow_up"], "origin": r["origin"], "scope": r["scope"],
                      "model": r["model"], "policy_version": r["policy_version"],
                      "policy_rules": json.loads(snap["rules"]) if snap else None, **check_record(db, secret, r)})
    return {"items": items, "by": by}


# ---------- admin / teacher audit log ----------

SECRET_NAMES = {"code", "otp", "token", "pin"}
SECRET_PARTS = ("password", "secret", "api_key", "apikey", "private")


def _is_secret(name: str) -> bool:
    n = name.lower()
    return n in SECRET_NAMES or any(p in n for p in SECRET_PARTS)


def _redact(value):
    if isinstance(value, dict):
        return {k: ("•••" if _is_secret(k) and v not in (None, "") else
                    f"(file, {len(v)} chars)" if k.endswith("_base64") and isinstance(v, str) else _redact(v))
                for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v) for v in value[:50]]
    if isinstance(value, str):
        return value[:500]
    return value


def details_from_body(body: bytes) -> str:
    if not body:
        return ""
    try:
        data = json.loads(body)
    except Exception:
        return f"({len(body)} bytes)"
    return json.dumps(_redact(data), ensure_ascii=False)[:4000]


def log_action(db: Database, secret: str, who: str, role: str, method: str, path: str, status: int, ip: str,
               details: str = "", now: float | None = None) -> None:
    now = now or time.time()
    with db.tx() as conn:
        last = conn.execute("SELECT hash FROM admin_audit ORDER BY id DESC LIMIT 1").fetchone()
        prev = last["hash"] if last else GENESIS
        h = _mac(secret, json.dumps([now, who, role, method, path, status, ip, details, prev], ensure_ascii=False))
        conn.execute("INSERT INTO admin_audit (at, who, role, method, path, status, ip, details, prev_hash, hash) "
                     "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (now, who, role, method, path, status, ip, details, prev, h))


def describe(method: str, path: str) -> str:
    """Plain words for the log."""
    rules = [
        (r"^POST /admin/api/login$", "Logged in to admin"), (r"^POST /admin/api/password$", "Changed own password"),
        (r"^POST /admin/api/teachers$", "Added a teacher"), (r"^PUT /admin/api/teachers/([^/]+)$", "Edited teacher {0}"),
        (r"^POST /admin/api/teachers/([^/]+)/checklist$", "Updated launch checklist of {0}"),
        (r"^POST /admin/api/teachers/([^/]+)/build$", "Started an app build for {0}"),
        (r"^PUT /admin/api/settings$", "Changed platform settings"),
        (r"^POST /admin/api/emergency$", "Used an emergency switch"),
        (r"^POST /admin/api/students/(\d+)/status$", "Changed status of student {0}"),
        (r"^GET /admin/api/students/(\d+)$", "Viewed flagged messages of student {0}"),
        (r"^GET /admin/api/verify$", "Looked up a reported conversation"),
        (r"^POST /admin/api/alerts/ack$", "Marked alerts as seen"),
        (r"^POST /admin/api/policy/(\d+)/rollback$", "Rolled the safety rules back to v{0}"),
        (r"^POST /admin/api/team$", "Added a team member"), (r"^PUT /admin/api/team/(\d+)$", "Changed team member {0}"),
        (r"^POST /admin/api/team/(\d+)/reset$", "Reset the password of team member {0}"),
        (r"^GET /admin/api/incidents/(\d+)$", "Opened review case {0}"),
        (r"^POST /admin/api/incidents/flag$", "Flagged a conversation for review"),
        (r"^POST /admin/api/incidents/(\d+)/act$", "Acted on review case {0}"),
        (r"^POST /teacher/documents$", "Teacher uploaded notes"), (r"^PUT /teacher/style$", "Teacher changed teaching style"),
        (r"^POST /teacher/review/(\d+)/approve$", "Teacher reviewed answer {0}"),
        (r"^POST /teacher/review/bulk$", "Teacher reviewed answers in bulk"), (r"^POST /teacher/review/undo$", "Teacher undid a review"),
        (r"^PUT /teacher/verified/(\d+)$", "Teacher edited verified answer {0}"),
    ]
    key = f"{method} {path}"
    for pattern, text in rules:
        m = re.match(pattern, key)
        if m:
            return text.format(*m.groups())
    return key


def audit_log(db: Database, secret: str, q: str = "", offset: int = 0, limit: int = 50) -> dict:
    where, args = "", ()
    if q:
        where, args = "WHERE who LIKE ? OR path LIKE ? OR details LIKE ?", (f"%{q}%",) * 3
    rows = db.all(f"SELECT * FROM admin_audit {where} ORDER BY id DESC LIMIT ? OFFSET ?",
                  (*args, max(1, min(int(limit), 200)), max(int(offset), 0)))
    total = db.one(f"SELECT COUNT(*) AS n FROM admin_audit {where}", args)["n"]
    return {"items": [{**dict(r), "what": describe(r["method"], r["path"])} for r in rows], "total": total}


def check_audit_chain(db: Database, secret: str) -> dict:
    """Walk the whole log: every entry must match its seal and point at the one before it."""
    prev, n = GENESIS, 0
    for r in db.all("SELECT * FROM admin_audit ORDER BY id"):
        expect = _mac(secret, json.dumps([r["at"], r["who"], r["role"], r["method"], r["path"], r["status"], r["ip"],
                                          r["details"], prev], ensure_ascii=False))
        if r["prev_hash"] != prev or not hmac.compare_digest(expect, r["hash"]):
            return {"ok": False, "entries": n, "broken_at": r["id"]}
        prev, n = r["hash"], n + 1
    return {"ok": True, "entries": n, "broken_at": None}
