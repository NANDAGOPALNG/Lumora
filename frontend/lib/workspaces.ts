import type { WorkspaceResponse } from "@/types/api";

/** Limits enforced by the backend (WorkspaceName in schemas/workspace.py). */
export const WORKSPACE_NAME_MAX = 100;

/** Length in characters (code points), matching how the backend counts. */
export function nameLength(name: string): number {
  return [...name.trim()].length;
}

/** Returns an error message, or null when the (trimmed) name is acceptable. */
export function validateWorkspaceName(raw: string): string | null {
  const length = nameLength(raw);
  if (length === 0) return "Enter a workspace name.";
  if (length > WORKSPACE_NAME_MAX) {
    return `Use ${WORKSPACE_NAME_MAX} characters or fewer.`;
  }
  return null;
}

const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function isUuid(value: string): boolean {
  return UUID_PATTERN.test(value);
}

/** The backend returns workspaces in no guaranteed order; show newest first. */
export function sortWorkspaces(workspaces: WorkspaceResponse[]): WorkspaceResponse[] {
  return [...workspaces].sort((a, b) => {
    const diff = Date.parse(b.created_at) - Date.parse(a.created_at);
    if (Number.isFinite(diff) && diff !== 0) return diff;
    return a.id.localeCompare(b.id);
  });
}
