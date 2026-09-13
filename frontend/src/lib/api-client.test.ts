import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import { useAuthStore } from "@/stores/authStore";

const sampleUser = {
  id: "1",
  email: "jane@example.com",
  full_name: "Jane Doe",
  role: "USER" as const,
  is_active: true,
  is_email_verified: false,
  created_at: "2026-01-01T00:00:00Z",
};

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

describe("apiClient", () => {
  beforeEach(() => {
    useAuthStore.setState({ user: null, accessToken: null, status: "idle" });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("attaches the Authorization header when an access token is present", async () => {
    useAuthStore.getState().setSession(sampleUser, "the-token");
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { ok: true }));
    vi.stubGlobal("fetch", fetchMock);

    await apiClient.get("/some/path");

    const [, init] = fetchMock.mock.calls[0];
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer the-token");
  });

  it("throws an ApiError with the server's code/message on failure", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse(409, { error: { code: "EMAIL_TAKEN", message: "Already registered." } }),
      ),
    );

    await expect(apiClient.post("/auth/register", {})).rejects.toMatchObject({
      status: 409,
      code: "EMAIL_TAKEN",
      message: "Already registered.",
    });
  });

  it("retries once with a refreshed token after a 401, and updates the store", async () => {
    useAuthStore.getState().setSession(sampleUser, "stale-token");

    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (url.includes("/auth/refresh")) {
        return Promise.resolve(
          jsonResponse(200, { access_token: "fresh-token", user: sampleUser }),
        );
      }
      const authHeader = fetchMock.mock.calls.length; // first call vs retry
      if (authHeader === 1) {
        return Promise.resolve(jsonResponse(401, { error: { code: "INVALID_TOKEN" } }));
      }
      return Promise.resolve(jsonResponse(200, { data: "secret" }));
    });
    vi.stubGlobal("fetch", fetchMock);

    const result = await apiClient.get<{ data: string }>("/watchlists");

    expect(result).toEqual({ data: "secret" });
    expect(useAuthStore.getState().accessToken).toBe("fresh-token");
    // original call, refresh call, retried call
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("clears the session and surfaces the 401 when refresh also fails", async () => {
    useAuthStore.getState().setSession(sampleUser, "stale-token");

    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((url: string) => {
        if (url.includes("/auth/refresh")) {
          return Promise.resolve(jsonResponse(401, { error: { code: "NO_REFRESH_TOKEN" } }));
        }
        return Promise.resolve(jsonResponse(401, { error: { code: "INVALID_TOKEN" } }));
      }),
    );

    await expect(apiClient.get("/watchlists")).rejects.toMatchObject({ status: 401 });
    expect(useAuthStore.getState().status).toBe("unauthenticated");
    expect(useAuthStore.getState().accessToken).toBeNull();
  });

  it("does not attempt a refresh loop when /auth/login itself returns 401", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse(401, { error: { code: "INVALID_CREDENTIALS" } }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(apiClient.post("/auth/login", {})).rejects.toMatchObject({
      code: "INVALID_CREDENTIALS",
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("returns undefined for a 204 No Content response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(204, null)));

    await expect(apiClient.post("/auth/logout")).resolves.toBeUndefined();
  });
});
