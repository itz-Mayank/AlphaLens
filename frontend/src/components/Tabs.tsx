import clsx from "clsx";

export interface TabItem {
  key: string;
  label: string;
  /** Optional small badge/count rendered after the label. */
  badge?: React.ReactNode;
}

interface TabsProps {
  items: TabItem[];
  active: string;
  onChange: (key: string) => void;
}

export function Tabs({ items, active, onChange }: TabsProps) {
  return (
    <div role="tablist" className="flex gap-1 border-b border-border">
      {items.map((item) => {
        const isActive = item.key === active;
        return (
          <button
            key={item.key}
            type="button"
            role="tab"
            aria-selected={isActive}
            onClick={() => onChange(item.key)}
            className={clsx(
              "flex items-center gap-1.5 border-b-2 px-3 py-2 text-sm font-medium transition-colors",
              isActive
                ? "border-primary text-foreground"
                : "border-transparent text-muted hover:text-foreground",
            )}
          >
            {item.label}
            {item.badge}
          </button>
        );
      })}
    </div>
  );
}
