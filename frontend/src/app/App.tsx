import { Suspense } from "react";
import { RouterProvider } from "react-router-dom";

import { AppProviders } from "@/app/providers";
import { router } from "@/app/router";

// Route-level code splitting (router.tsx lazy-loads every page) needs one
// Suspense boundary above the whole route tree — a route's own loading
// state (Skeleton, etc.) still renders once its chunk has loaded; this
// fallback only ever shows for the brief moment the chunk itself is being
// fetched, so it stays minimal rather than duplicating a full skeleton.
function RouteFallback() {
  return <div aria-hidden="true" />;
}

export function App() {
  return (
    <AppProviders>
      <Suspense fallback={<RouteFallback />}>
        <RouterProvider router={router} />
      </Suspense>
    </AppProviders>
  );
}
