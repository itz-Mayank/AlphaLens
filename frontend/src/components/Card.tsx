import type { HTMLAttributes } from "react";
import clsx from "clsx";

export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={clsx("rounded-lg border border-border bg-surface", className)} {...props} />
  );
}
