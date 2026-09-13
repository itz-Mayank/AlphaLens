from pydantic import BaseModel


class ModelRecordRead(BaseModel):
    record_id: str
    model_name: str
    model_type: str
    version: str
    dataset_version: str
    feature_version: str
    status: str
    # Both `None`-defaulted: a registry record written before Phase 10
    # added these fields to `ModelRecord` simply won't have these keys in
    # its JSON — a real, expected case for an append-only registry file
    # whose schema evolves over time, not something to reject.
    status_reason: str | None = None
    metrics: dict
    created_at: str
    artifact_checksum: str | None = None


class LivePerformanceResponse(BaseModel):
    model_type: str
    insufficient_data: bool
    reason: str | None
    sample_count: int
    mae: float | None
    rmse: float | None
    directional_hit_rate: float | None
    directional_sample_count: int
    disclaimer: str


class DriftReportItem(BaseModel):
    feature: str
    metric: str
    value: float
    baseline_period: tuple[str, str]
    current_period: tuple[str, str]
    severity: str
    timestamp: str


class DriftResponse(BaseModel):
    ticker: str
    reports: list[DriftReportItem]
    disclaimer: str = (
        "A drift signal is a monitoring signal, not a verdict — it never means a model "
        "has automatically become invalid."
    )


class RetrainTriggerResponse(BaseModel):
    job_id: str
    status: str
