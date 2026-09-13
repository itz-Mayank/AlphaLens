"""The inference-side interface: `Model.predict(features) -> PredictionResult`.
Not wired to FastAPI — see docs/ml-pipeline.md 'Training vs inference' and
docs/decisions.md ADR-001. A future backend integration imports from here
(`ml.inference`) for synchronous forecast serving, never from
`ml.pipelines`/`ml.models.*.model` training code, mirroring how
`app/services/market_data_service.py` is the only thing the backend
imports from `ml/` in this codebase's design — except here it'll be the
reverse direction, backend importing ml.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime


@dataclass(frozen=True)
class PredictionResult:
    ticker: str
    as_of: date
    model_name: str
    model_version: str
    feature_set_version: str
    prediction_timestamp: datetime
    expected_return: float | None = None
    predicted_class: str | None = None
    class_probabilities: dict[str, float] | None = None

    def as_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "as_of": self.as_of.isoformat(),
            "model_name": self.model_name,
            "model_version": self.model_version,
            "feature_set_version": self.feature_set_version,
            "prediction_timestamp": self.prediction_timestamp.isoformat(),
            "expected_return": self.expected_return,
            "predicted_class": self.predicted_class,
            "class_probabilities": self.class_probabilities,
        }


def predict_return(
    model,
    features,
    *,
    ticker: str,
    as_of: date,
    model_name: str,
    model_version: str,
    feature_set_version: str,
) -> PredictionResult:
    """`model` must expose `.predict(features) -> array-like` returning
    exactly one value for one row/sequence of input."""
    prediction = model.predict(features)
    return PredictionResult(
        ticker=ticker,
        as_of=as_of,
        model_name=model_name,
        model_version=model_version,
        feature_set_version=feature_set_version,
        prediction_timestamp=datetime.now(UTC),
        expected_return=float(prediction[0]),
    )


def predict_direction(
    model,
    features,
    *,
    ticker: str,
    as_of: date,
    model_name: str,
    model_version: str,
    feature_set_version: str,
    class_names: tuple[str, ...],
) -> PredictionResult:
    """`model` must expose `.predict(features)` and, for probabilities,
    `.predict_proba(features)` (e.g. `XGBoostDirectionModel`) — a baseline
    without calibrated probabilities simply omits `class_probabilities`
    rather than fabricating uniform/fake ones."""
    predicted_class = str(model.predict(features)[0])
    probabilities = None
    if hasattr(model, "predict_proba"):
        proba_row = model.predict_proba(features)[0]
        probabilities = dict(zip(class_names, (float(p) for p in proba_row), strict=True))

    return PredictionResult(
        ticker=ticker,
        as_of=as_of,
        model_name=model_name,
        model_version=model_version,
        feature_set_version=feature_set_version,
        prediction_timestamp=datetime.now(UTC),
        predicted_class=predicted_class,
        class_probabilities=probabilities,
    )
