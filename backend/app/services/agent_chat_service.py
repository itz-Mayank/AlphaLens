"""Thin glue between the API layer and `app/agent/orchestrator.py` — maps
`LLMProviderError`/`AgentError` to a clean `AppError` subclass, and
assembles the `ChatResponse`-shaped dict. No agent logic lives here; this
module only wires the pieces together, the same role
`forecast_service.py`/`backtest_service.py` play for their domains.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.agent.llm_provider import LLMProviderError, get_llm_provider
from app.agent.orchestrator import AgentError, run_agent
from app.agent.prompts import SYSTEM_PROMPT_VERSION
from app.core.errors import AppError
from app.db.models.user import User


class AgentUnavailableError(AppError):
    status_code = 503
    code = "AGENT_UNAVAILABLE"


def chat(db: Session, user: User, *, message: str, conversation_id: str | None) -> dict:
    try:
        provider = get_llm_provider()
    except LLMProviderError as exc:
        raise AgentUnavailableError(str(exc)) from exc

    try:
        result = run_agent(
            db, user, message=message, conversation_id=conversation_id, llm_provider=provider
        )
    except AgentError as exc:
        raise AgentUnavailableError(str(exc)) from exc

    citations = sorted({e.citation_tag() for e in result.evidence})
    return {
        "conversation_id": result.conversation_id,
        "answer": result.answer,
        "evidence": [e.as_dict() for e in result.evidence],
        "citations": citations,
        "tools_used": result.tools_used,
        "tool_calls": [
            {"name": t.name, "ok": t.ok, "latency_ms": round(t.latency_ms, 1)}
            for t in result.tool_call_traces
        ],
        "model": result.model,
        "provider": result.provider,
        "request_id": result.request_id,
        "prompt_version": SYSTEM_PROMPT_VERSION,
    }
