"""S3 · Cyber security (simple version first).

  2-step login   admin team: password + a 6-digit code from an authenticator app (Google Authenticator, Microsoft
                 Authenticator …), standard TOTP. 8 one-time backup codes for a lost phone. A code can't be used twice.
                 Super Admin can make it required for everyone (admin → Security).
  Sessions       every admin login is a session that can be seen and ended ("log out other devices"); a login from a
                 new place raises an alert. Students can log out every other phone (token version).
  Block list     phone numbers and IP addresses that abuse OTP / logins. An IP block ends by itself (many students in
                 India share one mobile-network IP), a number block stays until removed.
  Headers        browser security headers on every reply (no framing, no sniffing, CSP on pages, HSTS behind HTTPS).
  Request limit  a high per-IP request ceiling against bots (per server process, in memory).
"""
import base64
import hashlib
import hmac
import json
import secrets
import struct
import threading
import time
from collections import deque

from ..db import Database
from .. import secrets_box

ISSUER = "LiveTeach Admin"
STEP = 30
BACKUP_COUNT = 8


class SecurityError(ValueError):
    """A message ready for the admin."""


# ---------- 2-step login (TOTP, RFC 6238) ----------

def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _code(secret: str, step: int) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    digest = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    off = digest[-1] & 0x0F
    return f"{(struct.unpack('>I', digest[off:off + 4])[0] & 0x7FFFFFFF) % 1_000_000:06d}"


def code_at(secret: str, now: float | None = None) -> str:
    return _code(secret, int((now or time.time()) // STEP))


def match_step(secret: str, code: str, last_step: int | None, now: float | None = None) -> int | None:
    """The time step the code belongs to (one step either side for phone clocks), or None. A step already used fails."""
    code = "".join(ch for ch in str(code or "") if ch.isdigit())
    if len(code) != 6:
        return None
    cur = int((now or time.time()) // STEP)
    for step in (cur, cur - 1, cur + 1):
        if hmac.compare_digest(_code(secret, step), code) and (last_step is None or step > last_step):
            return step
    return None


def otpauth_uri(secret: str, email: str) -> str:
    from urllib.parse import quote
    return (f"otpauth://totp/{quote(ISSUER)}:{quote(email)}?secret={secret}&issuer={quote(ISSUER)}"
            f"&algorithm=SHA1&digits=6&period={STEP}")


def qr_svg(text: str) -> str | None:
    """The QR picture for the authenticator app (None if the QR library is missing: the key can be typed instead)."""
    try:
        import io
        import segno
    except ImportError:
        return None
    out = io.BytesIO()
    segno.make(text, error="m").save(out, kind="svg", scale=5, border=2, xmldecl=False, svgns=True)
    return out.getvalue().decode()


def _hash_backup(code: str) -> str:
    return hashlib.sha256(code.replace("-", "").lower().encode()).hexdigest()


def new_backup_codes() -> tuple[list[str], str]:
    plain = [f"{secrets.token_hex(2)}-{secrets.token_hex(2)}" for _ in range(BACKUP_COUNT)]
    return plain, json.dumps([_hash_backup(c) for c in plain])


def use_backup_code(stored: str | None, code: str) -> str | None:
    """The remaining codes (JSON) after using this one, or None if it isn't a valid unused code."""
    try:
        left = json.loads(stored or "[]")
    except ValueError:
        return None
    h = _hash_backup((code or "").strip())
    for i, c in enumerate(left):
        if hmac.compare_digest(c, h):
            return json.dumps(left[:i] + left[i + 1:])
    return None


def start_2step(db: Database, user_id: int, email: str) -> dict:
    secret = new_secret()
    db.execute("UPDATE admin_users SET totp_pending = ? WHERE id = ?", (secrets_box.seal(secret), user_id))
    uri = otpauth_uri(secret, email)
    return {"secret": " ".join(secret[i:i + 4] for i in range(0, len(secret), 4)), "uri": uri, "qr_svg": qr_svg(uri)}


def confirm_2step(db: Database, user_id: int, code: str) -> list[str]:
    row = db.one("SELECT totp_pending FROM admin_users WHERE id = ?", (user_id,))
    secret = secrets_box.unseal(row["totp_pending"]) if row else None
    if not secret:
        raise SecurityError("Start the 2-step set-up again")
    step = match_step(secret, code, None)
    if step is None:
        raise SecurityError("That code is not right. Check the phone's time and type the newest code.")
    plain, hashed = new_backup_codes()
    db.execute("UPDATE admin_users SET totp_secret = ?, totp_pending = NULL, totp_on = 1, totp_last_step = ?, "
               "backup_codes = ? WHERE id = ?", (secrets_box.seal(secret), step, hashed, user_id))
    return plain


def turn_off_2step(db: Database, user_id: int) -> None:
    db.execute("UPDATE admin_users SET totp_secret = NULL, totp_pending = NULL, totp_on = 0, totp_last_step = NULL, "
               "backup_codes = NULL WHERE id = ?", (user_id,))


def check_2step(db: Database, user, code: str) -> str:
    """'code' or 'backup' when it is right (and spends it); raises SecurityError otherwise."""
    secret = secrets_box.unseal(user["totp_secret"])
    step = match_step(secret, code, user["totp_last_step"]) if secret else None
    if step is not None:
        db.execute("UPDATE admin_users SET totp_last_step = ? WHERE id = ?", (step, user["id"]))
        return "code"
    left = use_backup_code(user["backup_codes"], code)
    if left is not None:
        db.execute("UPDATE admin_users SET backup_codes = ? WHERE id = ?", (left, user["id"]))
        return "backup"
    raise SecurityError("Wrong code")


def backup_left(user) -> int:
    try:
        return len(json.loads(user["backup_codes"] or "[]"))
    except ValueError:
        return 0


def _setting(db: Database) -> dict:
    row = db.one("SELECT value FROM platform_settings WHERE key = 'security'")
    try:
        return json.loads(row["value"]) if row else {}
    except ValueError:
        return {}


def require_2step(db: Database) -> bool:
    return bool(_setting(db).get("require_2step"))


def set_require_2step(db: Database, on: bool) -> None:
    value = json.dumps({**_setting(db), "require_2step": bool(on)})
    db.execute("INSERT INTO platform_settings (key, value) VALUES ('security', ?) "
               "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (value,))


# ---------- admin sessions ----------

NEW_PLACE_DAYS = 90


def start_session(db: Database, user_id: int, ip: str, ua: str, now: float | None = None) -> tuple[str, bool]:
    """A new login. Returns (session id, from a new place?) — new place = this person logged in before, but never
    from this IP address and browser in the last 90 days."""
    now = now or time.time()
    since = now - NEW_PLACE_DAYS * 86400
    before = db.one("SELECT 1 FROM admin_sessions WHERE user_id = ? AND created > ? LIMIT 1", (user_id, since))
    known = db.one("SELECT 1 FROM admin_sessions WHERE user_id = ? AND created > ? AND ip = ? AND ua = ? LIMIT 1",
                   (user_id, since, ip, ua[:200]))
    sid = secrets.token_urlsafe(16)
    db.execute("INSERT INTO admin_sessions (id, user_id, ip, ua, created, last_seen) VALUES (?, ?, ?, ?, ?, ?)",
               (sid, user_id, ip, ua[:200], now, now))
    return sid, bool(before and not known)


def session_ok(db: Database, sid: str | None, user_id: int, now: float | None = None) -> bool:
    if not sid:
        return False
    now = now or time.time()
    row = db.one("SELECT ended, last_seen FROM admin_sessions WHERE id = ? AND user_id = ?", (sid, user_id))
    if row is None or row["ended"]:
        return False
    if now - (row["last_seen"] or 0) > 60:
        db.execute("UPDATE admin_sessions SET last_seen = ? WHERE id = ?", (now, sid))
    return True


def end_session(db: Database, sid: str, user_id: int | None = None) -> bool:
    q, args = "UPDATE admin_sessions SET ended = ? WHERE id = ? AND ended IS NULL", [time.time(), sid]
    if user_id is not None:
        q += " AND user_id = ?"
        args.append(user_id)
    return db.execute(q, tuple(args)).rowcount > 0


def end_other_sessions(db: Database, user_id: int, keep: str | None) -> int:
    return db.execute("UPDATE admin_sessions SET ended = ? WHERE user_id = ? AND ended IS NULL AND id != ?",
                      (time.time(), user_id, keep or "")).rowcount


def end_all_sessions(db: Database, user_id: int) -> int:
    return end_other_sessions(db, user_id, None)


def sessions(db: Database, user_id: int | None = None, hours: int = 12) -> list[dict]:
    """Open sessions (not ended, not older than the 12-hour login)."""
    since = time.time() - hours * 3600
    q = ("SELECT s.id, s.user_id, s.ip, s.ua, s.created, s.last_seen, u.email, u.name FROM admin_sessions s "
         "JOIN admin_users u ON u.id = s.user_id WHERE s.ended IS NULL AND s.created > ?")
    args: list = [since]
    if user_id is not None:
        q += " AND s.user_id = ?"
        args.append(user_id)
    return [dict(r) for r in db.all(q + " ORDER BY s.last_seen DESC", tuple(args))]


# ---------- block list ----------

KINDS = ("phone", "ip")
IP_BLOCK_HOURS = 24
_cache = {"at": 0.0, "rows": {}}
_cache_lock = threading.Lock()


def _blocked_map(db: Database) -> dict:
    now = time.time()
    with _cache_lock:
        if now - _cache["at"] > 30:
            rows = db.all("SELECT kind, value, until FROM blocked WHERE until IS NULL OR until > ?", (now,))
            _cache["rows"] = {(r["kind"], r["value"]): r["until"] for r in rows}
            _cache["at"] = now
        return _cache["rows"]


def _forget_cache() -> None:
    with _cache_lock:
        _cache["at"] = 0.0


def is_blocked(db: Database, kind: str, value: str) -> bool:
    if not value:
        return False
    until = _blocked_map(db).get((kind, value), "missing")
    return until != "missing" and (until is None or until > time.time())


def block(db: Database, kind: str, value: str, reason: str, by: str, hours: float | None = None,
          own_ip: str = "") -> None:
    value = (value or "").strip()
    if kind not in KINDS:
        raise SecurityError("Choose phone number or IP address")
    if not value:
        raise SecurityError("Enter what to block")
    if not (reason or "").strip():
        raise SecurityError("Write why")
    if kind == "ip":
        import ipaddress
        try:
            value = str(ipaddress.ip_address(value))
        except ValueError:
            raise SecurityError("Not an IP address")
        if value == own_ip:
            raise SecurityError("That is your own IP address — you would lock yourself out")
        hours = hours or IP_BLOCK_HOURS
    until = time.time() + hours * 3600 if hours else None
    db.execute("INSERT INTO blocked (kind, value, reason, by_who, at, until) VALUES (?, ?, ?, ?, ?, ?) "
               "ON CONFLICT(kind, value) DO UPDATE SET reason = excluded.reason, by_who = excluded.by_who, "
               "at = excluded.at, until = excluded.until", (kind, value, reason.strip()[:300], by, time.time(), until))
    _forget_cache()


def unblock(db: Database, block_id: int) -> None:
    if db.execute("DELETE FROM blocked WHERE id = ?", (block_id,)).rowcount == 0:
        raise KeyError(block_id)
    _forget_cache()


def blocks(db: Database) -> list[dict]:
    return [dict(r) for r in db.all("SELECT * FROM blocked WHERE until IS NULL OR until > ? ORDER BY at DESC",
                                    (time.time(),))]


_noted: dict[str, float] = {}


def note(db: Database, key: str, every: float = 10) -> None:
    """Count a security event for the Security page (at most once every few seconds per key, so a flood of
    refused requests doesn't flood the database too)."""
    now = time.time()
    if now - _noted.get(key, 0) < every:
        return
    _noted[key] = now
    db.execute("INSERT INTO rate_events (key, at) VALUES (?, ?)", (key, now))


# ---------- what happened lately (Security page + alerts) ----------

def recent(db: Database, hours: int = 24, now: float | None = None) -> dict:
    now = now or time.time()
    since = now - hours * 3600
    n = lambda q, *a: db.one(q, a)["n"]   # noqa: E731
    return {
        "hours": hours,
        "otp_sent": n("SELECT COUNT(*) AS n FROM rate_events WHERE key LIKE 'otp:phone:%' AND at > ?", since),
        "wrong_codes": n("SELECT COUNT(*) AS n FROM rate_events WHERE key LIKE 'otp:wrong:%' AND at > ?", since),
        "admin_failed": n("SELECT COUNT(*) AS n FROM admin_logins WHERE success = 0 AND at > datetime(?, 'unixepoch')", since),
        "blocked_requests": n("SELECT COUNT(*) AS n FROM rate_events WHERE key LIKE 'sec:blocked:%' AND at > ?", since),
        "too_many_requests": n("SELECT COUNT(*) AS n FROM rate_events WHERE key = 'sec:ip_limit' AND at > ?", since),
        "failed_admin_logins": [dict(r) for r in db.all(
            "SELECT email, ip, at FROM admin_logins WHERE success = 0 AND at > datetime(?, 'unixepoch') "
            "ORDER BY id DESC LIMIT 20", (since,))],
    }


# ---------- browser security headers ----------

CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
       "font-src 'self' https://fonts.gstatic.com; img-src 'self' data: blob: https:; connect-src 'self'; "
       "frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'")


def headers(content_type: str, https: bool) -> dict:
    out = {"X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer",
           "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
           "Cross-Origin-Opener-Policy": "same-origin"}
    if content_type.startswith("text/html"):
        out["Content-Security-Policy"] = CSP
    if https:
        out["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return out


# ---------- per-IP request ceiling (bots) ----------

class IpLimiter:
    """Sliding one-minute window per IP, in memory. Generous: many students can share one mobile-network IP."""

    def __init__(self, per_minute: int = 600):
        self.per_minute = per_minute
        self._hits: dict[str, deque] = {}
        self._lock = threading.Lock()
        self._swept = time.time()

    def allow(self, ip: str, now: float | None = None) -> bool:
        if not ip:
            return True
        now = now or time.time()
        with self._lock:
            if now - self._swept > 300:   # forget quiet IPs
                self._hits = {k: q for k, q in self._hits.items() if q and q[-1] > now - 60}
                self._swept = now
            q = self._hits.setdefault(ip, deque())
            while q and q[0] <= now - 60:
                q.popleft()
            if len(q) >= self.per_minute:
                return False
            q.append(now)
            return True
