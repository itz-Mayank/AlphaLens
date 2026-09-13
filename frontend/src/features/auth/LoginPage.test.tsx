import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api-client";
import { useAuthStore } from "@/stores/authStore";

import * as authApi from "@/features/auth/api";
import { LoginPage } from "@/features/auth/LoginPage";

vi.mock("@/features/auth/api");

const sampleUser = {
  id: "1",
  email: "jane@example.com",
  full_name: "Jane Doe",
  role: "USER" as const,
  is_active: true,
  is_email_verified: false,
  created_at: "2026-01-01T00:00:00Z",
};

function renderLoginPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/login"]}>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/app" element={<div>Dashboard placeholder</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("LoginPage", () => {
  beforeEach(() => {
    useAuthStore.setState({ user: null, accessToken: null, status: "idle" });
    vi.mocked(authApi.login).mockReset();
  });

  it("shows validation errors for an empty submission", async () => {
    const user = userEvent.setup();
    renderLoginPage();

    await user.click(screen.getByRole("button", { name: /log in/i }));

    expect(await screen.findByText(/enter a valid email/i)).toBeInTheDocument();
    expect(authApi.login).not.toHaveBeenCalled();
  });

  it("logs in, stores the session, and navigates to /app on success", async () => {
    vi.mocked(authApi.login).mockResolvedValue({
      access_token: "token-123",
      token_type: "bearer",
      expires_in: 900,
      user: sampleUser,
    });
    const user = userEvent.setup();
    renderLoginPage();

    await user.type(screen.getByLabelText(/email/i), "jane@example.com");
    await user.type(screen.getByLabelText(/^password$/i), "correct-horse-9");
    await user.click(screen.getByRole("button", { name: /log in/i }));

    expect(await screen.findByText("Dashboard placeholder")).toBeInTheDocument();
    expect(useAuthStore.getState().accessToken).toBe("token-123");
    expect(useAuthStore.getState().user).toEqual(sampleUser);
  });

  it("shows the server error message when login fails", async () => {
    vi.mocked(authApi.login).mockRejectedValue(
      new ApiError(401, "INVALID_CREDENTIALS", "Incorrect email or password."),
    );
    const user = userEvent.setup();
    renderLoginPage();

    await user.type(screen.getByLabelText(/email/i), "jane@example.com");
    await user.type(screen.getByLabelText(/^password$/i), "wrong-password-1");
    await user.click(screen.getByRole("button", { name: /log in/i }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("Incorrect email or password.");
    });
  });
});
