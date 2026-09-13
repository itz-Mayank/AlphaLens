"""Demo Mode market data: a fixed universe of real, well-known tickers with
entirely SYNTHETIC price history (a seeded random walk — not real historical
prices for these companies). This is Demo Mode, not a claim about real
market data; every API response and the frontend both label rows with
`data_source="demo"` — see docs/security.md and docs/decisions.md ADR-007.

Determinism is load-bearing, not cosmetic: `get_daily_bars(ticker, start,
end)` must return byte-identical bars across repeated calls for the same
(ticker, end) regardless of how many times or in what order it's called,
because the ingestion idempotency guarantee (unique (security_id, ts),
upsert-on-conflict) is only meaningfully tested if re-ingesting the same
window actually produces the same values, not just the same row count.
That's why generation always walks forward from a fixed genesis date using a
per-ticker-only seed (never seeded by `start`/`end`/wall-clock time).
"""

import hashlib
import random
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from app.providers.base import MarketDataProvider, OHLCVBar, SecurityInfo
from app.providers.market_data.universe import KNOWN_SECURITIES

# Fixed, not "N days before today" — a sliding window would make generated
# history (and therefore test fixtures/snapshots) depend on wall-clock time.
_GENESIS_DATE = date(2023, 1, 1)

_UNIVERSE: list[SecurityInfo] = KNOWN_SECURITIES

_TWO_DP = Decimal("0.01")


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(_TWO_DP, rounding=ROUND_HALF_UP)


def _seed_for(ticker: str) -> int:
    digest = hashlib.sha256(ticker.encode("utf-8")).hexdigest()
    return int(digest[:16], 16)


def _base_price_for(ticker: str) -> Decimal:
    rng = random.Random(_seed_for(ticker) ^ 0x5EED)
    return Decimal(str(round(rng.uniform(20, 450), 2)))


def _base_volume_for(ticker: str) -> int:
    rng = random.Random(_seed_for(ticker) ^ 0x0101)
    return rng.randint(2_000_000, 60_000_000)


class DemoMarketDataProvider(MarketDataProvider):
    @property
    def data_source(self) -> str:
        return "demo"

    def list_securities(self) -> list[SecurityInfo]:
        return list(_UNIVERSE)

    def search_securities(self, query: str, *, limit: int = 10) -> list[SecurityInfo]:
        needle = query.strip().upper()
        if not needle:
            return []
        matches = [
            s for s in _UNIVERSE if needle in s.ticker.upper() or needle in s.name.upper()
        ]
        return matches[:limit]

    def get_daily_bars(self, ticker: str, start: date, end: date) -> list[OHLCVBar]:
        ticker = ticker.upper()
        if ticker not in {s.ticker for s in _UNIVERSE}:
            return []
        if end < _GENESIS_DATE or end < start:
            return []

        rng = random.Random(_seed_for(ticker))
        base_volume = _base_volume_for(ticker)
        price = _base_price_for(ticker)

        bars: list[OHLCVBar] = []
        current = _GENESIS_DATE
        while current <= end:
            if current.weekday() < 5:  # business days only
                daily_return = rng.gauss(mu=0.0003, sigma=0.02)
                open_price = price
                close_price = max(
                    Decimal("0.50"), price * (Decimal(1) + Decimal(str(daily_return)))
                )

                intraday_noise = abs(rng.gauss(mu=0, sigma=0.008))
                high_price = max(open_price, close_price) * (
                    Decimal(1) + Decimal(str(intraday_noise))
                )
                low_price = min(open_price, close_price) * (
                    Decimal(1) - Decimal(str(intraday_noise))
                )
                low_price = max(low_price, Decimal("0.01"))

                volume = max(0, int(rng.gauss(mu=base_volume, sigma=base_volume * 0.35)))

                if current >= start:
                    bars.append(
                        OHLCVBar(
                            ts=current,
                            open=_quantize(open_price),
                            high=_quantize(high_price),
                            low=_quantize(low_price),
                            close=_quantize(close_price),
                            adjusted_close=_quantize(close_price),
                            volume=volume,
                        )
                    )
                price = close_price
            current += timedelta(days=1)

        return bars
