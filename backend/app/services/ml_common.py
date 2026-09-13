"""Shared plumbing between `forecast_service.py` and `backtest_service.py`
— both need the same registered-model loading/caching and the same
`ml.inference.serving.ServingError` -> `AppError` mapping. Nothing here
runs training; both callers only ever load already-trained artifacts and
call `.predict()` (ADR-001)."""

from __future__ import annotations

from pathlib import Path

from ml.inference import serving

from app.core.config import get_settings
from app.core.errors import AppError


class ModelUnavailableError(AppError):
    status_code = 503
    code = "MODEL_UNAVAILABLE"


class InsufficientHistoryError(AppError):
    status_code = 422
    code = "INSUFFICIENT_HISTORY"


class UnsupportedTickerError(AppError):
    status_code = 422
    code = "UNSUPPORTED_TICKER"


class DataValidationFailedError(AppError):
    status_code = 422
    code = "DATA_VALIDATION_FAILED"


def wrap_serving_error(exc: serving.ServingError) -> AppError:
    if isinstance(exc, serving.ModelUnavailableError):
        return ModelUnavailableError(str(exc))
    if isinstance(exc, serving.UnsupportedTickerError):
        return UnsupportedTickerError(str(exc))
    if isinstance(exc, serving.InsufficientHistoryError):
        return InsufficientHistoryError(str(exc))
    if isinstance(exc, serving.DataValidationFailedError):
        return DataValidationFailedError(str(exc))
    return AppError(str(exc))  # pragma: no cover - exhaustive by construction


# In-process cache of loaded model artifacts, keyed by registry path and
# invalidated by the registry file's mtime — avoids re-reading/deserializing
# XGBoost artifacts from disk on every single request while still picking
# up a new training run (a new `registry.json`/artifacts) without a
# restart. Never caches predictions themselves — every request still calls
# `.predict()` fresh.
_models_cache: dict[str, tuple[float | None, serving.ForecastModels]] = {}


def load_models() -> serving.ForecastModels:
    registry_path = Path(get_settings().ml_registry_path)
    key = str(registry_path)
    mtime = registry_path.stat().st_mtime if registry_path.exists() else None
    cached = _models_cache.get(key)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    models = serving.load_forecast_models(registry_path)
    _models_cache[key] = (mtime, models)
    return models
