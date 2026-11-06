"use client";

import {
  useMutation,
  useMutationState,
  useQueries,
  useQuery,
  useQueryClient,
  type QueryClient,
  type QueryKey,
} from "@tanstack/react-query";
import type { DocumentResponse } from "@/types/api";
import { useAuth } from "@/hooks/use-auth";
import * as documentsApi from "@/lib/api/documents";
import type { UploadOptions } from "@/lib/api/client";
import { documentsRefetchInterval, sortDocuments } from "@/lib/documents";

/** Keys include the user id (like workspaces) so cached documents never cross sessions. */
const documentsKey = (userId: string | null, workspaceId: string): QueryKey => [
  "documents",
  userId ?? "anonymous",
  workspaceId,
];

const REINDEX_MUTATION_KEY = ["documents", "reindex"] as const;

function useSession() {
  const { user, status } = useAuth();
  return { userId: user?.id ?? null, signedIn: status === "authenticated" && user !== null };
}

function documentsQueryOptions(userId: string | null, workspaceId: string) {
  return {
    queryKey: documentsKey(userId, workspaceId),
    queryFn: ({ signal }: { signal: AbortSignal }) => documentsApi.listDocuments(workspaceId, signal),
    // Poll only while something is Processing; stops by itself once nothing is.
    refetchInterval: (query: {
      state: { data: DocumentResponse[] | undefined; dataUpdateCount: number };
    }) => documentsRefetchInterval(query.state.data, query.state.dataUpdateCount),
  };
}

/** One workspace's documents, newest first. */
export function useWorkspaceDocuments(workspaceId: string, { enabled = true }: { enabled?: boolean } = {}) {
  const { userId, signedIn } = useSession();
  return useQuery({ ...documentsQueryOptions(userId, workspaceId), enabled: signedIn && enabled });
}

/** Documents for several workspaces (the backend can only list per workspace). */
export function useMultiWorkspaceDocuments(workspaceIds: string[]) {
  const { userId, signedIn } = useSession();
  return useQueries({
    queries: workspaceIds.map((id) => ({ ...documentsQueryOptions(userId, id), enabled: signedIn })),
  });
}

/** Apply a change to a cached list, or mark it stale when it isn't loaded. */
function patchDocuments(
  client: QueryClient,
  key: QueryKey,
  change: (current: DocumentResponse[]) => DocumentResponse[],
) {
  const current = client.getQueryData<DocumentResponse[]>(key);
  if (current) client.setQueryData(key, sortDocuments(change(current)));
  else void client.invalidateQueries({ queryKey: key });
}

export interface UploadVariables extends UploadOptions {
  workspaceId: string;
  file: File;
}

export function useUploadDocument() {
  const client = useQueryClient();
  const { userId } = useSession();
  return useMutation({
    mutationFn: ({ workspaceId, file, onProgress, signal }: UploadVariables) =>
      documentsApi.uploadDocument(workspaceId, file, { onProgress, signal }),
    onSuccess: (created) =>
      patchDocuments(client, documentsKey(userId, created.workspace_id), (list) => [...list, created]),
  });
}

export interface DocumentTarget {
  id: string;
  workspaceId: string;
}

export function useReindexDocument() {
  const client = useQueryClient();
  const { userId } = useSession();
  return useMutation({
    mutationKey: REINDEX_MUTATION_KEY,
    mutationFn: ({ id }: DocumentTarget) => documentsApi.reindexDocument(id),
    onSuccess: (updated) =>
      patchDocuments(client, documentsKey(userId, updated.workspace_id), (list) =>
        list.map((d) => (d.id === updated.id ? updated : d)),
      ),
    // A failed reindex leaves the document "Failed" on the server, so always refresh.
    onError: (_error, { workspaceId }) =>
      void client.invalidateQueries({ queryKey: documentsKey(userId, workspaceId) }),
  });
}

export function useDeleteDocument() {
  const client = useQueryClient();
  const { userId } = useSession();
  return useMutation({
    mutationFn: ({ id }: DocumentTarget) => documentsApi.deleteDocument(id),
    // Destructive, so the list only changes once the server confirms.
    onSuccess: (_result, { id, workspaceId }) =>
      patchDocuments(client, documentsKey(userId, workspaceId), (list) => list.filter((d) => d.id !== id)),
    onError: (_error, { workspaceId }) =>
      void client.invalidateQueries({ queryKey: documentsKey(userId, workspaceId) }),
  });
}

/** Ids of documents currently being indexed by this app (reindex requests in flight). */
export function useReindexingIds(): string[] {
  return useMutationState({
    filters: { mutationKey: REINDEX_MUTATION_KEY, status: "pending" },
    select: (mutation) => (mutation.state.variables as DocumentTarget).id,
  });
}
