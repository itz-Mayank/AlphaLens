import { useNavigate } from "react-router-dom";

import { Card } from "@/components/Card";
import { DataTable, type DataTableColumn } from "@/components/DataTable";
import { EmptyState } from "@/components/EmptyState";
import { formatPrice, formatRelativeTime } from "@/lib/format";

import type { RecentActivityItem } from "../types";

export function RecentActivityList({ items }: { items: RecentActivityItem[] }) {
  const navigate = useNavigate();

  if (items.length === 0) {
    return <EmptyState title="No recently updated securities" />;
  }

  const columns: DataTableColumn<RecentActivityItem>[] = [
    { key: "ticker", header: "Ticker", render: (r) => <span className="font-medium">{r.ticker}</span> },
    { key: "name", header: "Name", render: (r) => <span className="text-muted">{r.name}</span> },
    { key: "price", header: "Price", align: "right", render: (r) => formatPrice(r.last_price) },
    {
      key: "updated",
      header: "Updated",
      align: "right",
      render: (r) => <span className="text-xs text-muted">{formatRelativeTime(r.as_of)}</span>,
    },
  ];

  return (
    <Card className="overflow-hidden p-0">
      <DataTable
        columns={columns}
        rows={items}
        rowKey={(r) => r.ticker}
        onRowClick={(r) => navigate(`/app/stocks/${r.ticker}`)}
      />
    </Card>
  );
}
