import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.errors import NotFoundError
from app.db.models.user import User
from app.db.session import get_db
from app.repositories.portfolio_repository import PortfolioRepository
from app.repositories.security_repository import SecurityRepository
from app.repositories.transaction_repository import TransactionRepository
from app.schemas.common import Page
from app.schemas.portfolio import (
    HoldingRead,
    PerformanceHistoryResponse,
    PerformancePointRead,
    PortfolioAnalyticsResponse,
    PortfolioCreate,
    PortfolioRead,
    TransactionCreate,
    TransactionRead,
)
from app.services import portfolio_service
from app.services.portfolio_service import create_transaction, get_portfolio_for_user

router = APIRouter()


def _transaction_read(txn, ticker: str | None) -> TransactionRead:  # noqa: ANN001 - Transaction ORM row
    return TransactionRead(
        id=txn.id,
        transaction_type=txn.transaction_type,
        ticker=ticker,
        quantity=txn.quantity,
        price=txn.price,
        amount=txn.amount,
        fees=txn.fees,
        currency=txn.currency,
        executed_at=txn.executed_at,
        created_at=txn.created_at,
    )


@router.post("", response_model=PortfolioRead, status_code=status.HTTP_201_CREATED)
def create_portfolio(
    body: PortfolioCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PortfolioRead:
    portfolio = PortfolioRepository(db).create(
        user_id=user.id,
        name=body.name,
        description=body.description,
        base_currency=body.base_currency.upper(),
    )
    db.commit()
    return PortfolioRead.model_validate(portfolio)


@router.get("", response_model=list[PortfolioRead])
def list_portfolios(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[PortfolioRead]:
    portfolios = PortfolioRepository(db).list_for_user(user_id=user.id)
    return [PortfolioRead.model_validate(p) for p in portfolios]


@router.get("/{portfolio_id}", response_model=PortfolioRead)
def get_portfolio(
    portfolio_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PortfolioRead:
    portfolio = get_portfolio_for_user(db, portfolio_id=portfolio_id, user_id=user.id)
    return PortfolioRead.model_validate(portfolio)


@router.delete("/{portfolio_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_portfolio(
    portfolio_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    portfolio = get_portfolio_for_user(db, portfolio_id=portfolio_id, user_id=user.id)
    PortfolioRepository(db).delete(portfolio)
    db.commit()


@router.post(
    "/{portfolio_id}/transactions",
    response_model=TransactionRead,
    status_code=status.HTTP_201_CREATED,
)
def create_portfolio_transaction(
    portfolio_id: uuid.UUID,
    body: TransactionCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TransactionRead:
    portfolio = get_portfolio_for_user(db, portfolio_id=portfolio_id, user_id=user.id)

    security_id = None
    ticker = None
    if body.ticker is not None:
        security = SecurityRepository(db).get_by_ticker(body.ticker)
        if security is None:
            raise NotFoundError(
                f"No stock found for ticker '{body.ticker.upper()}'.", code="STOCK_NOT_FOUND"
            )
        security_id = security.id
        ticker = security.ticker

    txn = create_transaction(
        db,
        portfolio,
        transaction_type=body.transaction_type,
        security_id=security_id,
        quantity=body.quantity,
        price=body.price,
        amount=body.amount,
        fees=body.fees,
        currency=body.currency,
        executed_at=body.executed_at,
        idempotency_key=body.idempotency_key,
    )
    db.commit()
    return _transaction_read(txn, ticker)


@router.get("/{portfolio_id}/transactions", response_model=Page[TransactionRead])
def list_portfolio_transactions(
    portfolio_id: uuid.UUID,
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Page[TransactionRead]:
    portfolio = get_portfolio_for_user(db, portfolio_id=portfolio_id, user_id=user.id)
    transactions, total = TransactionRepository(db).list_page(
        portfolio_id=portfolio.id, limit=limit, offset=offset
    )
    security_ids = {t.security_id for t in transactions if t.security_id is not None}
    tickers_by_id = {s.id: s.ticker for s in SecurityRepository(db).get_by_ids(list(security_ids))}
    items = [
        _transaction_read(t, tickers_by_id.get(t.security_id) if t.security_id else None)
        for t in transactions
    ]
    return Page[TransactionRead](items=items, total=total, limit=limit, offset=offset)


@router.get("/{portfolio_id}/holdings", response_model=list[HoldingRead])
def get_portfolio_holdings(
    portfolio_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[HoldingRead]:
    portfolio = get_portfolio_for_user(db, portfolio_id=portfolio_id, user_id=user.id)
    holdings = portfolio_service.get_holdings(db, portfolio)
    return [HoldingRead(**vars(h)) for h in holdings]


@router.get("/{portfolio_id}/analytics", response_model=PortfolioAnalyticsResponse)
def get_portfolio_analytics(
    portfolio_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PortfolioAnalyticsResponse:
    portfolio = get_portfolio_for_user(db, portfolio_id=portfolio_id, user_id=user.id)
    analytics = portfolio_service.get_analytics(db, portfolio)
    return PortfolioAnalyticsResponse(
        cash=analytics.cash,
        invested_capital=analytics.invested_capital,
        total_deposits=analytics.total_deposits,
        total_withdrawals=analytics.total_withdrawals,
        market_value=analytics.market_value,
        total_value=analytics.total_value,
        realized_pnl=analytics.realized_pnl,
        unrealized_pnl=analytics.unrealized_pnl,
        total_return_percent=analytics.total_return_percent,
        market_value_is_partial=analytics.market_value_is_partial,
        holdings=[HoldingRead(**vars(h)) for h in analytics.holdings],
    )


@router.get("/{portfolio_id}/performance", response_model=PerformanceHistoryResponse)
def get_portfolio_performance(
    portfolio_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PerformanceHistoryResponse:
    portfolio = get_portfolio_for_user(db, portfolio_id=portfolio_id, user_id=user.id)
    history = portfolio_service.get_performance_history(db, portfolio)
    return PerformanceHistoryResponse(
        available=history.available,
        reason=history.reason,
        points=[PerformancePointRead(**vars(p)) for p in history.points],
    )
