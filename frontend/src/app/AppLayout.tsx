import { useMutation } from "@tanstack/react-query";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import clsx from "clsx";

import { logout } from "@/features/auth/api";
import { AlertsIndicator } from "@/features/alerts/components/AlertsIndicator";
import { GlobalSearch } from "@/components/GlobalSearch";
import { useAuthStore } from "@/stores/authStore";
import { useUiStore } from "@/stores/uiStore";

const NAV_ITEMS = [
  { to: "/app", label: "Dashboard", end: true },
  { to: "/app/stocks", label: "Stocks", end: false },
  { to: "/app/screener", label: "Screener", end: false },
  { to: "/app/watchlists", label: "Watchlists", end: false },
  { to: "/app/portfolio", label: "Portfolio", end: false },
  { to: "/app/alerts", label: "Alerts", end: false },
  { to: "/app/research/backtest", label: "Backtest", end: false },
  { to: "/app/research/chat", label: "Assistant", end: false },
];

export function AppLayout() {
  const navigate = useNavigate();
  const user = useAuthStore((s) => s.user);
  const clear = useAuthStore((s) => s.clear);
  const theme = useUiStore((s) => s.theme);
  const toggleTheme = useUiStore((s) => s.toggleTheme);

  const logoutMutation = useMutation({
    mutationFn: logout,
    onSettled: () => {
      clear();
      navigate("/login", { replace: true });
    },
  });

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-20 border-b border-border bg-background/95 backdrop-blur">
        <div className="flex items-center gap-4 px-4 py-2.5">
          <span className="shrink-0 text-sm font-semibold tracking-tight text-foreground">
            Alpha<span className="text-primary">Lens</span>
          </span>
          <nav className="flex shrink-0 gap-0.5">
            {NAV_ITEMS.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  clsx(
                    "flex items-center gap-1.5 rounded px-2.5 py-1.5 text-sm font-medium transition-colors",
                    isActive ? "bg-border/50 text-foreground" : "text-muted hover:text-foreground",
                  )
                }
              >
                {item.label}
                {item.label === "Alerts" && <AlertsIndicator />}
              </NavLink>
            ))}
          </nav>
          <div className="flex-1" />
          <GlobalSearch />
          <div className="flex shrink-0 items-center gap-2 text-sm">
            <button
              type="button"
              onClick={toggleTheme}
              aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
              className="rounded border border-border px-2 py-1 text-muted hover:text-foreground"
            >
              {theme === "dark" ? "☀" : "☾"}
            </button>
            <span className="hidden max-w-[10rem] truncate text-muted lg:inline">{user?.email}</span>
            <button
              type="button"
              onClick={() => logoutMutation.mutate()}
              disabled={logoutMutation.isPending}
              className="rounded border border-border px-2.5 py-1 text-muted hover:text-foreground disabled:opacity-60"
            >
              {logoutMutation.isPending ? "Logging out…" : "Log out"}
            </button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-[1600px] px-4 py-6 sm:px-6">
        <Outlet />
      </main>
    </div>
  );
}
