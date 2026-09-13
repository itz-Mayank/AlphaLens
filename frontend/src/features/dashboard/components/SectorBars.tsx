import { Card } from "@/components/Card";
import { EmptyState } from "@/components/EmptyState";

import type { SectorPerformance } from "../types";

export function SectorBars({ sectors }: { sectors: SectorPerformance[] }) {
  if (sectors.length === 0) {
    return <EmptyState title="No sectors tracked yet" />;
  }

  const maxAbsReturn = Math.max(
    1,
    ...sectors.map((s) =>
      s.average_return_percent !== null ? Math.abs(Number(s.average_return_percent)) : 0,
    ),
  );

  return (
    <Card className="p-4">
      <ul className="flex flex-col gap-3">
        {sectors.map((sector) => {
          const value =
            sector.average_return_percent !== null ? Number(sector.average_return_percent) : null;
          const widthPercent = value !== null ? (Math.abs(value) / maxAbsReturn) * 50 : 0;
          const isPositive = value !== null && value >= 0;

          return (
            <li key={sector.sector} className="flex items-center gap-3 text-sm">
              <span className="w-36 shrink-0 truncate">{sector.sector}</span>
              <span className="relative h-4 flex-1">
                <span className="absolute left-1/2 top-0 h-full w-px bg-border" />
                <span
                  className={`absolute top-0 h-full ${isPositive ? "bg-bullish" : "bg-bearish"}`}
                  style={
                    isPositive
                      ? { left: "50%", width: `${widthPercent}%` }
                      : { right: "50%", width: `${widthPercent}%` }
                  }
                />
              </span>
              <span
                className={`w-20 shrink-0 text-right tabular-nums ${
                  value === null ? "text-muted" : isPositive ? "text-bullish" : "text-bearish"
                }`}
              >
                {value !== null ? `${value >= 0 ? "+" : ""}${value.toFixed(2)}%` : "—"}
              </span>
              <span className="w-16 shrink-0 text-right text-xs text-muted">
                {sector.securities_with_data}/{sector.security_count}
              </span>
            </li>
          );
        })}
      </ul>
    </Card>
  );
}
