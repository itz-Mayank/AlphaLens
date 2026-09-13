from datetime import date

from pydantic import BaseModel, Field, field_validator


class BacktestRequest(BaseModel):
    tickers: list[str] = Field(min_length=1, max_length=20)
    start_date: date
    end_date: date
    commission_bps: float = Field(default=5.0, ge=0)
    slippage_bps: float = Field(default=5.0, ge=0)
    initial_capital: float = Field(default=100_000.0, gt=0)
    max_position_weight: float | None = Field(default=None, gt=0, le=1)

    @field_validator("tickers")
    @classmethod
    def _uppercase_tickers(cls, value: list[str]) -> list[str]:
        return [t.upper() for t in value]

    @field_validator("end_date")
    @classmethod
    def _end_after_start(cls, value: date, info) -> date:
        start = info.data.get("start_date")
        if start is not None and value <= start:
            raise ValueError("end_date must be after start_date")
        return value


class EquityCurvePoint(BaseModel):
    ts: date
    equity: float
    benchmark_equity: float


class PortfolioMetricsRead(BaseModel):
    cumulative_return: float
    cagr: float
    annualized_volatility: float
    sharpe_ratio: float | None
    sortino_ratio: float | None
    max_drawdown: float
    win_rate: float | None
    turnover_mean: float
    total_transaction_costs: float
    num_rebalance_days: int
    benchmark_cumulative_return: float


class BacktestResponse(BaseModel):
    tickers: list[str]
    start_date: date
    end_date: date
    model_name: str
    model_version: str
    feature_version: str
    dataset_version: str
    commission_bps: float
    slippage_bps: float
    initial_capital: float
    equity_curve: list[EquityCurvePoint]
    metrics: PortfolioMetricsRead
    num_rebalance_events: int
    data_sources: list[str]
    disclaimer: str = (
        "Research backtest — not a live trading result and not financial "
        "advice. A positive result here is evidence the pipeline runs "
        "correctly end to end, not evidence of future profitability."
    )
