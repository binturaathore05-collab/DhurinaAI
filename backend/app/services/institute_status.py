"""Pause or block a whole institute (Super Admin), e.g. Dhurina's fees unpaid, a complaint, or a broken agreement.

  active    normal
  paused    for a while (optionally until a date, then it ends by itself): Sir's AI stops for its students and no new
            plans can be bought; students keep their notes and library; the institute can still log in to its panel
            (it sees why) and fix things.
  blocked   serious: as paused, plus no new students can sign up, the institute panel is closed and no new app builds.
            Nothing is deleted: everything comes back as it was when it is made active again.

Every change needs a reason, is kept in a history, is in the audit log and raises an alert.
This is separate from Admin → Emergency (a safety switch for the AI only).
"""
import time

from ..db import Database

STATES = ("active", "paused", "blocked")
LABELS = {"active": "Active", "paused": "Paused", "blocked": "Blocked"}


class StatusError(ValueError):
    pass


def get(db: Database, teacher_id: str, now: float | None = None) -> dict:
    """The institute's status now. A pause whose end date has passed is over (and is closed in the history)."""
    row = db.one("SELECT account_status, account_reason, account_until, account_by, account_at FROM teachers WHERE id = ?",
                 (teacher_id,))
    if row is None:
        raise KeyError(teacher_id)
    state = row["account_status"] or "active"
    now = now or time.time()
    if state == "paused" and row["account_until"] and row["account_until"] <= now:
        _write(db, teacher_id, "active", "The pause ended on its date", "system", None, now)
        return {"state": "active", "label": LABELS["active"], "reason": "", "until": None, "by": "system", "at": now}
    return {"state": state, "label": LABELS.get(state, state), "reason": row["account_reason"] or "",
            "until": row["account_until"], "by": row["account_by"], "at": row["account_at"]}


def state(db: Database, teacher_id: str | None) -> str:
    if not teacher_id:
        return "active"
    try:
        return get(db, teacher_id)["state"]
    except KeyError:
        return "active"


def change(db: Database, teacher_id: str, new: str, reason: str, by: str, until: float | None = None,
           now: float | None = None) -> dict:
    if new not in STATES:
        raise StatusError("Choose active, paused or blocked")
    reason = (reason or "").strip()
    if not reason:
        raise StatusError("Write the reason (the institute sees it in its panel)")
    now = now or time.time()
    if until is not None and (new != "paused" or until <= now):
        raise StatusError("An end date is only for a pause, and must be in the future")
    old = get(db, teacher_id, now)["state"]
    if old == new and new == "active":
        raise StatusError("The institute is already active")
    _write(db, teacher_id, new, reason, by, until, now)
    from . import alerts
    name = (db.one("SELECT name FROM teachers WHERE id = ?", (teacher_id,)) or {"name": teacher_id})["name"]
    alerts.raise_alert(db, "institute", "high" if new != "active" else "medium",
                       f"Institute {name}: {LABELS[old].lower()} → {LABELS[new].lower()} (by {by})", f"Why: {reason}",
                       f"#/t/{teacher_id}", f"institute:{teacher_id}:{new}:{int(now)}", teacher_id=teacher_id, now=now)
    return get(db, teacher_id, now)


def _write(db: Database, teacher_id: str, new: str, reason: str, by: str, until: float | None, now: float) -> None:
    old = db.one("SELECT account_status FROM teachers WHERE id = ?", (teacher_id,))["account_status"] or "active"
    with db.tx() as conn:
        conn.execute("UPDATE teachers SET account_status = ?, account_reason = ?, account_until = ?, account_by = ?, "
                     "account_at = ? WHERE id = ?",
                     (new, reason[:500] if new != "active" else None, until, by, now, teacher_id))
        conn.execute("INSERT INTO institute_status_log (teacher_id, old_status, new_status, reason, until, by_who, at) "
                     "VALUES (?, ?, ?, ?, ?, ?, ?)", (teacher_id, old, new, reason[:500], until, by, now))


def history(db: Database, teacher_id: str, limit: int = 30) -> list[dict]:
    return [dict(r) for r in db.all("SELECT old_status, new_status, reason, until, by_who, at FROM institute_status_log "
                                    "WHERE teacher_id = ? ORDER BY id DESC LIMIT ?", (teacher_id, limit))]


def all_states(db: Database) -> dict[str, str]:
    now = time.time()
    out = {}
    for r in db.all("SELECT id, account_status, account_until FROM teachers"):
        s = r["account_status"] or "active"
        out[r["id"]] = "active" if s == "paused" and r["account_until"] and r["account_until"] <= now else s
    return out
