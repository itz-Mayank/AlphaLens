from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    conversation_id: str | None = None


class EvidenceRead(BaseModel):
    source_type: str
    source_id: str
    ticker: str | None
    timestamp: datetime
    data: dict[str, Any]
    provenance: str


class ToolCallTraceRead(BaseModel):
    name: str
    ok: bool
    latency_ms: float


class ChatResponse(BaseModel):
    conversation_id: str
    answer: str
    evidence: list[EvidenceRead]
    citations: list[str]
    tools_used: list[str]
    tool_calls: list[ToolCallTraceRead]
    model: str
    provider: str
    request_id: str
    prompt_version: str
    disclaimer: str = (
        "AlphaLens Research Assistant — analytical and educational only, not financial advice. "
        "Not a guarantee of future performance."
    )
