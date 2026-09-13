import { apiClient } from "@/lib/api-client";

import type { DashboardOverview } from "./types";

export function getDashboardOverview() {
  return apiClient.get<DashboardOverview>("/dashboard/overview");
}
