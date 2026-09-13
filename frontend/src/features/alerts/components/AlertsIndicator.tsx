import { useQuery } from "@tanstack/react-query";

import { listAlerts } from "../api";

const RECENT_WINDOW_MS = 24 * 60 * 60 * 1000;

/** Small header badge showing how many of the user's alerts fired in the
 * last 24h — derived from real `last_triggered_at` timestamps (Celery
 * beat's alert-evaluation schedule), not a fabricated "unread" count.
 * Polls at a modest interval since evaluation genuinely runs in the
 * background independent of this tab being open. */
export function AlertsIndicator() {
  const query = useQuery({
    queryKey: ["alerts", "indicator"],
    queryFn: listAlerts,
    staleTime: 60_000,
    refetchInterval: 60_000,
  });

  const recentCount = (query.data ?? []).filter((alert) => {
    if (!alert.last_triggered_at) return false;
    return Date.now() - new Date(alert.last_triggered_at).getTime() < RECENT_WINDOW_MS;
  }).length;

  if (recentCount === 0) return null;

  return (
    <span className="flex h-4 min-w-4 items-center justify-center rounded-full bg-warning px-1 text-[10px] font-semibold text-background">
      {recentCount}
    </span>
  );
}
