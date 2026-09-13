import { Badge } from "@/components/Badge";

/** Every status vocabulary used across the app funnels through this one map
 * so "current"/"available"/"active" all read as the same visual "good"
 * signal, and "stale"/"unconfigured"/"paused" all read as the same
 * "attention" signal, without each page re-deriving its own tone ternary. */
const STATUS_TONE: Record<string, "bullish" | "bearish" | "warning" | "info" | "neutral"> = {
  current: "bullish",
  available: "bullish",
  active: "bullish",
  ok: "bullish",
  enabled: "bullish",
  healthy: "bullish",

  stale: "warning",
  outdated: "warning",
  unconfigured: "warning",
  demo: "warning",
  paused: "warning",
  degraded: "warning",

  unavailable: "bearish",
  no_data: "bearish",
  failed: "bearish",
  disabled: "neutral",

  archived: "neutral",
  candidate: "info",
};

const STATUS_LABEL: Record<string, string> = {
  current: "Current",
  stale: "Stale",
  outdated: "Outdated",
  no_data: "No data",
  available: "Available",
  unavailable: "Unavailable",
  unconfigured: "Unconfigured",
  demo: "Demo",
  ok: "OK",
  active: "Active",
  enabled: "Enabled",
  disabled: "Disabled",
  paused: "Paused",
  healthy: "Healthy",
  degraded: "Degraded",
  failed: "Failed",
  archived: "Archived",
  candidate: "Candidate",
};

interface StatusBadgeProps {
  status: string;
  label?: string;
  className?: string;
}

export function StatusBadge({ status, label, className }: StatusBadgeProps) {
  const key = status.toLowerCase();
  const tone = STATUS_TONE[key] ?? "neutral";
  return (
    <Badge tone={tone} className={className}>
      {label ?? STATUS_LABEL[key] ?? status}
    </Badge>
  );
}
