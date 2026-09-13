import { formatRelativeTime } from "@/lib/format";

/** For the common case of "we have a raw `as_of`/timestamp field and no
 * backend-computed freshness verdict" — e.g. a single stock row's quote
 * timestamp. Where an endpoint already returns a freshness enum (dashboard's
 * `market_summary.freshness_status`), render that via StatusBadge instead;
 * don't recompute a verdict here that duplicates the backend's semantics. */
export function DataFreshnessBadge({ timestamp }: { timestamp: string | null | undefined }) {
  if (!timestamp) {
    return <span className="text-xs text-muted">Unavailable</span>;
  }
  return <span className="text-xs text-muted">Updated {formatRelativeTime(timestamp)}</span>;
}
