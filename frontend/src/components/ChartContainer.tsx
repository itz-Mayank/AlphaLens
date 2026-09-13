import type { ReactNode } from "react";
import { Card } from "@/components/Card";
import { Skeleton } from "@/components/Skeleton";

interface ChartContainerProps {
  title?: string;
  legend?: ReactNode;
  actions?: ReactNode;
  isLoading?: boolean;
  isEmpty?: boolean;
  emptyMessage?: string;
  height?: number;
  children?: ReactNode;
}

/** Consistent chrome (title, legend, loading skeleton, empty state) around
 * every lightweight-charts chart in the app, so charts don't each re-invent
 * their own loading/empty handling. */
export function ChartContainer({
  title,
  legend,
  actions,
  isLoading,
  isEmpty,
  emptyMessage = "No chart data available.",
  height = 320,
  children,
}: ChartContainerProps) {
  return (
    <Card className="p-4">
      {(title || legend || actions) && (
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-3">
            {title && <h3 className="text-sm font-semibold text-foreground">{title}</h3>}
            {legend}
          </div>
          {actions}
        </div>
      )}
      {isLoading ? (
        <Skeleton className="w-full" style={{ height }} />
      ) : isEmpty ? (
        <div
          className="flex items-center justify-center rounded border border-dashed border-border text-sm text-muted"
          style={{ height }}
        >
          {emptyMessage}
        </div>
      ) : (
        children
      )}
    </Card>
  );
}
