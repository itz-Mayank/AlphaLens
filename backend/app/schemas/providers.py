from pydantic import BaseModel


class ProviderStatusRead(BaseModel):
    category: str
    configured_provider: str
    credential_required: bool
    credential_configured: bool
    last_success_at: str | None
    last_failure_at: str | None
    last_failure_reason: str | None
    last_latency_seconds: float | None


class ProviderStatusListResponse(BaseModel):
    providers: list[ProviderStatusRead]


class FundamentalFactRead(BaseModel):
    concept: str
    value: str
    unit: str
    period_end: str
    fiscal_period: str | None
    form: str
    filed_date: str
    accession_number: str | None


class FundamentalsResponse(BaseModel):
    ticker: str
    available: bool
    reason: str | None
    source: str | None
    retrieved_at: str | None
    facts: list[FundamentalFactRead]


class MacroObservationRead(BaseModel):
    observation_date: str
    value: str | None
    unit: str
    frequency: str
    vintage_date: str | None


class MacroSeriesResponse(BaseModel):
    series_id: str
    available: bool
    reason: str | None
    source: str | None
    observations: list[MacroObservationRead]
