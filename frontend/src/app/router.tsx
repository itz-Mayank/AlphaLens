import { lazy } from "react";
import { createBrowserRouter } from "react-router-dom";

import { AppLayout } from "@/app/AppLayout";
import { ProtectedRoute } from "@/app/ProtectedRoute";

// Route-level code splitting: each page is its own chunk, fetched only
// when its route is actually visited, instead of one bundle containing
// every feature (screener, portfolio, backtesting, the research agent,
// etc.) up front — see docs/architecture.md's frontend production audit
// note for the bundle-size measurement this fixes.
const ChatPage = lazy(() => import("@/features/agent/ChatPage").then((m) => ({ default: m.ChatPage })));
const AlertsPage = lazy(() =>
  import("@/features/alerts/AlertsPage").then((m) => ({ default: m.AlertsPage })),
);
const ForgotPasswordPage = lazy(() =>
  import("@/features/auth/ForgotPasswordPage").then((m) => ({ default: m.ForgotPasswordPage })),
);
const LoginPage = lazy(() =>
  import("@/features/auth/LoginPage").then((m) => ({ default: m.LoginPage })),
);
const RegisterPage = lazy(() =>
  import("@/features/auth/RegisterPage").then((m) => ({ default: m.RegisterPage })),
);
const ResetPasswordPage = lazy(() =>
  import("@/features/auth/ResetPasswordPage").then((m) => ({ default: m.ResetPasswordPage })),
);
const BacktestPage = lazy(() =>
  import("@/features/backtesting/BacktestPage").then((m) => ({ default: m.BacktestPage })),
);
const DashboardPage = lazy(() =>
  import("@/features/dashboard/DashboardPage").then((m) => ({ default: m.DashboardPage })),
);
const SystemStatusPage = lazy(() =>
  import("@/features/dashboard/SystemStatusPage").then((m) => ({ default: m.SystemStatusPage })),
);
const PortfolioDetailPage = lazy(() =>
  import("@/features/portfolio/PortfolioDetailPage").then((m) => ({
    default: m.PortfolioDetailPage,
  })),
);
const PortfoliosPage = lazy(() =>
  import("@/features/portfolio/PortfoliosPage").then((m) => ({ default: m.PortfoliosPage })),
);
const ScreenerPage = lazy(() =>
  import("@/features/screener/ScreenerPage").then((m) => ({ default: m.ScreenerPage })),
);
const StockDetailPage = lazy(() =>
  import("@/features/stocks/StockDetailPage").then((m) => ({ default: m.StockDetailPage })),
);
const StockExplorerPage = lazy(() =>
  import("@/features/stocks/StockExplorerPage").then((m) => ({ default: m.StockExplorerPage })),
);
const WatchlistDetailPage = lazy(() =>
  import("@/features/watchlist/WatchlistDetailPage").then((m) => ({
    default: m.WatchlistDetailPage,
  })),
);
const WatchlistsPage = lazy(() =>
  import("@/features/watchlist/WatchlistsPage").then((m) => ({ default: m.WatchlistsPage })),
);

export const router = createBrowserRouter([
  {
    path: "/",
    element: <SystemStatusPage />,
  },
  { path: "/login", element: <LoginPage /> },
  { path: "/register", element: <RegisterPage /> },
  { path: "/forgot-password", element: <ForgotPasswordPage /> },
  { path: "/reset-password", element: <ResetPasswordPage /> },
  {
    path: "/app",
    element: <ProtectedRoute />,
    children: [
      {
        element: <AppLayout />,
        children: [
          { index: true, element: <DashboardPage /> },
          { path: "stocks", element: <StockExplorerPage /> },
          { path: "stocks/:ticker", element: <StockDetailPage /> },
          { path: "screener", element: <ScreenerPage /> },
          { path: "watchlists", element: <WatchlistsPage /> },
          { path: "watchlists/:watchlistId", element: <WatchlistDetailPage /> },
          { path: "portfolio", element: <PortfoliosPage /> },
          { path: "portfolio/:portfolioId", element: <PortfolioDetailPage /> },
          { path: "alerts", element: <AlertsPage /> },
          { path: "research/backtest", element: <BacktestPage /> },
          { path: "research/chat", element: <ChatPage /> },
        ],
      },
    ],
  },
  // The marketing landing page replaces SystemStatusPage, and further
  // feature routes (news, etc.) are added under AppLayout as each later
  // phase implements them.
]);
