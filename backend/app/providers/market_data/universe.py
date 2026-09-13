"""The curated set of real, well-known companies AlphaLens tracks —
independent of which provider actually supplies their price data.

`DemoMarketDataProvider` uses this as its full universe (with synthetic
prices). A real provider like Twelve Data covers far more instruments than
this and deliberately does not enumerate one (see
`TwelveDataMarketDataProvider.list_securities`) — for real ingestion,
`market_data_service.run_ingestion` falls back to this list's metadata
(ticker/name/exchange/sector) for any requested ticker the provider itself
can't describe, so "ingest my tracked companies with real prices" has a
concrete meaning even against a provider with no universe of its own.
"""

from app.providers.base import SecurityInfo

KNOWN_SECURITIES: list[SecurityInfo] = [
    SecurityInfo("AAPL", "Apple Inc.", "NASDAQ", "Technology", "Consumer Electronics", "USD"),
    SecurityInfo(
        "MSFT", "Microsoft Corporation", "NASDAQ", "Technology", "Software—Infrastructure", "USD"
    ),
    SecurityInfo(
        "GOOGL", "Alphabet Inc.", "NASDAQ", "Communication Services", "Internet Content", "USD"
    ),
    SecurityInfo(
        "AMZN", "Amazon.com, Inc.", "NASDAQ", "Consumer Discretionary", "Internet Retail", "USD"
    ),
    SecurityInfo("NVDA", "NVIDIA Corporation", "NASDAQ", "Technology", "Semiconductors", "USD"),
    SecurityInfo(
        "TSLA", "Tesla, Inc.", "NASDAQ", "Consumer Discretionary", "Auto Manufacturers", "USD"
    ),
    SecurityInfo(
        "META",
        "Meta Platforms, Inc.",
        "NASDAQ",
        "Communication Services",
        "Internet Content",
        "USD",
    ),
    SecurityInfo("JPM", "JPMorgan Chase & Co.", "NYSE", "Financials", "Banks—Diversified", "USD"),
    SecurityInfo("XOM", "Exxon Mobil Corporation", "NYSE", "Energy", "Oil & Gas Integrated", "USD"),
    SecurityInfo(
        "JNJ", "Johnson & Johnson", "NYSE", "Healthcare", "Drug Manufacturers—General", "USD"
    ),
]
