"use client";

import { useEffect, useRef } from "react";
import { MessageSquareText, RotateCcw, TriangleAlert } from "lucide-react";
import type { ThreadMessage } from "@/lib/chat";
import { Button } from "@/components/ui/button";
import { AssistantShell, MessageBubble, UserMessage } from "@/components/chat/message-bubble";

interface MessageThreadProps {
  messages: ThreadMessage[];
  /** The question currently awaiting an answer. */
  pendingQuery: string | null;
  /** A question whose answer failed, with a message. Nothing was saved on the server. */
  failed: { query: string; message: string } | null;
  onRetry: () => void;
  onDismissFailed: () => void;
}

export function MessageThread({ messages, pendingQuery, failed, onRetry, onDismissFailed }: MessageThreadProps) {
  const endRef = useRef<HTMLDivElement>(null);
  const turnCount = messages.length + (pendingQuery ? 1 : 0) + (failed ? 1 : 0);

  useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: "end" });
  }, [turnCount]);

  const lacksSources = messages.some((message) => message.role === "assistant" && !message.sources);

  return (
    <div className="space-y-6">
      {lacksSources && (
        <p className="rounded-lg bg-secondary px-3 py-2 text-xs text-muted-foreground">
          Sources are only shown for answers received in this session. Lumora doesn’t store them with past
          conversations.
        </p>
      )}

      {messages.map((message) => (
        <MessageBubble key={message.id} message={message} />
      ))}

      {pendingQuery && (
        <>
          <UserMessage text={pendingQuery} />
          <AssistantShell>
            <p role="status" className="flex items-center gap-1.5 text-sm text-muted-foreground">
              Searching your documents and writing an answer
              <span className="flex gap-0.5" aria-hidden>
                <span className="size-1 animate-pulse rounded-full bg-muted-foreground" />
                <span className="size-1 animate-pulse rounded-full bg-muted-foreground [animation-delay:150ms]" />
                <span className="size-1 animate-pulse rounded-full bg-muted-foreground [animation-delay:300ms]" />
              </span>
            </p>
          </AssistantShell>
        </>
      )}

      {failed && (
        <>
          <UserMessage text={failed.query} />
          <div
            role="alert"
            className="flex flex-col gap-3 rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm sm:flex-row sm:items-center sm:justify-between"
          >
            <div className="flex gap-3">
              <TriangleAlert className="mt-0.5 size-4 shrink-0 text-destructive" aria-hidden />
              <div className="space-y-1">
                <p>{failed.message}</p>
                <p className="text-xs text-muted-foreground">Nothing was saved, so retrying won’t duplicate your question.</p>
              </div>
            </div>
            <div className="flex shrink-0 gap-2">
              <Button size="sm" onClick={onRetry}>
                <RotateCcw /> Retry
              </Button>
              <Button size="sm" variant="outline" onClick={onDismissFailed}>
                Edit message
              </Button>
            </div>
          </div>
        </>
      )}
      <div ref={endRef} />
    </div>
  );
}

export function EmptyThread({ children }: { children?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center rounded-xl border border-dashed px-6 py-14 text-center">
      <span className="mb-4 flex size-10 items-center justify-center rounded-lg bg-secondary text-muted-foreground">
        <MessageSquareText className="size-5" aria-hidden />
      </span>
      <h2 className="text-[15px] font-semibold">Ask your documents</h2>
      <p className="mt-1.5 max-w-sm text-sm leading-relaxed text-muted-foreground">
        Pick a workspace below and ask a question. Answers come from your indexed documents, with the sources
        they used.
      </p>
      {children}
    </div>
  );
}
