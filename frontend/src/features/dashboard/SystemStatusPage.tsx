import { useQuery } from "@tanstack/react-query";

import { fetchHealth } from "@/lib/api-client";
import { useUiStore } from "@/stores/uiStore";

export function SystemStatusPage() {
  const theme = useUiStore((s) => s.theme);
  const toggleTheme = useUiStore((s) => s.toggleTheme);

  const health = useQuery({
    queryKey: ["health"],
    queryFn: fetchHealth,
    retry: false,
  });

  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-6 px-6">
      <div className="text-center">
        <h1 className="text-3xl font-semibold tracking-tight">AlphaLens</h1>
        <p className="mt-1 text-sm text-muted">
          AI-powered market intelligence, forecasting, research, and portfolio analytics.
        </p>
      </div>

      <div className="w-full max-w-sm rounded-lg border border-border bg-surface p-4">
        <div className="flex items-center justify-between text-sm">
          <span className="text-muted">API status</span>
          {health.isLoading && <span className="text-muted">checking…</span>}
          {health.isSuccess && (
            <span className="font-medium text-bullish">{health.data.status}</span>
          )}
          {health.isError && <span className="font-medium text-bearish">unreachable</span>}
        </div>
      </div>

      <button
        type="button"
        onClick={toggleTheme}
        className="rounded border border-border px-3 py-1.5 text-sm text-muted hover:text-foreground"
      >
        Switch to {theme === "dark" ? "light" : "dark"} mode
      </button>

      <p className="max-w-md text-center text-xs text-muted">
        Analytical and educational information only. Not financial advice. Predictions are
        probabilistic and may be wrong; past performance does not guarantee future results.
      </p>
    </main>
  );
}
