import type { HTMLAttributes } from "react";
import clsx from "clsx";

type BadgeTone = "neutral" | "bullish" | "bearish" | "warning" | "info";

const TONE_CLASSES: Record<BadgeTone, string> = {
  neutral: "bg-border/60 text-muted",
  bullish: "bg-bullish/15 text-bullish",
  bearish: "bg-bearish/15 text-bearish",
  warning: "bg-warning/15 text-warning",
  info: "bg-primary/15 text-primary",
};

interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: BadgeTone;
}

export function Badge({ tone = "neutral", className, ...props }: BadgeProps) {
  return (
    <span
      className={clsx(
        "inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium",
        TONE_CLASSES[tone],
        className,
      )}
      {...props}
    />
  );
}
