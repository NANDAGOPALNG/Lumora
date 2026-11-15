import type { DashboardSummaryResponse } from "@/types/api";
import { apiFetch } from "@/lib/api/client";

export function getDashboardSummary(signal?: AbortSignal): Promise<DashboardSummaryResponse> {
  return apiFetch<DashboardSummaryResponse>("/api/v1/dashboard/summary", { signal });
}
