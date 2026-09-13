"""Research-only endpoints: not part of the core dashboard/stock-detail
product surface. `POST /research/backtest` runs the portfolio backtest
engine (`ml.backtest`) against already-registered models — never trains
anything (ADR-001). `POST /research/chat` is the grounded research agent
(Phase 8) — an LLM reasoning layer over the same deterministic services,
never a source of data itself (see app/agent/)."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.rate_limit import limiter
from app.db.models.user import User
from app.db.session import get_db
from app.schemas.agent import ChatRequest, ChatResponse
from app.schemas.backtest import BacktestRequest, BacktestResponse
from app.services import agent_chat_service, backtest_service

router = APIRouter()


@router.post("/backtest", response_model=BacktestResponse)
def run_backtest(
    request: BacktestRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> BacktestResponse:
    return BacktestResponse(
        **backtest_service.run_backtest(
            db,
            tickers=request.tickers,
            start_date=request.start_date,
            end_date=request.end_date,
            commission_bps=request.commission_bps,
            slippage_bps=request.slippage_bps,
            initial_capital=request.initial_capital,
            max_position_weight=request.max_position_weight,
        )
    )


@router.post("/chat", response_model=ChatResponse)
@limiter.limit("20/hour")
def chat(
    request: Request,
    payload: ChatRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ChatResponse:
    """The grounded research agent. Every factual claim in `answer` is
    backed by a tool call recorded in `evidence`/`tool_calls` — the LLM
    never computes a financial metric itself (see app/agent/tools.py).
    Rate-limited (cost/DoS control, Step 21/25): each LLM call has a real
    cost and latency, unlike the rest of this API.
    """
    return ChatResponse(
        **agent_chat_service.chat(
            db, user, message=payload.message, conversation_id=payload.conversation_id
        )
    )
