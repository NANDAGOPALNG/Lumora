import type { ChatMessage, ConversationDetail, ConversationSummary, SearchSource } from "@/types/api";
import { formatShortDateTime } from "@/lib/format";

/** Sources received for one conversation, keyed by the ordinal of the assistant message (0 = first answer). */
export type SourcesByAnswer = Record<number, SearchSource[]>;

export interface ThreadMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  createdAt: string;
  /** Present only for answers received in this session; the backend doesn't store sources. */
  sources?: SearchSource[];
}

/** Attach locally known sources to the matching assistant messages (by answer order). */
export function buildThread(messages: ChatMessage[], sources: SourcesByAnswer = {}): ThreadMessage[] {
  let answerIndex = 0;
  return messages.map((message) => {
    if (message.role !== "assistant") {
      return { id: message.id, role: "user", content: message.content, createdAt: message.created_at };
    }
    const attached = sources[answerIndex];
    answerIndex += 1;
    return {
      id: message.id,
      role: "assistant",
      content: message.content,
      createdAt: message.created_at,
      ...(attached ? { sources: attached } : {}),
    };
  });
}

export function countAnswers(messages: ChatMessage[]): number {
  return messages.filter((message) => message.role === "assistant").length;
}

const PREVIEW_LENGTH = 60;

export function firstQuestion(detail: ConversationDetail | undefined): string | null {
  const text = detail?.messages.find((message) => message.role === "user")?.content.trim();
  if (!text) return null;
  return text.length > PREVIEW_LENGTH ? `${text.slice(0, PREVIEW_LENGTH).trimEnd()}…` : text;
}

/**
 * Titles are never set by the backend, so label a conversation by its first question when that
 * is known (it has been opened or created in this session), otherwise by when it started.
 */
export function conversationLabel(
  conversation: ConversationSummary,
  detail?: ConversationDetail,
): string {
  return (
    conversation.title?.trim() ||
    firstQuestion(detail) ||
    `Conversation · ${formatShortDateTime(conversation.created_at)}`
  );
}
