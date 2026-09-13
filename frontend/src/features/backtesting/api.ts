import { apiClient } from "@/lib/api-client";

import type { BacktestRequest, BacktestResponse } from "./types";

export function runBacktest(request: BacktestRequest) {
  return apiClient.post<BacktestResponse>("/research/backtest", request);
}
