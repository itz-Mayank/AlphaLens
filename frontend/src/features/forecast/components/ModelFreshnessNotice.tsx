import { StatusBadge } from "@/components/StatusBadge";

const STALE_THRESHOLD_DAYS = 365;

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

/** Distinct from the demo-vs-real data_source disclosure: even a forecast
 * computed from real, current market data comes from a model trained on a
 * FIXED historical snapshot (see backend ForecastResponse.disclaimer) —
 * this makes that gap visible rather than letting "real data" imply
 * "recently validated model." All three dates come straight from the
 * model registry (app/services/forecast_service.py), never computed or
 * guessed here. */
export function ModelFreshnessNotice({
  trainingStart,
  trainingEnd,
  evaluationEnd,
}: {
  trainingStart: string;
  trainingEnd: string;
  evaluationEnd: string | null;
}) {
  const daysSinceTraining = Math.floor(
    (Date.now() - new Date(trainingEnd).getTime()) / (1000 * 60 * 60 * 24),
  );
  const isStale = daysSinceTraining > STALE_THRESHOLD_DAYS;
  const years = (daysSinceTraining / 365).toFixed(1);

  return (
    <div className="rounded border border-border bg-background/40 px-2.5 py-2 text-xs">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-muted">
          Trained on data {formatDate(trainingStart)} – {formatDate(trainingEnd)}
          {evaluationEnd && evaluationEnd !== trainingEnd && ` · evaluated through ${formatDate(evaluationEnd)}`}
        </span>
        {isStale && <StatusBadge status="stale" label={`${years}y old`} />}
      </div>
      {isStale && (
        <p className="mt-1 text-muted">
          This model was not retrained after {formatDate(trainingEnd)} — it has not been validated
          against current market conditions, even when the price data feeding it is real and
          current.
        </p>
      )}
    </div>
  );
}
