"""Encrypts teachers' Razorpay secrets before they are stored. Key comes from SECRETS_KEY in .env.
Values are stored as 'enc:<token>'; old plain values still read correctly."""
import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken


def _fernet() -> Fernet:
    raw = os.environ.get("SECRETS_KEY") or os.environ.get("JWT_SECRET", "change-me")
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(raw.encode()).digest()))


def seal(value: str | None) -> str | None:
    if not value:
        return value
    return "enc:" + _fernet().encrypt(value.encode()).decode()


def unseal(value: str | None) -> str | None:
    if not value or not value.startswith("enc:"):
        return value
    try:
        return _fernet().decrypt(value[4:].encode()).decode()
    except InvalidToken:
        return None


def mask(value: str | None) -> str:
    plain = unseal(value)
    return "" if not plain else "••••" + plain[-4:]
