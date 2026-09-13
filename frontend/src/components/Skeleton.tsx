import type { CSSProperties } from "react";
import clsx from "clsx";

export function Skeleton({ className, style }: { className?: string; style?: CSSProperties }) {
  return <div className={clsx("animate-pulse rounded bg-border/60", className)} style={style} />;
}

/** A row of stat-card skeletons — dashboard summary, portfolio analytics,
 * stock detail key metrics, etc. all use the same 4-up shape. */
export function SkeletonMetricCards({ count = 4 }: { count?: number }) {
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="rounded-lg border border-border bg-surface px-4 py-3">
          <Skeleton className="h-3 w-16" />
          <Skeleton className="mt-2 h-5 w-20" />
        </div>
      ))}
    </div>
  );
}

/** Generic block-of-text skeleton for cards without a table/chart shape. */
export function SkeletonText({ lines = 3 }: { lines?: number }) {
  return (
    <div className="space-y-2">
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton key={i} className={clsx("h-3.5", i === lines - 1 ? "w-2/3" : "w-full")} />
      ))}
    </div>
  );
}
