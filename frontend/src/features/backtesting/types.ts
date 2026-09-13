export interface BacktestRequest {
  tickers: string[];
  start_date: string;
  end_date: string;
  commission_bps?: number;
  slippage_bps?: number;
  initial_capital?: number;
  max_position_weight?: number | null;
}

export interface EquityCurvePoint {
  ts: string;
  equity: number;
  benchmark_equity: number;
}

export interface PortfolioMetrics {
  cumulative_return: number;
  cagr: number;
  annualized_volatility: number;
  sharpe_ratio: number | null;
  sortino_ratio: number | null;
  max_drawdown: number;
  win_rate: number | null;
  turnover_mean: number;
  total_transaction_costs: number;
  num_rebalance_days: number;
  benchmark_cumulative_return: number;
}

export interface BacktestResponse {
  tickers: string[];
  start_date: string;
  end_date: string;
  model_name: string;
  model_version: string;
  feature_version: string;
  dataset_version: string;
  commission_bps: number;
  slippage_bps: number;
  initial_capital: number;
  equity_curve: EquityCurvePoint[];
  metrics: PortfolioMetrics;
  num_rebalance_events: number;
  data_sources: string[];
  disclaimer: string;
}
