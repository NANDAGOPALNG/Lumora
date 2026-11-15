"use client";

import { useEffect, useState } from "react";
import { MutationCache, QueryClient, QueryClientProvider, useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/hooks/use-auth";
import { ApiError, NETWORK_ERROR } from "@/lib/api/client";
import { DASHBOARD_KEY_ROOT } from "@/hooks/use-dashboard";

/** Retry once for transient failures only; never for 4xx (401, 404, 422). */
function shouldRetry(failureCount: number, error: Error): boolean {
  if (failureCount >= 1) return false;
  return error instanceof ApiError && (error.code === NETWORK_ERROR || error.status >= 500);
}

/** Drop all cached server data when the session ends so it can't leak to the next user. */
function ClearCacheOnSignOut() {
  const { status } = useAuth();
  const client = useQueryClient();

  useEffect(() => {
    if (status === "unauthenticated") client.clear();
  }, [status, client]);

  return null;
}

export function createAppQueryClient(): QueryClient {
  const client: QueryClient = new QueryClient({
    // Any successful change (upload, delete, workspace, sync, chat...) can alter the dashboard
    // counts or activity, so mark them stale; they refetch when the dashboard is next shown.
    mutationCache: new MutationCache({
      onSuccess: () => void client.invalidateQueries({ queryKey: [DASHBOARD_KEY_ROOT] }),
    }),
    defaultOptions: {
      queries: { staleTime: 30_000, retry: shouldRetry, retryDelay: 800 },
    },
  });
  return client;
}

export function QueryProvider({ children }: { children: React.ReactNode }) {
  const [client] = useState(createAppQueryClient);

  return (
    <QueryClientProvider client={client}>
      <ClearCacheOnSignOut />
      {children}
    </QueryClientProvider>
  );
}
