"""B7 · Alerts: tell the team at once when something serious happens — in the admin panel (bell + Alerts page) and by
email. An alert never contains what a child wrote: only what kind of thing happened and a link into the admin panel
(where the permissions of B5 decide who may open it). WhatsApp needs a WhatsApp Business provider (later).

Alerts (level):
  care            a student may need help                                 critical
  ai_failure      a review case closed as "something unsafe reached a student"  critical
  shutdown        an Emergency switch was turned off                       critical
  check_down      the safety check failed again and again (spike of "could not run")  critical
  auto_block      a student was suspended / stopped for review automatically   high
  repeated        the same student made 3+ harmful requests in an open case     high
  pending         a high-priority case has waited longer than N hours           high
  spike           many more blocked questions / stopped AI answers than usual   high
  tests_failed    the safety tests failed                                  high
The same alert is not repeated within an hour (dedup key).
"""
import json
import smtplib
import threading
import time
from email.message import EmailMessage

from ..db import Database

LEVELS = ("critical", "high", "medium")
DEFAULT_ALERTS = {"email_to": [], "email_level": "high", "spike_min": 10, "pending_hours": 2, "check_down_min": 5}
DEDUP_SECONDS = 3600

# set by the API at start: how to send email (None = not configured) and the admin panel address
mailer = {"send": None, "base_url": ""}


def alert_settings(admin_settings: dict) -> dict:
    out = dict(DEFAULT_ALERTS)
    out.update({k: v for k, v in (admin_settings.get("alerts") or {}).items() if k in out})
    return out


def validate(values: dict) -> dict:
    out = dict(values or {})
    emails = out.get("email_to", [])
    if isinstance(emails, str):
        emails = [e.strip() for e in emails.replace(",", "\n").split("\n")]
    emails = [e.strip().lower() for e in emails if e and e.strip()]
    for e in emails:
        if "@" not in e or " " in e:
            raise ValueError(f"Not an email address: {e}")
    out["email_to"] = emails[:20]
    if out.get("email_level", "high") not in ("critical", "high", "all"):
        raise ValueError("Email level must be critical, high or all")
    for k in ("spike_min", "pending_hours", "check_down_min"):
        if k in out:
            try:
                n = int(out[k])
                ok = n >= 1 and float(out[k]) == n
            except (TypeError, ValueError):
                ok = False
            if not ok:
                raise ValueError("Alert numbers must be whole numbers, 1 or more")
            out[k] = n
    return out


def raise_alert(db: Database, kind: str, level: str, title: str, body: str = "", link: str = "",
                dedup: str | None = None, student_id: int | None = None, teacher_id: str | None = None,
                now: float | None = None) -> int | None:
    """Create an alert (unless the same one was raised within the last hour) and email it if set up. Never raises."""
    try:
        now = now or time.time()
        key = dedup or f"{kind}:{title}"
        if db.one("SELECT 1 FROM alerts WHERE dedup_key = ? AND at > ?", (key, now - DEDUP_SECONDS)):
            return None
        cur = db.execute("INSERT INTO alerts (at, kind, level, title, body, link, dedup_key, student_id, teacher_id) "
                         "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         (now, kind, level, title[:200], (body or "")[:1000], link, key, student_id, teacher_id))
        _email(db, cur.lastrowid, level, title, body, link)
        return cur.lastrowid
    except Exception as exc:   # an alert must never break what the student or admin is doing
        print(f"[alerts] could not raise {kind}: {exc}")
        return None


def _email(db: Database, alert_id: int, level: str, title: str, body: str, link: str) -> None:
    from . import admin as admin_mod
    s = alert_settings(admin_mod.get_settings(db))
    send = mailer["send"]
    if not send or not s["email_to"]:
        return
    if s["email_level"] == "critical" and level != "critical":
        return
    if s["email_level"] == "high" and level not in ("critical", "high"):
        return
    url = (mailer["base_url"] or "").rstrip("/") + "/admin" + (link or "#/alerts")
    subject = f"[LiveTeach {level.upper()}] {title}"
    text = (f"{title}\n\n{body}\n\nOpen the admin panel: {url}\n\n"
            "This email never contains what a student wrote. Log in to see the details (safety team only).")

    def run():
        try:
            send(s["email_to"], subject, text)
            db.execute("UPDATE alerts SET emailed = 1 WHERE id = ?", (alert_id,))
        except Exception as exc:
            db.execute("UPDATE alerts SET emailed = -1 WHERE id = ?", (alert_id,))
            print(f"[alerts] email failed: {exc}")
    threading.Thread(target=run, daemon=True).start()


def smtp_sender(host: str, port: int, user: str, password: str, sender: str):
    """Plain SMTP (e.g. Gmail / Zoho / SES) with STARTTLS."""
    def send(to: list[str], subject: str, text: str) -> None:
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = sender, ", ".join(to), subject
        msg.set_content(text)
        with smtplib.SMTP(host, port, timeout=20) as s:
            s.starttls()
            if user:
                s.login(user, password)
            s.send_message(msg)
    return send


# ---------- checks that run every few minutes ----------

def periodic(db: Database, admin_settings: dict, now: float | None = None) -> list[int]:
    now = now or time.time()
    s = alert_settings(admin_settings)
    made = []
    # high-priority cases waiting too long
    for r in db.all("SELECT id, title FROM incidents WHERE status IN ('open', 'in_review', 'escalated') AND severity = 'high' "
                    "AND created_at < ?", (now - s["pending_hours"] * 3600,)):
        a = raise_alert(db, "pending", "high", f"Case #{r['id']} waiting more than {s['pending_hours']} h: {r['title']}",
                        "A high-priority review case is still open.", f"#/case/{r['id']}", f"pending:{r['id']}", now=now)
        made.append(a)
    # spikes in the last hour vs. the usual hour of the last 7 days
    for kind_sql, label in (("stage = 'output' AND action = 'replaced'", "AI answers stopped"),
                            ("stage = 'input' AND action IN ('refused', 'redirected')", "blocked questions")):
        last = db.one(f"SELECT COUNT(*) AS n FROM safety_events WHERE {kind_sql} AND at > ?", (now - 3600,))["n"]
        week = db.one(f"SELECT COUNT(*) AS n FROM safety_events WHERE {kind_sql} AND at > ? AND at <= ?",
                      (now - 7 * 86400, now - 3600))["n"]
        usual = week / (7 * 24 - 1)
        if last >= s["spike_min"] and last >= 3 * max(usual, 1):
            made.append(raise_alert(db, "spike", "high", f"Spike: {last} {label} in the last hour",
                                    f"Usually about {usual:.1f} an hour. Check the Safety dashboard and consider Emergency.",
                                    "#/safety-dash", f"spike:{label}", now=now))
    # the safety check failing again and again
    down = db.one("SELECT COUNT(*) AS n FROM safety_events WHERE action = 'retry' AND at > ?", (now - 600,))["n"]
    if down >= s["check_down_min"]:
        made.append(raise_alert(db, "check_down", "critical", f"Safety check failed {down} times in 10 minutes",
                                "Students are being asked to try again; nothing unchecked is sent. Check the AI provider "
                                "or switch to the backup model in Emergency.", "#/emergency", "check_down", now=now))
    return [a for a in made if a]


def check_down_now(db: Database, admin_settings: dict) -> None:
    """Right after a failed check: don't wait for the next round if failures are piling up."""
    s = alert_settings(admin_settings)
    down = db.one("SELECT COUNT(*) AS n FROM safety_events WHERE action = 'retry' AND at > ?", (time.time() - 600,))["n"]
    if down >= s["check_down_min"]:
        raise_alert(db, "check_down", "critical", f"Safety check failed {down} times in 10 minutes",
                    "Students are being asked to try again; nothing unchecked is sent.", "#/emergency", "check_down")


def listing(db: Database, only_open: bool = True, limit: int = 100) -> dict:
    w = "WHERE ack_at IS NULL" if only_open else ""
    items = [dict(r) for r in db.all(f"SELECT * FROM alerts {w} ORDER BY CASE level WHEN 'critical' THEN 0 WHEN 'high' "
                                     f"THEN 1 ELSE 2 END, at DESC LIMIT ?", (limit,))]
    counts = {r["level"]: r["n"] for r in db.all("SELECT level, COUNT(*) AS n FROM alerts WHERE ack_at IS NULL GROUP BY level")}
    return {"items": items, "open": sum(counts.values()), "critical": counts.get("critical", 0)}


def acknowledge(db: Database, alert_id: int | None, by: str, note: str = "") -> None:
    if alert_id is None:
        db.execute("UPDATE alerts SET ack_at = ?, ack_by = ?, ack_note = ? WHERE ack_at IS NULL", (time.time(), by, note[:300]))
        return
    if db.one("SELECT 1 FROM alerts WHERE id = ?", (alert_id,)) is None:
        raise KeyError(alert_id)
    db.execute("UPDATE alerts SET ack_at = ?, ack_by = ?, ack_note = ? WHERE id = ? AND ack_at IS NULL",
               (time.time(), by, note[:300], alert_id))
