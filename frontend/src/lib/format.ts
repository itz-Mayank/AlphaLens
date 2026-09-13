export function formatPrice(value: string | null): string {
  if (value === null) return "—";
  return `$${Number(value).toFixed(2)}`;
}

export function formatChangePercent(value: string | null): { text: string; tone: string } {
  if (value === null) return { text: "—", tone: "text-muted" };
  const numeric = Number(value);
  const sign = numeric > 0 ? "+" : "";
  const tone = numeric > 0 ? "text-bullish" : numeric < 0 ? "text-bearish" : "text-muted";
  return { text: `${sign}${numeric.toFixed(2)}%`, tone };
}

export function formatVolume(value: number | null): string {
  if (value === null) return "—";
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}K`;
  return String(value);
}

export function formatRelativeDate(iso: string): string {
  const date = new Date(iso);
  const diffDays = Math.floor((Date.now() - date.getTime()) / (1000 * 60 * 60 * 24));
  if (diffDays <= 0) return "Today";
  if (diffDays === 1) return "Yesterday";
  if (diffDays < 7) return `${diffDays} days ago`;
  return date.toLocaleDateString();
}

/** Minute/hour-granularity "time ago" for freshness badges — falls back to
 * {@link formatRelativeDate} once the gap is a day or more. Only used where
 * the backend gives a raw timestamp and no freshness verdict of its own; if
 * an endpoint already returns a `freshness_status` enum, render that instead
 * of recomputing one client-side. */
export function formatRelativeTime(iso: string): string {
  const date = new Date(iso);
  const diffMs = Date.now() - date.getTime();
  const diffMinutes = Math.floor(diffMs / 60_000);
  if (diffMinutes < 1) return "Just now";
  if (diffMinutes < 60) return `${diffMinutes}m ago`;
  const diffHours = Math.floor(diffMinutes / 60);
  if (diffHours < 24) return `${diffHours}h ago`;
  return formatRelativeDate(iso);
}

/** Generic signed percentage formatter — accepts a number, a numeric string
 * (Decimal fields arrive as strings from the API), or null. Centralizes the
 * formatPercent/formatRatio variants previously duplicated per-page. */
export function formatPercent(
  value: number | string | null | undefined,
  decimals = 2,
): string {
  if (value === null || value === undefined) return "—";
  const numeric = typeof value === "string" ? Number(value) : value;
  if (Number.isNaN(numeric)) return "—";
  const sign = numeric > 0 ? "+" : "";
  return `${sign}${numeric.toFixed(decimals)}%`;
}

/** Plain (unsigned) ratio formatter for metrics like Sharpe/Sortino where a
 * leading "+" would be misleading. */
export function formatRatio(value: number | null | undefined, decimals = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toFixed(decimals);
}

const CURRENCY_FORMATTER = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

/** Full comma-grouped currency formatting (e.g. "$12,345.67") — distinct from
 * {@link formatPrice}'s bare `$X.XX`, which doesn't group large values. */
export function formatMoney(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  const numeric = typeof value === "string" ? Number(value) : value;
  if (Number.isNaN(numeric)) return "—";
  return CURRENCY_FORMATTER.format(numeric);
}

/** Tailwind text-color class for an arbitrary signed value (SHAP
 * contributions, sentiment momentum, etc.) — the same positive/negative/
 * neutral semantics used everywhere else, without repeating the ternary. */
export function toneForSign(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "text-muted";
  if (value > 0) return "text-bullish";
  if (value < 0) return "text-bearish";
  return "text-muted";
}

export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}
