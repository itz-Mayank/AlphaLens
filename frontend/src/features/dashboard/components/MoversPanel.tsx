import { useNavigate } from "react-router-dom";

import { Card } from "@/components/Card";
import { EmptyState } from "@/components/EmptyState";
import { formatChangePercent, formatVolume } from "@/lib/format";

import type { ActiveItem, MoverItem } from "../types";

interface MoversListProps {
  title: string;
  items: MoverItem[] | ActiveItem[];
  metric: "change" | "volume";
}

function isMoverItem(item: MoverItem | ActiveItem): item is MoverItem {
  return "change_percent" in item;
}

function MoversList({ title, items, metric }: MoversListProps) {
  const navigate = useNavigate();

  return (
    <Card className="p-4">
      <h3 className="text-sm font-medium text-foreground">{title}</h3>
      {items.length === 0 ? (
        <p className="mt-3 text-xs text-muted">Not enough data yet.</p>
      ) : (
        <ul className="mt-3 flex flex-col gap-2">
          {items.map((item) => {
            const change = isMoverItem(item) ? formatChangePercent(item.change_percent) : null;
            return (
              <li key={item.ticker}>
                <button
                  type="button"
                  onClick={() => navigate(`/app/stocks/${item.ticker}`)}
                  className="flex w-full items-center justify-between rounded px-1.5 py-1 text-left text-sm hover:bg-border/30"
                >
                  <span className="flex flex-col">
                    <span className="font-medium">{item.ticker}</span>
                    <span className="text-xs text-muted">{item.sector ?? "—"}</span>
                  </span>
                  <span
                    className={`tabular-nums ${metric === "change" ? change?.tone : "text-muted"}`}
                  >
                    {metric === "change" ? change?.text : formatVolume(item.volume)}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}

export function MoversPanel({
  topGainers,
  topLosers,
  mostActive,
}: {
  topGainers: MoverItem[];
  topLosers: MoverItem[];
  mostActive: ActiveItem[];
}) {
  if (topGainers.length === 0 && topLosers.length === 0 && mostActive.length === 0) {
    return (
      <EmptyState
        title="No market movers yet"
        description="Once securities have at least two days of price history, gainers, losers, and the most active names will appear here."
      />
    );
  }

  return (
    <div className="grid gap-3 sm:grid-cols-3">
      <MoversList title="Top Gainers" items={topGainers} metric="change" />
      <MoversList title="Top Losers" items={topLosers} metric="change" />
      <MoversList title="Most Active" items={mostActive} metric="volume" />
    </div>
  );
}
