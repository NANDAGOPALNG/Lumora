"use client";

import { useQuery, type QueryKey } from "@tanstack/react-query";
import { useAuth } from "@/hooks/use-auth";
import * as dashboardApi from "@/lib/api/dashboard";

/** Root of every dashboard query; invalidated after any successful mutation (see query-provider). */
export const DASHBOARD_KEY_ROOT = "dashboard";

/** Keyed by user id (never a token) so one user's summary can't be shown to another. */
export const dashboardKey = (userId: string | null): QueryKey => [
  DASHBOARD_KEY_ROOT,
  userId ?? "anonymous",
  "summary",
];

/** The signed-in user's dashboard statistics and recent activity. */
export function useDashboardSummary() {
  const { user, status } = useAuth();
  return useQuery({
    queryKey: dashboardKey(user?.id ?? null),
    queryFn: ({ signal }) => dashboardApi.getDashboardSummary(signal),
    enabled: status === "authenticated" && user !== null,
    // No polling: data refreshes on mount once stale, after mutations, and on manual retry.
    staleTime: 30_000,
  });
}
