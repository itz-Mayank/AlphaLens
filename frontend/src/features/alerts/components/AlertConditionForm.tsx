import type { AlertType } from "../types";

const INDICATORS = [
  "sma_20", "ema_12", "rsi_14", "macd_line", "macd_signal", "macd_histogram",
  "volatility_20d", "atr_14", "bollinger_percent_b", "relative_volume_20",
];

interface Props {
  alertType: AlertType;
  onAlertTypeChange: (type: AlertType) => void;
  config: Record<string, string>;
  onConfigChange: (config: Record<string, string>) => void;
}

const TYPE_OPTIONS: { value: AlertType; label: string }[] = [
  { value: "PRICE_ABOVE", label: "Price above" },
  { value: "PRICE_BELOW", label: "Price below" },
  { value: "PERCENT_CHANGE_ABOVE", label: "Day change above" },
  { value: "PERCENT_CHANGE_BELOW", label: "Day change below" },
  { value: "FORECAST_CLASS_CHANGE", label: "Forecast changes" },
  { value: "SENTIMENT_CHANGE", label: "Sentiment shifts" },
  { value: "TECHNICAL_THRESHOLD", label: "Technical indicator threshold" },
];

export function AlertConditionForm({ alertType, onAlertTypeChange, config, onConfigChange }: Props) {
  const setField = (key: string, value: string) => onConfigChange({ ...config, [key]: value });

  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <label className="flex flex-col gap-1 text-sm">
        <span className="text-xs text-muted">Condition</span>
        <select
          className="rounded border border-border bg-transparent px-2 py-1.5"
          value={alertType}
          onChange={(e) => onAlertTypeChange(e.target.value as AlertType)}
        >
          {TYPE_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      </label>

      {(alertType === "PRICE_ABOVE" || alertType === "PRICE_BELOW") && (
        <label className="flex flex-col gap-1 text-sm">
          <span className="text-xs text-muted">Threshold ($)</span>
          <input
            type="number"
            min={0}
            step="any"
            className="rounded border border-border bg-transparent px-2 py-1.5"
            value={config.threshold ?? ""}
            onChange={(e) => setField("threshold", e.target.value)}
          />
        </label>
      )}

      {(alertType === "PERCENT_CHANGE_ABOVE" || alertType === "PERCENT_CHANGE_BELOW") && (
        <label className="flex flex-col gap-1 text-sm">
          <span className="text-xs text-muted">Threshold (%)</span>
          <input
            type="number"
            step="any"
            className="rounded border border-border bg-transparent px-2 py-1.5"
            value={config.threshold_percent ?? ""}
            onChange={(e) => setField("threshold_percent", e.target.value)}
          />
        </label>
      )}

      {alertType === "FORECAST_CLASS_CHANGE" && (
        <label className="flex flex-col gap-1 text-sm">
          <span className="text-xs text-muted">Watch for (optional)</span>
          <select
            className="rounded border border-border bg-transparent px-2 py-1.5"
            value={config.watch_class ?? ""}
            onChange={(e) => setField("watch_class", e.target.value)}
          >
            <option value="">Any change</option>
            <option value="Bullish">Bullish</option>
            <option value="Neutral">Neutral</option>
            <option value="Bearish">Bearish</option>
          </select>
        </label>
      )}

      {alertType === "SENTIMENT_CHANGE" && (
        <label className="flex flex-col gap-1 text-sm">
          <span className="text-xs text-muted">Min. shift (0-2)</span>
          <input
            type="number"
            min={0}
            max={2}
            step="any"
            className="rounded border border-border bg-transparent px-2 py-1.5"
            value={config.threshold_delta ?? ""}
            onChange={(e) => setField("threshold_delta", e.target.value)}
          />
        </label>
      )}

      {alertType === "TECHNICAL_THRESHOLD" && (
        <>
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-xs text-muted">Indicator</span>
            <select
              className="rounded border border-border bg-transparent px-2 py-1.5"
              value={config.indicator ?? INDICATORS[0]}
              onChange={(e) => setField("indicator", e.target.value)}
            >
              {INDICATORS.map((ind) => (
                <option key={ind} value={ind}>
                  {ind}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-xs text-muted">Operator</span>
            <select
              className="rounded border border-border bg-transparent px-2 py-1.5"
              value={config.operator ?? "above"}
              onChange={(e) => setField("operator", e.target.value)}
            >
              <option value="above">Above</option>
              <option value="below">Below</option>
            </select>
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-xs text-muted">Threshold</span>
            <input
              type="number"
              step="any"
              className="rounded border border-border bg-transparent px-2 py-1.5"
              value={config.threshold ?? ""}
              onChange={(e) => setField("threshold", e.target.value)}
            />
          </label>
        </>
      )}
    </div>
  );
}
