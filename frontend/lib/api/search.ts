import type { SearchRequest, SearchResponse } from "@/types/api";
import { apiFetch } from "@/lib/api/client";

/**
 * Search indexed passages in a workspace (optionally one document). The backend runs hybrid
 * retrieval plus reranking; pass an AbortSignal so an abandoned search can be cancelled.
 */
export function searchKnowledge(request: SearchRequest, signal?: AbortSignal): Promise<SearchResponse> {
  return apiFetch<SearchResponse>("/api/v1/search", { method: "POST", body: request, signal });
}
