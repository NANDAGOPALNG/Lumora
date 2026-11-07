"use client";

import { useMutation, useQueries, useQuery, useQueryClient, type QueryClient, type QueryKey } from "@tanstack/react-query";
import type { ChatResponse, ConversationDetail, ConversationSummary } from "@/types/api";
import { useAuth } from "@/hooks/use-auth";
import * as chatApi from "@/lib/api/chat";
import { ApiError } from "@/lib/api/client";
import { countAnswers, type SourcesByAnswer } from "@/lib/chat";

/** Keys include the user id so one user's chats are never shown to the next session. */
const historyKey = (userId: string | null): QueryKey => ["chat", "history", userId ?? "anonymous"];
const conversationKey = (userId: string | null, id: string): QueryKey => [
  "chat",
  "conversation",
  userId ?? "anonymous",
  id,
];
const sourcesKey = (userId: string | null): QueryKey => ["chat", "sources", userId ?? "anonymous"];

type SourcesStore = Record<string, SourcesByAnswer>;

function useSession() {
  const { user, status } = useAuth();
  return { userId: user?.id ?? null, signedIn: status === "authenticated" && user !== null };
}

export function useConversations() {
  const { userId, signedIn } = useSession();
  return useQuery({
    queryKey: historyKey(userId),
    queryFn: ({ signal }) => chatApi.listConversations(signal),
    enabled: signedIn,
  });
}

export function useConversation(conversationId: string | null) {
  const { userId, signedIn } = useSession();
  return useQuery({
    queryKey: conversationKey(userId, conversationId ?? ""),
    queryFn: ({ signal }) => chatApi.getConversation(conversationId!, signal),
    enabled: signedIn && conversationId !== null,
  });
}

/**
 * Already-loaded details for a list of conversations, without fetching anything: used to label
 * history rows by their first question when a conversation has been opened or created.
 */
export function useCachedConversations(conversationIds: string[]): Record<string, ConversationDetail | undefined> {
  const { userId } = useSession();
  const results = useQueries({
    queries: conversationIds.map((id) => ({
      queryKey: conversationKey(userId, id),
      queryFn: () => chatApi.getConversation(id),
      enabled: false,
    })),
  });
  return Object.fromEntries(conversationIds.map((id, index) => [id, results[index]?.data]));
}

/**
 * Sources returned with answers in this session. The backend doesn't persist them, so they live
 * in the query cache (surviving navigation inside the app, not a full page reload).
 */
export function useChatSources(): SourcesStore {
  const { userId } = useSession();
  const { data } = useQuery<SourcesStore>({
    queryKey: sourcesKey(userId),
    queryFn: async () => ({}),
    enabled: false,
    initialData: {},
    staleTime: Infinity,
    gcTime: Infinity,
  });
  return data;
}

export interface SendVariables {
  query: string;
  workspaceId: string;
  /** Omit/null to start a new conversation. */
  conversationId?: string | null;
  documentId?: string | null;
}

let localMessageCounter = 0;
const localId = (kind: string) => `local-${kind}-${Date.now()}-${localMessageCounter++}`;

/** Fold a successful answer into the caches so the thread and history update without refetching. */
function recordTurn(
  client: QueryClient,
  userId: string | null,
  variables: SendVariables,
  response: ChatResponse,
) {
  const now = new Date().toISOString();
  const key = conversationKey(userId, response.conversation_id);
  const existing = client.getQueryData<ConversationDetail>(key);

  if (variables.conversationId && !existing) {
    // We don't hold this conversation's messages, so don't fabricate a partial thread.
    void client.invalidateQueries({ queryKey: key });
  } else {
    const turn = [
      { id: localId("user"), role: "user", content: variables.query.trim(), created_at: now },
      { id: localId("assistant"), role: "assistant", content: response.answer, created_at: now },
    ];
    const answerOrdinal = existing ? countAnswers(existing.messages) : 0;
    client.setQueryData<ConversationDetail>(key, {
      id: response.conversation_id,
      title: existing?.title ?? null,
      created_at: existing?.created_at ?? now,
      messages: [...(existing?.messages ?? []), ...turn],
    });
    client.setQueryData<SourcesStore>(sourcesKey(userId), (old = {}) => ({
      ...old,
      [response.conversation_id]: { ...old[response.conversation_id], [answerOrdinal]: response.sources },
    }));
  }

  const history = client.getQueryData<ConversationSummary[]>(historyKey(userId));
  if (!history) void client.invalidateQueries({ queryKey: historyKey(userId) });
  else if (!history.some((c) => c.id === response.conversation_id)) {
    client.setQueryData<ConversationSummary[]>(historyKey(userId), [
      { id: response.conversation_id, title: null, created_at: now },
      ...history,
    ]);
  }
}

export function useSendMessage() {
  const client = useQueryClient();
  const { userId } = useSession();
  return useMutation({
    mutationFn: (variables: SendVariables) =>
      chatApi.sendChatMessage({
        query: variables.query,
        workspace_id: variables.workspaceId,
        conversation_id: variables.conversationId ?? undefined,
        document_id: variables.documentId ?? undefined,
      }),
    onSuccess: (response, variables) => recordTurn(client, userId, variables, response),
    // A failed turn is rolled back by the server (nothing saved), but a vanished conversation
    // or workspace means our lists are stale.
    onError: (error) => {
      if (error instanceof ApiError && error.code === "CONVERSATION_NOT_FOUND") {
        void client.invalidateQueries({ queryKey: historyKey(userId) });
      }
    },
  });
}

export function useDeleteConversation() {
  const client = useQueryClient();
  const { userId } = useSession();
  return useMutation({
    mutationFn: (conversationId: string) => chatApi.deleteConversation(conversationId),
    onSuccess: (_result, conversationId) => {
      client.setQueryData<ConversationSummary[]>(historyKey(userId), (old) =>
        old?.filter((c) => c.id !== conversationId),
      );
      client.removeQueries({ queryKey: conversationKey(userId, conversationId) });
      client.setQueryData<SourcesStore>(sourcesKey(userId), (old = {}) => {
        const { [conversationId]: _removed, ...rest } = old;
        void _removed;
        return rest;
      });
    },
    onError: (error) => {
      if (error instanceof ApiError && error.code === "CONVERSATION_NOT_FOUND") {
        void client.invalidateQueries({ queryKey: historyKey(userId) });
      }
    },
  });
}
