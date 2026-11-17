"""B6 · Data protection: retention (old data deleted by itself), delete-my-data, daily encrypted backups.

Encryption at rest is done for the whole database (db.py, DB_ENCRYPTION_KEY), so backups are encrypted too.

What is kept, and why (needs a lawyer's check under India's DPDP Act):
  conversations (questions + answers), tests, class sessions   → `conversation_months` (default 12), then deleted
  safety records (flagged messages, safety events, closed cases) → `safety_months` (default 36), then deleted
  parent consents, payments, audit log                          → kept (proof / tax / legal duties)
  answers a safety case points to, a student's own saved notes  → kept while the case / account exists

Delete-my-data (student in the app or by saying it to Sir; or an admin on a parent's request): learning data is
deleted at once (questions, answers, notes + PDFs, tests, sessions, level, name, class) and the account is made
anonymous (no phone, no parent number) and closed. Payments, consents and safety records stay for the legal reasons
above, linked only to the anonymous account.

A5 seals: a deleted answer leaves only its seal (no text) so the chain of the remaining answers still verifies.
"""
import glob
import json
import os
import shutil
import time
from datetime import datetime, timedelta, timezone

from ..db import Database

DEFAULT_DATA = {"conversation_months": 12, "safety_months": 36, "backup_keep": 14}


class DataError(Exception):
    pass


def data_settings(admin_settings: dict) -> dict:
    out = dict(DEFAULT_DATA)
    for k, v in (admin_settings.get("data") or {}).items():
        if k in out:
            try:
                out[k] = max(1, int(v))
            except (TypeError, ValueError):
                pass
    return out


def validate(values: dict) -> dict:
    out = {}
    for k, v in (values or {}).items():
        try:
            n = int(v)
            ok = n >= 1 and float(v) == n
        except (TypeError, ValueError):
            ok = False
        if not ok:
            raise DataError("Data-keeping periods must be whole numbers, 1 or more")
        out[k] = n
    if out.get("safety_months", 36) < out.get("conversation_months", 12):
        raise DataError("Safety records must be kept at least as long as conversations")
    return out


def _cutoff(months: int, now: float) -> tuple[float, str]:
    dt = datetime.fromtimestamp(now, timezone.utc) - timedelta(days=round(months * 30.44))
    return dt.timestamp(), dt.strftime("%Y-%m-%d %H:%M:%S")


def _job(db: Database, kind: str, details: dict, now: float) -> None:
    db.execute("INSERT INTO data_jobs (kind, at, details) VALUES (?, ?, ?)", (kind, now, json.dumps(details)))


def _delete_answers(db: Database, where: str, args: tuple) -> int:
    """Delete answer rows, leaving their A5 seal behind (no text) so the seal chain still checks out."""
    db.execute(f"INSERT OR IGNORE INTO retention_tombstones (record_hash, deleted_at) "
               f"SELECT record_hash, ? FROM qa_history WHERE record_hash IS NOT NULL AND {where}", (time.time(), *args))
    before = db.one(f"SELECT COUNT(*) AS n FROM qa_history WHERE {where}", args)["n"]
    db.execute(f"DELETE FROM qa_history WHERE {where}", args)
    return before


KEEP_ANSWER = ("id NOT IN (SELECT qa_id FROM saved_notes WHERE qa_id IS NOT NULL) "
               "AND id NOT IN (SELECT qa_id FROM incidents WHERE qa_id IS NOT NULL)")


def run_retention(db: Database, admin_settings: dict, now: float | None = None) -> dict:
    now = now or time.time()
    ds = data_settings(admin_settings)
    conv_ts, conv_txt = _cutoff(ds["conversation_months"], now)
    safe_ts, _ = _cutoff(ds["safety_months"], now)
    out = {
        "answers": _delete_answers(db, f"created_at < ? AND {KEEP_ANSWER}", (conv_txt,)),
        "tests": db.execute("DELETE FROM tests WHERE created_at < ?", (conv_txt,)).rowcount,
        "class_sessions": db.execute(
            "DELETE FROM class_sessions WHERE last_at < ? AND id NOT IN (SELECT session_id FROM qa_history WHERE "
            "session_id IS NOT NULL) AND id NOT IN (SELECT session_id FROM saved_notes WHERE session_id IS NOT NULL)",
            (conv_ts,)).rowcount,
        "safety_events": db.execute("DELETE FROM safety_events WHERE at < ?", (safe_ts,)).rowcount,
        "flagged_messages": db.execute("DELETE FROM student_violations WHERE at < ?", (safe_ts,)).rowcount,
        "closed_cases": 0,
        "safety_check_memory": db.execute("DELETE FROM moderation_cache WHERE at < ?", (now - 30 * 86400,)).rowcount,
    }
    old_cases = [r["id"] for r in db.all("SELECT id FROM incidents WHERE status = 'resolved' AND resolved_at < ?", (safe_ts,))]
    for iid in old_cases:
        db.execute("DELETE FROM incident_notes WHERE incident_id = ?", (iid,))
        db.execute("DELETE FROM incidents WHERE id = ?", (iid,))
    out["closed_cases"] = len(old_cases)
    _job(db, "retention", {**out, "conversation_months": ds["conversation_months"], "safety_months": ds["safety_months"]}, now)
    return out


def delete_student(db: Database, student_id: int, by: str, reason: str, notes_dir: str = "") -> dict:
    """Delete-my-data. Learning data goes now; the account becomes anonymous and closed."""
    st = db.one("SELECT id, phone, teacher_id FROM students WHERE id = ?", (student_id,))
    if st is None:
        raise KeyError(student_id)
    if (st["phone"] or "").startswith("deleted:"):
        raise DataError("This account's data was already deleted")
    out = {}
    pdfs = [r["pdf_path"] for r in db.all("SELECT pdf_path FROM saved_notes WHERE student_id = ?", (student_id,))]
    out["notes"] = db.execute("DELETE FROM saved_notes WHERE student_id = ?", (student_id,)).rowcount
    for p in pdfs:
        try:
            full = p if os.path.isabs(p) else os.path.join(notes_dir, os.path.basename(p))
            if os.path.exists(full):
                os.remove(full)
        except OSError:
            pass
    out["answers"] = _delete_answers(db, "student_id = ? AND id NOT IN (SELECT qa_id FROM incidents WHERE qa_id IS NOT NULL)",
                                     (student_id,))
    out["tests"] = db.execute("DELETE FROM tests WHERE student_id = ?", (student_id,)).rowcount
    out["class_sessions"] = db.execute(
        "DELETE FROM class_sessions WHERE student_id = ? AND id NOT IN (SELECT session_id FROM qa_history WHERE "
        "session_id IS NOT NULL)", (student_id,)).rowcount
    db.execute("DELETE FROM otp_codes WHERE phone = ?", (st["phone"],))
    db.execute("UPDATE students SET phone = ?, name = NULL, parent_phone = NULL, class_level = NULL, is_adult = NULL, "
               "status = 'disabled', status_reason = 'Data deleted on request', status_until = NULL WHERE id = ?",
               (f"deleted:{student_id}", student_id))
    db.execute("INSERT INTO data_requests (student_id, teacher_id, kind, requested_by, reason, done_at, details) "
               "VALUES (?, ?, 'delete', ?, ?, ?, ?)", (student_id, st["teacher_id"], by, (reason or "")[:300], time.time(),
                                                       json.dumps(out)))
    return out


# ---------- backups ----------

def backup_now(db: Database, backup_dir: str, keep: int, now: float | None = None) -> dict:
    now = now or time.time()
    os.makedirs(backup_dir, exist_ok=True)
    name = "liveteach-" + datetime.fromtimestamp(now, timezone.utc).strftime("%Y%m%d-%H%M%S") + ".db"
    path = os.path.join(backup_dir, name)
    db.backup_to(path)
    files = sorted(glob.glob(os.path.join(backup_dir, "liveteach-*.db")))
    for old in files[:-keep] if keep > 0 else []:
        os.remove(old)
    info = {"file": name, "bytes": os.path.getsize(path), "encrypted": db.encrypted}
    _job(db, "backup", info, now)
    return info


def list_backups(backup_dir: str) -> list[dict]:
    out = []
    for p in sorted(glob.glob(os.path.join(backup_dir, "liveteach-*.db")), reverse=True):
        out.append({"file": os.path.basename(p), "bytes": os.path.getsize(p), "at": os.path.getmtime(p)})
    return out


# ---------- B9: restore (bring data back from a backup) ----------

RESTORE_TABLES = ("students", "teachers", "qa_history", "parent_consents", "payments", "admin_audit", "incidents",
                  "policy_versions")


def backup_path(backup_dir: str, name: str) -> str:
    """Only a file the server made (liveteach-….db in the backup folder) — never a path from outside."""
    base = os.path.basename(name or "")
    if base != name or not base.startswith("liveteach-") or not base.endswith(".db"):
        raise DataError("Unknown backup file")
    path = os.path.join(backup_dir, base)
    if not os.path.isfile(path):
        raise DataError("Backup file not found")
    return path


def check_backup(path: str, key: str | None, audit_secret: str = "") -> dict:
    """Open a COPY of a backup the way a restore would and check it: the key opens it, the file is not damaged,
    the main tables are there with their rows, and the audit log's seal chain is unbroken. The backup itself and
    the live database are not touched."""
    from ..db import connect
    tmp = path + ".restore-test"
    shutil.copyfile(path, tmp)
    out = {"file": os.path.basename(path), "ok": False, "problems": [], "rows": {}}
    conn = None
    try:
        try:
            conn = connect(tmp, key)
        except Exception as exc:
            out["problems"].append(f"Could not open the backup: {exc}")
            return out
        try:
            ic = conn.execute("PRAGMA integrity_check").fetchone()[0]
        except Exception as exc:   # wrong key or not a database at all
            out["problems"].append(f"Could not read the backup (wrong key or damaged file): {exc}")
            return out
        if ic != "ok":
            out["problems"].append(f"File is damaged: {ic}")
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        for tname in RESTORE_TABLES:
            if tname not in tables:
                out["problems"].append(f"Table missing: {tname}")
                continue
            out["rows"][tname] = conn.execute(f"SELECT COUNT(*) FROM {tname}").fetchone()[0]
        if audit_secret and "admin_audit" in tables:
            from .audit import check_audit_chain

            class _One:   # the few calls check_audit_chain needs
                def all(self, sql, args=()):
                    return conn.execute(sql, args).fetchall()

            chain = check_audit_chain(_One(), audit_secret)
            out["audit_chain"] = chain
            if not chain.get("ok"):
                out["problems"].append("Audit log seal chain is broken in the backup")
        out["ok"] = not out["problems"]
        return out
    finally:
        if conn is not None:
            conn.close()
        for extra in (tmp, tmp + "-wal", tmp + "-shm", tmp + "-journal"):
            if os.path.exists(extra):
                os.remove(extra)


def restore_test(db: Database, backup_dir: str, key: str | None, audit_secret: str = "", name: str = "",
                 now: float | None = None) -> dict:
    """Test-restore one backup (default: the newest) and record the result. A failure raises an alert."""
    now = now or time.time()
    files = list_backups(backup_dir)
    if not name:
        if not files:
            raise DataError("No backup yet — make one first")
        name = files[0]["file"]
    result = check_backup(backup_path(backup_dir, name), key, audit_secret)
    _job(db, "restore_test", result, now)
    if not result["ok"]:
        from . import alerts
        alerts.raise_alert(db, "backup_bad", "high", "A backup failed its restore test",
                           "The backup could not be restored cleanly. Make a new backup and check the server.",
                           "#/data", f"backup_bad:{name}", now=now)
    return result


def restore_apply(database_path: str, backup_file: str, key: str | None) -> str:
    """Replace the database with a backup (server must be STOPPED). The current database is kept next to it first.
    Returns the path of that safety copy. Used by `python -m app.restore apply …` (see docs/backup-restore.md)."""
    check = check_backup(backup_file, key)
    if not check["ok"]:
        raise DataError("This backup did not pass the check: " + "; ".join(check["problems"]))
    keep = ""
    if os.path.exists(database_path):
        keep = database_path + ".before-restore-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        shutil.copyfile(database_path, keep)
    for extra in (database_path + "-wal", database_path + "-shm"):
        if os.path.exists(extra):
            os.remove(extra)
    shutil.copyfile(backup_file, database_path)
    return keep


def last_job(db: Database, kind: str):
    r = db.one("SELECT at, details FROM data_jobs WHERE kind = ? ORDER BY at DESC LIMIT 1", (kind,))
    return {"at": r["at"], **json.loads(r["details"] or "{}")} if r else None


def daily(db: Database, admin_settings_fn, backup_dir: str, now: float | None = None, key: str | None = None,
          audit_secret: str = "") -> list[str]:
    """Called every hour by the server: does what is due (backup, clean-up) once a day; a restore test of the newest
    backup once a week (B9), so a backup is known to work before it is ever needed."""
    now = now or time.time()
    done = []
    for kind, fn, every in (
            ("backup", lambda: backup_now(db, backup_dir, data_settings(admin_settings_fn())["backup_keep"], now), 23.5),
            ("retention", lambda: run_retention(db, admin_settings_fn(), now), 23.5),
            ("restore_test", lambda: restore_test(db, backup_dir, key if key is not None else db._key, audit_secret,
                                                  now=now), 7 * 24 - 0.5)):
        last = last_job(db, kind)
        if not last or now - last["at"] >= every * 3600:
            fn()
            done.append(kind)
    return done


def requests_log(db: Database, limit: int = 50) -> list[dict]:
    return [{**dict(r), "details": json.loads(r["details"] or "{}")} for r in db.all(
        "SELECT * FROM data_requests ORDER BY done_at DESC LIMIT ?", (limit,))]
