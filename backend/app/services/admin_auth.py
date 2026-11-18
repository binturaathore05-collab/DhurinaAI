"""Admin panel login: email + password for each staff member.

Passwords are stored only as scrypt hashes (never in plain text). After 5 wrong passwords an account
is locked for 15 minutes. The first owner account is created from ADMIN_EMAIL / ADMIN_PASSWORD in .env
when the server starts and no admin exists yet.
"""
import hashlib
import hmac
import secrets
import time

import jwt

from ..db import Database
from . import security

MAX_FAILS, LOCK_SECONDS, SESSION_HOURS = 5, 15 * 60, 12


class LoginError(Exception):
    pass


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt${salt.hex()}${digest.hex()}"


def check_password(password: str, stored: str) -> bool:
    try:
        _, salt, digest = stored.split("$")
    except ValueError:
        return False
    test = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1)
    return hmac.compare_digest(test.hex(), digest)


def validate_password(password: str) -> None:
    if len(password) < 8 or password.isdigit() or password.isalpha():
        raise LoginError("Password must be at least 8 characters and mix letters and numbers")


def create_admin(db: Database, email: str, password: str, name: str = "", role: str = "owner") -> int:
    email = email.strip().lower()
    if "@" not in email:
        raise LoginError("Enter a valid email")
    validate_password(password)
    cur = db.execute("INSERT INTO admin_users (email, name, password_hash, role) VALUES (?, ?, ?, ?)",
                     (email, name or email.split("@")[0], hash_password(password), role))
    return cur.lastrowid


def ensure_first_admin(db: Database, email: str | None, password: str | None) -> None:
    if email and password and not db.one("SELECT 1 FROM admin_users LIMIT 1"):
        create_admin(db, email, password, "Owner", "owner")


def _fail(db: Database, user, now: float) -> None:
    fails = user["failed_attempts"] + 1
    locked = now + LOCK_SECONDS if fails >= MAX_FAILS else None
    db.execute("UPDATE admin_users SET failed_attempts = ?, locked_until = ? WHERE id = ?",
               (0 if locked else fails, locked, user["id"]))


def _check_open(user, now: float) -> None:
    if not user["active"]:
        raise LoginError("This account has been switched off. Ask the Super Admin.")
    if user["locked_until"] and user["locked_until"] > now:
        mins = int((user["locked_until"] - now) // 60) + 1
        raise LoginError(f"Too many wrong passwords or codes. Try again in {mins} minutes.")


def login(db: Database, email: str, password: str, secret: str, ip: str = "", ua: str = "") -> dict:
    """Step 1: email + password. With 2-step login on, this gives only a 5-minute ticket for step 2 (the code)."""
    email = (email or "").strip().lower()
    user = db.one("SELECT * FROM admin_users WHERE email = ?", (email,))
    now = time.time()
    if user:
        try:
            _check_open(user, now)
        except LoginError:
            db.execute("INSERT INTO admin_logins (email, ip, success) VALUES (?, ?, 0)", (email, ip))
            raise
    ok = bool(user) and check_password(password or "", user["password_hash"])
    if not ok:
        db.execute("INSERT INTO admin_logins (email, ip, success) VALUES (?, ?, 0)", (email, ip))
        if user:
            _fail(db, user, now)
        raise LoginError("Wrong email or password")
    if user["totp_on"]:
        ticket = jwt.encode({"sub": str(user["id"]), "aud": "admin-2step", "iat": int(now), "exp": int(now + 300),
                             "pv": user["password_hash"][-8:]}, secret, algorithm="HS256")
        return {"need_code": True, "ticket": ticket}
    return _issue(db, user, secret, ip, ua, now)


def login_code(db: Database, ticket: str, code: str, secret: str, ip: str = "", ua: str = "") -> dict:
    """Step 2: the 6-digit code from the authenticator app (or one backup code)."""
    try:
        data = jwt.decode(ticket or "", secret, algorithms=["HS256"], audience="admin-2step")
    except jwt.PyJWTError:
        raise LoginError("Too slow — log in again")
    user = db.one("SELECT * FROM admin_users WHERE id = ?", (int(data["sub"]),))
    now = time.time()
    if user is None or user["password_hash"][-8:] != data.get("pv") or not user["totp_on"]:
        raise LoginError("Log in again")
    _check_open(user, now)
    try:
        used = security.check_2step(db, user, code)
    except security.SecurityError:
        db.execute("INSERT INTO admin_logins (email, ip, success) VALUES (?, ?, 0)", (user["email"], ip))
        _fail(db, user, now)
        raise LoginError("Wrong code")
    out = _issue(db, db.one("SELECT * FROM admin_users WHERE id = ?", (user["id"],)), secret, ip, ua, now)
    if used == "backup":
        out["backup_left"] = security.backup_left(db.one("SELECT backup_codes FROM admin_users WHERE id = ?", (user["id"],)))
    return out


def _issue(db: Database, user, secret: str, ip: str, ua: str, now: float) -> dict:
    db.execute("INSERT INTO admin_logins (email, ip, success) VALUES (?, ?, 1)", (user["email"], ip))
    db.execute("UPDATE admin_users SET failed_attempts = 0, locked_until = NULL, last_login = CURRENT_TIMESTAMP "
               "WHERE id = ?", (user["id"],))
    sid, new_place = security.start_session(db, user["id"], ip, ua, now)
    if new_place:   # S3: a login from a new place → the team hears about it at once
        from . import alerts
        alerts.raise_alert(db, "new_login", "medium", f"Admin login from a new place: {user['email']}",
                           f"IP {ip or '?'} · {(ua or '?')[:80]}. If this was not them: Security → end the session, "
                           "then reset the password.", "#/security", f"new_login:{user['id']}:{ip}", now=now)
    token = jwt.encode({"sub": str(user["id"]), "aud": "admin", "iat": int(now), "sid": sid,
                        "exp": int(now + SESSION_HOURS * 3600), "pv": user["password_hash"][-8:]},
                       secret, algorithm="HS256")
    return {"token": token, "name": user["name"], "email": user["email"], "role": user["role"],
            "must_change": bool(user["must_change"])}


def session_id(token: str, secret: str) -> str | None:
    try:
        return jwt.decode(token, secret, algorithms=["HS256"], audience="admin").get("sid")
    except jwt.PyJWTError:
        return None


def read_session(db: Database, token: str, secret: str):
    try:
        data = jwt.decode(token, secret, algorithms=["HS256"], audience="admin")
    except jwt.PyJWTError:
        raise LoginError("Please log in again")
    user = db.one("SELECT * FROM admin_users WHERE id = ?", (int(data["sub"]),))
    if user is None or user["password_hash"][-8:] != data.get("pv") or not user["active"]:
        raise LoginError("Please log in again")   # password changed or account switched off → old sessions end
    if not security.session_ok(db, data.get("sid"), user["id"]):
        raise LoginError("Please log in again")   # S3: this login was ended (log out other devices / by Super Admin)
    return user


def change_password(db: Database, user_id: int, current: str, new: str) -> None:
    user = db.one("SELECT * FROM admin_users WHERE id = ?", (user_id,))
    if not check_password(current, user["password_hash"]):
        raise LoginError("Current password is wrong")
    validate_password(new)
    if check_password(new, user["password_hash"]):
        raise LoginError("Choose a new password, not the current one")
    db.execute("UPDATE admin_users SET password_hash = ?, must_change = 0 WHERE id = ?", (hash_password(new), user_id))


# ---------- B5: team ----------

def temp_password() -> str:
    """A one-time password the Super Admin passes on; it must be changed at first login."""
    alphabet = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ"
    digits = "23456789"
    core = [secrets.choice(alphabet) for _ in range(8)] + [secrets.choice(digits) for _ in range(4)]
    secrets.SystemRandom().shuffle(core)
    return "".join(core)


def team(db: Database) -> list[dict]:
    return [dict(r) for r in db.all("SELECT id, email, name, role, active, must_change, last_login, created_at, created_by, totp_on "
                                    "FROM admin_users ORDER BY active DESC, role, email")]


def add_member(db: Database, email: str, name: str, role: str, by: str, roles: dict) -> tuple[int, str]:
    if role not in roles:
        raise LoginError("Choose a role")
    email = (email or "").strip().lower()
    if db.one("SELECT 1 FROM admin_users WHERE email = ?", (email,)):
        raise LoginError("Someone with this email is already in the team")
    pw = temp_password()
    uid = create_admin(db, email, pw, (name or "").strip(), role)
    db.execute("UPDATE admin_users SET must_change = 1, created_by = ? WHERE id = ?", (by, uid))
    return uid, pw


def _active_owners(db: Database) -> int:
    return db.one("SELECT COUNT(*) AS n FROM admin_users WHERE role = 'owner' AND active = 1")["n"]


def update_member(db: Database, uid: int, me_id: int, roles: dict, role: str | None = None,
                  active: bool | None = None, name: str | None = None) -> None:
    u = db.one("SELECT * FROM admin_users WHERE id = ?", (uid,))
    if u is None:
        raise KeyError(uid)
    if uid == me_id and (role not in (None, u["role"]) or active is False):
        raise LoginError("You can't change your own role or switch yourself off")
    losing_owner = u["role"] == "owner" and u["active"] and (role not in (None, "owner") or active is False)
    if losing_owner and _active_owners(db) <= 1:
        raise LoginError("There must always be at least one active Super Admin")
    if role is not None and role not in roles:
        raise LoginError("Choose a role")
    db.execute("UPDATE admin_users SET role = COALESCE(?, role), active = COALESCE(?, active), name = COALESCE(?, name) "
               "WHERE id = ?", (role, None if active is None else int(active), (name or "").strip() or None, uid))


def reset_password(db: Database, uid: int) -> str:
    if db.one("SELECT 1 FROM admin_users WHERE id = ?", (uid,)) is None:
        raise KeyError(uid)
    pw = temp_password()
    db.execute("UPDATE admin_users SET password_hash = ?, must_change = 1, failed_attempts = 0, locked_until = NULL "
               "WHERE id = ?", (hash_password(pw), uid))   # the old password and every open session stop working
    return pw
