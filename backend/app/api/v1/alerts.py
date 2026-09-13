import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.errors import NotFoundError
from app.db.models.user import User
from app.db.session import get_db
from app.repositories.alert_repository import AlertRepository
from app.repositories.security_repository import SecurityRepository
from app.schemas.alert import AlertCreate, AlertEventRead, AlertRead, AlertUpdate
from app.schemas.common import Page

router = APIRouter()


def _get_alert_for_user_or_404(db: Session, *, alert_id: uuid.UUID, user_id: uuid.UUID):  # noqa: ANN201
    alert = AlertRepository(db).get_for_user(alert_id=alert_id, user_id=user_id)
    if alert is None:
        raise NotFoundError("Alert not found.", code="ALERT_NOT_FOUND")
    return alert


def _alert_read(alert, ticker: str) -> AlertRead:  # noqa: ANN001 - Alert ORM row
    return AlertRead(
        id=alert.id,
        ticker=ticker,
        alert_type=alert.alert_type,
        config=alert.config,
        enabled=alert.enabled,
        cooldown_minutes=alert.cooldown_minutes,
        last_triggered_at=alert.last_triggered_at,
        created_at=alert.created_at,
        updated_at=alert.updated_at,
    )


@router.post("", response_model=AlertRead, status_code=status.HTTP_201_CREATED)
def create_alert(
    body: AlertCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AlertRead:
    security = SecurityRepository(db).get_by_ticker(body.ticker)
    if security is None:
        raise NotFoundError(
            f"No stock found for ticker '{body.ticker.upper()}'.", code="STOCK_NOT_FOUND"
        )

    config_dict = body.config.model_dump(exclude={"alert_type"})
    alert = AlertRepository(db).create(
        user_id=user.id,
        security_id=security.id,
        alert_type=body.config.alert_type,
        config=config_dict,
        cooldown_minutes=body.cooldown_minutes,
    )
    db.commit()
    return _alert_read(alert, security.ticker)


@router.get("", response_model=list[AlertRead])
def list_alerts(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[AlertRead]:
    alerts = AlertRepository(db).list_for_user(user_id=user.id)
    if not alerts:
        return []
    securities_by_id = {
        s.id: s for s in SecurityRepository(db).get_by_ids([a.security_id for a in alerts])
    }
    return [
        _alert_read(
            a,
            securities_by_id[a.security_id].ticker
            if a.security_id in securities_by_id
            else "UNKNOWN",
        )
        for a in alerts
    ]


@router.patch("/{alert_id}", response_model=AlertRead)
def update_alert(
    alert_id: uuid.UUID,
    body: AlertUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AlertRead:
    alert = _get_alert_for_user_or_404(db, alert_id=alert_id, user_id=user.id)
    if body.enabled is not None:
        alert.enabled = body.enabled
    if body.cooldown_minutes is not None:
        alert.cooldown_minutes = body.cooldown_minutes
    db.commit()
    security = SecurityRepository(db).get_by_ids([alert.security_id])
    ticker = security[0].ticker if security else "UNKNOWN"
    return _alert_read(alert, ticker)


@router.delete("/{alert_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_alert(
    alert_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    alert = _get_alert_for_user_or_404(db, alert_id=alert_id, user_id=user.id)
    AlertRepository(db).delete(alert)
    db.commit()


@router.get("/{alert_id}/events", response_model=Page[AlertEventRead])
def list_alert_events(
    alert_id: uuid.UUID,
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Page[AlertEventRead]:
    _get_alert_for_user_or_404(db, alert_id=alert_id, user_id=user.id)
    events, total = AlertRepository(db).list_events_for_alert(
        alert_id=alert_id, limit=limit, offset=offset
    )
    items = [AlertEventRead.model_validate(e, from_attributes=True) for e in events]
    return Page[AlertEventRead](items=items, total=total, limit=limit, offset=offset)
