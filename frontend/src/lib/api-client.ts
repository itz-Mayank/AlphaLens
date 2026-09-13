import { useAuthStore } from "@/stores/authStore";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";
const ROOT_URL = API_BASE_URL.replace(/\/api\/v1\/?$/, "");

// Endpoints that must never trigger the 401 -> refresh -> retry dance
// below (refresh itself, and the unauthenticated auth endpoints).
const NO_REFRESH_RETRY_PATHS = new Set([
  "/auth/login",
  "/auth/register",
  "/auth/refresh",
  "/auth/forgot-password",
  "/auth/reset-password",
]);

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

let refreshPromise: Promise<string | null> | null = null;

async function refreshAccessToken(): Promise<string | null> {
  if (refreshPromise) return refreshPromise;

  refreshPromise = (async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/auth/refresh`, {
        method: "POST",
        credentials: "include",
      });
      if (!res.ok) {
        useAuthStore.getState().clear();
        return null;
      }
      const body = await res.json();
      useAuthStore.getState().setSession(body.user, body.access_token);
      return body.access_token as string;
    } catch {
      useAuthStore.getState().clear();
      return null;
    } finally {
      refreshPromise = null;
    }
  })();

  return refreshPromise;
}

async function request<T>(path: string, init?: RequestInit, isRetry = false): Promise<T> {
  const accessToken = useAuthStore.getState().accessToken;

  const res = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
      ...init?.headers,
    },
    credentials: "include",
  });

  if (res.status === 401 && !isRetry && !NO_REFRESH_RETRY_PATHS.has(path)) {
    const newToken = await refreshAccessToken();
    if (newToken) {
      return request<T>(path, init, true);
    }
  }

  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new ApiError(
      res.status,
      body?.error?.code ?? "UNKNOWN_ERROR",
      body?.error?.message ?? res.statusText,
    );
  }

  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const apiClient = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, data?: unknown) =>
    request<T>(path, { method: "POST", body: data ? JSON.stringify(data) : undefined }),
  patch: <T>(path: string, data?: unknown) =>
    request<T>(path, { method: "PATCH", body: data ? JSON.stringify(data) : undefined }),
  delete: <T>(path: string, data?: unknown) =>
    request<T>(path, { method: "DELETE", body: data ? JSON.stringify(data) : undefined }),
};

export async function fetchHealth(): Promise<{ status: string }> {
  const res = await fetch(`${ROOT_URL}/health`);
  if (!res.ok) throw new Error(`health check failed: ${res.status}`);
  return res.json();
}
