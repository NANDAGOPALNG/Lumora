import { describe, expect, it, vi } from "vitest";
import { ApiError, setUnauthorizedHandler } from "@/lib/api/client";
import { connectGitHub, deleteConnector, listConnectors, syncGitHubConnector } from "@/lib/api/connectors";
import { getAccessToken, setAccessToken } from "@/lib/auth/session";
import { connector, createFakeBackend, uuid, workspace } from "./fake-backend";

const seed = () => ({
  workspaces: [workspace(1, "Alpha"), workspace(2, "Beta", "someone-else")],
  connectors: [connector(1, 1, "acme/docs"), connector(2, 2, "foreign/repo")],
});

describe("listConnectors", () => {
  it("lists a workspace's connectors with the Bearer token", async () => {
    setAccessToken("token-ada");
    const backend = createFakeBackend(seed());
    const list = await listConnectors(uuid(1));
    const [call] = backend.callsTo("GET", "/api/v1/connectors");
    expect(call.query.get("workspace_id")).toBe(uuid(1));
    expect(call.authorization).toBe("Bearer token-ada");
    expect(list).toHaveLength(1);
    expect(list[0]).toMatchObject({ type: "github", github_repo: "acme/docs", last_synced: null, active: true });
  });

  it("treats another user's workspace as not found", async () => {
    setAccessToken("token-ada");
    createFakeBackend(seed());
    await expect(listConnectors(uuid(2))).rejects.toMatchObject({ status: 404, code: "WORKSPACE_NOT_FOUND" });
  });
});

describe("connectGitHub", () => {
  it("posts workspace, repository, token and optional name, returning safe metadata only", async () => {
    setAccessToken("token-ada");
    const backend = createFakeBackend(seed());
    const created = await connectGitHub({
      workspace_id: uuid(1),
      repo_full_name: "octocat/Hello-World",
      github_token: "ghp_valid",
      connection_name: "Hello",
    });
    expect(backend.callsTo("POST", "/api/v1/connectors/github")[0].body).toEqual({
      workspace_id: uuid(1),
      repo_full_name: "octocat/Hello-World",
      github_token: "ghp_valid",
      connection_name: "Hello",
    });
    expect(created).toMatchObject({ connection_name: "Hello", github_repo: "octocat/Hello-World" });
    expect(JSON.stringify(created)).not.toContain("ghp_valid"); // the response never contains the token
  });

  it("maps credential, repository and workspace errors", async () => {
    setAccessToken("token-ada");
    createFakeBackend(seed());
    const base = { workspace_id: uuid(1), repo_full_name: "octocat/Hello-World", github_token: "ghp_valid" };
    await expect(connectGitHub({ ...base, github_token: "ghp_bad" })).rejects.toMatchObject({ status: 400, code: "INVALID_GITHUB_CREDENTIALS" });
    await expect(connectGitHub({ ...base, repo_full_name: "octocat/missing-repo" })).rejects.toMatchObject({ status: 404, code: "GITHUB_REPOSITORY_NOT_FOUND" });
    await expect(connectGitHub({ ...base, workspace_id: uuid(2) })).rejects.toMatchObject({ status: 404, code: "WORKSPACE_NOT_FOUND" });
    await expect(connectGitHub({ ...base, repo_full_name: "not a repo" })).rejects.toMatchObject({ status: 422 });
  });

  it("ends the session on a 401", async () => {
    setAccessToken("expired");
    createFakeBackend({ ...seed(), users: {} });
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    await expect(
      connectGitHub({ workspace_id: uuid(1), repo_full_name: "a/b", github_token: "ghp_valid" }),
    ).rejects.toMatchObject({ status: 401 });
    expect(getAccessToken()).toBeNull();
    expect(handler).toHaveBeenCalledOnce();
  });
});

describe("syncGitHubConnector", () => {
  it("sends only the token in the body and returns the full summary", async () => {
    setAccessToken("token-ada");
    const backend = createFakeBackend(seed());
    const summary = await syncGitHubConnector(uuid(6001), "ghp_valid");
    const [call] = backend.callsTo("POST", `/api/v1/connectors/${uuid(6001)}/sync`);
    expect(call.body).toEqual({ github_token: "ghp_valid" });
    expect(call.query.toString()).toBe(""); // never in the URL
    expect(summary).toEqual({
      connector_id: uuid(6001),
      repository: "acme/docs",
      files_discovered: 3,
      files_added: 2,
      files_updated: 0,
      files_deleted: 0,
      files_unchanged: 1,
      files_skipped: 0,
      status: "completed",
    });
  });

  it("maps errors and never reaches another user's connector", async () => {
    setAccessToken("token-ada");
    const backend = createFakeBackend({ ...seed(), connectors: [...seed().connectors, connector(3, 1, "old/one", { github_repo: null })] });
    await expect(syncGitHubConnector(uuid(6001), "ghp_bad")).rejects.toMatchObject({ code: "INVALID_GITHUB_CREDENTIALS" });
    await expect(syncGitHubConnector(uuid(6002), "ghp_valid")).rejects.toMatchObject({ status: 404, code: "CONNECTOR_NOT_FOUND" });
    await expect(syncGitHubConnector(uuid(6003), "ghp_valid")).rejects.toMatchObject({ status: 400, code: "CONNECTOR_MISSING_REPOSITORY" });
    backend.state.down = true;
    await expect(syncGitHubConnector(uuid(6001), "ghp_valid")).rejects.toMatchObject({ status: 0, code: "NETWORK_ERROR" });
    expect(getAccessToken()).toBe("token-ada");
  });
});

describe("deleteConnector", () => {
  it("accepts the empty 204 response", async () => {
    setAccessToken("token-ada");
    const backend = createFakeBackend(seed());
    await expect(deleteConnector(uuid(6001))).resolves.toBeUndefined();
    expect(backend.callsTo("DELETE", `/api/v1/connectors/${uuid(6001)}`)).toHaveLength(1);
    expect(backend.state.connectors.some((c) => c.id === uuid(6001))).toBe(false);
  });

  it("returns 404 for another user's or an unknown connector", async () => {
    setAccessToken("token-ada");
    createFakeBackend(seed());
    await expect(deleteConnector(uuid(6002))).rejects.toBeInstanceOf(ApiError);
    await expect(deleteConnector(uuid(6002))).rejects.toMatchObject({ status: 404, code: "CONNECTOR_NOT_FOUND" });
  });
});
