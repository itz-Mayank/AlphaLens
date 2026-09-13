import { apiClient } from "@/lib/api-client";

import type { ProviderStatusListResponse } from "./types";

export function getProviderStatus() {
  return apiClient.get<ProviderStatusListResponse>("/system/providers");
}
