import type { ReactNode } from "react";

interface TooltipProps {
  content: ReactNode;
  children: ReactNode;
}

/** Lightweight hover/focus tooltip — no dependency, pure CSS group-hover +
 * focus-within so it's reachable by keyboard, not just mouse hover. */
export function Tooltip({ content, children }: TooltipProps) {
  return (
    <span className="group/tooltip relative inline-flex items-center focus-within:z-10">
      <span tabIndex={0} className="cursor-help border-b border-dotted border-muted outline-none">
        {children}
      </span>
      <span
        role="tooltip"
        className="pointer-events-none absolute bottom-full left-1/2 z-20 mb-1.5 w-max max-w-xs -translate-x-1/2 rounded border border-border bg-surface px-2 py-1 text-xs text-foreground opacity-0 shadow-lg transition-opacity group-hover/tooltip:opacity-100 group-focus-within/tooltip:opacity-100"
      >
        {content}
      </span>
    </span>
  );
}
