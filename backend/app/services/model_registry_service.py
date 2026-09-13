"""Read-only wrapper around `ml.registry.registry.ModelRegistry` — the ONE
place in `backend/app` that imports `ml.registry` directly, mirroring
`ml_common.py`'s equivalent role for `ml.inference.serving` (see ADR-001).
Never mutates the registry: promotion/status changes only ever happen
inside `ml.pipelines.train_pipeline` (via `ml.registry.promotion`),
reachable from the backend only through
`app/services/retraining_service.py`'s background-only path.
"""

from __future__ import annotations

from pathlib import Path

from ml.registry.registry import ModelRegistry

from app.core.config import get_settings


def _registry() -> ModelRegistry:
    return ModelRegistry(Path(get_settings().ml_registry_path))


def list_all_models() -> list[dict]:
    return _registry().list_all()


def get_active_model(model_type: str) -> dict | None:
    return _registry().get_active(model_type)
