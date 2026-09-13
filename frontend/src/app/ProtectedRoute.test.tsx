import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";

import { ProtectedRoute } from "@/app/ProtectedRoute";
import { useAuthStore } from "@/stores/authStore";

function renderAtApp() {
  render(
    <MemoryRouter initialEntries={["/app"]}>
      <Routes>
        <Route path="/login" element={<div>Login screen</div>} />
        <Route element={<ProtectedRoute />}>
          <Route path="/app" element={<div>Protected dashboard</div>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

describe("ProtectedRoute", () => {
  beforeEach(() => {
    useAuthStore.setState({ user: null, accessToken: null, status: "idle" });
  });

  it("shows a loading state while auth status is still resolving", () => {
    renderAtApp();
    expect(screen.getByText(/loading/i)).toBeInTheDocument();
  });

  it("redirects to /login when unauthenticated", () => {
    useAuthStore.setState({ status: "unauthenticated" });
    renderAtApp();
    expect(screen.getByText("Login screen")).toBeInTheDocument();
  });

  it("renders the protected content when authenticated", () => {
    useAuthStore.setState({ status: "authenticated" });
    renderAtApp();
    expect(screen.getByText("Protected dashboard")).toBeInTheDocument();
  });
});
