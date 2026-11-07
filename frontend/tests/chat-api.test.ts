import { describe, expect, it, vi } from "vitest";
import { setUnauthorizedHandler } from "@/lib/api/client";
import { deleteConversation, getConversation, listConversations, sendChatMessage } from "@/lib/api/chat";
import { getAccessToken, setAccessToken } from "@/lib/auth/session";
import { apiError } from "./helpers";
import { conversation, createFakeBackend, source, uuid, workspace } from "./fake-backend";

const seed = () => ({
  workspaces: [workspace(1, "Alpha"), workspace(2, "Beta", "someone-else")],
  conversations: [
    conversation(1, [["old question", "old answer"]], undefined, "2026-10-01T09:00:00+00:00"),
    conversation(3, [["new question", "new answer"]], undefined, "2026-10-03T09:00:00+00:00"),
    conversation(9, [["secret", "secret"]], "someone-else"),
  ],
});

describe("sendChatMessage", () => {
  it("posts the question and workspace with the Bearer token, omitting unset optional fields", async () => {
    setAccessToken("token-ada");
    const backend = createFakeBackend(seed());
    backend.state.chatAnswer = () => ({ answer: "42", sources: [source(1, "a.pdf", { score: 0.9 })] });

    const response = await sendChatMessage({ query: "What?", workspace_id: uuid(1) });

    const [call] = backend.callsTo("POST", "/api/v1/chat");
    expect(call.body).toEqual({ query: "What?", workspace_id: uuid(1) });
    expect(call.authorization).toBe("Bearer token-ada");
    expect(response.answer).toBe("42");
    expect(response.sources[0]).toMatchObject({ filename: "a.pdf", chunk_index: 1, score: 0.9 });
  });

  it("passes conversation_id and document_id when given", async () => {
    setAccessToken("token-ada");
    const backend = createFakeBackend(seed());
    await sendChatMessage({
      query: "Follow-up",
      workspace_id: uuid(1),
      conversation_id: uuid(8001),
      document_id: uuid(1001),
    });
    expect(backend.callsTo("POST", "/api/v1/chat")[0].body).toMatchObject({
      conversation_id: uuid(8001),
      document_id: uuid(1001),
    });
  });

  it("maps the backend's error codes", async () => {
    setAccessToken("token-ada");
    const backend = createFakeBackend(seed());
    await expect(sendChatMessage({ query: "q", workspace_id: uuid(2) })).rejects.toMatchObject({ status: 404, code: "WORKSPACE_NOT_FOUND" });
    await expect(sendChatMessage({ query: "q", workspace_id: uuid(1), conversation_id: uuid(8009) })).rejects.toMatchObject({ status: 404, code: "CONVERSATION_NOT_FOUND" });
    await expect(sendChatMessage({ query: "   ", workspace_id: uuid(1) })).rejects.toMatchObject({ status: 400, code: "INVALID_CHAT_REQUEST" });
    backend.state.override = (call) =>
      call.path === "/api/v1/chat" ? apiError(429, "TOO_MANY_REQUESTS", "The language model is temporarily rate-limited.") : null;
    await expect(sendChatMessage({ query: "q", workspace_id: uuid(1) })).rejects.toMatchObject({ status: 429, code: "TOO_MANY_REQUESTS" });
  });

  it("maps a network failure to NETWORK_ERROR without ending the session", async () => {
    setAccessToken("token-ada");
    const backend = createFakeBackend(seed());
    backend.state.down = true;
    await expect(sendChatMessage({ query: "q", workspace_id: uuid(1) })).rejects.toMatchObject({ status: 0, code: "NETWORK_ERROR" });
    expect(getAccessToken()).toBe("token-ada");
  });

  it("ends the session on a 401", async () => {
    setAccessToken("expired");
    createFakeBackend({ ...seed(), users: {} });
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    await expect(sendChatMessage({ query: "q", workspace_id: uuid(1) })).rejects.toMatchObject({ status: 401 });
    expect(getAccessToken()).toBeNull();
    expect(handler).toHaveBeenCalledOnce();
  });
});

describe("conversation endpoints", () => {
  it("lists only the user's conversations, newest first", async () => {
    setAccessToken("token-ada");
    createFakeBackend(seed());
    const list = await listConversations();
    expect(list.map((c) => c.id)).toEqual([uuid(8003), uuid(8001)]);
    expect(list[0]).toEqual({ id: uuid(8003), title: null, created_at: "2026-10-03T09:00:00+00:00" });
  });

  it("loads one conversation with its messages in order", async () => {
    setAccessToken("token-ada");
    createFakeBackend(seed());
    const detail = await getConversation(uuid(8003));
    expect(detail.messages.map((m) => [m.role, m.content])).toEqual([
      ["user", "new question"],
      ["assistant", "new answer"],
    ]);
  });

  it("treats another user's conversation exactly like a missing one", async () => {
    setAccessToken("token-ada");
    createFakeBackend(seed());
    await expect(getConversation(uuid(8009))).rejects.toMatchObject({ status: 404, code: "CONVERSATION_NOT_FOUND" });
    await expect(deleteConversation(uuid(8009))).rejects.toMatchObject({ status: 404, code: "CONVERSATION_NOT_FOUND" });
  });

  it("deletes with DELETE and accepts the empty 204 response", async () => {
    setAccessToken("token-ada");
    const backend = createFakeBackend(seed());
    await expect(deleteConversation(uuid(8001))).resolves.toBeUndefined();
    expect(backend.callsTo("DELETE", `/api/v1/chat/${uuid(8001)}`)).toHaveLength(1);
    expect(backend.state.conversations.some((c) => c.id === uuid(8001))).toBe(false);
  });

  it("is rejected without a session", async () => {
    setAccessToken("");
    createFakeBackend({ ...seed(), users: {} });
    await expect(listConversations()).rejects.toMatchObject({ status: 401 });
  });
});
