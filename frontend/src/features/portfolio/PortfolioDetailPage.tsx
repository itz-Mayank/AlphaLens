import { useQuery } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";

import { Card } from "@/components/Card";
import { ChartContainer } from "@/components/ChartContainer";
import { DataTable, type DataTableColumn } from "@/components/DataTable";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { MetricCard } from "@/components/MetricCard";
import { PageHeader } from "@/components/PageHeader";
import { SectionHeader } from "@/components/SectionHeader";
import { Skeleton, SkeletonMetricCards } from "@/components/Skeleton";
import { ApiError } from "@/lib/api-client";
import { formatMoney, formatPercent, toneForSign } from "@/lib/format";

import { getAnalytics, getHoldings, getPerformance, getPortfolio, listTransactions } from "./api";
import { AllocationBars } from "./components/AllocationBars";
import { PortfolioValueChart } from "./components/PortfolioValueChart";
import { TransactionForm } from "./components/TransactionForm";
import type { Holding, Transaction } from "./types";

export function PortfolioDetailPage() {
  const { portfolioId } = useParams<{ portfolioId: string }>();
  const navigate = useNavigate();
  const id = portfolioId as string;

  const portfolioQuery = useQuery({
    queryKey: ["portfolios", id],
    queryFn: () => getPortfolio(id),
    enabled: Boolean(id),
  });
  const analyticsQuery = useQuery({
    queryKey: ["portfolios", id, "analytics"],
    queryFn: () => getAnalytics(id),
    enabled: Boolean(id),
  });
  const holdingsQuery = useQuery({
    queryKey: ["portfolios", id, "holdings"],
    queryFn: () => getHoldings(id),
    enabled: Boolean(id),
  });
  const transactionsQuery = useQuery({
    queryKey: ["portfolios", id, "transactions"],
    queryFn: () => listTransactions(id, 20, 0),
    enabled: Boolean(id),
  });
  const performanceQuery = useQuery({
    queryKey: ["portfolios", id, "performance"],
    queryFn: () => getPerformance(id),
    enabled: Boolean(id),
  });

  if (portfolioQuery.isLoading) {
    return (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-8 w-64" />
        <SkeletonMetricCards />
      </div>
    );
  }

  if (portfolioQuery.isError) {
    const error = portfolioQuery.error;
    if (error instanceof ApiError && error.status === 404) {
      return <ErrorState message="This portfolio doesn't exist or isn't yours." />;
    }
    return <ErrorState onRetry={() => portfolioQuery.refetch()} />;
  }

  const portfolio = portfolioQuery.data;
  if (!portfolio) return null;

  const analytics = analyticsQuery.data;
  const holdings = holdingsQuery.data ?? [];
  const transactions = transactionsQuery.data?.items ?? [];

  const holdingColumns: DataTableColumn<Holding>[] = [
    { key: "ticker", header: "Ticker", render: (r) => <span className="font-medium">{r.ticker}</span> },
    { key: "quantity", header: "Quantity", align: "right", render: (r) => r.quantity },
    { key: "avgCost", header: "Avg Cost", align: "right", render: (r) => formatMoney(r.average_cost) },
    {
      key: "lastPrice",
      header: "Current Price",
      align: "right",
      render: (r) => (r.last_price === null ? <span className="text-muted">No data yet</span> : formatMoney(r.last_price)),
    },
    {
      key: "marketValue",
      header: "Market Value",
      align: "right",
      render: (r) => (r.market_value === null ? <span className="text-muted">—</span> : formatMoney(r.market_value)),
    },
    {
      key: "pnl",
      header: "P&L",
      align: "right",
      render: (r) =>
        r.unrealized_pnl === null ? (
          <span className="text-muted">—</span>
        ) : (
          <span className={toneForSign(Number(r.unrealized_pnl))}>{formatMoney(r.unrealized_pnl)}</span>
        ),
    },
    {
      key: "pnlPercent",
      header: "P&L %",
      align: "right",
      render: (r) =>
        r.unrealized_pnl_percent === null ? (
          <span className="text-muted">—</span>
        ) : (
          <span className={toneForSign(Number(r.unrealized_pnl_percent))}>
            {formatPercent(r.unrealized_pnl_percent)}
          </span>
        ),
    },
  ];

  const transactionColumns: DataTableColumn<Transaction>[] = [
    { key: "date", header: "Date", render: (t) => new Date(t.executed_at).toLocaleDateString() },
    { key: "type", header: "Type", render: (t) => t.transaction_type },
    { key: "ticker", header: "Ticker", render: (t) => t.ticker ?? "—" },
    { key: "quantity", header: "Quantity", align: "right", render: (t) => t.quantity ?? "—" },
    { key: "price", header: "Price", align: "right", render: (t) => (t.price ? formatMoney(t.price) : "—") },
    { key: "amount", header: "Amount", align: "right", render: (t) => (t.amount ? formatMoney(t.amount) : "—") },
    { key: "fees", header: "Fees", align: "right", className: "text-muted", render: (t) => formatMoney(t.fees) },
  ];

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title={portfolio.name}
        description={`Base currency ${portfolio.base_currency}`}
        meta={
          <button
            type="button"
            onClick={() => navigate("/app/portfolio")}
            className="text-xs text-muted hover:text-foreground"
          >
            ← All portfolios
          </button>
        }
      />

      {analyticsQuery.isLoading && <SkeletonMetricCards />}
      {analyticsQuery.isError && <ErrorState onRetry={() => analyticsQuery.refetch()} />}
      {analytics && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <MetricCard label="Cash" value={formatMoney(analytics.cash)} />
          <MetricCard
            label="Market value"
            value={analytics.market_value_is_partial ? "Partially unavailable" : formatMoney(analytics.market_value)}
          />
          <MetricCard label="Total value" value={formatMoney(analytics.total_value)} />
          <MetricCard
            label="Total return"
            value={formatPercent(analytics.total_return_percent)}
            tone={analytics.total_return_percent !== null ? toneForSign(Number(analytics.total_return_percent)) : undefined}
          />
          <MetricCard
            label="Realized P&L"
            value={formatMoney(analytics.realized_pnl)}
            tone={toneForSign(Number(analytics.realized_pnl))}
          />
          <MetricCard
            label="Unrealized P&L"
            value={formatMoney(analytics.unrealized_pnl)}
            tone={analytics.unrealized_pnl !== null ? toneForSign(Number(analytics.unrealized_pnl)) : undefined}
          />
          <MetricCard label="Net contributed" value={formatMoney(analytics.invested_capital)} />
        </div>
      )}
      {analytics && <p className="text-xs text-muted">{analytics.methodology_note}</p>}

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <SectionHeader title="Portfolio Value" />
          {performanceQuery.isLoading && <Skeleton className="h-72 w-full" />}
          {performanceQuery.data && !performanceQuery.data.available && (
            <ChartContainer isEmpty emptyMessage={performanceQuery.data.reason ?? "Not enough data yet."} />
          )}
          {performanceQuery.data?.available && (
            <ChartContainer>
              <PortfolioValueChart points={performanceQuery.data.points} />
              <p className="mt-2 text-xs text-muted">{performanceQuery.data.methodology_note}</p>
            </ChartContainer>
          )}
        </div>
        <div>
          <SectionHeader title="Allocation" description="By current market value" />
          <Card className="p-4">
            <AllocationBars holdings={holdings} />
          </Card>
        </div>
      </div>

      <section>
        <SectionHeader title="Record a Transaction" />
        <Card className="p-4">
          <TransactionForm portfolioId={id} />
        </Card>
      </section>

      <section>
        <SectionHeader title="Holdings" />
        {holdingsQuery.isLoading && <Skeleton className="h-24 w-full" />}
        {holdingsQuery.isSuccess && holdings.length === 0 && (
          <EmptyState title="No open positions" description="Record a BUY transaction above to see holdings here." />
        )}
        {holdings.length > 0 && (
          <Card className="overflow-hidden p-0">
            <DataTable columns={holdingColumns} rows={holdings} rowKey={(h) => h.security_id} />
          </Card>
        )}
      </section>

      <section>
        <SectionHeader title="Recent Transactions" />
        {transactionsQuery.isLoading && <Skeleton className="h-24 w-full" />}
        {transactionsQuery.isSuccess && transactions.length === 0 && (
          <EmptyState title="No transactions yet" description="Record one above to get started." />
        )}
        {transactions.length > 0 && (
          <Card className="overflow-hidden p-0">
            <DataTable columns={transactionColumns} rows={transactions} rowKey={(t) => t.id} />
          </Card>
        )}
      </section>
    </div>
  );
}
