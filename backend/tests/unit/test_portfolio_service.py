"""Pure-function accounting tests for `replay_transactions` — no DB, no I/O.
Exercises average-cost basis, fee treatment, and realized P&L directly
against a hand-built transaction list, per the accounting methodology
documented in `app/services/portfolio_service.py`'s module docstring.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from app.db.models.portfolio import Transaction, TransactionType
from app.services.portfolio_service import replay_transactions

SEC = 1


def _txn(
    transaction_type: str,
    *,
    quantity: Decimal | None = None,
    price: Decimal | None = None,
    amount: Decimal | None = None,
    fees: Decimal = Decimal(0),
    security_id: int | None = SEC,
    executed_at: datetime | None = None,
) -> Transaction:
    return Transaction(
        id=uuid.uuid4(),
        portfolio_id=uuid.uuid4(),
        security_id=security_id if transaction_type in TransactionType.SECURITY_TYPES else None,
        transaction_type=transaction_type,
        quantity=quantity,
        price=price,
        amount=amount,
        fees=fees,
        currency="USD",
        executed_at=executed_at or datetime(2025, 1, 1, tzinfo=UTC),
    )


class TestCashOnly:
    def test_a_deposit_increases_cash_and_net_contributed(self):
        ledger = replay_transactions([_txn(TransactionType.CASH_DEPOSIT, amount=Decimal(1000))])
        assert ledger.cash == Decimal(1000)
        assert ledger.net_contributed == Decimal(1000)

    def test_a_withdrawal_decreases_cash_and_net_contributed(self):
        ledger = replay_transactions(
            [
                _txn(TransactionType.CASH_DEPOSIT, amount=Decimal(1000)),
                _txn(TransactionType.CASH_WITHDRAWAL, amount=Decimal(300)),
            ]
        )
        assert ledger.cash == Decimal(700)
        assert ledger.net_contributed == Decimal(700)


class TestAverageCostBasis:
    def test_two_buys_at_different_prices_average_the_cost_basis(self):
        ledger = replay_transactions(
            [
                _txn(TransactionType.CASH_DEPOSIT, amount=Decimal(10_000)),
                _txn(TransactionType.BUY, quantity=Decimal(10), price=Decimal(100)),
                _txn(TransactionType.BUY, quantity=Decimal(10), price=Decimal(200)),
            ]
        )
        position = ledger.positions[SEC]
        assert position.quantity == Decimal(20)
        assert position.total_cost == Decimal(3000)  # 10*100 + 10*200
        assert position.average_cost == Decimal(150)
        assert ledger.cash == Decimal(10_000) - Decimal(3000)

    def test_fees_are_added_to_buy_cost_basis(self):
        ledger = replay_transactions(
            [
                _txn(TransactionType.CASH_DEPOSIT, amount=Decimal(10_000)),
                _txn(
                    TransactionType.BUY,
                    quantity=Decimal(10),
                    price=Decimal(100),
                    fees=Decimal(5),
                ),
            ]
        )
        position = ledger.positions[SEC]
        assert position.total_cost == Decimal(1005)  # 10*100 + 5 fee
        assert ledger.cash == Decimal(10_000) - Decimal(1005)

    def test_a_partial_sell_removes_cost_basis_at_the_average_and_realizes_pnl(self):
        ledger = replay_transactions(
            [
                _txn(TransactionType.CASH_DEPOSIT, amount=Decimal(10_000)),
                _txn(TransactionType.BUY, quantity=Decimal(10), price=Decimal(100)),
                _txn(TransactionType.SELL, quantity=Decimal(4), price=Decimal(150)),
            ]
        )
        position = ledger.positions[SEC]
        # average cost was 100/share; selling 4 removes 400 of cost basis
        assert position.quantity == Decimal(6)
        assert position.total_cost == Decimal(600)
        proceeds = Decimal(4) * Decimal(150)
        assert ledger.realized_pnl == proceeds - Decimal(400)

    def test_fees_reduce_sell_proceeds_and_therefore_realized_pnl(self):
        ledger = replay_transactions(
            [
                _txn(TransactionType.CASH_DEPOSIT, amount=Decimal(10_000)),
                _txn(TransactionType.BUY, quantity=Decimal(10), price=Decimal(100)),
                _txn(
                    TransactionType.SELL,
                    quantity=Decimal(10),
                    price=Decimal(150),
                    fees=Decimal(10),
                ),
            ]
        )
        proceeds = Decimal(10) * Decimal(150) - Decimal(10)
        assert ledger.realized_pnl == proceeds - Decimal(1000)
        assert SEC not in ledger.positions  # fully closed position isn't "open"

    def test_selling_the_entire_position_removes_it_from_open_positions(self):
        ledger = replay_transactions(
            [
                _txn(TransactionType.CASH_DEPOSIT, amount=Decimal(10_000)),
                _txn(TransactionType.BUY, quantity=Decimal(5), price=Decimal(100)),
                _txn(TransactionType.SELL, quantity=Decimal(5), price=Decimal(120)),
            ]
        )
        assert SEC not in ledger.positions


class TestTransactionOrderingDeterminism:
    def test_replaying_the_same_transactions_twice_yields_an_identical_ledger(self):
        """Same input list in, same ledger out — no hidden non-determinism
        (e.g. dict ordering, wall-clock reads) in the accounting engine
        itself."""
        transactions = [
            _txn(TransactionType.CASH_DEPOSIT, amount=Decimal(10_000)),
            _txn(TransactionType.BUY, quantity=Decimal(10), price=Decimal(100)),
            _txn(TransactionType.SELL, quantity=Decimal(3), price=Decimal(110)),
        ]
        first = replay_transactions(transactions)
        second = replay_transactions(transactions)
        assert first == second
