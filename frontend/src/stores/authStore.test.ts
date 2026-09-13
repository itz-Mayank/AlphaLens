import { beforeEach, describe, expect, it } from "vitest";

import { useAuthStore } from "@/stores/authStore";

const sampleUser = {
  id: "11111111-1111-1111-1111-111111111111",
  email: "jane@example.com",
  full_name: "Jane Doe",
  role: "USER" as const,
  is_active: true,
  is_email_verified: false,
  created_at: "2026-01-01T00:00:00Z",
};

describe("useAuthStore", () => {
  beforeEach(() => {
    useAuthStore.setState({ user: null, accessToken: null, status: "idle" });
  });

  it("starts in the idle state with no session", () => {
    const state = useAuthStore.getState();
    expect(state.status).toBe("idle");
    expect(state.user).toBeNull();
    expect(state.accessToken).toBeNull();
  });

  it("setSession stores the user/token and marks authenticated", () => {
    useAuthStore.getState().setSession(sampleUser, "token-123");

    const state = useAuthStore.getState();
    expect(state.status).toBe("authenticated");
    expect(state.user).toEqual(sampleUser);
    expect(state.accessToken).toBe("token-123");
  });

  it("clear wipes the session and marks unauthenticated", () => {
    useAuthStore.getState().setSession(sampleUser, "token-123");

    useAuthStore.getState().clear();

    const state = useAuthStore.getState();
    expect(state.status).toBe("unauthenticated");
    expect(state.user).toBeNull();
    expect(state.accessToken).toBeNull();
  });

  it("setStatus updates only the status field", () => {
    useAuthStore.getState().setSession(sampleUser, "token-123");

    useAuthStore.getState().setStatus("loading");

    const state = useAuthStore.getState();
    expect(state.status).toBe("loading");
    expect(state.user).toEqual(sampleUser);
  });
});
