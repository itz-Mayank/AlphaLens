"""Portfolio accounting: transactions are the ONLY source of truth. No
derived figure (cash, position quantity, average cost, market value, P&L)
is ever persisted — every call to this module recomputes them fresh from
the full transaction history plus current prices, so there is no
"derived state drifted out of sync with reality" failure mode (see
`app/db/models/portfolio.py`'s docstring and docs/decisions.md's Phase 9
accounting ADR).

**Accounting methodology (documented, not buried):**
- **Average-cost basis**, not FIFO/LIFO — the position's cost basis is one
  running total divided by quantity; a partial SELL removes cost basis at
  that average, it does not track individual lots.
- **Long-only** — a SELL can never exceed the currently-held quantity;
  short selling is rejected, not silently allowed.
- **Fees**: added to cost basis on BUY (so they reduce future unrealized
  gains, correctly), subtracted from proceeds on SELL (so they reduce
  realized gains, correctly). `CASH_DEPOSIT`/`CASH_WITHDRAWAL` carry no
  fees in Phase 9 (enforced by a DB CHECK constraint) — this models a
  brokerage transfer, not a wire-fee scenario.
- **Cash sufficiency**: a BUY that would take cash negative is rejected.
  This is Phase 9's only cash constraint — it does not model margin.
- **Return methodology**: `total_return_percent` is a simple money-weighted
  return, `(total_value - net_contributed) / net_contributed`. This is
  NOT a time-weighted return (which would need a cash-flow-adjusted daily
  calculation) — a deliberate, documented Phase 9 scope limitation.
"""

from __future__ import annotations

import uuid
from bisect import bisect_right
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.errors import AppError, ConflictError, NotFoundError
from app.db.models.portfolio import Portfolio, Transaction, TransactionType
from app.repositories.portfolio_repository import PortfolioRepository
from app.repositories.price_bar_repository import PriceBarRepository
from app.repositories.security_repository import SecurityRepository
from app.repositories.transaction_repository import TransactionRepository
from app.services.market_data_service import quote_from_latest_row

ZERO = Decimal(0)


class InsufficientCashError(AppError):
    status_code = 422
    code = "INSUFFICIENT_CASH"


class InsufficientPositionError(AppError):
    status_code = 422
    code = "INSUFFICIENT_POSITION"


class DuplicateTransactionError(ConflictError):
    code = "DUPLICATE_TRANSACTION"


def get_portfolio_for_user(
    db: Session, *, portfolio_id: uuid.UUID, user_id: uuid.UUID
) -> Portfolio:
    """404 (never 403) when the portfolio doesn't exist OR belongs to a
    different user — a non-owner must never be able to distinguish "not
    yours" from "doesn't exist" (see docs/security.md)."""
    portfolio = PortfolioRepository(db).get_for_user(portfolio_id=portfolio_id, user_id=user_id)
    if portfolio is None:
        raise NotFoundError("Portfolio not found.", code="PORTFOLIO_NOT_FOUND")
    return portfolio


@dataclass(frozen=True)
class _Position:
    quantity: Decimal
    total_cost: Decimal  # cost basis for the currently-held quantity (average-cost)

    @property
    def average_cost(self) -> Decimal:
        return self.total_cost / self.quantity if self.quantity != ZERO else ZERO


@dataclass(frozen=True)
class PortfolioLedger:
    """The full replay of a portfolio's transaction history at one point
    in time: cash, open positions (by security_id), and cumulative
    realized P&L. Contains no market prices — see `Holding`/
    `PortfolioAnalytics` for the price-dependent figures built on top."""

    cash: Decimal
    positions: dict[int, _Position]
    realized_pnl: Decimal
    total_deposits: Decimal
    total_withdrawals: Decimal

    @property
    def net_contributed(self) -> Decimal:
        return self.total_deposits - self.total_withdrawals


def replay_transactions(transactions: list[Transaction]) -> PortfolioLedger:
    """Pure function: transaction list (already filtered/ordered by the
    caller — see `TransactionRepository.list_chronological`'s ordering
    guarantee) in, ledger out. No I/O, so this is directly unit-testable
    for accounting correctness without a database."""
    cash = ZERO
    positions: dict[int, _Position] = {}
    realized_pnl = ZERO
    total_deposits = ZERO
    total_withdrawals = ZERO

    for txn in transactions:
        # The DB's `ck_transactions_type_fields` CHECK constraint guarantees
        # exactly one of these two field shapes per row — the `assert`s
        # below just tell mypy what the constraint already enforces at
        # the database level, not a new runtime rule.
        if txn.transaction_type == TransactionType.CASH_DEPOSIT:
            assert txn.amount is not None
            cash += txn.amount
            total_deposits += txn.amount
        elif txn.transaction_type == TransactionType.CASH_WITHDRAWAL:
            assert txn.amount is not None
            cash -= txn.amount
            total_withdrawals += txn.amount
        elif txn.transaction_type == TransactionType.BUY:
            assert (
                txn.security_id is not None
                and txn.quantity is not None
                and txn.price is not None
            )
            cost = txn.quantity * txn.price + txn.fees
            cash -= cost
            existing = positions.get(txn.security_id, _Position(ZERO, ZERO))
            positions[txn.security_id] = _Position(
                quantity=existing.quantity + txn.quantity,
                total_cost=existing.total_cost + cost,
            )
        elif txn.transaction_type == TransactionType.SELL:
            assert (
                txn.security_id is not None
                and txn.quantity is not None
                and txn.price is not None
            )
            proceeds = txn.quantity * txn.price - txn.fees
            cash += proceeds
            existing = positions.get(txn.security_id, _Position(ZERO, ZERO))
            cost_removed = existing.average_cost * txn.quantity
            realized_pnl += proceeds - cost_removed
            remaining_qty = existing.quantity - txn.quantity
            positions[txn.security_id] = _Position(
                quantity=remaining_qty,
                total_cost=existing.total_cost - cost_removed if remaining_qty > ZERO else ZERO,
            )

    open_positions = {sid: pos for sid, pos in positions.items() if pos.quantity > ZERO}
    return PortfolioLedger(
        cash=cash,
        positions=open_positions,
        realized_pnl=realized_pnl,
        total_deposits=total_deposits,
        total_withdrawals=total_withdrawals,
    )


def create_transaction(
    db: Session,
    portfolio: Portfolio,
    *,
    transaction_type: str,
    security_id: int | None,
    quantity: Decimal | None,
    price: Decimal | None,
    amount: Decimal | None,
    fees: Decimal,
    currency: str | None,
    executed_at: datetime | None,
    idempotency_key: str | None,
) -> Transaction:
    """Validates cash sufficiency (BUY) and position sufficiency (SELL)
    against the portfolio's CURRENT state (the full existing transaction
    history) before inserting — see this module's docstring for why
    out-of-order backdated inserts are not re-validated against what the
    position was at that historical instant, only against the present.
    Idempotency: if `idempotency_key` matches an existing transaction on
    this portfolio, that existing transaction is returned unchanged rather
    than creating a duplicate (the DB's own unique constraint is the
    ultimate guarantee; this check just turns it into a clean, expected
    response instead of an integrity-error race)."""
    txn_repo = TransactionRepository(db)

    if idempotency_key is not None:
        existing = txn_repo.get_by_idempotency_key(
            portfolio_id=portfolio.id, idempotency_key=idempotency_key
        )
        if existing is not None:
            return existing

    resolved_currency = currency or portfolio.base_currency
    resolved_executed_at = executed_at or datetime.now(UTC)

    # `security_id` existence (BUY/SELL) is the API layer's job — it
    # resolves a request ticker to a security_id up front, raising
    # STOCK_NOT_FOUND for an unknown ticker, before this function ever
    # runs (the same `_get_security_or_404` pattern `stocks.py` uses).

    ledger = replay_transactions(
        TransactionRepository(db).list_chronological(portfolio_id=portfolio.id)
    )

    if transaction_type == TransactionType.BUY:
        assert security_id is not None and quantity is not None and price is not None
        cost = quantity * price + fees
        if ledger.cash - cost < ZERO:
            raise InsufficientCashError(
                f"This purchase costs {cost} but only {ledger.cash} cash is available."
            )
    elif transaction_type == TransactionType.SELL:
        assert security_id is not None and quantity is not None
        held = ledger.positions.get(security_id)
        held_qty = held.quantity if held is not None else ZERO
        if quantity > held_qty:
            raise InsufficientPositionError(
                f"Cannot sell {quantity} shares — only {held_qty} are held "
                "(short selling is not supported)."
            )

    try:
        return txn_repo.create(
            portfolio_id=portfolio.id,
            security_id=security_id,
            transaction_type=transaction_type,
            quantity=quantity,
            price=price,
            amount=amount,
            fees=fees,
            currency=resolved_currency,
            executed_at=resolved_executed_at,
            idempotency_key=idempotency_key,
        )
    except Exception as exc:
        # A concurrent request racing on the same idempotency_key hits the
        # unique constraint despite the pre-check above — never a raw
        # IntegrityError/500 for a case that has a clean, expected outcome.
        db.rollback()
        if idempotency_key is not None:
            existing = txn_repo.get_by_idempotency_key(
                portfolio_id=portfolio.id, idempotency_key=idempotency_key
            )
            if existing is not None:
                return existing
        raise DuplicateTransactionError(
            "A transaction with this idempotency key already exists."
        ) from exc


@dataclass(frozen=True)
class Holding:
    security_id: int
    ticker: str
    name: str
    quantity: Decimal
    average_cost: Decimal
    cost_basis: Decimal
    last_price: Decimal | None
    market_value: Decimal | None
    unrealized_pnl: Decimal | None
    unrealized_pnl_percent: Decimal | None


def get_holdings(db: Session, portfolio: Portfolio) -> list[Holding]:
    ledger = replay_transactions(
        TransactionRepository(db).list_chronological(portfolio_id=portfolio.id)
    )
    if not ledger.positions:
        return []

    security_ids = list(ledger.positions.keys())
    # Both lookups below are ONE query each regardless of how many
    # securities are held — never one query per holding.
    quotes_by_id = {
        row.security_id: quote_from_latest_row(row)
        for row in PriceBarRepository(db).get_latest_quotes(security_ids=security_ids)
    }
    securities_by_id = {s.id: s for s in SecurityRepository(db).get_by_ids(security_ids)}

    holdings = []
    for security_id, position in ledger.positions.items():
        security = securities_by_id.get(security_id)
        quote = quotes_by_id.get(security_id)
        last_price = quote.last_price if quote else None
        market_value = position.quantity * last_price if last_price is not None else None
        unrealized_pnl = market_value - position.total_cost if market_value is not None else None
        unrealized_pnl_percent = (
            (unrealized_pnl / position.total_cost) * Decimal(100)
            if unrealized_pnl is not None and position.total_cost > ZERO
            else None
        )
        holdings.append(
            Holding(
                security_id=security_id,
                ticker=security.ticker if security else "UNKNOWN",
                name=security.name if security else "Unknown security",
                quantity=position.quantity,
                average_cost=position.average_cost,
                cost_basis=position.total_cost,
                last_price=last_price,
                market_value=market_value,
                unrealized_pnl=unrealized_pnl,
                unrealized_pnl_percent=unrealized_pnl_percent,
            )
        )
    return sorted(holdings, key=lambda h: h.ticker)


@dataclass(frozen=True)
class PortfolioAnalytics:
    cash: Decimal
    invested_capital: Decimal
    total_deposits: Decimal
    total_withdrawals: Decimal
    market_value: Decimal | None
    total_value: Decimal | None
    realized_pnl: Decimal
    unrealized_pnl: Decimal | None
    total_return_percent: Decimal | None
    market_value_is_partial: bool
    holdings: list[Holding]


def get_analytics(db: Session, portfolio: Portfolio) -> PortfolioAnalytics:
    holdings = get_holdings(db, portfolio)
    ledger = replay_transactions(
        TransactionRepository(db).list_chronological(portfolio_id=portfolio.id)
    )

    known_values = [h.market_value for h in holdings if h.market_value is not None]
    market_value_is_partial = len(known_values) != len(holdings)
    # An honest total is only possible when every holding's price is known
    # — a partial sum presented as "the" market value would understate
    # reality without saying so (see this module's docstring: never
    # substitute a fabricated/misleading figure for missing data).
    market_value = None if market_value_is_partial else sum(known_values, start=ZERO)
    total_value = ledger.cash + market_value if market_value is not None else None
    unrealized_pnl = (
        sum((h.unrealized_pnl for h in holdings if h.unrealized_pnl is not None), start=ZERO)
        if not market_value_is_partial
        else None
    )

    total_return_percent = None
    if total_value is not None and ledger.net_contributed > ZERO:
        total_return_percent = (
            (total_value - ledger.net_contributed) / ledger.net_contributed
        ) * Decimal(100)

    return PortfolioAnalytics(
        cash=ledger.cash,
        invested_capital=ledger.net_contributed,
        total_deposits=ledger.total_deposits,
        total_withdrawals=ledger.total_withdrawals,
        market_value=market_value,
        total_value=total_value,
        realized_pnl=ledger.realized_pnl,
        unrealized_pnl=unrealized_pnl,
        total_return_percent=total_return_percent,
        market_value_is_partial=market_value_is_partial,
        holdings=holdings,
    )


@dataclass(frozen=True)
class PerformancePoint:
    as_of: datetime
    cash: Decimal
    market_value: Decimal | None
    total_value: Decimal | None
    net_contributed: Decimal


@dataclass(frozen=True)
class PerformanceHistory:
    available: bool
    reason: str | None
    points: list[PerformancePoint]


def get_performance_history(db: Session, portfolio: Portfolio) -> PerformanceHistory:
    """Portfolio value at every date a relevant price bar exists, computed
    with NO look-ahead: at date D, only transactions with
    `executed_at.date() <= D` are replayed, and only price bars with
    `ts.date() <= D` are used for that day's market value (the latest
    such bar per security, forward-filled across non-trading days — never
    a future bar). See `tests/integration/test_portfolio_service.py`'s
    temporal-correctness tests for the adversarial cases this guards
    against (a future transaction/price must never move a past point).
    """
    transactions = TransactionRepository(db).list_chronological(portfolio_id=portfolio.id)
    if not transactions:
        return PerformanceHistory(available=False, reason="No transactions yet.", points=[])

    ever_held_security_ids = sorted(
        {t.security_id for t in transactions if t.security_id is not None}
    )
    earliest = min(t.executed_at for t in transactions)

    price_series: dict[int, tuple[list, list]] = {}  # security_id -> (dates, closes), ascending
    if ever_held_security_ids:
        bars = PriceBarRepository(db).get_bars_for_securities(
            security_ids=ever_held_security_ids, start=earliest
        )
        by_security: dict[int, list] = {}
        for bar in bars:
            by_security.setdefault(bar.security_id, []).append(bar)
        for security_id, security_bars in by_security.items():
            security_bars.sort(key=lambda b: b.ts)
            price_series[security_id] = (
                [b.ts.date() for b in security_bars],
                [b.close for b in security_bars],
            )

    timeline = sorted(
        {t.executed_at.date() for t in transactions}
        | {d for dates, _ in price_series.values() for d in dates}
    )

    def _price_as_of(security_id: int, day: date) -> Decimal | None:
        series = price_series.get(security_id)
        if series is None:
            return None
        dates, closes = series
        idx = bisect_right(dates, day) - 1
        return closes[idx] if idx >= 0 else None

    points: list[PerformancePoint] = []
    for day in timeline:
        day_end = datetime.combine(day, datetime.max.time(), tzinfo=UTC)
        day_transactions = [t for t in transactions if t.executed_at <= day_end]
        ledger = replay_transactions(day_transactions)

        known_values = []
        any_unknown = False
        for security_id, position in ledger.positions.items():
            price = _price_as_of(security_id, day)
            if price is None:
                any_unknown = True
                continue
            known_values.append(position.quantity * price)

        market_value = None if (any_unknown or not ledger.positions) else sum(
            known_values, start=ZERO
        )
        if not ledger.positions:
            market_value = ZERO
        total_value = ledger.cash + market_value if market_value is not None else None

        points.append(
            PerformancePoint(
                as_of=day_end,
                cash=ledger.cash,
                market_value=market_value,
                total_value=total_value,
                net_contributed=ledger.net_contributed,
            )
        )

    return PerformanceHistory(available=True, reason=None, points=points)
