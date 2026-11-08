import { describe, expect, it } from "vitest";
import { isGitHubConnector, needsReconnect, normaliseRepoInput, validateRepoFullName, validateToken } from "@/lib/connectors";
import { beginSync, endSync } from "@/lib/sync-tracker";
import { describeApiError } from "@/lib/api/errors";
import { ApiError } from "@/lib/api/client";
import { connector } from "./fake-backend";

describe("repository validation", () => {
  it.each(["octocat/Hello-World", "owner/repo.name", "a_b/c-d", "  octocat/Hello-World  "])("accepts %s", (value) => {
    expect(validateRepoFullName(value)).toBeNull();
  });

  it.each(["", "   ", "justarepo", "owner/", "/repo", "a/b/c", "own er/repo", "owner/re po", "owner\\repo", "owner/repo?x=1"])(
    "rejects %j",
    (value) => expect(validateRepoFullName(value)).not.toBeNull(),
  );

  it("tidies a pasted GitHub URL into owner/repo", () => {
    expect(normaliseRepoInput("https://github.com/octocat/Hello-World")).toBe("octocat/Hello-World");
    expect(normaliseRepoInput("https://github.com/octocat/Hello-World.git")).toBe("octocat/Hello-World");
    expect(normaliseRepoInput("github.com/octocat/Hello-World/")).toBe("octocat/Hello-World");
    expect(validateRepoFullName("https://github.com/octocat/Hello-World")).toBeNull();
  });
});

describe("token validation", () => {
  it("rejects empty tokens", () => {
    expect(validateToken("")).not.toBeNull();
    expect(validateToken("   ")).not.toBeNull();
    expect(validateToken("ghp_abc")).toBeNull();
  });
});

describe("connector helpers", () => {
  it("recognises GitHub connectors and ones that must be reconnected", () => {
    expect(isGitHubConnector(connector(1, 1, "a/b"))).toBe(true);
    expect(isGitHubConnector(connector(2, 1, "a/b", { type: "google-drive" }))).toBe(false);
    expect(needsReconnect(connector(3, 1, "a/b", { github_repo: null }))).toBe(true);
    expect(needsReconnect(connector(4, 1, "a/b"))).toBe(false);
  });
});

describe("sync tracker", () => {
  it("allows one sync per connector at a time", () => {
    expect(beginSync("c1")).toBe(true);
    expect(beginSync("c1")).toBe(false); // already running
    expect(beginSync("c2")).toBe(true); // other connectors are independent
    endSync("c1");
    expect(beginSync("c1")).toBe(true);
    endSync("c1");
    endSync("c2");
  });
});

describe("connector error messages", () => {
  it("uses fixed wording for credential problems rather than raw backend text", () => {
    const raw = new ApiError(400, "INVALID_GITHUB_CREDENTIALS", "Invalid or expired GitHub token ghp_secret");
    const message = describeApiError(raw);
    expect(message).toMatch(/didn’t accept the token/);
    expect(message).not.toContain("ghp_secret");
    expect(describeApiError(new ApiError(404, "GITHUB_REPOSITORY_NOT_FOUND", "x"))).toMatch(/couldn’t find that repository/);
    expect(describeApiError(new ApiError(404, "CONNECTOR_NOT_FOUND", "x"))).toMatch(/no longer exists/);
    expect(describeApiError(new ApiError(400, "CONNECTOR_MISSING_REPOSITORY", "x"))).toMatch(/connect the repository again/);
  });
});
