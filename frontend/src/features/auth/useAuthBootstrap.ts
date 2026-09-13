import { useEffect } from "react";

import { refreshSession } from "@/features/auth/api";
import { useAuthStore } from "@/stores/authStore";

/**
 * Runs once on app load: tries to restore a session from the httpOnly
 * refresh cookie (no access token is ever persisted client-side — see
 * authStore). Resolves the store's status to "authenticated" or
 * "unauthenticated" either way, so ProtectedRoute knows when it's safe to
 * make a redirect decision.
 */
export function useAuthBootstrap(): void {
  const setStatus = useAuthStore((s) => s.setStatus);
  const setSession = useAuthStore((s) => s.setSession);
  const clear = useAuthStore((s) => s.clear);

  useEffect(() => {
    let cancelled = false;
    setStatus("loading");

    refreshSession()
      .then((body) => {
        if (!cancelled) setSession(body.user, body.access_token);
      })
      .catch(() => {
        if (!cancelled) clear();
      });

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
}
