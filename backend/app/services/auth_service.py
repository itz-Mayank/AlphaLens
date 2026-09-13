"""Registration, login, token refresh/rotation, and password reset.

Token strategy (docs/decisions.md ADR-005): short-lived JWT access tokens
are returned in the response body only; opaque refresh tokens are set as an
httpOnly cookie and rotated on every use (old session row revoked, new one
created) so token reuse after theft is detectable. Only hashes of
refresh/reset tokens are ever persisted — see app.core.security.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import ConflictError, UnauthorizedError
from app.core.security import (
    create_access_token,
    generate_opaque_token,
    hash_opaque_token,
    hash_password,
    verify_password,
)
from app.db.models.audit_log import AuditAction
from app.db.models.user import User
from app.providers.email import get_email_provider
from app.repositories.audit_log_repository import AuditLogRepository
from app.repositories.password_reset_repository import PasswordResetRepository
from app.repositories.session_repository import SessionRepository
from app.repositories.user_repository import UserRepository

settings = get_settings()


@dataclass
class IssuedTokens:
    access_token: str
    access_token_expires_in: int
    refresh_token: str
    refresh_token_expires_at: datetime


class AuthService:
    def __init__(self, db: Session):
        self.db = db
        self.users = UserRepository(db)
        self.sessions = SessionRepository(db)
        self.resets = PasswordResetRepository(db)
        self.audit = AuditLogRepository(db)

    def _issue_tokens(
        self, user: User, *, user_agent: str | None, ip_address: str | None
    ) -> IssuedTokens:
        access_token, access_expires_at = create_access_token(user_id=str(user.id), role=user.role)
        refresh_token = generate_opaque_token()
        refresh_expires_at = datetime.now(UTC) + timedelta(days=settings.refresh_token_expire_days)
        self.sessions.create(
            user_id=user.id,
            refresh_token_hash=hash_opaque_token(refresh_token),
            expires_at=refresh_expires_at,
            user_agent=user_agent,
            ip_address=ip_address,
        )
        access_expires_in = int((access_expires_at - datetime.now(UTC)).total_seconds())
        return IssuedTokens(
            access_token=access_token,
            access_token_expires_in=access_expires_in,
            refresh_token=refresh_token,
            refresh_token_expires_at=refresh_expires_at,
        )

    def register(
        self,
        *,
        email: str,
        password: str,
        full_name: str,
        user_agent: str | None,
        ip_address: str | None,
    ) -> tuple[User, IssuedTokens]:
        if self.users.get_by_email(email) is not None:
            raise ConflictError("An account with this email already exists.", code="EMAIL_TAKEN")

        user = self.users.create(
            email=email, password_hash=hash_password(password), full_name=full_name
        )
        tokens = self._issue_tokens(user, user_agent=user_agent, ip_address=ip_address)
        self.audit.record(action=AuditAction.REGISTER, user_id=user.id, ip_address=ip_address)
        return user, tokens

    def login(
        self, *, email: str, password: str, user_agent: str | None, ip_address: str | None
    ) -> tuple[User, IssuedTokens]:
        user = self.users.get_by_email(email)
        if user is None or not verify_password(password, user.password_hash):
            self.audit.record(
                action=AuditAction.LOGIN_FAILED,
                user_id=user.id if user else None,
                ip_address=ip_address,
                meta={"email": email.lower()},
            )
            raise UnauthorizedError("Incorrect email or password.", code="INVALID_CREDENTIALS")
        if not user.is_active:
            raise UnauthorizedError("This account has been deactivated.", code="ACCOUNT_INACTIVE")

        tokens = self._issue_tokens(user, user_agent=user_agent, ip_address=ip_address)
        self.audit.record(action=AuditAction.LOGIN, user_id=user.id, ip_address=ip_address)
        return user, tokens

    def refresh(
        self, *, raw_refresh_token: str, user_agent: str | None, ip_address: str | None
    ) -> tuple[User, IssuedTokens]:
        token_hash = hash_opaque_token(raw_refresh_token)
        session = self.sessions.get_by_token_hash(token_hash)
        if session is None or not self.sessions.is_valid(session):
            raise UnauthorizedError("Session expired or revoked.", code="INVALID_REFRESH_TOKEN")

        user = self.users.get_by_id(session.user_id)
        if user is None or not user.is_active:
            raise UnauthorizedError("Session expired or revoked.", code="INVALID_REFRESH_TOKEN")

        # Rotate: revoke the used token and issue a fresh pair.
        self.sessions.revoke(session)
        tokens = self._issue_tokens(user, user_agent=user_agent, ip_address=ip_address)
        return user, tokens

    def logout(self, *, raw_refresh_token: str | None, ip_address: str | None) -> None:
        user_id: uuid.UUID | None = None
        if raw_refresh_token:
            session = self.sessions.get_by_token_hash(hash_opaque_token(raw_refresh_token))
            if session is not None:
                user_id = session.user_id
                self.sessions.revoke(session)
        self.audit.record(action=AuditAction.LOGOUT, user_id=user_id, ip_address=ip_address)

    def forgot_password(self, *, email: str, ip_address: str | None) -> None:
        user = self.users.get_by_email(email)
        # Always behave identically whether the account exists or not, so
        # this endpoint cannot be used to enumerate registered emails.
        if user is not None:
            raw_token = generate_opaque_token()
            expires_at = datetime.now(UTC) + timedelta(
                minutes=settings.password_reset_token_expire_minutes
            )
            self.resets.create(
                user_id=user.id, token_hash=hash_opaque_token(raw_token), expires_at=expires_at
            )
            reset_link = f"{settings.frontend_base_url}/reset-password?token={raw_token}"
            get_email_provider().send(
                to=user.email,
                subject="Reset your AlphaLens password",
                body=(
                    f"Use this link to reset your password (valid for "
                    f"{settings.password_reset_token_expire_minutes} minutes): {reset_link}"
                ),
            )
            self.audit.record(
                action=AuditAction.PASSWORD_RESET_REQUESTED, user_id=user.id, ip_address=ip_address
            )

    def reset_password(self, *, raw_token: str, new_password: str, ip_address: str | None) -> None:
        invalid_token_error = UnauthorizedError(
            "This reset link is invalid or has expired.", code="INVALID_RESET_TOKEN"
        )
        token = self.resets.get_by_token_hash(hash_opaque_token(raw_token))
        if token is None or not self.resets.is_valid(token):
            raise invalid_token_error

        user = self.users.get_by_id(token.user_id)
        if user is None:
            raise invalid_token_error

        user.password_hash = hash_password(new_password)
        self.resets.mark_used(token)
        self.sessions.revoke_all_for_user(user.id)
        self.audit.record(
            action=AuditAction.PASSWORD_RESET_COMPLETED, user_id=user.id, ip_address=ip_address
        )

    def change_password(
        self, *, user: User, current_password: str, new_password: str, ip_address: str | None
    ) -> None:
        if not verify_password(current_password, user.password_hash):
            raise UnauthorizedError("Current password is incorrect.", code="INVALID_CREDENTIALS")
        user.password_hash = hash_password(new_password)
        self.sessions.revoke_all_for_user(user.id)
        self.audit.record(
            action=AuditAction.PASSWORD_CHANGE, user_id=user.id, ip_address=ip_address
        )

    def delete_account(self, *, user: User, password: str, ip_address: str | None) -> None:
        if not verify_password(password, user.password_hash):
            raise UnauthorizedError("Incorrect password.", code="INVALID_CREDENTIALS")
        self.audit.record(
            action=AuditAction.ACCOUNT_DELETED, user_id=user.id, ip_address=ip_address
        )
        self.users.delete(user)
