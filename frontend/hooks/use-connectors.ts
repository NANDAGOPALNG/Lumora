"use client";

import { useMutation, useQuery, useQueryClient, type QueryKey } from "@tanstack/react-query";
import type { ConnectorResponse, GitHubSyncResponse } from "@/types/api";
import { useAuth } from "@/hooks/use-auth";
import { documentsKey } from "@/hooks/use-documents";
import * as connectorsApi from "@/lib/api/connectors";
import { beginSync, endSync } from "@/lib/sync-tracker";
import { ApiError } from "@/lib/api/client";

/** Keys hold the user and workspace ids only, never a credential. */
const connectorsKey = (userId: string | null, workspaceId: string): QueryKey => [
  "connectors",
  userId ?? "anonymous",
  workspaceId,
];

function useSession() {
  const { user, status } = useAuth();
  return { userId: user?.id ?? null, signedIn: status === "authenticated" && user !== null };
}

export function useConnectors(workspaceId: string | null) {
  const { userId, signedIn } = useSession();
  return useQuery({
    queryKey: connectorsKey(userId, workspaceId ?? ""),
    queryFn: ({ signal }) => connectorsApi.listConnectors(workspaceId!, signal),
    enabled: signedIn && workspaceId !== null,
  });
}

/**
 * Connect and sync carry a GitHub token, so they are plain async functions rather than TanStack
 * mutations (a mutation's variables are retained in the mutation cache). The token is passed
 * straight to the request and only the safe response is written to the cache.
 */
export function useGitHubConnectorActions() {
  const client = useQueryClient();
  const { userId } = useSession();

  async function connect(request: Parameters<typeof connectorsApi.connectGitHub>[0]): Promise<ConnectorResponse> {
    const created = await connectorsApi.connectGitHub(request);
    const key = connectorsKey(userId, created.workspace_id);
    const current = client.getQueryData<ConnectorResponse[]>(key);
    if (current) client.setQueryData(key, [...current, created]);
    void client.invalidateQueries({ queryKey: key });
    return created;
  }

  /** Throws SyncAlreadyRunningError instead of sending a second request for the same connector. */
  async function sync(connector: ConnectorResponse, githubToken: string): Promise<GitHubSyncResponse> {
    if (!beginSync(connector.id)) throw new SyncAlreadyRunningError();
    try {
      const summary = await connectorsApi.syncGitHubConnector(connector.id, githubToken);
      // The sync changed the connector (last synced) and the workspace's documents.
      void client.invalidateQueries({ queryKey: connectorsKey(userId, connector.workspace_id) });
      void client.invalidateQueries({ queryKey: documentsKey(userId, connector.workspace_id) });
      // Search results may now be out of date; mark them stale without re-running expensive searches.
      void client.invalidateQueries({ queryKey: ["search", userId ?? "anonymous"], refetchType: "none" });
      return summary;
    } catch (error) {
      if (error instanceof ApiError && error.code === "CONNECTOR_NOT_FOUND") {
        void client.invalidateQueries({ queryKey: connectorsKey(userId, connector.workspace_id) });
      }
      throw error;
    } finally {
      endSync(connector.id);
    }
  }

  return { connect, sync };
}

export class SyncAlreadyRunningError extends Error {
  constructor() {
    super("A sync is already running for this connection.");
    this.name = "SyncAlreadyRunningError";
  }
}

/** Disconnecting involves no secret, so it is an ordinary mutation. */
export function useDisconnectConnector() {
  const client = useQueryClient();
  const { userId } = useSession();
  return useMutation({
    mutationFn: ({ id }: { id: string; workspaceId: string }) => connectorsApi.deleteConnector(id),
    onSuccess: (_result, { id, workspaceId }) => {
      client.setQueryData<ConnectorResponse[]>(connectorsKey(userId, workspaceId), (old) =>
        old?.filter((connector) => connector.id !== id),
      );
      void client.invalidateQueries({ queryKey: connectorsKey(userId, workspaceId) });
    },
    onError: (error, { workspaceId }) => {
      if (error instanceof ApiError && error.code === "CONNECTOR_NOT_FOUND") {
        void client.invalidateQueries({ queryKey: connectorsKey(userId, workspaceId) });
      }
    },
  });
}
