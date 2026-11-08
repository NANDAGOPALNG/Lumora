import type {
  ConnectorResponse,
  GitHubConnectorCreate,
  GitHubSyncRequest,
  GitHubSyncResponse,
} from "@/types/api";
import { apiFetch } from "@/lib/api/client";

const BASE = "/api/v1/connectors";

/** Connectors of one workspace the user owns. Responses never contain a credential. */
export function listConnectors(workspaceId: string, signal?: AbortSignal): Promise<ConnectorResponse[]> {
  return apiFetch<ConnectorResponse[]>(`${BASE}?workspace_id=${encodeURIComponent(workspaceId)}`, { signal });
}

/**
 * The token is only forwarded to the backend to validate access. Call this directly from a handler
 * (not through a TanStack mutation, whose variables are kept in its cache) and discard the token after.
 */
export function connectGitHub(request: GitHubConnectorCreate): Promise<ConnectorResponse> {
  return apiFetch<ConnectorResponse>(`${BASE}/github`, { method: "POST", body: request });
}

/** The backend doesn't keep the token, so every sync needs it again. The request stays open until the sync ends. */
export function syncGitHubConnector(connectorId: string, githubToken: string): Promise<GitHubSyncResponse> {
  const body: GitHubSyncRequest = { github_token: githubToken };
  return apiFetch<GitHubSyncResponse>(`${BASE}/${encodeURIComponent(connectorId)}/sync`, { method: "POST", body });
}

/** Responds 204 with no body. */
export function deleteConnector(connectorId: string): Promise<void> {
  return apiFetch<void>(`${BASE}/${encodeURIComponent(connectorId)}`, { method: "DELETE" });
}
