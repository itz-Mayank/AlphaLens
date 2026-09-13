import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { listAlertEvents } from "../api";

/** The per-alert triggered-event history — a real endpoint
 * (GET /alerts/:id/events) that the alert card previously never called,
 * showing only `last_triggered_at`. Fetched lazily, only once expanded, so
 * the Alerts list page itself stays a single batched `listAlerts()` call. */
export function AlertEventsList({ alertId }: { alertId: string }) {
  const [open, setOpen] = useState(false);

  const query = useQuery({
    queryKey: ["alerts", alertId, "events"],
    queryFn: () => listAlertEvents(alertId, 5, 0),
    enabled: open,
  });

  return (
    <div className="mt-2 border-t border-border/60 pt-2">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="text-xs text-muted hover:text-foreground"
      >
        {open ? "Hide recent events" : "Show recent events"}
      </button>
      {open && (
        <div className="mt-2 flex flex-col gap-1.5">
          {query.isLoading && <p className="text-xs text-muted">Loading…</p>}
          {query.isSuccess && query.data.items.length === 0 && (
            <p className="text-xs text-muted">No trigger events recorded yet.</p>
          )}
          {query.data?.items.map((event) => (
            <div key={event.id} className="rounded border border-border bg-background/40 px-2 py-1.5 text-xs">
              <p className="text-foreground">{event.message}</p>
              <p className="mt-0.5 text-muted">{new Date(event.triggered_at).toLocaleString()}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
