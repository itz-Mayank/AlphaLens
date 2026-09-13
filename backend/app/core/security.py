"""Password hashing, JWT issuance/verification, and opaque-token helpers.

Access tokens are short-lived JWTs returned in the response body and kept in
memory client-side. Refresh tokens and password-reset tokens are opaque
random strings; only their SHA-256 hash is ever persisted, so a database
leak does not expose usable tokens (same rationale as password hashing).
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import get_settings

settings = get_settings()

_pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")


class TokenType(StrEnum):
    ACCESS = "access"
    REFRESH = "refresh"


def hash_password(plain_password: str) -> str:
    return _pwd_context.hash(plain_password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    return _pwd_context.verify(plain_password, password_hash)


def generate_opaque_token() -> str:
    """A high-entropy, URL-safe token for refresh/reset tokens (raw, unhashed)."""
    return secrets.token_urlsafe(48)


def hash_opaque_token(raw_token: str) -> str:
    """Deterministic hash used to look up an opaque token without storing it raw."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def create_access_token(*, user_id: str, role: str) -> tuple[str, datetime]:
    expires_at = datetime.now(UTC) + timedelta(minutes=settings.access_token_expire_minutes)
    payload: dict[str, Any] = {
        "sub": user_id,
        "role": role,
        "type": TokenType.ACCESS.value,
        "exp": expires_at,
        "iat": datetime.now(UTC),
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, expires_at


def decode_access_token(token: str) -> dict[str, Any] | None:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None
    if payload.get("type") != TokenType.ACCESS.value:
        return None
    return payload
