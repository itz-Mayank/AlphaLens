export interface Portfolio {
  id: string;
  name: string;
  description: string | null;
  base_currency: string;
  created_at: string;
  updated_at: string;
}

export type TransactionType = "BUY" | "SELL" | "CASH_DEPOSIT" | "CASH_WITHDRAWAL";

export interface Transaction {
  id: string;
  transaction_type: TransactionType;
  ticker: string | null;
  quantity: string | null;
  price: string | null;
  amount: string | null;
  fees: string;
  currency: string;
  executed_at: string;
  created_at: string;
}

export interface Holding {
  security_id: number;
  ticker: string;
  name: string;
  quantity: string;
  average_cost: string;
  cost_basis: string;
  last_price: string | null;
  market_value: string | null;
  unrealized_pnl: string | null;
  unrealized_pnl_percent: string | null;
}

export interface PortfolioAnalytics {
  cash: string;
  invested_capital: string;
  total_deposits: string;
  total_withdrawals: string;
  market_value: string | null;
  total_value: string | null;
  realized_pnl: string;
  unrealized_pnl: string | null;
  total_return_percent: string | null;
  market_value_is_partial: boolean;
  holdings: Holding[];
  methodology_note: string;
}

export interface PerformancePoint {
  as_of: string;
  cash: string;
  market_value: string | null;
  total_value: string | null;
  net_contributed: string;
}

export interface PerformanceHistory {
  available: boolean;
  reason: string | null;
  points: PerformancePoint[];
  methodology_note: string;
}

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface CreateTransactionInput {
  transaction_type: TransactionType;
  ticker?: string;
  quantity?: string;
  price?: string;
  amount?: string;
  fees?: string;
  executed_at?: string;
}
