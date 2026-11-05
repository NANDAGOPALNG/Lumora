import type {
  MessageResponse,
  WorkspaceCreate,
  WorkspaceResponse,
  WorkspaceUpdate,
} from "@/types/api";
import { apiFetch } from "@/lib/api/client";
import { sortWorkspaces } from "@/lib/workspaces";

const BASE = "/api/v1/workspaces";

export async function listWorkspaces(signal?: AbortSignal): Promise<WorkspaceResponse[]> {
  const workspaces = await apiFetch<WorkspaceResponse[]>(BASE, { signal });
  return sortWorkspaces(workspaces);
}

export function createWorkspace(name: string): Promise<WorkspaceResponse> {
  const body: WorkspaceCreate = { name };
  return apiFetch<WorkspaceResponse>(BASE, { method: "POST", body });
}

export function renameWorkspace(id: string, name: string): Promise<WorkspaceResponse> {
  const body: WorkspaceUpdate = { name };
  return apiFetch<WorkspaceResponse>(`${BASE}/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body,
  });
}

export function deleteWorkspace(id: string): Promise<MessageResponse> {
  return apiFetch<MessageResponse>(`${BASE}/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
}
