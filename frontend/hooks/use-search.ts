"use client";

import { useQuery } from "@tanstack/react-query";
import { useAuth } from "@/hooks/use-auth";
import { searchKnowledge } from "@/lib/api/search";
import type { SearchParams } from "@/lib/search";

/**
 * Runs a search only once `params` is set (after an explicit submit). The key holds the user id
 * and every input, so results can't leak between users or selections, and identical searches
 * share a cached result. The abort signal cancels the request if the page or selection goes away.
 */
export function useKnowledgeSearch(params: SearchParams | null) {
  const { user, status } = useAuth();
  const userId = user?.id ?? null;

  return useQuery({
    queryKey: [
      "search",
      userId ?? "anonymous",
      params?.workspaceId ?? null,
      params?.documentId ?? null,
      params?.topK ?? null,
      params?.query ?? null,
    ],
    queryFn: ({ signal }) =>
      searchKnowledge(
        {
          query: params!.query,
          workspace_id: params!.workspaceId,
          // Omitted (not null) when searching the whole workspace.
          ...(params!.documentId ? { document_id: params!.documentId } : {}),
          top_k: params!.topK,
        },
        signal,
      ),
    enabled: status === "authenticated" && user !== null && params !== null,
    // Searches are expensive (embedding + reranking): never re-run them just for focus/reconnect.
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    retry: false,
  });
}
