import clsx from "clsx";
import type { FeatureContribution } from "../types";

/** Horizontal SHAP contribution bars — the actual per-feature signed values
 * from the backend's TreeExplainer output, never recomputed or estimated in
 * the frontend. Bar length is each feature's |contribution| relative to the
 * largest in the set; sign determines color and side. */
export function ShapBars({ factors }: { factors: FeatureContribution[] }) {
  if (factors.length === 0) {
    return <p className="text-sm text-muted">No contributing factors returned.</p>;
  }

  const maxAbs = Math.max(...factors.map((f) => Math.abs(f.contribution)), 1e-9);

  return (
    <ul className="flex flex-col gap-2">
      {factors.map((factor) => {
        const isPositive = factor.direction === "positive";
        const widthPercent = (Math.abs(factor.contribution) / maxAbs) * 100;
        return (
          <li key={factor.feature} className="grid grid-cols-[9rem_1fr_5rem] items-center gap-2 text-sm">
            <span className="truncate font-mono text-xs text-muted" title={factor.feature}>
              {factor.feature}
            </span>
            <span className="relative h-4">
              <span
                className={clsx("absolute top-0 h-full rounded-sm", isPositive ? "bg-bullish" : "bg-bearish")}
                style={{ width: `${Math.max(widthPercent, 3)}%` }}
              />
            </span>
            <span
              className={clsx(
                "text-right font-mono text-xs tabular-nums",
                isPositive ? "text-bullish" : "text-bearish",
              )}
            >
              {isPositive ? "+" : ""}
              {factor.contribution.toFixed(3)}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
