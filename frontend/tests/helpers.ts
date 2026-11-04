import { vi } from "vitest";

/** Build an unsigned JWT-shaped token with the given expiry (seconds since epoch). */
export function makeJwt(expSeconds: number): string {
  const encode = (value: object) =>
    btoa(JSON.stringify(value)).replace(/=+$/, "").replace(/\+/g, "-").replace(/\//g, "_");
  return `${encode({ alg: "HS256", typ: "JWT" })}.${encode({ sub: "user-1", type: "access", exp: expSeconds })}.sig`;
}

export const inMinutes = (minutes: number) => Math.floor(Date.now() / 1000) + minutes * 60;

export const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

/** Matches the backend's error envelope (backend/main.py exception handlers). */
export const apiError = (status: number, code: string, message: string) =>
  json(status, { success: false, error: { code, message } });

export const USER = {
  id: "11111111-1111-1111-1111-111111111111",
  email: "ada@example.com",
  name: "Ada Lovelace",
  picture_url: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

type Handler = (request: { url: string; init: RequestInit }) => Response | Promise<Response>;

/** Stub global fetch with per-path handlers; unknown paths fail the test. */
export function mockBackend(routes: Record<string, Handler>) {
  const calls: { path: string; init: RequestInit }[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = String(input);
    const path = new URL(url).pathname;
    calls.push({ path, init });
    const handler = routes[path];
    if (!handler) throw new Error(`Unexpected request to ${path}`);
    return handler({ url, init });
  });
  vi.stubGlobal("fetch", fetchMock);
  return { calls, fetchMock };
}

export const headerOf = (init: RequestInit, name: string) =>
  (init.headers as Record<string, string> | undefined)?.[name];
