import type { ReactNode } from "react";
import clsx from "clsx";

export interface DataTableColumn<T> {
  key: string;
  header: string;
  align?: "left" | "right" | "center";
  className?: string;
  render: (row: T) => ReactNode;
  /** Present + non-undefined marks the column sortable; the table shows a
   * sort indicator and calls onSortChange with this key on click. */
  sortKey?: string;
}

interface DataTableProps<T> {
  columns: DataTableColumn<T>[];
  rows: T[];
  rowKey: (row: T) => string | number;
  onRowClick?: (row: T) => void;
  sortBy?: string;
  sortDirection?: "asc" | "desc";
  onSortChange?: (key: string) => void;
  isLoading?: boolean;
  skeletonRows?: number;
  /** Rendered in place of the body when rows is empty and not loading. */
  emptyContent?: ReactNode;
}

const ALIGN_CLASSES: Record<NonNullable<DataTableColumn<unknown>["align"]>, string> = {
  left: "text-left",
  right: "text-right",
  center: "text-center",
};

/** Shared dense data table used across Stock Explorer, Screener, Watchlists,
 * Portfolio holdings/transactions, and Alerts — replaces the hand-rolled
 * <table> markup that used to be duplicated per page. */
export function DataTable<T>({
  columns,
  rows,
  rowKey,
  onRowClick,
  sortBy,
  sortDirection,
  onSortChange,
  isLoading,
  skeletonRows = 6,
  emptyContent,
}: DataTableProps<T>) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr className="border-b border-border text-xs uppercase tracking-wide text-muted">
            {columns.map((col) => {
              const sortable = Boolean(col.sortKey && onSortChange);
              const isActive = sortable && sortBy === col.sortKey;
              return (
                <th
                  key={col.key}
                  className={clsx(
                    "whitespace-nowrap px-3 py-2 font-medium",
                    ALIGN_CLASSES[col.align ?? "left"],
                    sortable && "cursor-pointer select-none hover:text-foreground",
                    col.className,
                  )}
                  onClick={sortable ? () => onSortChange!(col.sortKey!) : undefined}
                  aria-sort={isActive ? (sortDirection === "asc" ? "ascending" : "descending") : undefined}
                >
                  <span className="inline-flex items-center gap-1">
                    {col.header}
                    {isActive && <span aria-hidden="true">{sortDirection === "asc" ? "▲" : "▼"}</span>}
                  </span>
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {isLoading
            ? Array.from({ length: skeletonRows }).map((_, i) => (
                <tr key={i} className="border-b border-border/60">
                  {columns.map((col) => (
                    <td key={col.key} className="px-3 py-2.5">
                      <div className="h-3.5 w-full max-w-[8rem] animate-pulse rounded bg-border/60" />
                    </td>
                  ))}
                </tr>
              ))
            : rows.map((row) => (
                <tr
                  key={rowKey(row)}
                  onClick={onRowClick ? () => onRowClick(row) : undefined}
                  className={clsx(
                    "border-b border-border/60 transition-colors",
                    onRowClick && "cursor-pointer hover:bg-border/30",
                  )}
                >
                  {columns.map((col) => (
                    <td
                      key={col.key}
                      className={clsx("px-3 py-2.5 tabular-nums", ALIGN_CLASSES[col.align ?? "left"], col.className)}
                    >
                      {col.render(row)}
                    </td>
                  ))}
                </tr>
              ))}
        </tbody>
      </table>
      {!isLoading && rows.length === 0 && emptyContent && <div className="py-10">{emptyContent}</div>}
    </div>
  );
}
