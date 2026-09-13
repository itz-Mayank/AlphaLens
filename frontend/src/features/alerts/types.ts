export type AlertType =
  | "PRICE_ABOVE"
  | "PRICE_BELOW"
  | "PERCENT_CHANGE_ABOVE"
  | "PERCENT_CHANGE_BELOW"
  | "FORECAST_CLASS_CHANGE"
  | "SENTIMENT_CHANGE"
  | "TECHNICAL_THRESHOLD";

export interface Alert {
  id: string;
  ticker: string;
  alert_type: AlertType;
  config: Record<string, unknown>;
  enabled: boolean;
  cooldown_minutes: number;
  last_triggered_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface AlertEvent {
  id: string;
  triggered_at: string;
  observed_value: Record<string, unknown>;
  message: string;
  created_at: string;
}

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface CreateAlertInput {
  ticker: string;
  config: Record<string, unknown> & { alert_type: AlertType };
  cooldown_minutes?: number;
}
