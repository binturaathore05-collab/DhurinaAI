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


def login(db: Database, email: str, password: str, secret: str, ip: str = "") -> dict:
    email = (email or "").strip().lower()
    user = db.one("SELECT * FROM admin_users WHERE email = ?", (email,))
    now = time.time()
    if user and user["locked_until"] and user["locked_until"] > now:
        mins = int((user["locked_until"] - now) // 60) + 1
        raise LoginError(f"Too many wrong passwords. Try again in {mins} minutes.")
    ok = bool(user) and check_password(password or "", user["password_hash"])
    db.execute("INSERT INTO admin_logins (email, ip, success) VALUES (?, ?, ?)", (email, ip, int(ok)))
    if not ok:
        if user:
            fails = user["failed_attempts"] + 1
            locked = now + LOCK_SECONDS if fails >= MAX_FAILS else None
            db.execute("UPDATE admin_users SET failed_attempts = ?, locked_until = ? WHERE id = ?",
                       (0 if locked else fails, locked, user["id"]))
        raise LoginError("Wrong email or password")
    db.execute("UPDATE admin_users SET failed_attempts = 0, locked_until = NULL, last_login = CURRENT_TIMESTAMP "
               "WHERE id = ?", (user["id"],))
    token = jwt.encode({"sub": str(user["id"]), "aud": "admin", "iat": int(now),
                        "exp": int(now + SESSION_HOURS * 3600), "pv": user["password_hash"][-8:]},
                       secret, algorithm="HS256")
    return {"token": token, "name": user["name"], "email": user["email"], "role": user["role"]}


def read_session(db: Database, token: str, secret: str):
    try:
        data = jwt.decode(token, secret, algorithms=["HS256"], audience="admin")
    except jwt.PyJWTError:
        raise LoginError("Please log in again")
    user = db.one("SELECT * FROM admin_users WHERE id = ?", (int(data["sub"]),))
    if user is None or user["password_hash"][-8:] != data.get("pv"):  # password changed → old sessions end
        raise LoginError("Please log in again")
    return user


def change_password(db: Database, user_id: int, current: str, new: str) -> None:
    user = db.one("SELECT * FROM admin_users WHERE id = ?", (user_id,))
    if not check_password(current, user["password_hash"]):
        raise LoginError("Current password is wrong")
    validate_password(new)
    db.execute("UPDATE admin_users SET password_hash = ? WHERE id = ?", (hash_password(new), user_id))
