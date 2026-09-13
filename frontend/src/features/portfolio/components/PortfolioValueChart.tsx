import { type IChartApi, ColorType, createChart } from "lightweight-charts";
import { useEffect, useRef } from "react";

import { useUiStore } from "@/stores/uiStore";

import type { PerformancePoint } from "../types";

interface PortfolioValueChartProps {
  points: PerformancePoint[];
}

/** Plots real total_value against net_contributed (cost basis) over time —
 * the same computation as the analytics card's "Total return", just as a
 * series. Points where total_value is null (a holding's price was
 * unavailable that day) are skipped rather than shown as zero, so a gap in
 * data never reads as a market crash. */
export function PortfolioValueChart({ points }: PortfolioValueChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const theme = useUiStore((s) => s.theme);

  const plottedCount = points.filter((p) => p.total_value !== null).length;
  const skippedCount = points.length - plottedCount;

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const isDark = theme === "dark";
    const gridColor = isDark ? "#202530" : "#e2e5eb";
    const chart = createChart(container, {
      width: container.clientWidth,
      height: 280,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: isDark ? "#94a3ad" : "#6b7280",
        attributionLogo: false,
      },
      grid: { vertLines: { color: gridColor }, horzLines: { color: gridColor } },
      timeScale: { borderColor: gridColor },
      rightPriceScale: { borderColor: gridColor },
    });
    chartRef.current = chart;

    const valueSeries = chart.addLineSeries({ color: "#3b82f6", lineWidth: 2 });
    valueSeries.setData(
      points
        .filter((p) => p.total_value !== null)
        .map((p) => ({ time: p.as_of.slice(0, 10), value: Number(p.total_value) })),
    );

    const contributedSeries = chart.addLineSeries({ color: "#94a3ad", lineWidth: 1, lineStyle: 2 });
    contributedSeries.setData(points.map((p) => ({ time: p.as_of.slice(0, 10), value: Number(p.net_contributed) })));

    chart.timeScale().fitContent();

    const handleResize = () => chart.applyOptions({ width: container.clientWidth });
    window.addEventListener("resize", handleResize);

    return () => {
      window.removeEventListener("resize", handleResize);
      chart.remove();
      chartRef.current = null;
    };
  }, [points, theme]);

  return (
    <div>
      <div className="mb-2 flex flex-wrap gap-4 text-xs text-muted">
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-0.5 w-3 bg-[#3b82f6]" /> Total value
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-0.5 w-3 bg-[#94a3ad]" /> Net contributed (cost basis)
        </span>
      </div>
      <div ref={containerRef} data-testid="portfolio-value-chart-container" />
      {skippedCount > 0 && (
        <p className="mt-2 text-xs text-muted">
          {skippedCount} of {points.length} days omitted from the value line — a holding's price was
          unavailable on those dates.
        </p>
      )}
    </div>
  );
}
