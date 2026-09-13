from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.prediction import Prediction


class PredictionRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(
        self,
        *,
        security_id: int,
        model_type: str,
        model_version: str,
        feature_version: str,
        as_of_date: date,
        horizon_days: int,
        predicted_return: Decimal | None,
        predicted_class: str | None,
        predicted_probabilities: dict | None,
        prediction_timestamp: datetime,
    ) -> Prediction:
        prediction = Prediction(
            security_id=security_id,
            model_type=model_type,
            model_version=model_version,
            feature_version=feature_version,
            as_of_date=as_of_date,
            horizon_days=horizon_days,
            predicted_return=predicted_return,
            predicted_class=predicted_class,
            predicted_probabilities=predicted_probabilities,
            prediction_timestamp=prediction_timestamp,
        )
        self.db.add(prediction)
        self.db.flush()
        return prediction

    def list_unevaluated(self, *, limit: int = 500) -> list[Prediction]:
        """Oldest first, capped — `evaluate_matured_predictions` runs on a
        schedule and re-checks whatever wasn't matured last time; a cap
        keeps one evaluation cycle bounded even if a large backlog ever
        builds up (e.g. after price ingestion was paused for a while)."""
        stmt = (
            select(Prediction)
            .where(Prediction.evaluated_at.is_(None))
            .order_by(Prediction.as_of_date.asc(), Prediction.id.asc())
            .limit(limit)
        )
        return list(self.db.execute(stmt).scalars())

    def mark_evaluated(
        self,
        prediction: Prediction,
        *,
        realized_return: Decimal,
        realized_direction: str,
        evaluated_at: datetime,
    ) -> None:
        prediction.realized_return = realized_return
        prediction.realized_direction = realized_direction
        prediction.evaluated_at = evaluated_at

    def list_evaluated(self, *, model_type: str, since: datetime | None = None) -> list[Prediction]:
        stmt = select(Prediction).where(
            Prediction.model_type == model_type, Prediction.evaluated_at.is_not(None)
        )
        if since is not None:
            stmt = stmt.where(Prediction.evaluated_at >= since)
        stmt = stmt.order_by(Prediction.evaluated_at.asc())
        return list(self.db.execute(stmt).scalars())

    def count_all(self, *, model_type: str) -> int:
        stmt = select(Prediction).where(Prediction.model_type == model_type)
        return len(list(self.db.execute(stmt).scalars()))
