import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { Card } from "@/components/Card";
import { DataFreshnessBadge } from "@/components/DataFreshnessBadge";
import { DataTable, type DataTableColumn } from "@/components/DataTable";
import { DemoDataBanner } from "@/components/DemoDataBanner";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { SelectField, TextField } from "@/components/Field";
import { PageHeader } from "@/components/PageHeader";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { formatChangePercent, formatPrice, formatVolume } from "@/lib/format";

import { listStocks } from "./api";
import type { StockListItem } from "./types";

const PAGE_SIZE = 20;

export function StockExplorerPage() {
  const navigate = useNavigate();
  const [searchInput, setSearchInput] = useState("");
  const [sector, setSector] = useState("");
  const [offset, setOffset] = useState(0);
  const debouncedSearch = useDebouncedValue(searchInput, 300);

  const sectorOptionsQuery = useQuery({
    queryKey: ["stocks", "sector-options"],
    queryFn: () => listStocks({ limit: 100 }),
    staleTime: 5 * 60_000,
  });
  const sectorOptions = useMemo(() => {
    const sectors = new Set<string>();
    for (const item of sectorOptionsQuery.data?.items ?? []) {
      if (item.sector) sectors.add(item.sector);
    }
    return Array.from(sectors).sort();
  }, [sectorOptionsQuery.data]);

  const stocksQuery = useQuery({
    queryKey: ["stocks", { q: debouncedSearch, sector, offset }],
    queryFn: () =>
      listStocks({
        q: debouncedSearch || undefined,
        sector: sector || undefined,
        limit: PAGE_SIZE,
        offset,
      }),
  });

  const hasFilters = Boolean(debouncedSearch || sector);
  const items = stocksQuery.data?.items ?? [];
  const total = stocksQuery.data?.total ?? 0;
  const showsDemoData = items.some((item) => item.data_source === "demo");

  const columns: DataTableColumn<StockListItem>[] = [
    { key: "ticker", header: "Ticker", render: (r) => <span className="font-medium">{r.ticker}</span> },
    { key: "name", header: "Company", render: (r) => <span className="text-muted">{r.name}</span> },
    { key: "sector", header: "Sector", render: (r) => r.sector ?? "—" },
    { key: "price", header: "Price", align: "right", render: (r) => formatPrice(r.last_price) },
    {
      key: "change",
      header: "Change",
      align: "right",
      render: (r) => {
        const change = formatChangePercent(r.change_percent);
        return <span className={change.tone}>{change.text}</span>;
      },
    },
    {
      key: "volume",
      header: "Volume",
      align: "right",
      className: "text-muted",
      render: (r) => formatVolume(r.volume),
    },
    {
      key: "freshness",
      header: "Data Freshness",
      align: "right",
      render: (r) => <DataFreshnessBadge timestamp={r.as_of} />,
    },
  ];

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Stock Explorer"
        description="Search and filter tracked securities."
        meta={total > 0 ? <span className="text-xs text-muted">{total} securities tracked</span> : undefined}
      />

      {showsDemoData && <DemoDataBanner />}

      <Card className="flex flex-wrap gap-3 p-3">
        <TextField
          type="search"
          label="Search ticker or company name"
          value={searchInput}
          onChange={(e) => {
            setSearchInput(e.target.value);
            setOffset(0);
          }}
          placeholder="Search ticker or company name…"
          className="w-64"
        />
        <SelectField
          label="Sector"
          value={sector}
          onChange={(e) => {
            setSector(e.target.value);
            setOffset(0);
          }}
          className="w-48"
        >
          <option value="">All sectors</option>
          {sectorOptions.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </SelectField>
      </Card>

      {stocksQuery.isError && <ErrorState onRetry={() => stocksQuery.refetch()} />}

      {stocksQuery.isSuccess && items.length === 0 && (
        <EmptyState
          title={hasFilters ? "No matching stocks" : "No stocks yet"}
          description={
            hasFilters
              ? "Try a different search term or clear the sector filter."
              : "No securities have been ingested yet. An analyst or admin can trigger ingestion."
          }
        />
      )}

      {(!stocksQuery.isError && (stocksQuery.isLoading || items.length > 0)) && (
        <Card className="overflow-hidden p-0">
          <DataTable
            columns={columns}
            rows={items}
            rowKey={(r) => r.id}
            onRowClick={(r) => navigate(`/app/stocks/${r.ticker}`)}
            isLoading={stocksQuery.isLoading}
          />
        </Card>
      )}

      {stocksQuery.isSuccess && total > PAGE_SIZE && (
        <div className="flex items-center justify-between text-sm text-muted">
          <span>
            {offset + 1}–{Math.min(offset + PAGE_SIZE, total)} of {total}
          </span>
          <div className="flex gap-2">
            <button
              type="button"
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
              className="rounded border border-border px-3 py-1 disabled:opacity-40"
            >
              Previous
            </button>
            <button
              type="button"
              disabled={offset + PAGE_SIZE >= total}
              onClick={() => setOffset(offset + PAGE_SIZE)}
              className="rounded border border-border px-3 py-1 disabled:opacity-40"
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
