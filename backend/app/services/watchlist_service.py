"""Watchlist CRUD + enrichment. Ownership is enforced by every read/write
going through `get_watchlist_for_user` (query-scoped by `user_id`, 404 —
never 403 — for a watchlist that doesn't exist or isn't the caller's; see
docs/security.md).

Enrichment is deliberately limited to the latest quote (one batched query
regardless of watchlist size — see `PriceBarRepository.get_latest_quotes`),
not a per-item forecast/sentiment call: those are materially more expensive
(model inference, multiple aggregation queries) and are already available
per-ticker on the stock detail page. This is a documented Phase 9 scope
decision, not an oversight — see docs/decisions.md's Phase 9 ADR.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.db.models.watchlist import Watchlist
from app.repositories.price_bar_repository import PriceBarRepository
from app.repositories.security_repository import SecurityRepository
from app.repositories.watchlist_repository import WatchlistRepository
from app.services.market_data_service import Quote, quote_from_latest_row


def get_watchlist_for_user(
    db: Session, *, watchlist_id: uuid.UUID, user_id: uuid.UUID
) -> Watchlist:
    watchlist = WatchlistRepository(db).get_for_user(watchlist_id=watchlist_id, user_id=user_id)
    if watchlist is None:
        raise NotFoundError("Watchlist not found.", code="WATCHLIST_NOT_FOUND")
    return watchlist


@dataclass(frozen=True)
class WatchlistItemView:
    security_id: int
    ticker: str
    name: str
    sector: str | None
    last_price: Decimal | None
    change: Decimal | None
    change_percent: Decimal | None
    volume: int | None
    as_of: str | None
    data_unavailable: bool


@dataclass(frozen=True)
class WatchlistDetail:
    watchlist: Watchlist
    items: list[WatchlistItemView]


def get_watchlist_detail(db: Session, watchlist: Watchlist) -> WatchlistDetail:
    security_ids = WatchlistRepository(db).list_item_security_ids(watchlist_id=watchlist.id)
    if not security_ids:
        return WatchlistDetail(watchlist=watchlist, items=[])

    securities_by_id = {s.id: s for s in SecurityRepository(db).get_by_ids(security_ids)}
    quotes_by_id = {
        row.security_id: quote_from_latest_row(row)
        for row in PriceBarRepository(db).get_latest_quotes(security_ids=security_ids)
    }

    items = []
    for security_id in security_ids:
        security = securities_by_id.get(security_id)
        if security is None:
            continue
        quote: Quote = quotes_by_id.get(security_id, Quote(None, None, None, None, None))
        items.append(
            WatchlistItemView(
                security_id=security_id,
                ticker=security.ticker,
                name=security.name,
                sector=security.sector,
                last_price=quote.last_price,
                change=quote.change,
                change_percent=quote.change_percent,
                volume=quote.volume,
                as_of=quote.as_of.isoformat() if quote.as_of else None,
                data_unavailable=quote.as_of is None,
            )
        )
    return WatchlistDetail(watchlist=watchlist, items=sorted(items, key=lambda i: i.ticker))
