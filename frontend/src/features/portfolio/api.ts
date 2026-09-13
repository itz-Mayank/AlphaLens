import { apiClient } from "@/lib/api-client";

import type {
  CreateTransactionInput,
  Holding,
  Page,
  PerformanceHistory,
  Portfolio,
  PortfolioAnalytics,
  Transaction,
} from "./types";

export function listPortfolios() {
  return apiClient.get<Portfolio[]>("/portfolios");
}

export function getPortfolio(portfolioId: string) {
  return apiClient.get<Portfolio>(`/portfolios/${portfolioId}`);
}

export function createPortfolio(data: { name: string; description?: string }) {
  return apiClient.post<Portfolio>("/portfolios", data);
}

export function deletePortfolio(portfolioId: string) {
  return apiClient.delete<void>(`/portfolios/${portfolioId}`);
}

export function listTransactions(portfolioId: string, limit = 25, offset = 0) {
  return apiClient.get<Page<Transaction>>(
    `/portfolios/${portfolioId}/transactions?limit=${limit}&offset=${offset}`,
  );
}

export function createTransaction(portfolioId: string, data: CreateTransactionInput) {
  return apiClient.post<Transaction>(`/portfolios/${portfolioId}/transactions`, data);
}

export function getHoldings(portfolioId: string) {
  return apiClient.get<Holding[]>(`/portfolios/${portfolioId}/holdings`);
}

export function getAnalytics(portfolioId: string) {
  return apiClient.get<PortfolioAnalytics>(`/portfolios/${portfolioId}/analytics`);
}

export function getPerformance(portfolioId: string) {
  return apiClient.get<PerformanceHistory>(`/portfolios/${portfolioId}/performance`);
}
