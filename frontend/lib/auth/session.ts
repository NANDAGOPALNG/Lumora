/**
 * Client-side session storage for the Lumora access token.
 *
 * Only the access token is stored (never the Google ID token or the user
 * profile; the profile is always re-fetched from /auth/me). sessionStorage
 * keeps the session across page refreshes but drops it when the tab closes.
 * Like any browser storage it is readable by injected scripts, so the token
 * is short-lived by design (30 min, no refresh) and the backend remains the
 * authority on validity.
 */

const STORAGE_KEY = "lumora:access-token";

// Fallback so the session still works for this page load if storage throws.
let memoryToken: string | null = null;

/**
 * Read the `exp` claim (ms since epoch) without verifying the signature.
 * Used only to schedule a clean logout and skip pointless requests; it is a
 * convenience, never a trust decision.
 */
export function getTokenExpiryMs(token: string): number | null {
  try {
    const payload = token.split(".")[1];
    if (!payload) return null;
    const json = atob(payload.replace(/-/g, "+").replace(/_/g, "/"));
    const exp = (JSON.parse(json) as { exp?: unknown }).exp;
    return typeof exp === "number" ? exp * 1000 : null;
  } catch {
    return null;
  }
}

export function isTokenExpired(token: string, now = Date.now()): boolean {
  const expiry = getTokenExpiryMs(token);
  return expiry !== null && expiry <= now;
}

export function getAccessToken(): string | null {
  if (memoryToken) return memoryToken;
  try {
    memoryToken = window.sessionStorage.getItem(STORAGE_KEY);
  } catch {
    memoryToken = null;
  }
  return memoryToken;
}

export function setAccessToken(token: string): void {
  memoryToken = token;
  try {
    window.sessionStorage.setItem(STORAGE_KEY, token);
  } catch {
    // Storage unavailable: keep the in-memory copy only.
  }
}

export function clearAccessToken(): void {
  memoryToken = null;
  try {
    window.sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    // Nothing to clear.
  }
}
