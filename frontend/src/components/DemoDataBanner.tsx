/** Shown whenever displayed data carries `data_source: "demo"` — see
 * docs/decisions.md ADR-007. Never hide this behind a tooltip: it must be
 * structurally impossible to mistake demo prices for real market data. */
export function DemoDataBanner() {
  return (
    <div className="rounded border border-warning/30 bg-warning/10 px-3 py-2 text-xs text-warning">
      Demo data — simulated prices for a fixed set of real tickers, not real market data.
    </div>
  );
}
