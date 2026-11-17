"""A6 · Rate limits: AI questions per student (per minute, per day) and OTP abuse (sends per phone, device and IP;
wrong codes per phone). Every check is on the server; the numbers live in admin Settings → "Limits" and apply
at once. Events are kept in one small table and old rows are cleaned up as we go.
"""
import time
from dataclasses import dataclass

from ..db import Database
from ..i18n import t

MINUTE, HOUR, DAY = 60, 3600, 86400

# Defaults (admin Settings → Limits can change each one; every value must be at least 1)
DEFAULT_LIMITS = {
    "questions_per_minute": 8,      # a real student rarely asks more than this in a minute
    "questions_per_day": 250,       # paid plans are "unlimited", but this caps runaway AI cost per student
    "otp_per_phone_10min": 3,
    "otp_per_phone_day": 10,
    "otp_gap_seconds": 30,          # same as the app's "Resend in 0:30" timer
    "otp_per_device_day": 10,
    "otp_per_ip_hour": 30,          # generous: many phones in India share one mobile-network IP
    "otp_wrong_per_phone_day": 10,  # wrong codes across all codes, then the number is locked for the day
}


class Limited(Exception):
    """Raised with a message ready for the student and how many seconds to wait."""

    def __init__(self, message: str, retry_after: int):
        super().__init__(message)
        self.retry_after = max(int(retry_after), 1)


@dataclass
class Rule:
    key: str        # e.g. "ask:student:12", "otp:phone:+919876543210"
    limit: int
    window: int     # seconds
    message: str    # i18n key


def _wait_text(seconds: int) -> dict:
    if seconds < 90:
        return {"wait": f"{seconds} seconds"}
    if seconds < 2 * HOUR:
        return {"wait": f"{(seconds + 59) // 60} minutes"}
    return {"wait": f"{(seconds + HOUR - 1) // HOUR} hours"}


def check_and_record(db: Database, rules: list[Rule], lang: str = "en", now: float | None = None,
                     record: bool = True) -> None:
    """Raise Limited if any rule is already full; otherwise count one event for every rule (atomically)."""
    now = now or time.time()
    with db.tx() as conn:
        for r in rules:
            rows = conn.execute("SELECT at FROM rate_events WHERE key = ? AND at > ? ORDER BY at LIMIT ?",
                                (r.key, now - r.window, r.limit)).fetchall()
            if len(rows) >= r.limit:
                wait = int(rows[0]["at"] + r.window - now) + 1
                raise Limited(t(r.message, lang, **_wait_text(wait)), wait)
        if record:
            conn.executemany("INSERT INTO rate_events (key, at) VALUES (?, ?)", [(k, now) for k in dict.fromkeys(r.key for r in rules)])
        if int(now) % 50 == 0:   # cheap, occasional clean-up of rows nobody will look at again
            conn.execute("DELETE FROM rate_events WHERE at < ?", (now - 2 * DAY,))


def record(db: Database, key: str, now: float | None = None) -> None:
    db.execute("INSERT INTO rate_events (key, at) VALUES (?, ?)", (key, now or time.time()))


def settings(admin_settings: dict) -> dict:
    out = dict(DEFAULT_LIMITS)
    for k, v in (admin_settings.get("limits") or {}).items():
        if k in out:
            try:
                out[k] = max(int(v), 1)
            except (TypeError, ValueError):
                pass
    return out


def question_rules(student_id: int, lim: dict) -> list[Rule]:
    key = f"ask:student:{student_id}"
    return [Rule(key, lim["questions_per_minute"], MINUTE, "limit_ask_minute"),
            Rule(key, lim["questions_per_day"], DAY, "limit_ask_day")]


def otp_send_rules(teacher_id: str, phone: str, device: str, ip: str, lim: dict) -> list[Rule]:
    p = f"otp:phone:{teacher_id}:{phone}"
    rules = [Rule(p, 1, lim["otp_gap_seconds"], "limit_otp_gap"),
             Rule(p, lim["otp_per_phone_10min"], 10 * MINUTE, "limit_otp"),
             Rule(p, lim["otp_per_phone_day"], DAY, "limit_otp")]
    if device:
        rules.append(Rule(f"otp:device:{device[:80]}", lim["otp_per_device_day"], DAY, "limit_otp"))
    if ip:
        rules.append(Rule(f"otp:ip:{ip}", lim["otp_per_ip_hour"], HOUR, "limit_otp"))
    return rules


def wrong_code_rule(teacher_id: str, phone: str, lim: dict) -> Rule:
    return Rule(f"otp:wrong:{teacher_id}:{phone}", lim["otp_wrong_per_phone_day"], DAY, "limit_otp_locked")
