"use client";

import { useState } from "react";
import type { ThreadMessage } from "@/lib/chat";
import { LogoMark } from "@/components/layout/logo";
import { MessageContent } from "@/components/chat/message-content";
import { SourceList } from "@/components/chat/source-list";

export function UserMessage({ text }: { text: string }) {
  return (
    <div className="flex justify-end">
      <p className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-secondary px-4 py-2.5 text-sm leading-relaxed [overflow-wrap:anywhere]">
        {text}
      </p>
    </div>
  );
}

export function AssistantShell({ children, label = "Lumora" }: { children: React.ReactNode; label?: string }) {
  return (
    <div className="flex gap-3">
      <LogoMark className="mt-0.5 size-6" />
      <div className="min-w-0 flex-1 space-y-3">
        <p className="text-xs font-medium text-muted-foreground">{label}</p>
        {children}
      </div>
    </div>
  );
}

export function MessageBubble({ message }: { message: ThreadMessage }) {
  const [sourcesOpen, setSourcesOpen] = useState(false);
  const [expanded, setExpanded] = useState<number[]>([]);

  if (message.role === "user") return <UserMessage text={message.content} />;

  const sources = message.sources;

  function toggleExcerpt(number: number) {
    setExpanded((current) =>
      current.includes(number) ? current.filter((n) => n !== number) : [...current, number],
    );
  }

  function cite(number: number) {
    setSourcesOpen(true);
    setExpanded((current) => (current.includes(number) ? current : [...current, number]));
    // Wait for the list to render before scrolling to the cited source.
    window.setTimeout(
      () => document.getElementById(`${message.id}-source-${number}`)?.scrollIntoView?.({ block: "nearest" }),
      0,
    );
  }

  return (
    <AssistantShell>
      <MessageContent text={message.content} sourceCount={sources?.length ?? 0} onCite={sources ? cite : undefined} />
      {sources && (
        <SourceList
          sources={sources}
          open={sourcesOpen}
          onOpenChange={setSourcesOpen}
          expanded={expanded}
          onToggleExcerpt={toggleExcerpt}
          idPrefix={message.id}
        />
      )}
    </AssistantShell>
  );
}
