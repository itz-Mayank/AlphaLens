import { Badge } from "@/components/Badge";

/** Renders a forecast/technical direction class (the model's actual output —
 * "Bullish" | "Neutral" | "Bearish" — never an invented "score"). `null`
 * renders as an explicit "No signal" rather than defaulting to Neutral,
 * since missing data must never be visually indistinguishable from a real
 * neutral prediction. */
export function SignalBadge({ direction }: { direction: string | null | undefined }) {
  if (!direction) return <Badge tone="neutral">No signal</Badge>;
  const tone = direction === "Bullish" ? "bullish" : direction === "Bearish" ? "bearish" : "neutral";
  return <Badge tone={tone}>{direction}</Badge>;
}
