import type { ReactNode } from "react";

interface PageHeaderProps {
  title: string;
  description?: string;
  actions?: ReactNode;
  /** Rendered below the title/description row — status pills, freshness, etc. */
  meta?: ReactNode;
}

export function PageHeader({ title, description, actions, meta }: PageHeaderProps) {
  return (
    <div className="mb-6 flex flex-col gap-3 border-b border-border pb-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight text-foreground">{title}</h1>
          {description && <p className="mt-1 text-sm text-muted">{description}</p>}
        </div>
        {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
      </div>
      {meta && <div className="flex flex-wrap items-center gap-2">{meta}</div>}
    </div>
  );
}
