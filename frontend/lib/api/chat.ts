import type {
  ChatRequest,
  ChatResponse,
  ConversationDetail,
  ConversationSummary,
} from "@/types/api";
import { apiFetch } from "@/lib/api/client";

const BASE = "/api/v1/chat";

/** Ask a question. The reply is a regular response (the backend doesn't stream). */
export function sendChatMessage(request: ChatRequest): Promise<ChatResponse> {
  return apiFetch<ChatResponse>(BASE, { method: "POST", body: request });
}

/** The user's conversations, newest first. They belong to the user, not to a workspace. */
export async function listConversations(signal?: AbortSignal): Promise<ConversationSummary[]> {
  const conversations = await apiFetch<ConversationSummary[]>(`${BASE}/history`, { signal });
  return [...conversations].sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at));
}

/** One conversation with its messages, oldest first. Messages carry no sources. */
export function getConversation(conversationId: string, signal?: AbortSignal): Promise<ConversationDetail> {
  return apiFetch<ConversationDetail>(`${BASE}/${encodeURIComponent(conversationId)}`, { signal });
}

/** Responds 204 with no body. */
export function deleteConversation(conversationId: string): Promise<void> {
  return apiFetch<void>(`${BASE}/${encodeURIComponent(conversationId)}`, { method: "DELETE" });
}
