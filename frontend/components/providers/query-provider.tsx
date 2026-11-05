"use client";

import { useEffect, useState } from "react";
import { QueryClient, QueryClientProvider, useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/hooks/use-auth";
import { ApiError, NETWORK_ERROR } from "@/lib/api/client";

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
  return new QueryClient({
    defaultOptions: {
      queries: { staleTime: 30_000, retry: shouldRetry, retryDelay: 800 },
    },
  });
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
