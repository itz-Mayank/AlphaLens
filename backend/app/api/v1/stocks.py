from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from ml.features.pipeline import FEATURE_COLUMNS
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.cache import (
    STOCK_DETAIL_TTL_SECONDS,
    STOCK_LIST_TTL_SECONDS,
    STOCK_PRICES_TTL_SECONDS,
    cache_get_json,
    cache_set_json,
)
from app.core.errors import AppError, NotFoundError
from app.db.models.security import Security
from app.db.models.user import User
from app.db.session import get_db
from app.providers.http_client import ProviderRateLimitedError, ProviderResponseError
from app.providers.market_data import get_market_data_provider
from app.repositories.price_bar_repository import PriceBarRepository
from app.repositories.security_repository import SecurityRepository
from app.schemas.common import Page
from app.schemas.forecast import ForecastExplanationResponse, ForecastResponse
from app.schemas.market_data import (
    PriceBarRead,
    PriceHistoryResponse,
    SecurityDiscoveryResult,
    StockDetailResponse,
    StockListItem,
)
from app.schemas.news import NewsListResponse, SentimentHistoryResponse, SentimentOverviewResponse
from app.schemas.providers import FundamentalFactRead, FundamentalsResponse
from app.services import forecast_service, fundamentals_service, news_query_service
from app.services.market_data_service import (
    Quote,
    compute_52_week_range,
    compute_quote,
    quote_from_latest_row,
)

router = APIRouter()

_RANGE_TO_DAYS = {"1M": 30, "3M": 90, "6M": 182, "1Y": 365, "5Y": 1825}


def _security_fields(security: Security) -> dict:
    return {
        "id": security.id,
        "ticker": security.ticker,
        "name": security.name,
        "exchange": security.exchange,
        "sector": security.sector,
        "industry": security.industry,
        "currency": security.currency,
        "status": security.status,
        "data_source": security.data_source,
    }


def _quote_fields(quote: Quote) -> dict:
    return {
        "last_price": quote.last_price,
        "change": quote.change,
        "change_percent": quote.change_percent,
        "volume": quote.volume,
        "as_of": quote.as_of,
    }


@router.get("", response_model=Page[StockListItem])
def list_stocks(
    q: str | None = Query(default=None, description="Search by ticker or company name"),
    sector: str | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> Page[StockListItem]:
    cache_key = f"stocks:list:q={q or ''}:sector={sector or ''}:limit={limit}:offset={offset}"
    cached = cache_get_json(cache_key)
    if cached is not None:
        return Page[StockListItem].model_validate(cached)

    securities_repo = SecurityRepository(db)
    price_bars_repo = PriceBarRepository(db)

    securities, total = securities_repo.search(query=q, sector=sector, limit=limit, offset=offset)

    # One query for every security's quote on this page, not one per row —
    # see PriceBarRepository.get_latest_quotes' docstring.
    quotes_by_id = {
        row.security_id: quote_from_latest_row(row)
        for row in price_bars_repo.get_latest_quotes(security_ids=[s.id for s in securities])
    }
    items = [
        StockListItem(
            **_security_fields(security),
            **_quote_fields(quotes_by_id.get(security.id, Quote(None, None, None, None, None))),
        )
        for security in securities
    ]

    page = Page[StockListItem](items=items, total=total, limit=limit, offset=offset)
    cache_set_json(cache_key, page.model_dump(mode="json"), ttl_seconds=STOCK_LIST_TTL_SECONDS)
    return page


@router.get("/discover", response_model=list[SecurityDiscoveryResult])
def discover_securities(
    q: str = Query(min_length=1, max_length=50, description="Ticker or company name"),
    limit: int = Query(default=10, ge=1, le=25),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> list[SecurityDiscoveryResult]:
    """Live discovery against the configured provider's own search
    capability (e.g. Twelve Data's symbol_search) — distinct from `GET
    /stocks?q=`, which only searches securities AlphaLens has already
    ingested. This is what lets a user find and research a ticker
    AlphaLens has never seen before, without it needing to be
    pre-enumerated anywhere. Registered before `/{ticker}` so it isn't
    swallowed by that catch-all path."""
    provider = get_market_data_provider()
    try:
        matches = provider.search_securities(q, limit=limit)
    except ProviderRateLimitedError as exc:
        raise AppError(str(exc), code="PROVIDER_RATE_LIMITED", status_code=429) from exc
    except ProviderResponseError as exc:
        raise AppError(str(exc), code="PROVIDER_UNAVAILABLE", status_code=503) from exc

    securities_repo = SecurityRepository(db)
    return [
        SecurityDiscoveryResult(
            ticker=m.ticker,
            name=m.name,
            exchange=m.exchange,
            currency=m.currency,
            already_tracked=securities_repo.get_by_ticker(m.ticker) is not None,
        )
        for m in matches
    ]


@router.get("/{ticker}", response_model=StockDetailResponse)
def get_stock_detail(
    ticker: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> StockDetailResponse:
    ticker = ticker.upper()
    cache_key = f"stocks:detail:{ticker}"
    cached = cache_get_json(cache_key)
    if cached is not None:
        return StockDetailResponse.model_validate(cached)

    securities_repo = SecurityRepository(db)
    price_bars_repo = PriceBarRepository(db)

    security = securities_repo.get_by_ticker(ticker)
    if security is None:
        raise NotFoundError(f"No stock found for ticker '{ticker}'.", code="STOCK_NOT_FOUND")

    latest_bars = price_bars_repo.get_latest(security_id=security.id, limit=2)
    quote = compute_quote(latest_bars)
    as_of = quote.as_of or datetime.now(UTC)
    week_52_high, week_52_low = compute_52_week_range(
        price_bars_repo, security_id=security.id, as_of=as_of
    )

    detail = StockDetailResponse(
        **_security_fields(security),
        **_quote_fields(quote),
        week_52_high=week_52_high,
        week_52_low=week_52_low,
    )
    cache_set_json(cache_key, detail.model_dump(mode="json"), ttl_seconds=STOCK_DETAIL_TTL_SECONDS)
    return detail


@router.get("/{ticker}/prices", response_model=PriceHistoryResponse)
def get_stock_prices(
    ticker: str,
    range_: str | None = Query(
        default="1Y", alias="range", description="1M, 3M, 6M, 1Y, 5Y, or MAX"
    ),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> PriceHistoryResponse:
    ticker = ticker.upper()
    cache_key = f"stocks:prices:{ticker}:range={range_}"
    cached = cache_get_json(cache_key)
    if cached is not None:
        return PriceHistoryResponse.model_validate(cached)

    security = SecurityRepository(db).get_by_ticker(ticker)
    if security is None:
        raise NotFoundError(f"No stock found for ticker '{ticker}'.", code="STOCK_NOT_FOUND")

    start = None
    if range_ and range_.upper() != "MAX":
        days = _RANGE_TO_DAYS.get(range_.upper())
        if days is not None:
            start = datetime.now(UTC) - timedelta(days=days)

    bars = PriceBarRepository(db).get_range(security_id=security.id, start=start, end=None)
    response = PriceHistoryResponse(
        ticker=ticker,
        data_source=security.data_source,
        bars=[PriceBarRead.model_validate(bar) for bar in bars],
    )
    cache_set_json(
        cache_key, response.model_dump(mode="json"), ttl_seconds=STOCK_PRICES_TTL_SECONDS
    )
    return response


@router.get("/{ticker}/forecast", response_model=ForecastResponse)
def get_stock_forecast(
    ticker: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> ForecastResponse:
    """Real inference from the registered XGBoost models — never a
    hardcoded value. Never trains anything (ADR-001): this route only ever
    loads already-trained artifacts via `ml.inference` and calls
    `.predict()`. See `app/services/forecast_service.py` for the
    unknown-ticker/insufficient-history/model-unavailable error mapping and
    the demo-vs-real data-source disclosure this response always carries.
    """
    return ForecastResponse(**forecast_service.get_forecast(db, ticker.upper()))


@router.get("/{ticker}/forecast/explanation", response_model=ForecastExplanationResponse)
def get_stock_forecast_explanation(
    ticker: str,
    top_n: int = Query(default=5, ge=1, le=len(FEATURE_COLUMNS)),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> ForecastExplanationResponse:
    """SHAP explanation for the direction model's prediction — a separate,
    materially more expensive call than `/forecast`, deliberately not
    computed on every forecast request (see
    `ml.explainability.shap_explainer`'s module docstring for the
    contribution-not-causality methodology note echoed in this response)."""
    return ForecastExplanationResponse(
        **forecast_service.get_forecast_explanation(db, ticker.upper(), top_n=top_n)
    )


def _get_security_or_404(db: Session, ticker: str) -> Security:
    security = SecurityRepository(db).get_by_ticker(ticker)
    if security is None:
        raise NotFoundError(f"No stock found for ticker '{ticker}'.", code="STOCK_NOT_FOUND")
    return security


@router.get("/{ticker}/news", response_model=NewsListResponse)
def get_stock_news(
    ticker: str,
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> NewsListResponse:
    """Recent articles mapped to this security, each with its sentiment if
    already processed (`sentiment: null` if the ingestion pipeline hasn't
    scored it yet — never a fabricated placeholder). `data_sources` on the
    response discloses whether these are demo or real articles, never
    hidden (mirrors the forecast endpoints' `data_source` disclosure)."""
    security = _get_security_or_404(db, ticker.upper())
    return NewsListResponse(
        **news_query_service.get_recent_news(db, security=security, limit=limit)
    )


@router.get("/{ticker}/sentiment", response_model=SentimentOverviewResponse)
def get_stock_sentiment(
    ticker: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> SentimentOverviewResponse:
    """Current 24-hour and 7-day sentiment aggregates. Sentiment is an
    informational signal, not a guaranteed trading signal — see this
    response's own `disclaimer` field."""
    security = _get_security_or_404(db, ticker.upper())
    return SentimentOverviewResponse(
        **news_query_service.get_sentiment_overview(db, security=security)
    )


@router.get("/{ticker}/sentiment/history", response_model=SentimentHistoryResponse)
def get_stock_sentiment_history(
    ticker: str,
    days: int = Query(default=30, ge=1, le=90),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> SentimentHistoryResponse:
    """Daily sentiment aggregates for the trailing `days` days, oldest
    first (chart-ready). Each day's figures use only articles published
    within that day — see `app/services/news_sentiment_aggregation.py`
    for the no-temporal-leakage guarantee this relies on."""
    security = _get_security_or_404(db, ticker.upper())
    return SentimentHistoryResponse(
        **news_query_service.get_sentiment_history(db, security=security, days=days)
    )


@router.get("/{ticker}/fundamentals", response_model=FundamentalsResponse)
def get_stock_fundamentals(
    ticker: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> FundamentalsResponse:
    """As-filed company facts only — never a derived ratio (P/E, growth,
    valuation). `available=False` in Demo Mode or for any security that
    hasn't had fundamentals ingested, never a fabricated value — see
    app/services/fundamentals_service.py."""
    _get_security_or_404(db, ticker.upper())
    report = fundamentals_service.get_fundamentals(db, ticker=ticker.upper())
    assert report is not None  # security existence already checked above
    return FundamentalsResponse(
        ticker=report.ticker,
        available=report.available,
        reason=report.reason,
        source=report.source,
        retrieved_at=report.retrieved_at,
        facts=[FundamentalFactRead(**vars(f)) for f in report.facts],
    )
