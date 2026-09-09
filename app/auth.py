"""Identidade, senhas e sessões opacas do ManaPonte."""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import time
from pathlib import Path

from .db import get_connection

USERNAME_RE = re.compile(r"^[a-z0-9_.-]{3,30}$")
EMAIL_RE = re.compile(r"^[^\s@]{1,64}@[a-z0-9.-]{1,190}\.[a-z]{2,63}$")
SCRYPT_N, SCRYPT_R, SCRYPT_P, DKLEN = 2**14, 8, 1, 32
DEFAULT_SESSION_TTL = 7 * 24 * 60 * 60


def normalize_email(value: str) -> str:
    return str(value).strip().casefold()


def normalize_username(value: str) -> str:
    return str(value).strip().casefold()


def valid_email(value: str) -> bool:
    return len(value) <= 254 and EMAIL_RE.fullmatch(value) is not None


def valid_username(value: str) -> bool:
    return USERNAME_RE.fullmatch(value) is not None


def validate_password(password: str) -> bool:
    if not isinstance(password, str) or not 12 <= len(password) <= 128:
        return False
    return all((any(c.islower() for c in password), any(c.isupper() for c in password),
                any(c.isdigit() for c in password), any(not c.isalnum() for c in password)))


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=SCRYPT_N,
                             r=SCRYPT_R, p=SCRYPT_P, dklen=DKLEN)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(derived)}"


def verify_password(password: str, encoded: str | None) -> bool:
    try:
        algorithm, n, r, p, salt, expected = encoded.split("$", 5)
        n, r, p = int(n), int(r), int(p)
        if algorithm != "scrypt" or n < 2**14 or n > 2**18 or r not in range(1, 17) or p not in range(1, 9):
            return False
        derived = hashlib.scrypt(password.encode("utf-8"), salt=_unb64(salt), n=n,
                                 r=r, p=p, dklen=len(_unb64(expected)))
        return hmac.compare_digest(derived, _unb64(expected))
    except (AttributeError, TypeError, ValueError):
        return False


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(user_id: int, db_path: str | Path | None = None,
                   ttl: int = DEFAULT_SESSION_TTL) -> dict:
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
    now = int(time.time())
    connection = get_connection(db_path)
    try:
        connection.execute("DELETE FROM sessions WHERE expires_at<=?", (now,))
        connection.execute(
            "INSERT INTO sessions(token_hash,user_id,csrf_token,created_at,expires_at) VALUES(?,?,?,?,?)",
            (_token_hash(token), user_id, csrf, now, now + max(60, ttl)))
        connection.commit()
    finally:
        connection.close()
    return {"token": token, "csrf_token": csrf, "expires_at": now + max(60, ttl)}


def get_session(token: str | None, db_path: str | Path | None = None) -> dict | None:
    if not token:
        return None
    connection = get_connection(db_path)
    try:
        row = connection.execute(
            """SELECT s.user_id,s.csrf_token,s.expires_at,u.username,u.email,u.display_name,
                      u.city,u.state,u.email_verified
               FROM sessions s JOIN users u ON u.id=s.user_id
               WHERE s.token_hash=? AND s.expires_at>?""",
            (_token_hash(token), int(time.time()))).fetchone()
        return dict(row) if row else None
    finally:
        connection.close()


def csrf_matches(session: dict | None, supplied: str | None) -> bool:
    return bool(session and supplied and hmac.compare_digest(session["csrf_token"], supplied))


def revoke_session(token: str | None, db_path: str | Path | None = None) -> bool:
    if not token:
        return False
    connection = get_connection(db_path)
    try:
        cursor = connection.execute("DELETE FROM sessions WHERE token_hash=?", (_token_hash(token),))
        connection.commit()
        return cursor.rowcount == 1
    finally:
        connection.close()


def delete_expired_sessions(db_path: str | Path | None = None, now: int | None = None) -> int:
    connection = get_connection(db_path)
    try:
        cursor = connection.execute("DELETE FROM sessions WHERE expires_at<=?", (now or int(time.time()),))
        connection.commit()
        return cursor.rowcount
    finally:
        connection.close()
