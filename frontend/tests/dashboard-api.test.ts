import { describe, expect, it } from "vitest";
import { ApiError } from "@/lib/api/client";
import { getDashboardSummary } from "@/lib/api/dashboard";
import { setAccessToken } from "@/lib/auth/session";
import { formatRelativeTime } from "@/lib/format";
import { safeInternalLink } from "@/lib/dashboard";
import { apiError, headerOf, json, mockBackend } from "./helpers";

const SUMMARY = {
  stats: { workspaces: 2, documents: 5, indexed_chunks: 40, conversations: 3 },
  recent_activity: [],
};

describe("dashboard API client", () => {
  it("GETs /api/v1/dashboard/summary with the bearer token and no user id in the request", async () => {
    setAccessToken("token-ada");
    const { calls } = mockBackend({ "/api/v1/dashboard/summary": () => json(200, SUMMARY) });
    await expect(getDashboardSummary()).resolves.toEqual(SUMMARY);
    expect(calls).toHaveLength(1);
    expect(calls[0].init.method ?? "GET").toBe("GET");
    expect(headerOf(calls[0].init, "Authorization")).toBe("Bearer token-ada");
    expect(calls[0].init.body).toBeUndefined();
  });

  it("surfaces server errors as ApiError", async () => {
    setAccessToken("token-ada");
    mockBackend({
      "/api/v1/dashboard/summary": () => apiError(500, "INTERNAL_ERROR", "Something failed"),
    });
    await expect(getDashboardSummary()).rejects.toMatchObject({
      name: "ApiError",
      status: 500,
      code: "INTERNAL_ERROR",
    });
  });

  it("reports an unreachable server as a network error", async () => {
    setAccessToken("token-ada");
    mockBackend({
      "/api/v1/dashboard/summary": () => {
        throw new TypeError("Failed to fetch");
      },
    });
    const error = await getDashboardSummary().catch((e) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(0);
  });
});

describe("formatRelativeTime", () => {
  const now = Date.parse("2026-11-10T12:00:00Z");
  const ago = (seconds: number) => new Date(now - seconds * 1000).toISOString();

  it("describes recent times relatively", () => {
    expect(formatRelativeTime(ago(5), now)).toBe("just now");
    expect(formatRelativeTime(ago(5 * 60), now)).toBe("5 minutes ago");
    expect(formatRelativeTime(ago(60), now)).toBe("1 minute ago");
    expect(formatRelativeTime(ago(3 * 3600), now)).toBe("3 hours ago");
    expect(formatRelativeTime(ago(2 * 86400), now)).toBe("2 days ago");
  });

  it("falls back to a date for old, far-future or invalid values", () => {
    expect(formatRelativeTime(ago(30 * 86400), now)).toMatch(/2026/);
    expect(formatRelativeTime(ago(-3600), now)).toMatch(/2026/);
    expect(formatRelativeTime("not-a-date", now)).toBe("Unknown date");
  });
});

describe("safeInternalLink", () => {
  it("allows only app-relative paths", () => {
    expect(safeInternalLink("/integrations")).toBe("/integrations");
    expect(safeInternalLink("/chat?c=abc")).toBe("/chat?c=abc");
    for (const bad of [null, undefined, "", "https://evil.example", "//evil.example", "javascript:alert(1)", "/\\evil", "relative"]) {
      expect(safeInternalLink(bad)).toBeNull();
    }
  });
});
