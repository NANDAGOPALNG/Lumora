import type { DocumentResponse, MessageResponse } from "@/types/api";
import { apiFetch, apiUpload, type UploadOptions } from "@/lib/api/client";
import { sortDocuments } from "@/lib/documents";

const BASE = "/api/v1/documents";

/** The backend has no "all documents" endpoint: listing is always per workspace. */
export async function listDocuments(workspaceId: string, signal?: AbortSignal): Promise<DocumentResponse[]> {
  const documents = await apiFetch<DocumentResponse[]>(
    `${BASE}?workspace_id=${encodeURIComponent(workspaceId)}`,
    { signal },
  );
  return sortDocuments(documents);
}

export function getDocument(documentId: string, signal?: AbortSignal): Promise<DocumentResponse> {
  return apiFetch<DocumentResponse>(`${BASE}/${encodeURIComponent(documentId)}`, { signal });
}

/** Uploads a file. The document comes back with status "Uploaded"; indexing is a separate call. */
export function uploadDocument(
  workspaceId: string,
  file: File,
  options?: UploadOptions,
): Promise<DocumentResponse> {
  const form = new FormData();
  form.append("workspace_id", workspaceId);
  form.append("file", file, file.name);
  return apiUpload<DocumentResponse>(`${BASE}/upload`, form, options);
}

export function deleteDocument(documentId: string): Promise<MessageResponse> {
  return apiFetch<MessageResponse>(`${BASE}/${encodeURIComponent(documentId)}`, { method: "DELETE" });
}

/**
 * Re-runs ingestion. The request stays open until indexing finishes and resolves with the
 * final document ("Indexed"); a failure responds 422 INGESTION_FAILED after marking it "Failed".
 */
export function reindexDocument(documentId: string): Promise<DocumentResponse> {
  return apiFetch<DocumentResponse>(`${BASE}/${encodeURIComponent(documentId)}/reindex`, {
    method: "POST",
  });
}
