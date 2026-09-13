import { apiClient } from "@/lib/api-client";

import type { Alert, CreateAlertInput, Page, AlertEvent } from "./types";

export function listAlerts() {
  return apiClient.get<Alert[]>("/alerts");
}

export function createAlert(data: CreateAlertInput) {
  return apiClient.post<Alert>("/alerts", data);
}

export function updateAlert(alertId: string, data: { enabled?: boolean; cooldown_minutes?: number }) {
  return apiClient.patch<Alert>(`/alerts/${alertId}`, data);
}

export function deleteAlert(alertId: string) {
  return apiClient.delete<void>(`/alerts/${alertId}`);
}

export function listAlertEvents(alertId: string, limit = 10, offset = 0) {
  return apiClient.get<Page<AlertEvent>>(`/alerts/${alertId}/events?limit=${limit}&offset=${offset}`);
}
