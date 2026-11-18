"""Institute panel login (Step 3 of multi-teacher): each institute logs in with its own login and password.

Dhurina (Super Admin) sets the login (email or mobile) in admin → the institute's page; a one-time password is shown
once there and must be changed at the first login. Passwords are stored only as scrypt hashes (same as admin users).
5 wrong passwords lock the login for 15 minutes. Changing the password ends every older login.
The older teacher key (TEACHER_KEY_<ID> in .env) still works for scripts.
"""
import re
import time

import jwt

from ..db import Database
from . import admin_auth

MAX_FAILS = 5
LOCK_SECONDS = 15 * 60
SESSION_HOURS = 12


class InstituteAuthError(ValueError):
    pass


def clean_login(login: str) -> str:
    s = (login or "").strip().lower()
    digits = re.sub(r"\D", "", s)
    if "@" not in s and len(digits) in (10, 12):   # a mobile number: last 10 digits
        return digits[-10:]
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", s):
        raise InstituteAuthError("Use an email or a 10-digit mobile number")
    return s


def set_login(db: Database, institute: str, login: str) -> str:
    """Super Admin: set / reset the institute's login. Returns a one-time password (shown once)."""
    login = clean_login(login)
    other = db.one("SELECT id FROM teachers WHERE panel_login = ? AND id != ?", (login, institute))
    if other:
        raise InstituteAuthError("Another institute already uses this login")
    temp = admin_auth.temp_password()
    db.execute("UPDATE teachers SET panel_login = ?, panel_password_hash = ?, panel_must_change = 1, panel_failed = 0, "
               "panel_locked_until = NULL, panel_pw_changed = ? WHERE id = ?",
               (login, admin_auth.hash_password(temp), time.time(), institute))
    return temp


def login(db: Database, login_id: str, password: str, secret: str) -> dict:
    try:
        login_id = clean_login(login_id)
    except InstituteAuthError:
        raise InstituteAuthError("Wrong login or password")
    row = db.one("SELECT * FROM teachers WHERE panel_login = ?", (login_id,))
    now = time.time()
    if row and row["panel_locked_until"] and row["panel_locked_until"] > now:
        mins = int((row["panel_locked_until"] - now) // 60) + 1
        raise InstituteAuthError(f"Too many wrong passwords. Try again in {mins} minutes.")
    if not row or not row["panel_password_hash"] or not admin_auth.check_password(password or "", row["panel_password_hash"]):
        if row:
            fails = (row["panel_failed"] or 0) + 1
            locked = now + LOCK_SECONDS if fails >= MAX_FAILS else None
            db.execute("UPDATE teachers SET panel_failed = ?, panel_locked_until = ? WHERE id = ?",
                       (0 if locked else fails, locked, row["id"]))
        raise InstituteAuthError("Wrong login or password")
    db.execute("UPDATE teachers SET panel_failed = 0, panel_locked_until = NULL WHERE id = ?", (row["id"],))
    token = _token(row["id"], row["panel_pw_changed"], secret)
    return {"token": token, "institute": row["id"], "must_change": bool(row["panel_must_change"])}


def _token(institute: str, pw_version, secret: str) -> str:
    """pv = the password's version: a new password (or a reset) ends every login made with the old one."""
    now = int(time.time())
    return jwt.encode({"inst": institute, "pv": pw_version or 0, "iat": now, "exp": now + SESSION_HOURS * 3600},
                      secret, algorithm="HS256")


def read(db: Database, token: str, secret: str) -> str:
    try:
        data = jwt.decode(token, secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise InstituteAuthError("Please log in again")
    inst = data.get("inst")
    if not inst:
        raise InstituteAuthError("Please log in again")
    row = db.one("SELECT panel_pw_changed FROM teachers WHERE id = ?", (inst,))
    if row is None or (data.get("pv") or 0) != (row["panel_pw_changed"] or 0):
        raise InstituteAuthError("Please log in again")
    return inst


def change_password(db: Database, institute: str, current: str, new: str, secret: str) -> str:
    """Every older login ends; the one that changed the password gets a fresh login (returned)."""
    row = db.one("SELECT panel_password_hash FROM teachers WHERE id = ?", (institute,))
    if not row or not row["panel_password_hash"] or not admin_auth.check_password(current or "", row["panel_password_hash"]):
        raise InstituteAuthError("Your current password is not right")
    try:
        admin_auth.validate_password(new or "")   # same rule as Dhurina's team
    except admin_auth.LoginError as exc:
        raise InstituteAuthError(str(exc))
    version = time.time()
    db.execute("UPDATE teachers SET panel_password_hash = ?, panel_must_change = 0, panel_pw_changed = ? WHERE id = ?",
               (admin_auth.hash_password(new), version, institute))
    return _token(institute, version, secret)
