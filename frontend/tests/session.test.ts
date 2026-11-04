import { describe, expect, it } from "vitest";
import {
  clearAccessToken,
  getAccessToken,
  getTokenExpiryMs,
  isTokenExpired,
  setAccessToken,
} from "@/lib/auth/session";
import { inMinutes, makeJwt } from "./helpers";

describe("session storage", () => {
  it("stores the token in sessionStorage (not localStorage) and clears it", () => {
    setAccessToken("abc");
    expect(window.sessionStorage.getItem("lumora:access-token")).toBe("abc");
    expect(window.localStorage.length).toBe(0);
    expect(getAccessToken()).toBe("abc");
    clearAccessToken();
    expect(getAccessToken()).toBeNull();
    expect(window.sessionStorage.length).toBe(0);
  });

  it("reads the expiry claim and detects expired tokens", () => {
    const future = makeJwt(inMinutes(5));
    const past = makeJwt(inMinutes(-5));
    expect(getTokenExpiryMs(future)).toBeGreaterThan(Date.now());
    expect(isTokenExpired(future)).toBe(false);
    expect(isTokenExpired(past)).toBe(true);
  });

  it("treats tokens without a readable expiry as not expired (backend decides)", () => {
    expect(getTokenExpiryMs("not-a-jwt")).toBeNull();
    expect(isTokenExpired("not-a-jwt")).toBe(false);
  });
});
