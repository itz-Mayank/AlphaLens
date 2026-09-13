import { type IChartApi, ColorType, createChart } from "lightweight-charts";
import { useEffect, useRef } from "react";

import { useUiStore } from "@/stores/uiStore";

import type { EquityCurvePoint } from "../types";

interface EquityCurveChartProps {
  points: EquityCurvePoint[];
}

export function EquityCurveChart({ points }: EquityCurveChartProps) {
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
      height: 320,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: isDark ? "#94a3ad" : "#6b7280",
        attributionLogo: false,
      },
      grid: {
        vertLines: { color: gridColor },
        horzLines: { color: gridColor },
      },
      timeScale: { borderColor: gridColor },
      rightPriceScale: { borderColor: gridColor },
    });
    chartRef.current = chart;

    const strategySeries = chart.addLineSeries({ color: "#3b82f6", lineWidth: 2 });
    strategySeries.setData(
      points.map((point) => ({ time: point.ts.slice(0, 10), value: point.equity })),
    );

    const benchmarkSeries = chart.addLineSeries({
      color: "#94a3ad",
      lineWidth: 1,
      lineStyle: 2,
    });
    benchmarkSeries.setData(
      points.map((point) => ({ time: point.ts.slice(0, 10), value: point.benchmark_equity })),
    );

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
      <div className="mb-2 flex gap-4 text-xs text-muted">
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-0.5 w-3 bg-[#3b82f6]" /> Strategy
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-0.5 w-3 bg-[#94a3ad]" /> Benchmark (equal-weight buy-and-hold)
        </span>
      </div>
      <div ref={containerRef} data-testid="equity-curve-chart-container" />
    </div>
  );
}
