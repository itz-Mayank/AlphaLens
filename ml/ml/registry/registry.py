"""A lightweight, file-backed model registry — deliberately not MLflow:
nothing here needs a tracking server, a database, or a UI yet, and a plain
JSON file is trivially inspectable, diffable, and dependency-free. See
docs/decisions.md for the ADR on this choice and what would justify
reconsidering it later (many more models, multiple people training
concurrently, a real need for a comparison UI).
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path


class ModelStatus:
    TRAINING = "TRAINING"
    # Trained and evaluated, metrics computed — NOT yet eligible to be
    # served. Becoming PRODUCTION requires passing the promotion gate
    # (see ml/registry/promotion.py) — training succeeding is necessary
    # but never sufficient (Phase 10 ADR).
    VALIDATED = "VALIDATED"
    STAGING = "STAGING"
    # The one status `ml.inference.serving.load_forecast_models` will
    # actually load — see that module's docstring.
    PRODUCTION = "PRODUCTION"
    # A model that used to be PRODUCTION, superseded by a later promotion.
    ARCHIVED = "ARCHIVED"
    # Trained successfully but rejected by the promotion gate (didn't beat
    # its baseline, or regressed against the current PRODUCTION model).
    FAILED = "FAILED"


def compute_artifact_checksum(path: Path) -> str | None:
    """SHA-256 over every file directly inside `path` (sorted by name, so
    the result is deterministic regardless of filesystem iteration order),
    concatenated as `name:hexdigest` per file. Generic across model types
    on purpose — XGBoost saves `model.json`, LSTM/GRU save `weights.pt` +
    `scaler.npz` + `config.json`; hashing "every file in the artifact
    directory" needs no per-model-type special-casing. Returns `None` if
    `path` doesn't exist or contains no files (never a fabricated
    checksum for a missing artifact).
    """
    if not path.exists() or not path.is_dir():
        return None
    files = sorted(p for p in path.iterdir() if p.is_file())
    if not files:
        return None
    digest = hashlib.sha256()
    for file_path in files:
        digest.update(file_path.name.encode("utf-8"))
        digest.update(file_path.read_bytes())
    return digest.hexdigest()


@dataclass
class ModelRecord:
    model_name: str
    model_type: str
    version: str
    dataset_version: str
    feature_version: str
    hyperparameters: dict
    train_period: tuple[str, str]
    validation_period: tuple[str, str]
    test_period: tuple[str, str]
    metrics: dict
    artifact_path: str
    created_at: str
    git_commit: str | None
    status: str
    # SHA-256 over the artifact directory's files — `None` only for records
    # with no artifact (e.g. a baseline that isn't actually saved to disk).
    # Set at registration time; `ModelRegistry.verify_artifact_integrity`
    # recomputes it at load time to detect a tampered/corrupted artifact.
    artifact_checksum: str | None = None
    # Human-readable justification for the current `status` — set whenever
    # `set_status` changes it (e.g. "beat baseline MAE 0.0209 -> 0.0203",
    # "rejected: regressed vs current PRODUCTION f1_macro"). `None` only for
    # a record that has never had its status changed since registration.
    status_reason: str | None = None
    record_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def as_dict(self) -> dict:
        return asdict(self)


def get_git_commit() -> str | None:
    """Best-effort — `None` (never a fabricated placeholder) if this isn't
    a git checkout or `git` isn't on `PATH`."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5, check=True
        )
        return result.stdout.strip()
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return None


class ModelRegistry:
    def __init__(self, registry_path: Path):
        self.registry_path = registry_path
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.registry_path.exists():
            self.registry_path.write_text("[]")

    def _read_all(self) -> list[dict]:
        return json.loads(self.registry_path.read_text())

    def _write_all(self, records: list[dict]) -> None:
        self.registry_path.write_text(json.dumps(records, indent=2, default=str))

    def register(self, record: ModelRecord) -> None:
        records = self._read_all()
        records.append(record.as_dict())
        self._write_all(records)

    def list_all(self) -> list[dict]:
        return self._read_all()

    def get(self, record_id: str) -> dict | None:
        for record in self._read_all():
            if record["record_id"] == record_id:
                return record
        return None

    def set_status(self, record_id: str, status: str, *, reason: str | None = None) -> None:
        records = self._read_all()
        for record in records:
            if record["record_id"] == record_id:
                record["status"] = status
                record["status_reason"] = reason
                break
        else:
            raise KeyError(f"No record with id {record_id!r}")
        self._write_all(records)

    def get_active(self, model_type: str) -> dict | None:
        """The current `PRODUCTION`-status record for `model_type`, or
        `None` if nothing has ever been promoted for it yet. Promotion
        (`ml.registry.promotion`) guarantees at most one `PRODUCTION`
        record per `model_type` at a time — this returns that one, not
        "the best-scoring record regardless of whether it was ever
        approved to serve," which is what made the pre-Phase-10 status
        field decorative (see ADR)."""
        active = [
            r
            for r in self._read_all()
            if r["model_type"] == model_type and r["status"] == ModelStatus.PRODUCTION
        ]
        if len(active) > 1:  # pragma: no cover - defensive; promotion enforces at most one
            raise RuntimeError(
                f"Invariant violated: {len(active)} PRODUCTION records for "
                f"model_type={model_type!r}; promotion should archive the previous one."
            )
        return active[0] if active else None

    def list_by_status(self, *, model_type: str, status: str) -> list[dict]:
        return [
            r for r in self._read_all() if r["model_type"] == model_type and r["status"] == status
        ]

    def best_by_metric(
        self,
        *,
        model_type: str | None = None,
        metric_path: tuple[str, ...],
        higher_is_better: bool,
        statuses: tuple[str, ...] | None = None,
    ) -> dict | None:
        """`metric_path`, e.g. `("test_metrics", "regression", "rmse")` —
        registered metrics are nested dicts, so a single flat key isn't
        enough to address them. `statuses`, if given, restricts candidates
        to those status values (e.g. promotion compares only `VALIDATED`
        candidates against `PRODUCTION`/baseline records) — `None` means
        every status, which is what a promotion-gate policy comparison
        needs but what production *serving* must never do (see
        `ml.inference.serving.load_forecast_models`)."""
        candidates = self._read_all()
        if model_type is not None:
            candidates = [r for r in candidates if r["model_type"] == model_type]
        if statuses is not None:
            candidates = [r for r in candidates if r["status"] in statuses]

        def _extract(record: dict) -> float | None:
            value = record
            for key in metric_path:
                if value is None or key not in value:
                    return None
                value = value[key]
            return value

        scored = [(r, _extract(r)) for r in candidates]
        scored = [(r, v) for r, v in scored if v is not None]
        if not scored:
            return None
        best = (
            max(scored, key=lambda rv: rv[1])
            if higher_is_better
            else min(scored, key=lambda rv: rv[1])
        )
        return best[0]

    def verify_artifact_integrity(self, record: dict) -> bool:
        """Recomputes the artifact directory's checksum and compares it
        against what was stored at registration time. `True` if they match
        OR the record predates this field (`artifact_checksum` is `None` —
        an old record, not a corrupted one). `False` means the artifact on
        disk has changed since it was registered — a real, actionable
        signal (corrupted download, manual tampering, a bug in a script
        that overwrote a saved model's directory), never ignored silently
        by callers that check it (see `ml.inference.serving`)."""
        stored = record.get("artifact_checksum")
        if stored is None:
            return True
        current = compute_artifact_checksum(Path(record["artifact_path"]))
        return current == stored


def new_version_string(model_name: str) -> str:
    return f"{model_name}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
