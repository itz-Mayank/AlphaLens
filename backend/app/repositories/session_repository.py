import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.auth_session import AuthSession


class SessionRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(
        self,
        *,
        user_id: uuid.UUID,
        refresh_token_hash: str,
        expires_at: datetime,
        user_agent: str | None,
        ip_address: str | None,
    ) -> AuthSession:
        session = AuthSession(
            user_id=user_id,
            refresh_token_hash=refresh_token_hash,
            expires_at=expires_at,
            user_agent=user_agent,
            ip_address=ip_address,
        )
        self.db.add(session)
        self.db.flush()
        return session

    def get_by_token_hash(self, refresh_token_hash: str) -> AuthSession | None:
        stmt = select(AuthSession).where(AuthSession.refresh_token_hash == refresh_token_hash)
        return self.db.execute(stmt).scalar_one_or_none()

    def revoke(self, session: AuthSession) -> None:
        session.revoked_at = datetime.now(UTC)

    def revoke_all_for_user(self, user_id: uuid.UUID) -> None:
        stmt = select(AuthSession).where(
            AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None)
        )
        for session in self.db.execute(stmt).scalars():
            session.revoked_at = datetime.now(UTC)

    @staticmethod
    def is_valid(session: AuthSession) -> bool:
        return session.revoked_at is None and session.expires_at > datetime.now(UTC)
