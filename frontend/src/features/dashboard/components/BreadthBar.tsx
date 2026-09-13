import { Card } from "@/components/Card";
import { EmptyState } from "@/components/EmptyState";

import type { MarketBreadth } from "../types";

export function BreadthBar({ breadth }: { breadth: MarketBreadth }) {
  if (breadth.status === "unavailable") {
    return (
      <EmptyState
        title="Market breadth unavailable"
        description="No securities currently have two consecutive days of price history as of the same date."
      />
    );
  }

  const advancing = breadth.advancing ?? 0;
  const declining = breadth.declining ?? 0;
  const unchanged = breadth.unchanged ?? 0;
  const total = advancing + declining + unchanged;

  return (
    <Card className="p-4">
      <div className="flex h-3 overflow-hidden rounded-full bg-border/40">
        {total > 0 && (
          <>
            <div className="bg-bullish" style={{ width: `${(advancing / total) * 100}%` }} />
            <div className="bg-border" style={{ width: `${(unchanged / total) * 100}%` }} />
            <div className="bg-bearish" style={{ width: `${(declining / total) * 100}%` }} />
          </>
        )}
      </div>
      <div className="mt-3 flex flex-wrap gap-x-6 gap-y-1 text-sm">
        <span>
          <span className="font-medium text-bullish">{advancing}</span>{" "}
          <span className="text-muted">advancing</span>
        </span>
        <span>
          <span className="font-medium text-bearish">{declining}</span>{" "}
          <span className="text-muted">declining</span>
        </span>
        <span>
          <span className="font-medium">{unchanged}</span>{" "}
          <span className="text-muted">unchanged</span>
        </span>
        {breadth.no_data > 0 && (
          <span className="text-muted">{breadth.no_data} without enough history</span>
        )}
      </div>
    </Card>
  );
}
