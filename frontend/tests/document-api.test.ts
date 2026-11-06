import { describe, expect, it, vi } from "vitest";
import { ApiError, setUnauthorizedHandler } from "@/lib/api/client";
import {
  deleteDocument,
  getDocument,
  listDocuments,
  reindexDocument,
  uploadDocument,
} from "@/lib/api/documents";
import { clearAccessToken, getAccessToken, setAccessToken } from "@/lib/auth/session";
import { createFakeBackend, document, uuid, workspace } from "./fake-backend";
import { deferred, makeFile } from "./ui-helpers";

const seed = () => ({
  workspaces: [workspace(1, "Alpha"), workspace(2, "Beta", "someone-else")],
  documents: [
    document(1, 1, "old.txt", "Indexed"),
    document(3, 1, "new.md", "Uploaded", { chunk_count: 0 }),
    document(9, 2, "foreign.txt"),
  ],
});

describe("listDocuments", () => {
  it("requests the workspace's documents with the Bearer token, newest first", async () => {
    setAccessToken("token-ada");
    const backend = createFakeBackend(seed());
    const documents = await listDocuments(uuid(1));
    const [call] = backend.callsTo("GET", "/api/v1/documents");
    expect(call.query.get("workspace_id")).toBe(uuid(1));
    expect(call.authorization).toBe("Bearer token-ada");
    expect(documents.map((d) => d.filename)).toEqual(["new.md", "old.txt"]);
  });

  it("URL-encodes the workspace id", async () => {
    setAccessToken("token-ada");
    const backend = createFakeBackend(seed());
    await listDocuments("a&b=c").catch(() => undefined);
    expect(backend.callsTo("GET", "/api/v1/documents")[0].query.get("workspace_id")).toBe("a&b=c");
  });

  it("treats another user's workspace as not found", async () => {
    setAccessToken("token-ada");
    createFakeBackend(seed());
    await expect(listDocuments(uuid(2))).rejects.toMatchObject({ status: 404, code: "WORKSPACE_NOT_FOUND" });
  });

  it("is rejected without a session", async () => {
    clearAccessToken();
    createFakeBackend(seed());
    await expect(listDocuments(uuid(1))).rejects.toMatchObject({ status: 401 });
  });
});

describe("getDocument / deleteDocument / reindexDocument", () => {
  it("gets one document", async () => {
    setAccessToken("token-ada");
    createFakeBackend(seed());
    expect((await getDocument(uuid(1001))).filename).toBe("old.txt");
    await expect(getDocument(uuid(1009))).rejects.toMatchObject({ code: "DOCUMENT_NOT_FOUND" }); // not the user's
  });

  it("deletes with DELETE and reports success", async () => {
    setAccessToken("token-ada");
    const backend = createFakeBackend(seed());
    await expect(deleteDocument(uuid(1001))).resolves.toEqual({ message: "Document deleted successfully" });
    expect(backend.callsTo("DELETE", `/api/v1/documents/${uuid(1001)}`)).toHaveLength(1);
    await expect(deleteDocument(uuid(1001))).rejects.toMatchObject({ status: 404 });
  });

  it("reindexes with POST and returns the final document", async () => {
    setAccessToken("token-ada");
    const backend = createFakeBackend(seed());
    const result = await reindexDocument(uuid(1003));
    expect(backend.callsTo("POST", `/api/v1/documents/${uuid(1003)}/reindex`)).toHaveLength(1);
    expect(result).toMatchObject({ status: "Indexed", chunk_count: 3 });
  });

  it("surfaces an ingestion failure as a 422 INGESTION_FAILED error", async () => {
    setAccessToken("token-ada");
    const backend = createFakeBackend(seed());
    backend.state.failReindex.add(uuid(1003));
    await expect(reindexDocument(uuid(1003))).rejects.toMatchObject({ status: 422, code: "INGESTION_FAILED" });
  });

  it("cannot touch another user's document", async () => {
    setAccessToken("token-ada");
    createFakeBackend(seed());
    await expect(reindexDocument(uuid(1009))).rejects.toMatchObject({ status: 404, code: "DOCUMENT_NOT_FOUND" });
    await expect(deleteDocument(uuid(1009))).rejects.toMatchObject({ status: 404, code: "DOCUMENT_NOT_FOUND" });
  });
});

describe("uploadDocument", () => {
  it("sends multipart workspace_id + file with the Bearer token and no manual Content-Type", async () => {
    setAccessToken("token-ada");
    const backend = createFakeBackend(seed());
    const created = await uploadDocument(uuid(1), makeFile("notes.md", "# hi"));
    const [call] = backend.callsTo("POST", "/api/v1/documents/upload");
    expect(call.form?.get("workspace_id")).toBe(uuid(1));
    expect((call.form?.get("file") as File).name).toBe("notes.md");
    expect(call.authorization).toBe("Bearer token-ada");
    expect(call.headers["Content-Type"]).toBeUndefined(); // the browser must add the multipart boundary
    expect(created).toMatchObject({ filename: "notes.md", status: "Uploaded", chunk_count: 0 });
  });

  it("reports upload progress as a fraction ending at 1", async () => {
    setAccessToken("token-ada");
    createFakeBackend(seed());
    const onProgress = vi.fn();
    await uploadDocument(uuid(1), makeFile("a.txt"), { onProgress });
    const fractions = onProgress.mock.calls.map(([f]) => f as number);
    expect(fractions.length).toBeGreaterThan(1);
    expect(fractions.at(-1)).toBe(1);
    expect(fractions).toEqual([...fractions].sort((a, b) => a - b));
  });

  it("can be cancelled", async () => {
    setAccessToken("token-ada");
    const backend = createFakeBackend(seed());
    const gate = deferred();
    backend.state.uploadGate = () => gate.promise;
    const controller = new AbortController();
    const pending = uploadDocument(uuid(1), makeFile("a.txt"), { signal: controller.signal });
    controller.abort();
    await expect(pending).rejects.toMatchObject({ name: "AbortError" });
    gate.resolve();
    expect(backend.state.documents.some((d) => d.filename === "a.txt")).toBe(false);
  });

  it("maps a network failure to NETWORK_ERROR without ending the session", async () => {
    setAccessToken("token-ada");
    const backend = createFakeBackend(seed());
    backend.state.down = true;
    await expect(uploadDocument(uuid(1), makeFile("a.txt"))).rejects.toMatchObject({ status: 0, code: "NETWORK_ERROR" });
    expect(getAccessToken()).toBe("token-ada");
  });

  it("clears the session on a 401, like every other authenticated request", async () => {
    setAccessToken("expired-token");
    createFakeBackend({ ...seed(), users: {} }); // no token is valid
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    await expect(uploadDocument(uuid(1), makeFile("a.txt"))).rejects.toMatchObject({ status: 401 });
    expect(getAccessToken()).toBeNull();
    expect(handler).toHaveBeenCalledOnce();
  });

  it("surfaces the server's validation errors", async () => {
    setAccessToken("token-ada");
    const backend = createFakeBackend(seed());
    await expect(uploadDocument(uuid(1), makeFile("virus.exe"))).rejects.toMatchObject({ status: 415, code: "UNSUPPORTED_FILE_TYPE" });
    backend.state.maxUploadBytes = 4;
    await expect(uploadDocument(uuid(1), makeFile("big.txt", "too many bytes"))).rejects.toMatchObject({ status: 413, code: "FILE_TOO_LARGE" });
    await expect(uploadDocument(uuid(2), makeFile("a.txt"))).rejects.toMatchObject({ status: 404, code: "WORKSPACE_NOT_FOUND" });
  });

  it("reports a clear configuration error when the API base URL is missing", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "");
    await expect(uploadDocument(uuid(1), makeFile("a.txt"))).rejects.toBeInstanceOf(ApiError);
  });
});
