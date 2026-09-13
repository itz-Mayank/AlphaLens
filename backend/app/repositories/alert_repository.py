import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.alert import Alert, AlertEvent


class AlertRepository:
    """`get_for_user`/`list_for_user` are ownership-scoped the same way as
    `WatchlistRepository`/`PortfolioRepository`. `list_enabled_for_evaluation`
    is deliberately NOT user-scoped — the Celery evaluator runs once for
    every enabled alert across every user, which is exactly its job (see
    `app/services/alert_evaluation_service.py`)."""

    def __init__(self, db: Session):
        self.db = db

    def create(
        self,
        *,
        user_id: uuid.UUID,
        security_id: int,
        alert_type: str,
        config: dict,
        cooldown_minutes: int,
    ) -> Alert:
        alert = Alert(
            user_id=user_id,
            security_id=security_id,
            alert_type=alert_type,
            config=config,
            cooldown_minutes=cooldown_minutes,
        )
        self.db.add(alert)
        self.db.flush()
        return alert

    def get_for_user(self, *, alert_id: uuid.UUID, user_id: uuid.UUID) -> Alert | None:
        stmt = select(Alert).where(Alert.id == alert_id, Alert.user_id == user_id)
        return self.db.execute(stmt).scalar_one_or_none()

    def list_for_user(self, *, user_id: uuid.UUID) -> list[Alert]:
        stmt = (
            select(Alert)
            .where(Alert.user_id == user_id)
            .order_by(Alert.created_at.asc(), Alert.id.asc())
        )
        return list(self.db.execute(stmt).scalars())

    def delete(self, alert: Alert) -> None:
        self.db.delete(alert)

    def list_enabled_for_evaluation(self) -> list[Alert]:
        stmt = select(Alert).where(Alert.enabled.is_(True)).order_by(Alert.id.asc())
        return list(self.db.execute(stmt).scalars())

    def mark_triggered(self, alert: Alert, *, triggered_at: datetime) -> None:
        alert.last_triggered_at = triggered_at

    def update_last_observed_state(self, alert: Alert, *, state: dict) -> None:
        alert.last_observed_state = state

    def create_event(
        self,
        *,
        alert_id: uuid.UUID,
        triggered_at: datetime,
        observed_value: dict,
        message: str,
    ) -> AlertEvent:
        event = AlertEvent(
            alert_id=alert_id,
            triggered_at=triggered_at,
            observed_value=observed_value,
            message=message,
        )
        self.db.add(event)
        self.db.flush()
        return event

    def list_events_for_alert(
        self, *, alert_id: uuid.UUID, limit: int, offset: int
    ) -> tuple[list[AlertEvent], int]:
        count_stmt = select(func.count()).select_from(AlertEvent).where(
            AlertEvent.alert_id == alert_id
        )
        total = self.db.execute(count_stmt).scalar_one()

        stmt = (
            select(AlertEvent)
            .where(AlertEvent.alert_id == alert_id)
            .order_by(AlertEvent.triggered_at.desc(), AlertEvent.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(self.db.execute(stmt).scalars()), total
