import { Link } from "react-router-dom";
import type { PropsWithChildren, ReactNode } from "react";

interface AuthLayoutProps {
  title: string;
  subtitle?: ReactNode;
}

export function AuthLayout({ title, subtitle, children }: PropsWithChildren<AuthLayoutProps>) {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center px-6 py-12">
      <Link to="/" className="mb-8 text-lg font-semibold tracking-tight">
        AlphaLens
      </Link>

      <div className="w-full max-w-sm rounded-lg border border-border bg-surface p-6 shadow-sm">
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-muted">{subtitle}</p>}
        <div className="mt-6">{children}</div>
      </div>

      <p className="mt-6 max-w-sm text-center text-xs text-muted">
        Analytical and educational information only. Not financial advice.
      </p>
    </main>
  );
}
