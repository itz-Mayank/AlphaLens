import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

import { Card } from "@/components/Card";
import { DemoDataBanner } from "@/components/DemoDataBanner";
import { MetricCard } from "@/components/MetricCard";
import { PageHeader } from "@/components/PageHeader";
import { SectionHeader } from "@/components/SectionHeader";
import { ApiError } from "@/lib/api-client";
import { toneForSign } from "@/lib/format";

import { runBacktest } from "./api";
import { DrawdownChart } from "./components/DrawdownChart";
import { EquityCurveChart } from "./components/EquityCurveChart";
import type { BacktestResponse } from "./types";

const KNOWN_ERROR_MESSAGES: Record<string, string> = {
  STOCK_NOT_FOUND: "One of the tickers you entered isn't known to this deployment yet.",
  TOO_MANY_TICKERS: "Too many tickers — please select 20 or fewer.",
  INSUFFICIENT_HISTORY: "Not enough price history for the requested tickers/date range.",
  UNSUPPORTED_TICKER: "None of the requested tickers are covered by the current research model.",
  MODEL_UNAVAILABLE: "No trained forecasting model is available right now.",
  DATA_VALIDATION_FAILED: "The requested tickers' price history failed data validation.",
  VALIDATION_ERROR: "Please check the form values (date range, ticker count).",
};

function formatPercent(value: number | null): string {
  if (value === null) return "—";
  return `${(value * 100).toFixed(2)}%`;
}

function formatRatio(value: number | null): string {
  return value === null ? "—" : value.toFixed(2);
}

export function BacktestPage() {
  const [tickersInput, setTickersInput] = useState("AAPL, MSFT, JPM");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [commissionBps, setCommissionBps] = useState(5);
  const [slippageBps, setSlippageBps] = useState(5);

  const backtestMutation = useMutation({
    mutationFn: () =>
      runBacktest({
        tickers: tickersInput
          .split(",")
          .map((t) => t.trim().toUpperCase())
          .filter(Boolean),
        start_date: startDate,
        end_date: endDate,
        commission_bps: commissionBps,
        slippage_bps: slippageBps,
      }),
  });

  const result: BacktestResponse | undefined = backtestMutation.data;
  const error = backtestMutation.error;
  const errorMessage =
    error instanceof ApiError
      ? (KNOWN_ERROR_MESSAGES[error.code] ?? error.message)
      : error
        ? "Something went wrong running this backtest."
        : null;

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Research Backtest"
        description="Runs the portfolio backtest engine against already-trained research models. Not a live trading result and not financial advice."
      />

      <Card className="flex flex-col gap-3 p-4">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <label className="flex flex-col gap-1 text-sm sm:col-span-2">
            <span className="text-xs text-muted">Tickers (comma-separated)</span>
            <input
              className="rounded border border-border bg-transparent px-2 py-1.5"
              value={tickersInput}
              onChange={(e) => setTickersInput(e.target.value)}
              placeholder="AAPL, MSFT, JPM"
            />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-xs text-muted">Start date</span>
            <input
              type="date"
              className="rounded border border-border bg-transparent px-2 py-1.5"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
            />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-xs text-muted">End date</span>
            <input
              type="date"
              className="rounded border border-border bg-transparent px-2 py-1.5"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
            />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-xs text-muted">Commission (bps)</span>
            <input
              type="number"
              min={0}
              className="rounded border border-border bg-transparent px-2 py-1.5"
              value={commissionBps}
              onChange={(e) => setCommissionBps(Number(e.target.value))}
            />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-xs text-muted">Slippage (bps)</span>
            <input
              type="number"
              min={0}
              className="rounded border border-border bg-transparent px-2 py-1.5"
              value={slippageBps}
              onChange={(e) => setSlippageBps(Number(e.target.value))}
            />
          </label>
        </div>

        <div>
          <button
            type="button"
            onClick={() => backtestMutation.mutate()}
            disabled={backtestMutation.isPending || !startDate || !endDate}
            className="rounded bg-primary px-3 py-1.5 text-sm font-medium text-white disabled:opacity-60"
          >
            {backtestMutation.isPending ? "Running backtest…" : "Run backtest"}
          </button>
        </div>

        {errorMessage && <p className="text-sm text-bearish">{errorMessage}</p>}
      </Card>

      {result && (
        <div className="flex flex-col gap-4">
          {result.data_sources.includes("demo") && <DemoDataBanner />}

          <section>
            <SectionHeader title="Equity Curve" />
            <Card className="p-4">
              <EquityCurveChart points={result.equity_curve} />
            </Card>
          </section>

          <section>
            <SectionHeader title="Drawdown" description="Computed from the equity curve above." />
            <Card className="p-4">
              <DrawdownChart points={result.equity_curve} />
            </Card>
          </section>

          <section>
            <SectionHeader title="Portfolio Metrics" />
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <MetricCard label="Cumulative return" value={formatPercent(result.metrics.cumulative_return)} tone={toneForSign(result.metrics.cumulative_return)} />
              <MetricCard label="CAGR" value={formatPercent(result.metrics.cagr)} tone={toneForSign(result.metrics.cagr)} />
              <MetricCard label="Annualized volatility" value={formatPercent(result.metrics.annualized_volatility)} />
              <MetricCard label="Sharpe ratio" value={formatRatio(result.metrics.sharpe_ratio)} />
              <MetricCard label="Sortino ratio" value={formatRatio(result.metrics.sortino_ratio)} />
              <MetricCard label="Max drawdown" value={formatPercent(result.metrics.max_drawdown)} tone="text-bearish" />
              <MetricCard label="Win rate" value={formatPercent(result.metrics.win_rate)} />
              <MetricCard label="Benchmark cumulative return" value={formatPercent(result.metrics.benchmark_cumulative_return)} tone={toneForSign(result.metrics.benchmark_cumulative_return)} />
              <MetricCard label="Rebalance events" value={String(result.num_rebalance_events)} />
              <MetricCard label="Mean turnover" value={formatPercent(result.metrics.turnover_mean)} />
              <MetricCard label="Total transaction costs" value={formatPercent(result.metrics.total_transaction_costs)} />
            </div>
          </section>

          <section>
            <SectionHeader title="Execution Assumptions" />
            <Card className="p-4 text-sm">
              <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
                <div>
                  <p className="text-xs text-muted">Commission</p>
                  <p className="font-medium">{result.commission_bps} bps</p>
                </div>
                <div>
                  <p className="text-xs text-muted">Slippage</p>
                  <p className="font-medium">{result.slippage_bps} bps</p>
                </div>
                <div>
                  <p className="text-xs text-muted">Initial capital</p>
                  <p className="font-medium">${result.initial_capital.toLocaleString("en-US")}</p>
                </div>
              </div>
              <p className="mt-3 text-xs text-muted">
                Signals are generated using information available at time t and executed with the
                configured lag — the backtest never looks ahead at future price or fundamentals data.
              </p>
            </Card>
          </section>

          <Card className="p-4 text-xs text-muted">
            <p>
              Model: {result.model_name} ({result.model_version}) · Feature set:{" "}
              {result.feature_version} · Dataset: {result.dataset_version}
            </p>
            <p className="mt-1">{result.disclaimer}</p>
          </Card>
        </div>
      )}
    </div>
  );
}
