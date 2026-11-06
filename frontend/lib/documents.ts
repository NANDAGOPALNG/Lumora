import type { DocumentResponse, DocumentStatus } from "@/types/api";

/** Extensions the backend accepts (ALLOWED_FILE_TYPES in document_service.py). */
export const SUPPORTED_EXTENSIONS = ["pdf", "docx", "txt", "md"] as const;
export const ACCEPT_ATTRIBUTE = SUPPORTED_EXTENSIONS.map((ext) => `.${ext}`).join(",");

/**
 * The backend reads its limit from the MAX_DOCUMENT_SIZE_MB setting (default 20,
 * see backend/app/config/settings.py) and exposes no endpoint for it. This mirrors
 * that default and can be overridden with NEXT_PUBLIC_MAX_UPLOAD_MB if the backend
 * is configured differently. It is only a courtesy pre-check: the server's 413
 * response is always authoritative.
 */
const BACKEND_DEFAULT_MAX_MB = 20;

export function getMaxUploadBytes(): number {
  // Referenced literally so Next.js can inline it at build time.
  const configured = Number(process.env.NEXT_PUBLIC_MAX_UPLOAD_MB);
  const megabytes = Number.isFinite(configured) && configured > 0 ? configured : BACKEND_DEFAULT_MAX_MB;
  return megabytes * 1024 * 1024;
}

export function formatFileSize(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return "Unknown size";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(bytes < 10 * 1024 ? 1 : 0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(bytes < 10 * 1024 * 1024 ? 1 : 0)} MB`;
}

export function fileExtension(filename: string): string | null {
  if (!filename.includes(".")) return null;
  return filename.slice(filename.lastIndexOf(".") + 1).toLowerCase();
}

export type FileValidation = { ok: true } | { ok: false; message: string };

/** Client-side pre-check; the backend re-validates everything. */
export function validateFile(file: File): FileValidation {
  const extension = fileExtension(file.name);
  if (extension === null || !(SUPPORTED_EXTENSIONS as readonly string[]).includes(extension)) {
    return { ok: false, message: "Unsupported file type. Upload PDF, DOCX, TXT or MD files." };
  }
  if (file.size === 0) {
    return { ok: false, message: "This file is empty." };
  }
  const max = getMaxUploadBytes();
  if (file.size > max) {
    return {
      ok: false,
      message: `This file is ${formatFileSize(file.size)}, over the ${formatFileSize(max)} limit.`,
    };
  }
  return { ok: true };
}

/** The backend returns documents in no guaranteed order; show newest first. */
export function sortDocuments(documents: DocumentResponse[]): DocumentResponse[] {
  return [...documents].sort((a, b) => {
    const diff = Date.parse(b.uploaded_at) - Date.parse(a.uploaded_at);
    if (Number.isFinite(diff) && diff !== 0) return diff;
    return a.id.localeCompare(b.id);
  });
}

export const DOCUMENT_STATUSES: DocumentStatus[] = ["Uploaded", "Processing", "Indexed", "Failed"];

export const POLL_INTERVAL_MS = 3000;
const SLOW_POLL_INTERVAL_MS = 10_000;
const FAST_POLLS = 20;

/**
 * Poll only while some document is Processing, and back off after about a minute
 * so a document stuck in that state doesn't poll quickly forever.
 */
export function documentsRefetchInterval(
  documents: DocumentResponse[] | undefined,
  updateCount: number,
): number | false {
  if (!documents?.some((document) => document.status === "Processing")) return false;
  return updateCount < FAST_POLLS ? POLL_INTERVAL_MS : SLOW_POLL_INTERVAL_MS;
}
