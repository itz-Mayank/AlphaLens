import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Card } from "@/components/Card";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { PageHeader } from "@/components/PageHeader";
import { SectionHeader } from "@/components/SectionHeader";
import { Skeleton } from "@/components/Skeleton";
import { StatusBadge } from "@/components/StatusBadge";
import { ApiError } from "@/lib/api-client";

import { createAlert, deleteAlert, listAlerts, updateAlert } from "./api";
import { AlertConditionForm } from "./components/AlertConditionForm";
import { AlertEventsList } from "./components/AlertEventsList";
import type { Alert, AlertType } from "./types";

const KNOWN_ERROR_MESSAGES: Record<string, string> = {
  STOCK_NOT_FOUND: "That ticker isn't known to this deployment yet.",
  VALIDATION_ERROR: "Please check the condition values.",
};

function describeCondition(alert: Alert): string {
  const c = alert.config;
  switch (alert.alert_type) {
    case "PRICE_ABOVE":
      return `Price above $${c.threshold}`;
    case "PRICE_BELOW":
      return `Price below $${c.threshold}`;
    case "PERCENT_CHANGE_ABOVE":
      return `Day change above ${c.threshold_percent}%`;
    case "PERCENT_CHANGE_BELOW":
      return `Day change below ${c.threshold_percent}%`;
    case "FORECAST_CLASS_CHANGE":
      return c.watch_class ? `Forecast changes to ${c.watch_class}` : "Forecast changes (any)";
    case "SENTIMENT_CHANGE":
      return `Sentiment shifts by ${c.threshold_delta}`;
    case "TECHNICAL_THRESHOLD":
      return `${c.indicator} ${c.operator} ${c.threshold}`;
    default:
      return alert.alert_type;
  }
}

export function AlertsPage() {
  const queryClient = useQueryClient();
  const [ticker, setTicker] = useState("");
  const [alertType, setAlertType] = useState<AlertType>("PRICE_ABOVE");
  const [config, setConfig] = useState<Record<string, string>>({});

  const alertsQuery = useQuery({ queryKey: ["alerts"], queryFn: listAlerts });

  const createMutation = useMutation({
    mutationFn: () => {
      const numericConfig: Record<string, unknown> = { alert_type: alertType };
      for (const [key, value] of Object.entries(config)) {
        numericConfig[key] = key === "watch_class" || key === "indicator" || key === "operator"
          ? value || undefined
          : Number(value);
      }
      return createAlert({
        ticker: ticker.trim().toUpperCase(),
        config: numericConfig as Record<string, unknown> & { alert_type: AlertType },
      });
    },
    onSuccess: () => {
      setTicker("");
      setConfig({});
      queryClient.invalidateQueries({ queryKey: ["alerts"] });
    },
  });

  const toggleMutation = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      updateAlert(id, { enabled }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["alerts"] }),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteAlert(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["alerts"] }),
  });

  const alerts = alertsQuery.data ?? [];
  const activeAlerts = alerts.filter((a) => a.enabled);
  const pausedAlerts = alerts.filter((a) => !a.enabled);
  const error = createMutation.error;
  const errorMessage =
    error instanceof ApiError ? (KNOWN_ERROR_MESSAGES[error.code] ?? error.message) : null;

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Alerts"
        description="Get notified when a real, application-computed condition is met. Alerts are evaluated periodically in the background."
        meta={
          alerts.length > 0 ? (
            <span className="text-xs text-muted">
              {activeAlerts.length} active · {pausedAlerts.length} paused
            </span>
          ) : undefined
        }
      />

      <Card className="flex flex-col gap-3 p-4">
        <label className="flex max-w-xs flex-col gap-1 text-sm">
          <span className="text-xs text-muted">Ticker</span>
          <input
            className="rounded border border-border bg-transparent px-2 py-1.5 uppercase"
            value={ticker}
            onChange={(e) => setTicker(e.target.value)}
            placeholder="AAPL"
          />
        </label>
        <AlertConditionForm
          alertType={alertType}
          onAlertTypeChange={(type) => {
            setAlertType(type);
            setConfig({});
          }}
          config={config}
          onConfigChange={setConfig}
        />
        <div>
          <button
            type="button"
            onClick={() => createMutation.mutate()}
            disabled={!ticker.trim() || createMutation.isPending}
            className="rounded bg-primary px-3 py-1.5 text-sm font-medium text-white disabled:opacity-60"
          >
            {createMutation.isPending ? "Creating…" : "Create alert"}
          </button>
        </div>
        {errorMessage && <p className="text-sm text-bearish">{errorMessage}</p>}
      </Card>

      {alertsQuery.isLoading && (
        <div className="flex flex-col gap-2">
          {Array.from({ length: 2 }).map((_, i) => (
            <Skeleton key={i} className="h-16 w-full" />
          ))}
        </div>
      )}

      {alertsQuery.isError && <ErrorState onRetry={() => alertsQuery.refetch()} />}

      {alertsQuery.isSuccess && alerts.length === 0 && (
        <EmptyState
          title="No alerts yet"
          description="Create one above to get notified when a real condition is met."
        />
      )}

      {activeAlerts.length > 0 && (
        <section>
          <SectionHeader title="Active" />
          <div className="flex flex-col gap-2">
            {activeAlerts.map((alert) => (
              <AlertCard
                key={alert.id}
                alert={alert}
                onToggle={() => toggleMutation.mutate({ id: alert.id, enabled: !alert.enabled })}
                onDelete={() => deleteMutation.mutate(alert.id)}
                togglePending={toggleMutation.isPending}
                deletePending={deleteMutation.isPending}
              />
            ))}
          </div>
        </section>
      )}

      {pausedAlerts.length > 0 && (
        <section>
          <SectionHeader title="Paused" />
          <div className="flex flex-col gap-2">
            {pausedAlerts.map((alert) => (
              <AlertCard
                key={alert.id}
                alert={alert}
                onToggle={() => toggleMutation.mutate({ id: alert.id, enabled: !alert.enabled })}
                onDelete={() => deleteMutation.mutate(alert.id)}
                togglePending={toggleMutation.isPending}
                deletePending={deleteMutation.isPending}
              />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

function AlertCard({
  alert,
  onToggle,
  onDelete,
  togglePending,
  deletePending,
}: {
  alert: Alert;
  onToggle: () => void;
  onDelete: () => void;
  togglePending: boolean;
  deletePending: boolean;
}) {
  return (
    <Card className="p-4">
      <div className="flex items-center justify-between">
        <div>
          <p className="font-medium">
            {alert.ticker} / {describeCondition(alert)}
          </p>
          <p className="text-xs text-muted">
            {alert.last_triggered_at
              ? `Last triggered ${new Date(alert.last_triggered_at).toLocaleString()}`
              : "Never triggered yet"}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <StatusBadge status={alert.enabled ? "active" : "paused"} label={alert.enabled ? "Active" : "Paused"} />
          <button
            type="button"
            onClick={onToggle}
            disabled={togglePending}
            className="rounded border border-border px-2.5 py-1 text-xs text-muted hover:text-foreground disabled:opacity-50"
          >
            {alert.enabled ? "Pause" : "Resume"}
          </button>
          <button
            type="button"
            onClick={onDelete}
            disabled={deletePending}
            className="rounded border border-border px-2.5 py-1 text-xs text-muted hover:text-bearish disabled:opacity-50"
          >
            Delete
          </button>
        </div>
      </div>
      <AlertEventsList alertId={alert.id} />
    </Card>
  );
}
