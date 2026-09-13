import { type IChartApi, ColorType, createChart } from "lightweight-charts";
import { useEffect, useRef } from "react";

import { useUiStore } from "@/stores/uiStore";

import type { PriceBar } from "../types";

interface PriceChartProps {
  bars: PriceBar[];
}

export function PriceChart({ bars }: PriceChartProps) {
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
      height: 360,
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

    const series = chart.addCandlestickSeries({
      upColor: "#22c55e",
      downColor: "#f84e4e",
      borderVisible: false,
      wickUpColor: "#22c55e",
      wickDownColor: "#f84e4e",
    });

    series.setData(
      bars.map((bar) => ({
        time: bar.ts.slice(0, 10),
        open: Number(bar.open),
        high: Number(bar.high),
        low: Number(bar.low),
        close: Number(bar.close),
      })),
    );
    chart.timeScale().fitContent();

    const handleResize = () => chart.applyOptions({ width: container.clientWidth });
    window.addEventListener("resize", handleResize);

    return () => {
      window.removeEventListener("resize", handleResize);
      chart.remove();
      chartRef.current = null;
    };
  }, [bars, theme]);

  return <div ref={containerRef} data-testid="price-chart-container" />;
}
