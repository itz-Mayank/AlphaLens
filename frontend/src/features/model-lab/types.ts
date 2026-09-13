export interface ProviderStatus {
  category: string;
  configured_provider: string;
  credential_required: boolean;
  credential_configured: boolean;
  last_success_at: string | null;
  last_failure_at: string | null;
  last_failure_reason: string | null;
  last_latency_seconds: number | null;
}

export interface ProviderStatusListResponse {
  providers: ProviderStatus[];
}
