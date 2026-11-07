import { vi } from "vitest";
import type {
  ChatMessage,
  DocumentResponse,
  DocumentStatus,
  SearchSource,
  UserResponse,
  WorkspaceResponse,
} from "@/types/api";
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

export function document(
  n: number,
  workspaceN: number,
  filename: string,
  status: DocumentStatus = "Indexed",
  overrides: Partial<DocumentResponse> = {},
): DocumentResponse {
  return {
    id: uuid(1000 + n),
    workspace_id: uuid(workspaceN),
    filename,
    file_type: filename.split(".").pop() ?? "txt",
    file_size: 2048,
    status,
    chunk_count: status === "Indexed" ? 3 : 0,
    uploaded_at: `2026-10-${String(n).padStart(2, "0")}T12:00:00+00:00`,
    ...overrides,
  };
}

export function source(n: number, filename: string, overrides: Partial<SearchSource> = {}): SearchSource {
  return {
    chunk_id: uuid(7000 + n),
    document_id: uuid(1000 + n),
    filename,
    source: filename.split(".").pop() ?? "txt",
    chunk_index: n,
    score: 0.5,
    content: `Excerpt from ${filename}`,
    ...overrides,
  };
}

export interface SeedConversation {
  id: string;
  user_id: string;
  title: string | null;
  created_at: string;
  messages: ChatMessage[];
}

export function conversation(
  n: number,
  turns: Array<[question: string, answer: string]>,
  userId = USER.id,
  createdAt?: string,
): SeedConversation {
  const created = createdAt ?? `2026-10-${String(n).padStart(2, "0")}T09:00:00+00:00`;
  return {
    id: uuid(8000 + n),
    user_id: userId,
    title: null,
    created_at: created,
    messages: turns.flatMap(([question, answer], index) => [
      { id: uuid(9000 + n * 100 + index * 2), role: "user", content: question, created_at: created },
      { id: uuid(9000 + n * 100 + index * 2 + 1), role: "assistant", content: answer, created_at: created },
    ]),
  };
}

export interface Call {
  method: string;
  path: string;
  query: URLSearchParams;
  body: unknown;
  /** Multipart body, for uploads. */
  form?: FormData;
  authorization?: string;
  headers: Record<string, string>;
}

const ALLOWED_TYPES = ["pdf", "docx", "txt", "md"];

/**
 * In-memory stand-in for the FastAPI backend, mirroring behaviour read from the real routers
 * (workspace and document): owner-scoped queries, unordered lists, name rules, 404 for missing or
 * foreign resources, upload validation order (workspace, type, size), and reindex that completes
 * inside the request. This is a mock, not the real server.
 */
export function createFakeBackend(options: {
  workspaces?: WorkspaceResponse[];
  documents?: DocumentResponse[];
  conversations?: SeedConversation[];
  /** Maps an access token to the user it belongs to. Default: any token is USER. */
  users?: Record<string, UserResponse>;
} = {}) {
  const state = {
    workspaces: [...(options.workspaces ?? [])],
    documents: [...(options.documents ?? [])],
    conversations: [...(options.conversations ?? [])],
    calls: [] as Call[],
    down: false,
    maxUploadBytes: 20 * 1024 * 1024,
    /** Document ids whose reindex should fail with 422 INGESTION_FAILED. */
    failReindex: new Set<string>(),
    /** Awaited before a reindex / upload completes, so tests can observe in-flight states. */
    reindexGate: null as null | (() => Promise<void>),
    uploadGate: null as null | (() => Promise<void>),
    /** A Processing document becomes Indexed after this many list requests. */
    indexedAfterListCalls: {} as Record<string, number>,
    /** Return a Response to override the next matching request. */
    override: null as null | ((call: Call) => Response | null),
    nextId: 100,
    nextDocId: 5000,
    /** Held before a chat answer is returned, so tests can observe the in-flight state. */
    chatGate: null as null | (() => Promise<void>),
    /** Produces the answer (and sources) for a chat request. */
    chatAnswer: ((query: string): { answer: string; sources: SearchSource[] } => ({
      answer: `Answer to: ${query}`,
      sources: [],
    })) as (query: string, body: Record<string, unknown>) => { answer: string; sources: SearchSource[] },
    /** Held before a search returns, so tests can observe the in-flight state. */
    searchGate: null as null | (() => Promise<void>),
    /** Produces the passages for a search request. */
    searchResults: ((): SearchSource[] => [
      source(1, "alpha.pdf", { chunk_index: 2, score: 0.8731, content: "Alpha passage about authentication." }),
      source(2, "beta.md", { chunk_index: 0, score: 0.4123, content: "Beta passage." }),
    ]) as (body: Record<string, unknown>) => SearchSource[],
    nextConversationId: 8500,
    nextMessageId: 20000,
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

  const handle = async (call: Call): Promise<Response> => {
    const forced = state.override?.(call);
    if (forced) return forced;

    const user = userFor(call.authorization);
    if (!user) return apiError(401, "UNAUTHORIZED", "Invalid or expired authentication token");

    if (call.path === "/api/v1/auth/me") return json(200, user);

    const mine = () => state.workspaces.filter((w) => w.user_id === user.id);
    const ownsWorkspace = (id: string) => mine().some((w) => w.id === id);
    const ownedDocument = (id: string) =>
      state.documents.find((d) => d.id === id && ownsWorkspace(d.workspace_id));
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
        state.documents = state.documents.filter((d) => d.workspace_id !== id);
        return json(200, { message: "Workspace deleted successfully" });
      }
    }

    // ---- documents ----
    if (call.path === "/api/v1/documents" && call.method === "GET") {
      const workspaceId = call.query.get("workspace_id") ?? "";
      if (!ownsWorkspace(workspaceId)) return apiError(404, "WORKSPACE_NOT_FOUND", "Workspace not found");
      const listed = state.documents.filter((d) => d.workspace_id === workspaceId);
      const snapshot = listed.map((d) => ({ ...d })); // what this request sees
      for (const d of listed) {
        const remaining = state.indexedAfterListCalls[d.id];
        if (d.status === "Processing" && remaining !== undefined) {
          if (remaining <= 1) {
            d.status = "Indexed";
            d.chunk_count = 5;
            delete state.indexedAfterListCalls[d.id];
          } else {
            state.indexedAfterListCalls[d.id] = remaining - 1;
          }
        }
      }
      return json(200, snapshot);
    }

    if (call.path === "/api/v1/documents/upload" && call.method === "POST") {
      const workspaceId = String(call.form?.get("workspace_id") ?? "");
      const file = call.form?.get("file");
      if (!ownsWorkspace(workspaceId)) return apiError(404, "WORKSPACE_NOT_FOUND", "Workspace not found");
      if (!(file instanceof File)) return apiError(422, "VALIDATION_ERROR", "Invalid request");
      const extension = file.name.includes(".") ? file.name.split(".").pop()!.toLowerCase() : "";
      if (!ALLOWED_TYPES.includes(extension)) {
        return apiError(415, "UNSUPPORTED_FILE_TYPE", `Unsupported file extension: .${extension}`);
      }
      if (file.size > state.maxUploadBytes) {
        return apiError(
          413,
          "FILE_TOO_LARGE",
          `File exceeds the maximum allowed size of ${state.maxUploadBytes} bytes`,
        );
      }
      const created: DocumentResponse = {
        id: uuid(state.nextDocId++),
        workspace_id: workspaceId,
        filename: file.name,
        file_type: extension,
        file_size: file.size,
        status: "Uploaded",
        chunk_count: 0,
        uploaded_at: new Date().toISOString(),
      };
      state.documents.push(created);
      return json(201, created);
    }

    const docMatch = call.path.match(/^\/api\/v1\/documents\/([^/]+)(\/reindex)?$/);
    if (docMatch) {
      const target = ownedDocument(docMatch[1]);
      if (!target) return apiError(404, "DOCUMENT_NOT_FOUND", "Document not found");
      if (docMatch[2] && call.method === "POST") {
        await state.reindexGate?.();
        if (state.failReindex.has(target.id)) {
          target.status = "Failed";
          return apiError(422, "INGESTION_FAILED", "Document processing failed");
        }
        target.status = "Indexed";
        target.chunk_count = 3;
        return json(200, target);
      }
      if (!docMatch[2] && call.method === "GET") return json(200, target);
      if (!docMatch[2] && call.method === "DELETE") {
        state.documents = state.documents.filter((d) => d.id !== target.id);
        return json(200, { message: "Document deleted successfully" });
      }
    }

    // ---- search ----
    if (call.path === "/api/v1/search" && call.method === "POST") {
      const body = (call.body ?? {}) as Record<string, unknown>;
      if (!ownsWorkspace(String(body.workspace_id))) {
        return apiError(404, "WORKSPACE_NOT_FOUND", "Workspace not found");
      }
      const topK = body.top_k === undefined ? 5 : body.top_k;
      if (typeof topK !== "number" || !Number.isInteger(topK) || topK < 1 || topK > 50) {
        return apiError(422, "VALIDATION_ERROR", "Invalid request");
      }
      if (typeof body.query !== "string" || !body.query.trim()) {
        return apiError(400, "INVALID_SEARCH_REQUEST", "query must be a non-empty string");
      }
      await state.searchGate?.();
      let sources = state.searchResults(body);
      if (typeof body.document_id === "string") {
        sources = sources.filter((s) => s.document_id === body.document_id);
      }
      return json(200, {
        query: body.query.trim().replace(/\s+/g, " "),
        context: "[1] assembled context text",
        sources: sources.slice(0, topK),
      });
    }

    // ---- chat ----
    const mineConversations = () => state.conversations.filter((c) => c.user_id === user.id);
    const chatMatch = call.path.match(/^\/api\/v1\/chat\/([^/]+)$/);

    if (call.path === "/api/v1/chat" && call.method === "POST") {
      const body = (call.body ?? {}) as Record<string, unknown>;
      if (!ownsWorkspace(String(body.workspace_id))) {
        return apiError(404, "WORKSPACE_NOT_FOUND", "Workspace not found");
      }
      let target = body.conversation_id
        ? mineConversations().find((c) => c.id === body.conversation_id)
        : undefined;
      if (body.conversation_id && !target) {
        return apiError(404, "CONVERSATION_NOT_FOUND", "Conversation not found");
      }
      if (typeof body.query !== "string" || !body.query.trim()) {
        return apiError(400, "INVALID_CHAT_REQUEST", "query must be a non-empty string");
      }
      await state.chatGate?.();
      const query = body.query.trim();
      const { answer, sources } = state.chatAnswer(query, body);
      if (!target) {
        target = {
          id: uuid(state.nextConversationId++),
          user_id: user.id,
          title: null,
          created_at: new Date().toISOString(),
          messages: [],
        };
        state.conversations.push(target);
      }
      const now = new Date().toISOString();
      target.messages.push(
        { id: uuid(state.nextMessageId++), role: "user", content: query, created_at: now },
        { id: uuid(state.nextMessageId++), role: "assistant", content: answer, created_at: now },
      );
      return json(200, { answer, query: query.toLowerCase(), conversation_id: target.id, sources });
    }

    if (call.path === "/api/v1/chat/history" && call.method === "GET") {
      return json(
        200,
        [...mineConversations()]
          .sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at))
          .map(({ id, title, created_at }) => ({ id, title, created_at })),
      );
    }

    if (chatMatch) {
      const found = mineConversations().find((c) => c.id === chatMatch[1]);
      if (!found) return apiError(404, "CONVERSATION_NOT_FOUND", "Conversation not found");
      if (call.method === "GET") {
        return json(200, { id: found.id, title: found.title, created_at: found.created_at, messages: found.messages });
      }
      if (call.method === "DELETE") {
        state.conversations = state.conversations.filter((c) => c.id !== found.id);
        return new Response(null, { status: 204 }); // the real endpoint returns no body
      }
    }

    throw new Error(`Unhandled request: ${call.method} ${call.path}`);
  };

  const buildCall = (
    method: string,
    rawUrl: string,
    headers: Record<string, string>,
    extra: { body?: unknown; form?: FormData } = {},
  ): Call => {
    const url = new URL(rawUrl);
    return {
      method,
      path: url.pathname,
      query: url.searchParams,
      body: extra.body,
      form: extra.form,
      authorization: headers.Authorization,
      headers,
    };
  };

  const fetchMock = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const path = new URL(String(input)).pathname;
    // "down" simulates an outage that starts after sign-in (restoring a session is tested separately).
    if (state.down && path !== "/api/v1/auth/me") throw new TypeError("Failed to fetch");
    const call = buildCall(init.method ?? "GET", String(input), (init.headers ?? {}) as Record<string, string>, {
      body: typeof init.body === "string" ? JSON.parse(init.body) : undefined,
    });
    state.calls.push(call);
    return handle(call);
  });
  vi.stubGlobal("fetch", fetchMock);

  /** Minimal XMLHttpRequest that routes uploads into the fake backend and reports progress. */
  class FakeXhr {
    upload: { onprogress: ((event: { lengthComputable: boolean; loaded: number; total: number }) => void) | null } = {
      onprogress: null,
    };
    onload: (() => void) | null = null;
    onerror: (() => void) | null = null;
    onabort: (() => void) | null = null;
    status = 0;
    responseText = "";
    private method = "GET";
    private url = "";
    private headers: Record<string, string> = {};
    private aborted = false;

    open(method: string, url: string) {
      this.method = method;
      this.url = url;
    }
    setRequestHeader(name: string, value: string) {
      this.headers[name] = value;
    }
    abort() {
      this.aborted = true;
      this.onabort?.();
    }
    send(form: FormData) {
      void this.run(form);
    }
    private async run(form: FormData) {
      const call = buildCall(this.method, this.url, this.headers, { form });
      state.calls.push(call);
      if (state.down) {
        this.onerror?.();
        return;
      }
      await state.uploadGate?.();
      if (this.aborted) return;
      const file = form.get("file");
      const total = file instanceof File ? Math.max(file.size, 2) : 2;
      this.upload.onprogress?.({ lengthComputable: true, loaded: Math.floor(total / 2), total });
      this.upload.onprogress?.({ lengthComputable: true, loaded: total, total });
      const response = await handle(call);
      if (this.aborted) return;
      this.status = response.status;
      this.responseText = await response.text();
      this.onload?.();
    }
  }
  vi.stubGlobal("XMLHttpRequest", FakeXhr);

  return {
    state,
    callsTo: (method: string, path: string) =>
      state.calls.filter((c) => c.method === method && c.path === path),
  };
}
