import { vi } from "vitest";
import type { UserResponse, WorkspaceResponse } from "@/types/api";
import { apiError, json, USER } from "./helpers";

export const uuid = (n: number) => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;

export function workspace(n: number, name: string, userId = USER.id, createdAt?: string): WorkspaceResponse {
  return {
    id: uuid(n),
    user_id: userId,
    name,
    created_at: createdAt ?? `2026-10-${String(n).padStart(2, "0")}T10:00:00+00:00`,
  };
}

export interface Call {
  method: string;
  path: string;
  body: unknown;
  authorization?: string;
}

/**
 * In-memory stand-in for the FastAPI backend, mirroring the behaviour read from
 * backend/app/api/v1/workspace/router.py: owner-scoped queries, unordered list,
 * name stripped and limited to 1-100 characters (422 VALIDATION_ERROR), and 404
 * WORKSPACE_NOT_FOUND for missing or foreign workspaces. This is a mock, not the real server.
 */
export function createFakeBackend(options: {
  workspaces?: WorkspaceResponse[];
  /** Maps an access token to the user it belongs to. Default: any token is USER. */
  users?: Record<string, UserResponse>;
} = {}) {
  const state = {
    workspaces: [...(options.workspaces ?? [])],
    calls: [] as Call[],
    down: false,
    /** Return a Response to override the next matching request. */
    override: null as null | ((call: Call) => Response | null),
    nextId: 100,
  };

  const userFor = (authorization?: string): UserResponse | null => {
    const token = authorization?.replace(/^Bearer /, "");
    if (!token) return null;
    return options.users ? (options.users[token] ?? null) : USER;
  };

  const validName = (raw: unknown): string | null => {
    if (typeof raw !== "string") return null;
    const name = raw.trim();
    const length = [...name].length;
    return length >= 1 && length <= 100 ? name : null;
  };

  const handle = (call: Call): Response => {
    const forced = state.override?.(call);
    if (forced) return forced;

    const user = userFor(call.authorization);
    if (!user) return apiError(401, "UNAUTHORIZED", "Invalid or expired authentication token");

    if (call.path === "/api/v1/auth/me") return json(200, user);

    const mine = () => state.workspaces.filter((w) => w.user_id === user.id);
    const idMatch = call.path.match(/^\/api\/v1\/workspaces\/([^/]+)$/);

    if (call.path === "/api/v1/workspaces" && call.method === "GET") return json(200, mine());

    if (call.path === "/api/v1/workspaces" && call.method === "POST") {
      const name = validName((call.body as { name?: unknown })?.name);
      if (name === null) return apiError(422, "VALIDATION_ERROR", "Invalid request");
      const created = workspace(state.nextId++, name, user.id, new Date().toISOString());
      state.workspaces.push(created);
      return json(201, created);
    }

    if (idMatch) {
      const id = idMatch[1];
      const target = mine().find((w) => w.id === id);
      if (call.method === "PATCH") {
        const name = validName((call.body as { name?: unknown })?.name);
        if (name === null) return apiError(422, "VALIDATION_ERROR", "Invalid request");
        if (!target) return apiError(404, "WORKSPACE_NOT_FOUND", "Workspace not found");
        target.name = name;
        return json(200, target);
      }
      if (call.method === "DELETE") {
        if (!target) return apiError(404, "WORKSPACE_NOT_FOUND", "Workspace not found");
        state.workspaces = state.workspaces.filter((w) => w.id !== id);
        return json(200, { message: "Workspace deleted successfully" });
      }
    }

    throw new Error(`Unhandled request: ${call.method} ${call.path}`);
  };

  const fetchMock = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const path = new URL(String(input)).pathname;
    // "down" simulates an outage that starts after sign-in (restoring a session is tested separately).
    if (state.down && path !== "/api/v1/auth/me") throw new TypeError("Failed to fetch");
    const headers = (init.headers ?? {}) as Record<string, string>;
    const call: Call = {
      method: init.method ?? "GET",
      path,
      body: typeof init.body === "string" ? JSON.parse(init.body) : undefined,
      authorization: headers.Authorization,
    };
    state.calls.push(call);
    return handle(call);
  });
  vi.stubGlobal("fetch", fetchMock);

  return {
    state,
    callsTo: (method: string, path: string) =>
      state.calls.filter((c) => c.method === method && c.path === path),
  };
}
