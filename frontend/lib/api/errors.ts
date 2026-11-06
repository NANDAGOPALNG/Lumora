import { ApiError, CONFIG_ERROR, NETWORK_ERROR } from "@/lib/api/client";

/** Turn any thrown value into a message that is safe and useful to show a person. */
export function describeApiError(error: unknown): string {
  if (!(error instanceof ApiError)) return "Something went wrong. Please try again.";

  if (error.code === NETWORK_ERROR) {
    return "Can’t reach the Lumora server. Check your connection and try again.";
  }
  if (error.code === CONFIG_ERROR) return error.message;
  if (error.status === 401) return "Your session has ended. Please sign in again.";
  if (error.code === "WORKSPACE_NOT_FOUND") {
    return "This workspace no longer exists. It may have been deleted.";
  }
  if (error.code === "DOCUMENT_NOT_FOUND") {
    return "This document no longer exists. It may have been deleted.";
  }
  if (error.code === "UNSUPPORTED_FILE_TYPE") {
    return "This file type isn’t supported. Upload PDF, DOCX, TXT or MD files.";
  }
  if (error.code === "FILE_TOO_LARGE") {
    // The backend message states its limit in bytes, e.g. "...maximum allowed size of 20971520 bytes".
    const bytes = Number(error.message.match(/(\d+)\s*bytes/)?.[1]);
    const limit = Number.isFinite(bytes) && bytes > 0 ? ` (limit ${Math.round(bytes / 1024 / 1024)} MB)` : "";
    return `This file is larger than the server allows${limit}.`;
  }
  if (error.code === "INGESTION_FAILED") {
    return "Indexing failed. The file may contain no readable text (for example a scanned PDF) or may be damaged. You can try again.";
  }
  if (error.code === "VALIDATION_ERROR") {
    // The backend only says "Invalid request"; the usual cause is the name rules.
    return "The server rejected this request. Names must be 1–100 characters.";
  }
  if (error.status >= 500) return "Something went wrong on our side. Please try again.";
  return error.message;
}
