import { type IChartApi, ColorType, createChart } from "lightweight-charts";
import { useEffect, useRef } from "react";

import { useUiStore } from "@/stores/uiStore";

import type { EquityCurvePoint } from "../types";

/** Drawdown-from-peak, computed client-side from the same equity_curve the
 * backend already returned — a standard, deterministic transformation
 * (running-peak vs current equity), not a fabricated series. Its trough
 * should match the response's own scalar `metrics.max_drawdown`. */
function toDrawdownSeries(points: EquityCurvePoint[]) {
  let peak = -Infinity;
  return points.map((p) => {
    peak = Math.max(peak, p.equity);
    const drawdown = peak > 0 ? (p.equity - peak) / peak : 0;
    return { time: p.ts.slice(0, 10), value: drawdown * 100 };
  });
}

export function DrawdownChart({ points }: { points: EquityCurvePoint[] }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const theme = useUiStore((s) => s.theme);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const isDark = theme === "dark";
    const gridColor = isDark ? "#202530" : "#e2e5eb";
    const chart = createChart(container, {
      width: container.clientWidth,
      height: 200,
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

    const series = chart.addAreaSeries({
      lineColor: "#f43f5e",
      topColor: "rgba(244, 63, 94, 0.25)",
      bottomColor: "rgba(244, 63, 94, 0.02)",
      lineWidth: 2,
    });
    series.setData(toDrawdownSeries(points));

    chart.timeScale().fitContent();

    const handleResize = () => chart.applyOptions({ width: container.clientWidth });
    window.addEventListener("resize", handleResize);

    return () => {
      window.removeEventListener("resize", handleResize);
      chart.remove();
      chartRef.current = null;
    };
  }, [points, theme]);

  return <div ref={containerRef} data-testid="drawdown-chart-container" />;
}
