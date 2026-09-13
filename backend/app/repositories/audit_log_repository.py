import uuid

from sqlalchemy.orm import Session

from app.db.models.audit_log import AuditLog


class AuditLogRepository:
    def __init__(self, db: Session):
        self.db = db

    def record(
        self,
        *,
        action: str,
        user_id: uuid.UUID | None,
        ip_address: str | None,
        meta: dict | None = None,
    ) -> AuditLog:
        entry = AuditLog(action=action, user_id=user_id, ip_address=ip_address, meta=meta)
        self.db.add(entry)
        self.db.flush()
        return entry
