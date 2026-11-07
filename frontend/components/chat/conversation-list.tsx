"use client";

import { useState } from "react";
import { MessageSquare, MoreHorizontal, Trash2, TriangleAlert } from "lucide-react";
import type { ConversationSummary } from "@/types/api";
import { useCachedConversations, useConversations } from "@/hooks/use-chat";
import { describeApiError } from "@/lib/api/errors";
import { conversationLabel } from "@/lib/chat";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Skeleton } from "@/components/ui/skeleton";
import { DeleteConversationDialog } from "@/components/chat/delete-conversation-dialog";
import { formatShortDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

interface ConversationListProps {
  activeId: string | null;
  onSelect: (conversationId: string) => void;
  /** Called after the active conversation has been deleted. */
  onActiveDeleted: () => void;
}

export function ConversationList({ activeId, onSelect, onActiveDeleted }: ConversationListProps) {
  const query = useConversations();
  const conversations = query.data ?? [];
  const details = useCachedConversations(conversations.map((c) => c.id));
  const [target, setTarget] = useState<ConversationSummary | null>(null);
  const [deleteOpen, setDeleteOpen] = useState(false);

  if (query.isError && !query.data) {
    return (
      <div className="space-y-3 rounded-xl border border-dashed p-4 text-center">
        <TriangleAlert className="mx-auto size-5 text-muted-foreground" aria-hidden />
        <p className="text-sm text-muted-foreground">{describeApiError(query.error)}</p>
        <Button size="sm" variant="outline" onClick={() => void query.refetch()} loading={query.isFetching}>
          Try again
        </Button>
      </div>
    );
  }

  if (!query.data) {
    return (
      <div role="status" aria-label="Loading conversations" className="space-y-2">
        {[0, 1, 2, 3].map((item) => (
          <Skeleton key={item} className="h-12 w-full rounded-lg" />
        ))}
      </div>
    );
  }

  if (conversations.length === 0) {
    return (
      <div className="rounded-xl border border-dashed p-4 text-center">
        <MessageSquare className="mx-auto mb-2 size-5 text-muted-foreground" aria-hidden />
        <p className="text-sm font-medium">No conversations yet</p>
        <p className="mt-1 text-xs text-muted-foreground">Your questions and answers will be listed here.</p>
      </div>
    );
  }

  const targetLabel = target ? conversationLabel(target, details[target.id]) : "";

  return (
    <>
      <ul aria-label="Conversations" className="space-y-1">
        {conversations.map((conversation) => {
          const label = conversationLabel(conversation, details[conversation.id]);
          const active = conversation.id === activeId;
          return (
            <li key={conversation.id} className="group relative">
              <button
                type="button"
                aria-current={active ? "true" : undefined}
                onClick={() => onSelect(conversation.id)}
                className={cn(
                  "flex w-full flex-col items-start gap-0.5 rounded-lg px-3 py-2 pr-10 text-left transition-colors hover:bg-accent/60",
                  active && "bg-accent",
                )}
              >
                <span className="w-full truncate text-sm font-medium" title={label}>
                  {label}
                </span>
                <span className="text-xs text-muted-foreground">
                  <time dateTime={conversation.created_at}>{formatShortDateTime(conversation.created_at)}</time>
                </span>
              </button>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    className="absolute right-1.5 top-2 opacity-0 transition-opacity focus-visible:opacity-100 group-hover:opacity-100 data-[state=open]:opacity-100 max-lg:opacity-100"
                    aria-label={`Actions for ${label}`}
                  >
                    <MoreHorizontal />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="w-40">
                  <DropdownMenuItem
                    className="text-destructive [&_svg]:text-destructive!"
                    onSelect={() => {
                      setTarget(conversation);
                      setDeleteOpen(true);
                    }}
                  >
                    <Trash2 /> Delete
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </li>
          );
        })}
      </ul>

      {target && (
        <DeleteConversationDialog
          conversationId={target.id}
          label={targetLabel}
          open={deleteOpen}
          onOpenChange={setDeleteOpen}
          onDeleted={target.id === activeId ? onActiveDeleted : undefined}
        />
      )}
    </>
  );
}
