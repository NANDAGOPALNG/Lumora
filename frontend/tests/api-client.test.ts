import { describe, expect, it, vi } from "vitest";
import { ApiError, apiFetch, setUnauthorizedHandler } from "@/lib/api/client";
import { getAccessToken, setAccessToken } from "@/lib/auth/session";
import { apiError, headerOf, json, mockBackend } from "./helpers";

describe("apiFetch", () => {
  it("attaches the Bearer token to authenticated requests", async () => {
    setAccessToken("lumora-jwt");
    const { calls } = mockBackend({ "/api/v1/auth/me": () => json(200, { ok: true }) });
    await apiFetch("/api/v1/auth/me");
    expect(headerOf(calls[0].init, "Authorization")).toBe("Bearer lumora-jwt");
  });

  it("does not send the token when auth is disabled", async () => {
    setAccessToken("lumora-jwt");
    const { calls } = mockBackend({ "/x": () => json(200, {}) });
    await apiFetch("/x", { auth: false });
    expect(headerOf(calls[0].init, "Authorization")).toBeUndefined();
  });

  it("clears the session and notifies on a 401 for an authenticated request", async () => {
    setAccessToken("expired");
    const onUnauthorized = vi.fn();
    setUnauthorizedHandler(onUnauthorized);
    mockBackend({
      "/api/v1/auth/me": () => apiError(401, "UNAUTHORIZED", "Invalid or expired authentication token"),
    });
    await expect(apiFetch("/api/v1/auth/me")).rejects.toMatchObject({ status: 401, code: "UNAUTHORIZED" });
    expect(getAccessToken()).toBeNull();
    expect(onUnauthorized).toHaveBeenCalledOnce();
  });

  it("does not treat a failed Google login (401) as an expired session", async () => {
    setAccessToken("still-valid");
    const onUnauthorized = vi.fn();
    setUnauthorizedHandler(onUnauthorized);
    mockBackend({
      "/api/v1/auth/google": () => apiError(401, "INVALID_GOOGLE_TOKEN", "Google authentication failed"),
    });
    await expect(apiFetch("/api/v1/auth/google", { method: "POST", body: {}, auth: false })).rejects.toMatchObject({
      code: "INVALID_GOOGLE_TOKEN",
    });
    expect(getAccessToken()).toBe("still-valid");
    expect(onUnauthorized).not.toHaveBeenCalled();
  });

  it("ignores a late 401 from a request made with an older token", async () => {
    setAccessToken("old-token");
    const onUnauthorized = vi.fn();
    setUnauthorizedHandler(onUnauthorized);
    mockBackend({
      "/slow": () => {
        setAccessToken("new-token"); // user signed in again while the request was in flight
        return apiError(401, "UNAUTHORIZED", "expired");
      },
    });
    await expect(apiFetch("/slow")).rejects.toBeInstanceOf(ApiError);
    expect(getAccessToken()).toBe("new-token");
    expect(onUnauthorized).not.toHaveBeenCalled();
  });

  it("maps network failures to NETWORK_ERROR without touching the session", async () => {
    setAccessToken("t");
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    await expect(apiFetch("/x")).rejects.toMatchObject({ status: 0, code: "NETWORK_ERROR" });
    expect(getAccessToken()).toBe("t");
  });

  it("handles non-JSON error bodies", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("<html>bad gateway</html>", { status: 502 })));
    await expect(apiFetch("/x")).rejects.toMatchObject({ status: 502, code: "UNEXPECTED_RESPONSE" });
  });

  it("reports a clear configuration error when the API base URL is missing", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "");
    await expect(apiFetch("/x")).rejects.toMatchObject({ code: "CONFIG_ERROR" });
  });
});
