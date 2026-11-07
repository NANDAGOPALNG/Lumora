import { describe, expect, it, vi } from "vitest";
import { searchKnowledge } from "@/lib/api/search";
import { getAccessToken, setAccessToken } from "@/lib/auth/session";
import { setUnauthorizedHandler } from "@/lib/api/client";
import { apiError } from "./helpers";
import { createFakeBackend, source, uuid, workspace } from "./fake-backend";

const seed = () => ({ workspaces: [workspace(1, "Alpha"), workspace(2, "Beta", "someone-else")] });
const calls = (backend: ReturnType<typeof createFakeBackend>) => backend.callsTo("POST", "/api/v1/search");

describe("searchKnowledge", () => {
  it("posts the query and workspace with the Bearer token and returns the sources in order", async () => {
    setAccessToken("token-ada");
    const backend = createFakeBackend(seed());
    const response = await searchKnowledge({ query: "auth", workspace_id: uuid(1), top_k: 5 });

    expect(calls(backend)[0].body).toEqual({ query: "auth", workspace_id: uuid(1), top_k: 5 });
    expect(calls(backend)[0].authorization).toBe("Bearer token-ada");
    expect(response.sources.map((s) => s.filename)).toEqual(["alpha.pdf", "beta.md"]);
    expect(response.sources[0]).toMatchObject({ chunk_index: 2, score: 0.8731, source: "pdf" });
    expect(response.context).toBeTruthy();
  });

  it("sends document_id only when given", async () => {
    setAccessToken("token-ada");
    const backend = createFakeBackend(seed());
    await searchKnowledge({ query: "q", workspace_id: uuid(1) });
    await searchKnowledge({ query: "q", workspace_id: uuid(1), document_id: uuid(1001) });
    expect("document_id" in (calls(backend)[0].body as object)).toBe(false);
    expect(calls(backend)[1].body).toMatchObject({ document_id: uuid(1001) });
  });

  it("passes the abort signal to the request", async () => {
    setAccessToken("token-ada");
    createFakeBackend(seed());
    const controller = new AbortController();
    await searchKnowledge({ query: "q", workspace_id: uuid(1) }, controller.signal);
    const init = vi.mocked(fetch).mock.calls[0][1] as RequestInit;
    expect(init.signal).toBe(controller.signal);
  });

  it("maps the backend's error codes", async () => {
    setAccessToken("token-ada");
    const backend = createFakeBackend(seed());
    await expect(searchKnowledge({ query: "q", workspace_id: uuid(2) })).rejects.toMatchObject({ status: 404, code: "WORKSPACE_NOT_FOUND" });
    await expect(searchKnowledge({ query: "  ", workspace_id: uuid(1) })).rejects.toMatchObject({ status: 400, code: "INVALID_SEARCH_REQUEST" });
    await expect(searchKnowledge({ query: "q", workspace_id: uuid(1), top_k: 51 })).rejects.toMatchObject({ status: 422, code: "VALIDATION_ERROR" });
    backend.state.override = (call) =>
      call.path === "/api/v1/search" ? apiError(500, "INTERNAL_SERVER_ERROR", "An unexpected error occurred") : null;
    await expect(searchKnowledge({ query: "q", workspace_id: uuid(1) })).rejects.toMatchObject({ status: 500 });
  });

  it("maps a network failure to NETWORK_ERROR without ending the session", async () => {
    setAccessToken("token-ada");
    const backend = createFakeBackend(seed());
    backend.state.down = true;
    await expect(searchKnowledge({ query: "q", workspace_id: uuid(1) })).rejects.toMatchObject({ status: 0, code: "NETWORK_ERROR" });
    expect(getAccessToken()).toBe("token-ada");
  });

  it("ends the session on a 401", async () => {
    setAccessToken("expired");
    createFakeBackend({ ...seed(), users: {} });
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    await expect(searchKnowledge({ query: "q", workspace_id: uuid(1) })).rejects.toMatchObject({ status: 401 });
    expect(getAccessToken()).toBeNull();
    expect(handler).toHaveBeenCalledOnce();
  });

  it("only returns passages from the requested document", async () => {
    setAccessToken("token-ada");
    const backend = createFakeBackend(seed());
    backend.state.searchResults = () => [source(1, "a.pdf"), source(2, "b.md")];
    const response = await searchKnowledge({ query: "q", workspace_id: uuid(1), document_id: uuid(1002) });
    expect(response.sources.map((s) => s.filename)).toEqual(["b.md"]);
  });
});
