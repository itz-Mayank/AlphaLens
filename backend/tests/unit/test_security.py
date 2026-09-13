from datetime import UTC, datetime, timedelta

from app.api.deps import require_roles
from app.core.config import get_settings
from app.core.errors import ForbiddenError
from app.core.security import (
    TokenType,
    create_access_token,
    decode_access_token,
    generate_opaque_token,
    hash_opaque_token,
    hash_password,
    verify_password,
)
from app.db.models.user import UserRole
from jose import jwt

settings = get_settings()


class _FakeUser:
    def __init__(self, role: str):
        self.role = role


def test_hash_password_roundtrip():
    hashed = hash_password("correct-horse-9")
    assert hashed != "correct-horse-9"
    assert verify_password("correct-horse-9", hashed)
    assert not verify_password("wrong-password", hashed)


def test_hash_password_is_salted():
    assert hash_password("same-password-1") != hash_password("same-password-1")


def test_opaque_token_is_unique_and_hash_is_deterministic():
    token_a = generate_opaque_token()
    token_b = generate_opaque_token()
    assert token_a != token_b
    assert hash_opaque_token(token_a) == hash_opaque_token(token_a)
    assert hash_opaque_token(token_a) != hash_opaque_token(token_b)


def test_access_token_roundtrip():
    token, expires_at = create_access_token(user_id="user-123", role=UserRole.ANALYST)
    payload = decode_access_token(token)
    assert payload is not None
    assert payload["sub"] == "user-123"
    assert payload["role"] == UserRole.ANALYST
    assert expires_at > datetime.now(UTC)


def test_decode_access_token_rejects_garbage():
    assert decode_access_token("not-a-jwt") is None


def test_decode_access_token_rejects_expired_token():
    payload = {
        "sub": "user-123",
        "role": UserRole.USER,
        "type": TokenType.ACCESS.value,
        "exp": datetime.now(UTC) - timedelta(minutes=1),
        "iat": datetime.now(UTC) - timedelta(minutes=16),
    }
    expired = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    assert decode_access_token(expired) is None


def test_decode_access_token_rejects_wrong_token_type():
    payload = {
        "sub": "user-123",
        "role": UserRole.USER,
        "type": TokenType.REFRESH.value,
        "exp": datetime.now(UTC) + timedelta(minutes=5),
        "iat": datetime.now(UTC),
    }
    refresh_shaped = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    assert decode_access_token(refresh_shaped) is None


def test_require_roles_allows_matching_role():
    check = require_roles(UserRole.ADMIN, UserRole.ANALYST)
    admin = _FakeUser(UserRole.ADMIN)
    assert check(user=admin) is admin


def test_require_roles_rejects_non_matching_role():
    check = require_roles(UserRole.ADMIN)
    try:
        check(user=_FakeUser(UserRole.USER))
        raise AssertionError("expected ForbiddenError")
    except ForbiddenError:
        pass
