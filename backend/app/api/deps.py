import uuid
from collections.abc import Callable

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.errors import ForbiddenError, UnauthorizedError
from app.core.security import decode_access_token
from app.db.models.user import User
from app.db.session import get_db
from app.repositories.user_repository import UserRepository

_bearer_scheme = HTTPBearer(auto_error=False)


def get_client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise UnauthorizedError("Authentication required.", code="NOT_AUTHENTICATED")

    payload = decode_access_token(credentials.credentials)
    if payload is None:
        raise UnauthorizedError("Invalid or expired access token.", code="INVALID_TOKEN")

    try:
        user_id = uuid.UUID(payload["sub"])
    except (KeyError, ValueError, TypeError) as exc:
        raise UnauthorizedError("Invalid or expired access token.", code="INVALID_TOKEN") from exc

    user = UserRepository(db).get_by_id(user_id)
    if user is None or not user.is_active:
        raise UnauthorizedError("Invalid or expired access token.", code="INVALID_TOKEN")

    return user


def require_roles(*allowed_roles: str) -> Callable[[User], User]:
    def _check(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed_roles:
            raise ForbiddenError("You do not have permission to perform this action.")
        return user

    return _check
