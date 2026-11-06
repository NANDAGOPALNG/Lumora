import { describe, expect, it } from "vitest";
import { ApiError } from "@/lib/api/client";
import { describeApiError } from "@/lib/api/errors";
import {
  documentsRefetchInterval,
  formatFileSize,
  getMaxUploadBytes,
  POLL_INTERVAL_MS,
  sortDocuments,
  validateFile,
} from "@/lib/documents";
import { document } from "./fake-backend";
import { makeFile, withSize } from "./ui-helpers";
import { vi } from "vitest";

describe("validateFile", () => {
  it.each(["a.pdf", "a.docx", "a.txt", "a.md", "REPORT.PDF", "Notes.Md", "my.report.v2.docx"])(
    "accepts %s",
    (name) => expect(validateFile(makeFile(name)).ok).toBe(true),
  );

  it.each(["photo.png", "archive.zip", "noextension", "script.exe", "doc.pdf.exe", ".hidden"])(
    "rejects unsupported %s",
    (name) => {
      const result = validateFile(makeFile(name));
      expect(result.ok).toBe(false);
      if (!result.ok) expect(result.message).toMatch(/Unsupported file type/);
    },
  );

  it("rejects empty files", () => {
    const result = validateFile(makeFile("empty.txt", ""));
    expect(result).toEqual({ ok: false, message: "This file is empty." });
  });

  it("enforces the size limit, accepting exactly the limit", () => {
    const limit = getMaxUploadBytes();
    expect(validateFile(withSize(makeFile("a.pdf"), limit)).ok).toBe(true);
    const over = validateFile(withSize(makeFile("a.pdf"), limit + 1));
    expect(over.ok).toBe(false);
    if (!over.ok) expect(over.message).toMatch(/over the 20 MB limit/);
  });
});

describe("upload size limit", () => {
  it("defaults to the backend's default of 20 MB", () => {
    expect(getMaxUploadBytes()).toBe(20 * 1024 * 1024);
  });

  it("can be overridden for a differently configured backend, ignoring bad values", () => {
    vi.stubEnv("NEXT_PUBLIC_MAX_UPLOAD_MB", "5");
    expect(getMaxUploadBytes()).toBe(5 * 1024 * 1024);
    vi.stubEnv("NEXT_PUBLIC_MAX_UPLOAD_MB", "nonsense");
    expect(getMaxUploadBytes()).toBe(20 * 1024 * 1024);
    vi.stubEnv("NEXT_PUBLIC_MAX_UPLOAD_MB", "-3");
    expect(getMaxUploadBytes()).toBe(20 * 1024 * 1024);
  });
});

describe("formatFileSize", () => {
  it("formats bytes, KB and MB", () => {
    expect(formatFileSize(512)).toBe("512 B");
    expect(formatFileSize(2048)).toBe("2.0 KB");
    expect(formatFileSize(500 * 1024)).toBe("500 KB");
    expect(formatFileSize(5.5 * 1024 * 1024)).toBe("5.5 MB");
    expect(formatFileSize(20 * 1024 * 1024)).toBe("20 MB");
    expect(formatFileSize(-1)).toBe("Unknown size");
  });
});

describe("sortDocuments", () => {
  it("orders newest first without mutating the input", () => {
    const input = [document(1, 1, "old.txt"), document(3, 1, "new.txt"), document(2, 1, "mid.txt")];
    expect(sortDocuments(input).map((d) => d.filename)).toEqual(["new.txt", "mid.txt", "old.txt"]);
    expect(input.map((d) => d.filename)).toEqual(["old.txt", "new.txt", "mid.txt"]);
  });
});

describe("documentsRefetchInterval (polling)", () => {
  it("does not poll when nothing is processing", () => {
    expect(documentsRefetchInterval(undefined, 0)).toBe(false);
    expect(documentsRefetchInterval([], 0)).toBe(false);
    const idle = [document(1, 1, "a.txt", "Indexed"), document(2, 1, "b.txt", "Uploaded"), document(3, 1, "c.txt", "Failed")];
    expect(documentsRefetchInterval(idle, 0)).toBe(false);
  });

  it("polls while any document is Processing, backing off after about a minute", () => {
    const busy = [document(1, 1, "a.txt", "Indexed"), document(2, 1, "b.txt", "Processing")];
    expect(documentsRefetchInterval(busy, 0)).toBe(POLL_INTERVAL_MS);
    expect(documentsRefetchInterval(busy, 19)).toBe(POLL_INTERVAL_MS);
    expect(documentsRefetchInterval(busy, 25)).toBeGreaterThan(POLL_INTERVAL_MS);
  });
});

describe("document error messages", () => {
  it("explains upload and indexing failures", () => {
    expect(describeApiError(new ApiError(415, "UNSUPPORTED_FILE_TYPE", "x"))).toMatch(/PDF, DOCX, TXT or MD/);
    expect(
      describeApiError(new ApiError(413, "FILE_TOO_LARGE", "File exceeds the maximum allowed size of 20971520 bytes")),
    ).toMatch(/limit 20 MB/);
    expect(describeApiError(new ApiError(413, "FILE_TOO_LARGE", "too big"))).toMatch(/larger than the server allows/);
    expect(describeApiError(new ApiError(422, "INGESTION_FAILED", "x"))).toMatch(/Indexing failed/);
    expect(describeApiError(new ApiError(404, "DOCUMENT_NOT_FOUND", "x"))).toMatch(/no longer exists/);
  });
});
