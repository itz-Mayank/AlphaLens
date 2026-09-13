import { useState } from "react";

export interface EvidenceLike {
  source_type: string;
  source_id: string;
  ticker: string | null;
  timestamp: string;
  data: Record<string, unknown>;
  provenance: string;
}

function sourceTypeLabel(sourceType: string): string {
  return sourceType
    .toLowerCase()
    .split("_")
    .map((word) => (word === "shap" ? "SHAP" : word[0].toUpperCase() + word.slice(1)))
    .join(" ");
}

function formatDataValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(4);
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

/** An expandable card for one agent-response Evidence item — the tool-call
 * output the assistant's answer was actually grounded in. Expanding it shows
 * the raw `data` fields the backend returned, so a claim in the answer can
 * be traced back to the exact number/record that produced it. */
export function EvidenceCard({ evidence }: { evidence: EvidenceLike }) {
  const [open, setOpen] = useState(false);
  const dataEntries = Object.entries(evidence.data ?? {});

  return (
    <div className="rounded border border-border bg-background/40 text-xs">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between gap-2 px-2 py-1.5 text-left hover:bg-border/20"
        aria-expanded={open}
      >
        <span className="flex flex-wrap items-center gap-1 text-muted">
          <span className="font-medium text-foreground">{sourceTypeLabel(evidence.source_type)}</span>
          {evidence.ticker && <span>· {evidence.ticker}</span>}
          <span>· {evidence.provenance}</span>
          <span>· {new Date(evidence.timestamp).toLocaleString()}</span>
        </span>
        <span aria-hidden="true" className="text-muted">
          {open ? "▲" : "▼"}
        </span>
      </button>
      {open && dataEntries.length > 0 && (
        <dl className="grid grid-cols-2 gap-x-3 gap-y-1 border-t border-border px-2 py-2 sm:grid-cols-3">
          {dataEntries.map(([key, value]) => (
            <div key={key} className="min-w-0">
              <dt className="truncate text-muted">{key}</dt>
              <dd className="truncate font-medium text-foreground">{formatDataValue(value)}</dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  );
}
