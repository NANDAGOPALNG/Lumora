"use client";

import {
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
  type QueryKey,
} from "@tanstack/react-query";
import type { WorkspaceResponse } from "@/types/api";
import { useAuth } from "@/hooks/use-auth";
import * as workspacesApi from "@/lib/api/workspaces";
import { ApiError } from "@/lib/api/client";
import { sortWorkspaces } from "@/lib/workspaces";

/** Keys include the user id so one user's cache can never be shown to another. */
const listKey = (userId: string | null): QueryKey => ["workspaces", userId ?? "anonymous"];

function useWorkspacesKey() {
  const { user, status } = useAuth();
  return { key: listKey(user?.id ?? null), enabled: status === "authenticated" && user !== null };
}

/** The signed-in user's workspaces, newest first. */
export function useWorkspaces() {
  const { key, enabled } = useWorkspacesKey();
  return useQuery({
    queryKey: key,
    queryFn: ({ signal }) => workspacesApi.listWorkspaces(signal),
    enabled,
  });
}

/**
 * One workspace, resolved from the list (the backend has no GET-by-id).
 * `data` is undefined while loading and null when the list has no such id,
 * which covers both "doesn't exist" and "belongs to someone else".
 */
export function useWorkspace(workspaceId: string, { enabled = true }: { enabled?: boolean } = {}) {
  const { key, enabled: signedIn } = useWorkspacesKey();
  return useQuery({
    queryKey: key,
    queryFn: ({ signal }) => workspacesApi.listWorkspaces(signal),
    enabled: signedIn && enabled,
    select: (workspaces) => workspaces.find((w) => w.id === workspaceId) ?? null,
  });
}

/** Apply a change to the cached list, or mark it stale when it isn't loaded yet. */
function patchList(
  client: QueryClient,
  key: QueryKey,
  change: (current: WorkspaceResponse[]) => WorkspaceResponse[],
) {
  const current = client.getQueryData<WorkspaceResponse[]>(key);
  if (current) client.setQueryData(key, sortWorkspaces(change(current)));
  else void client.invalidateQueries({ queryKey: key });
}

/** If the workspace is already gone, refresh the list so the UI matches the server. */
function reconcileOnNotFound(client: QueryClient, key: QueryKey, error: unknown) {
  if (error instanceof ApiError && error.code === "WORKSPACE_NOT_FOUND") {
    void client.invalidateQueries({ queryKey: key });
  }
}

export function useCreateWorkspace() {
  const client = useQueryClient();
  const { key } = useWorkspacesKey();
  return useMutation({
    mutationFn: (name: string) => workspacesApi.createWorkspace(name),
    onSuccess: (created) => patchList(client, key, (list) => [...list, created]),
  });
}

export function useRenameWorkspace() {
  const client = useQueryClient();
  const { key } = useWorkspacesKey();
  return useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) =>
      workspacesApi.renameWorkspace(id, name),
    onSuccess: (updated) =>
      patchList(client, key, (list) => list.map((w) => (w.id === updated.id ? updated : w))),
    onError: (error) => reconcileOnNotFound(client, key, error),
  });
}

export function useDeleteWorkspace() {
  const client = useQueryClient();
  const { key } = useWorkspacesKey();
  return useMutation({
    mutationFn: (id: string) => workspacesApi.deleteWorkspace(id),
    // Destructive, so the list only changes once the server confirms.
    onSuccess: (_result, id) => patchList(client, key, (list) => list.filter((w) => w.id !== id)),
    onError: (error) => reconcileOnNotFound(client, key, error),
  });
}
