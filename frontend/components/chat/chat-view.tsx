"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { FolderKanban, History, Plus, SearchX, TriangleAlert } from "lucide-react";
import { useChatSources, useConversation, useSendMessage, type SendVariables } from "@/hooks/use-chat";
import { useActiveConversation } from "@/hooks/use-active-conversation";
import { useWorkspaceDocuments } from "@/hooks/use-documents";
import { useWorkspaces } from "@/hooks/use-workspaces";
import { ApiError } from "@/lib/api/client";
import { describeApiError } from "@/lib/api/errors";
import { buildThread } from "@/lib/chat";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { EmptyState } from "@/components/shared/empty-state";
import { PageHeader } from "@/components/shared/page-header";
import { ChatComposer } from "@/components/chat/chat-composer";
import { ConversationList } from "@/components/chat/conversation-list";
import { EmptyThread, MessageThread } from "@/components/chat/message-thread";
import { Skeleton } from "@/components/ui/skeleton";

export function ChatView() {
  const { conversationId, invalid, open } = useActiveConversation();
  const workspacesQuery = useWorkspaces();
  const workspaces = workspacesQuery.data ?? [];
  const conversation = useConversation(conversationId);
  const sourcesStore = useChatSources();
  const send = useSendMessage();

  const [workspaceChoice, setWorkspaceChoice] = useState<string | null>(null);
  const [documentChoice, setDocumentChoice] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [historyOpen, setHistoryOpen] = useState(false);

  // A single workspace is chosen for you; with several, the user must pick one.
  const workspaceId =
    (workspaceChoice && workspaces.some((w) => w.id === workspaceChoice) ? workspaceChoice : null) ??
    (workspaces.length === 1 ? workspaces[0].id : null);

  const documentsQuery = useWorkspaceDocuments(workspaceId ?? "", { enabled: workspaceId !== null });
  const indexedDocuments = documentsQuery.data?.filter((document) => document.status === "Indexed");
  const documentId = indexedDocuments?.some((d) => d.id === documentChoice) ? documentChoice : null;

  // Lets the "answer arrived" callback tell whether the user is still on the conversation it was asked in.
  const activeRef = useRef(conversationId);
  useEffect(() => {
    activeRef.current = conversationId;
  }, [conversationId]);

  const inThisConversation = (variables: { conversationId?: string | null } | undefined) =>
    (variables?.conversationId ?? null) === conversationId;
  const pendingQuery = send.isPending && inThisConversation(send.variables) ? send.variables.query : null;
  const failed =
    send.isError && inThisConversation(send.variables)
      ? { query: send.variables.query, message: describeApiError(send.error) }
      : null;

  /** Send a turn (also used by Retry) and follow a brand-new conversation, unless the user has moved on. */
  function sendTurn(variables: SendVariables) {
    send.mutate(variables, {
      onSuccess: (response) => {
        if (activeRef.current === variables.conversationId) open(response.conversation_id);
      },
    });
  }

  function submit(text: string) {
    if (!workspaceId || send.isPending) return;
    setDraft("");
    sendTurn({ query: text, workspaceId, conversationId, documentId });
  }

  function startNewConversation() {
    setHistoryOpen(false);
    if (!send.isPending) send.reset();
    open(null);
  }

  const messages = buildThread(conversation.data?.messages ?? [], conversationId ? sourcesStore[conversationId] : undefined);
  const notFound =
    invalid ||
    (conversation.isError && conversation.error instanceof ApiError && conversation.error.code === "CONVERSATION_NOT_FOUND");

  let thread: React.ReactNode;
  if (notFound) {
    thread = (
      <EmptyState
        icon={SearchX}
        title="Conversation not found"
        description="It may have been deleted, or it isn’t in your account."
        action={<Button onClick={startNewConversation}>Start a new conversation</Button>}
      />
    );
  } else if (conversationId && conversation.isError) {
    thread = (
      <EmptyState
        icon={TriangleAlert}
        title="Couldn’t load this conversation"
        description={describeApiError(conversation.error)}
        action={
          <Button onClick={() => void conversation.refetch()} loading={conversation.isFetching}>
            Try again
          </Button>
        }
      />
    );
  } else if (conversationId && conversation.isPending) {
    thread = (
      <div role="status" aria-label="Loading conversation" className="space-y-6">
        <Skeleton className="ml-auto h-10 w-2/3 rounded-2xl" />
        <Skeleton className="h-24 w-full rounded-xl" />
      </div>
    );
  } else if (workspacesQuery.isSuccess && workspaces.length === 0) {
    thread = (
      <EmptyState
        icon={FolderKanban}
        title="Create a workspace first"
        description="Chat answers come from documents inside a workspace. Create one and add documents to get started."
        action={
          <Button asChild>
            <Link href="/workspaces">Go to workspaces</Link>
          </Button>
        }
      />
    );
  } else if (messages.length === 0 && !pendingQuery && !failed) {
    thread = <EmptyThread />;
  } else {
    thread = (
      <MessageThread
        messages={messages}
        pendingQuery={pendingQuery}
        failed={failed}
        onRetry={() => send.variables && sendTurn(send.variables)}
        onDismissFailed={() => {
          if (send.variables) setDraft(send.variables.query);
          send.reset();
        }}
      />
    );
  }

  const list = (
    <ConversationList
      activeId={conversationId}
      onSelect={(id) => {
        setHistoryOpen(false);
        open(id);
      }}
      onActiveDeleted={() => open(null)}
    />
  );

  return (
    <>
      <PageHeader
        title="AI Chat"
        description="Ask questions and get answers drawn from your own documents."
        actions={
          <>
            <Button variant="outline" className="lg:hidden" onClick={() => setHistoryOpen(true)}>
              <History /> History
            </Button>
            <Button onClick={startNewConversation}>
              <Plus /> New conversation
            </Button>
          </>
        }
      />

      <div className="flex items-start gap-8">
        <aside aria-label="Conversation history" className="hidden w-72 shrink-0 lg:block">
          <h2 className="mb-3 text-[15px] font-semibold">Conversations</h2>
          {list}
        </aside>

        <section aria-label="Conversation" className="flex min-w-0 flex-1 flex-col gap-6">
          <div className="min-h-[40dvh]">{thread}</div>
          <div className="sticky bottom-0 -mx-1 bg-background px-1 pb-1 pt-2">
            <ChatComposer
              workspaces={workspaces}
              workspacesLoading={workspacesQuery.isPending}
              workspaceId={workspaceId}
              onWorkspaceChange={(id) => {
                setWorkspaceChoice(id);
                setDocumentChoice(null); // a document belongs to one workspace
              }}
              indexedDocuments={indexedDocuments}
              documentId={documentId}
              onDocumentChange={setDocumentChoice}
              draft={draft}
              onDraftChange={setDraft}
              onSubmit={submit}
              sending={send.isPending}
              blocked={conversationId !== null && (conversation.isPending || notFound || conversation.isError)}
            />
            {workspacesQuery.isError && !workspacesQuery.data && (
              <p role="alert" className="mt-2 text-xs text-destructive">
                {describeApiError(workspacesQuery.error)}{" "}
                <button type="button" className="font-medium underline" onClick={() => void workspacesQuery.refetch()}>
                  Retry
                </button>
              </p>
            )}
          </div>
        </section>
      </div>

      <Sheet open={historyOpen} onOpenChange={setHistoryOpen}>
        <SheetContent className="lg:hidden">
          <SheetTitle className="px-4 pt-4 text-[15px] font-semibold">Conversations</SheetTitle>
          <SheetDescription className="sr-only">Your previous conversations</SheetDescription>
          <div className="max-h-[calc(100dvh-4rem)] overflow-y-auto p-3">{list}</div>
        </SheetContent>
      </Sheet>
    </>
  );
}
