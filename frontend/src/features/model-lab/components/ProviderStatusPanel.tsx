import { useQuery } from "@tanstack/react-query";

import { Card } from "@/components/Card";
import { Skeleton } from "@/components/Skeleton";
import { StatusBadge } from "@/components/StatusBadge";
import { formatRelativeTime } from "@/lib/format";
import { useAuthStore } from "@/stores/authStore";

import { getProviderStatus } from "../api";
import type { ProviderStatus } from "../types";

const CATEGORY_LABELS: Record<string, string> = {
  market_data: "Market Data",
  fundamentals: "Fundamentals",
  macro: "Macro",
  news: "News",
};

/** Derives a display status purely from the fields the backend already
 * returns — never invents a health check of its own. "Unconfigured" means
 * a credential this category needs is missing; "Demo" means the demo
 * provider is active (needs no credential, by design); "Unavailable" means
 * the most recent attempt failed; "Available" means the most recent
 * attempt succeeded. */
function deriveStatus(p: ProviderStatus): string {
  if (p.configured_provider === "none") return "unconfigured";
  if (p.configured_provider === "demo") return "demo";
  if (p.credential_required && !p.credential_configured) return "unconfigured";
  const lastFailureIsNewer =
    p.last_failure_at && (!p.last_success_at || p.last_failure_at > p.last_success_at);
  if (lastFailureIsNewer) return "unavailable";
  if (p.last_success_at) return "available";
  return "unconfigured";
}

/** Compact provider-health area — GET /api/v1/system/providers is
 * ANALYST/ADMIN only, so this renders nothing for a plain USER rather than
 * eagerly issuing a request that will 403. */
export function ProviderStatusPanel() {
  const role = useAuthStore((s) => s.user?.role);
  const canView = role === "ANALYST" || role === "ADMIN";

  const query = useQuery({
    queryKey: ["system", "providers"],
    queryFn: getProviderStatus,
    enabled: canView,
    staleTime: 60_000,
  });

  if (!canView) return null;

  return (
    <Card className="p-4">
      {query.isLoading && <Skeleton className="h-20 w-full" />}
      {query.isError && <p className="text-sm text-muted">Provider status is unavailable right now.</p>}
      {query.data && (
        <ul className="flex flex-col divide-y divide-border/60">
          {query.data.providers.map((p) => {
            const status = deriveStatus(p);
            return (
              <li key={p.category} className="flex items-center justify-between gap-3 py-2 text-sm">
                <div>
                  <p className="font-medium text-foreground">{CATEGORY_LABELS[p.category] ?? p.category}</p>
                  <p className="text-xs text-muted">
                    {p.configured_provider === "none" ? "No provider configured" : p.configured_provider}
                    {p.last_success_at && ` · Last success ${formatRelativeTime(p.last_success_at)}`}
                  </p>
                  {status === "unavailable" && p.last_failure_reason && (
                    <p className="mt-0.5 text-xs text-bearish">{p.last_failure_reason}</p>
                  )}
                </div>
                <StatusBadge status={status} />
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}
