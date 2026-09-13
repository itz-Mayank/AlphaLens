import type { ReactNode } from "react";
import clsx from "clsx";
import { Card } from "@/components/Card";

interface MetricCardProps {
  label: string;
  value: ReactNode;
  /** Optional secondary line under the value — a delta, a unit, a caption. */
  sublabel?: ReactNode;
  /** Text color class applied to `value`, e.g. from formatChangePercent/toneForSign. */
  tone?: string;
  className?: string;
}

export function MetricCard({ label, value, sublabel, tone, className }: MetricCardProps) {
  return (
    <Card className={clsx("px-4 py-3", className)}>
      <p className="text-xs uppercase tracking-wide text-muted">{label}</p>
      <p className={clsx("mt-1 text-lg font-semibold tabular-nums", tone ?? "text-foreground")}>{value}</p>
      {sublabel && <p className="mt-0.5 text-xs text-muted">{sublabel}</p>}
    </Card>
  );
}
