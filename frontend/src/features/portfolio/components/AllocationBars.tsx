import { formatMoney } from "@/lib/format";

import type { Holding } from "../types";

const BAR_COLORS = ["#3b82f6", "#22c55e", "#f59e0b", "#a855f7", "#ec4899", "#14b8a6", "#f43f5e", "#6366f1"];

/** Allocation by market value, computed purely from real holdings —
 * excludes any holding whose price is currently unavailable (its
 * market_value is null) rather than treating it as zero, since that would
 * misrepresent the actual weighting. */
export function AllocationBars({ holdings }: { holdings: Holding[] }) {
  const priced = holdings
    .filter((h): h is Holding & { market_value: string } => h.market_value !== null)
    .map((h) => ({ ...h, value: Number(h.market_value) }))
    .sort((a, b) => b.value - a.value);

  const excludedCount = holdings.length - priced.length;
  const total = priced.reduce((sum, h) => sum + h.value, 0);

  if (priced.length === 0) {
    return <p className="text-sm text-muted">No holdings currently have a priced market value.</p>;
  }

  return (
    <div>
      <div className="flex h-3 overflow-hidden rounded-full bg-border/40">
        {priced.map((h, i) => (
          <div
            key={h.security_id}
            style={{ width: `${(h.value / total) * 100}%`, backgroundColor: BAR_COLORS[i % BAR_COLORS.length] }}
            title={`${h.ticker} — ${formatMoney(h.value)}`}
          />
        ))}
      </div>
      <ul className="mt-3 flex flex-col gap-1.5">
        {priced.map((h, i) => (
          <li key={h.security_id} className="flex items-center justify-between text-sm">
            <span className="flex items-center gap-2">
              <span
                className="inline-block h-2 w-2 shrink-0 rounded-full"
                style={{ backgroundColor: BAR_COLORS[i % BAR_COLORS.length] }}
              />
              {h.ticker}
            </span>
            <span className="tabular-nums text-muted">{((h.value / total) * 100).toFixed(1)}%</span>
          </li>
        ))}
      </ul>
      {excludedCount > 0 && (
        <p className="mt-2 text-xs text-muted">
          {excludedCount} holding{excludedCount === 1 ? "" : "s"} excluded — price currently unavailable.
        </p>
      )}
    </div>
  );
}
