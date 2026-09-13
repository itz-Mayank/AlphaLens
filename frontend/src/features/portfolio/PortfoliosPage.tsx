import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { Card } from "@/components/Card";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { Skeleton } from "@/components/Skeleton";
import { formatRelativeDate } from "@/lib/format";

import { createPortfolio, deletePortfolio, listPortfolios } from "./api";

export function PortfoliosPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [name, setName] = useState("");

  const portfoliosQuery = useQuery({ queryKey: ["portfolios"], queryFn: listPortfolios });

  const createMutation = useMutation({
    mutationFn: () => createPortfolio({ name: name.trim() }),
    onSuccess: () => {
      setName("");
      queryClient.invalidateQueries({ queryKey: ["portfolios"] });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (portfolioId: string) => deletePortfolio(portfolioId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["portfolios"] }),
  });

  const items = portfoliosQuery.data ?? [];

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Portfolios</h1>
        <p className="mt-1 text-sm text-muted">
          Track real holdings from transactions you record — no simulated or fabricated
          performance.
        </p>
      </div>

      <Card className="flex flex-wrap items-end gap-3 p-4">
        <label className="flex flex-1 min-w-[200px] flex-col gap-1 text-sm">
          <span className="text-xs text-muted">New portfolio name</span>
          <input
            className="rounded border border-border bg-transparent px-2 py-1.5"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Main Brokerage"
          />
        </label>
        <button
          type="button"
          onClick={() => createMutation.mutate()}
          disabled={!name.trim() || createMutation.isPending}
          className="rounded bg-primary px-3 py-1.5 text-sm font-medium text-white disabled:opacity-60"
        >
          {createMutation.isPending ? "Creating…" : "Create portfolio"}
        </button>
      </Card>

      {portfoliosQuery.isLoading && (
        <div className="flex flex-col gap-2">
          {Array.from({ length: 2 }).map((_, i) => (
            <Skeleton key={i} className="h-16 w-full" />
          ))}
        </div>
      )}

      {portfoliosQuery.isError && <ErrorState onRetry={() => portfoliosQuery.refetch()} />}

      {portfoliosQuery.isSuccess && items.length === 0 && (
        <EmptyState
          title="No portfolios yet"
          description="Create one above, then record deposits and trades to see real holdings and performance."
        />
      )}

      {items.length > 0 && (
        <div className="flex flex-col gap-2">
          {items.map((portfolio) => (
            <Card
              key={portfolio.id}
              className="flex cursor-pointer items-center justify-between p-4 hover:bg-border/20"
              onClick={() => navigate(`/app/portfolio/${portfolio.id}`)}
            >
              <div>
                <p className="font-medium">{portfolio.name}</p>
                <p className="text-xs text-muted">
                  {portfolio.base_currency} · Created {formatRelativeDate(portfolio.created_at)}
                </p>
              </div>
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  deleteMutation.mutate(portfolio.id);
                }}
                disabled={deleteMutation.isPending}
                className="rounded border border-border px-2.5 py-1 text-xs text-muted hover:text-bearish disabled:opacity-50"
              >
                Delete
              </button>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
