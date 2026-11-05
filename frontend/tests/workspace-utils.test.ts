import { describe, expect, it } from "vitest";
import { ApiError } from "@/lib/api/client";
import { describeApiError } from "@/lib/api/errors";
import { formatDate } from "@/lib/format";
import { isUuid, nameLength, sortWorkspaces, validateWorkspaceName } from "@/lib/workspaces";
import { uuid, workspace } from "./fake-backend";

describe("validateWorkspaceName", () => {
  it("rejects empty and whitespace-only names", () => {
    expect(validateWorkspaceName("")).not.toBeNull();
    expect(validateWorkspaceName("   ")).not.toBeNull();
  });

  it("accepts 1 to 100 characters after trimming", () => {
    expect(validateWorkspaceName("  A  ")).toBeNull();
    expect(validateWorkspaceName("x".repeat(100))).toBeNull();
    expect(validateWorkspaceName(`  ${"x".repeat(100)}  `)).toBeNull();
    expect(validateWorkspaceName("x".repeat(101))).not.toBeNull();
  });

  it("counts characters the way the backend does (emoji count once)", () => {
    expect(nameLength("😀".repeat(100))).toBe(100);
    expect(validateWorkspaceName("😀".repeat(100))).toBeNull();
  });
});

describe("sortWorkspaces", () => {
  it("orders newest first without mutating the input", () => {
    const input = [workspace(1, "old"), workspace(3, "new"), workspace(2, "mid")];
    expect(sortWorkspaces(input).map((w) => w.name)).toEqual(["new", "mid", "old"]);
    expect(input.map((w) => w.name)).toEqual(["old", "new", "mid"]);
  });
});

describe("isUuid", () => {
  it("recognises UUIDs and rejects other strings", () => {
    expect(isUuid(uuid(1))).toBe(true);
    expect(isUuid("not-a-uuid")).toBe(false);
    expect(isUuid("")).toBe(false);
  });
});

describe("describeApiError", () => {
  it("gives specific, safe messages", () => {
    expect(describeApiError(new ApiError(0, "NETWORK_ERROR", "x"))).toMatch(/Can’t reach/);
    expect(describeApiError(new ApiError(404, "WORKSPACE_NOT_FOUND", "x"))).toMatch(/no longer exists/);
    expect(describeApiError(new ApiError(422, "VALIDATION_ERROR", "Invalid request"))).toMatch(/1–100/);
    expect(describeApiError(new ApiError(500, "INTERNAL_SERVER_ERROR", "boom"))).toMatch(/our side/);
    expect(describeApiError(new Error("raw internal text"))).not.toMatch(/raw internal/);
  });
});

describe("formatDate", () => {
  it("formats valid dates and tolerates invalid ones", () => {
    expect(formatDate("2026-10-05T10:00:00+00:00")).toMatch(/2026/);
    expect(formatDate("garbage")).toBe("Unknown date");
  });
});
