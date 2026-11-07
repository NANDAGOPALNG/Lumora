"use client";

import { useEffect, useRef } from "react";
import Link from "next/link";
import { SendHorizontal } from "lucide-react";
import type { DocumentResponse, WorkspaceResponse } from "@/types/api";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";

interface ChatComposerProps {
  workspaces: WorkspaceResponse[];
  workspacesLoading: boolean;
  workspaceId: string | null;
  onWorkspaceChange: (workspaceId: string | null) => void;
  /** Only indexed documents can be searched, so only those are offered. */
  indexedDocuments: DocumentResponse[] | undefined;
  documentId: string | null;
  onDocumentChange: (documentId: string | null) => void;
  draft: string;
  onDraftChange: (draft: string) => void;
  onSubmit: (text: string) => void;
  sending: boolean;
  /** True while the conversation being continued is still loading. */
  blocked: boolean;
}

const MAX_TEXTAREA_HEIGHT = 200;

export function ChatComposer({
  workspaces,
  workspacesLoading,
  workspaceId,
  onWorkspaceChange,
  indexedDocuments,
  documentId,
  onDocumentChange,
  draft,
  onDraftChange,
  onSubmit,
  sending,
  blocked,
}: ChatComposerProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const trimmed = draft.trim();
  const canSend = workspaceId !== null && trimmed.length > 0 && !sending && !blocked;

  // Grow with the text, up to a cap.
  useEffect(() => {
    const element = textareaRef.current;
    if (!element) return;
    element.style.height = "auto";
    element.style.height = `${Math.min(element.scrollHeight, MAX_TEXTAREA_HEIGHT)}px`;
  }, [draft]);

  function submit() {
    if (canSend) onSubmit(trimmed);
  }

  const noIndexedDocuments = workspaceId !== null && indexedDocuments !== undefined && indexedDocuments.length === 0;

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
      className="space-y-3 rounded-2xl border bg-card p-3 shadow-sm shadow-black/5"
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="grid gap-1">
          <label htmlFor="chat-workspace" className="text-xs font-medium text-muted-foreground">
            Workspace
          </label>
          <Select
            id="chat-workspace"
            value={workspaceId ?? ""}
            disabled={workspacesLoading || workspaces.length === 0}
            onChange={(event) => onWorkspaceChange(event.target.value || null)}
          >
            {workspaceId === null && <option value="">Choose a workspace…</option>}
            {workspaces.map((workspace) => (
              <option key={workspace.id} value={workspace.id}>
                {workspace.name}
              </option>
            ))}
          </Select>
        </div>
        <div className="grid gap-1">
          <label htmlFor="chat-document" className="text-xs font-medium text-muted-foreground">
            Document
          </label>
          <Select
            id="chat-document"
            value={documentId ?? ""}
            disabled={workspaceId === null || indexedDocuments === undefined}
            onChange={(event) => onDocumentChange(event.target.value || null)}
          >
            <option value="">All indexed documents</option>
            {(indexedDocuments ?? []).map((document) => (
              <option key={document.id} value={document.id}>
                {document.filename}
              </option>
            ))}
          </Select>
        </div>
      </div>

      {noIndexedDocuments && (
        <p className="text-xs text-muted-foreground">
          This workspace has no indexed documents yet, so answers won’t cite any sources.{" "}
          <Link href={`/workspaces/${workspaceId}`} className="font-medium text-foreground underline-offset-2 hover:underline">
            Add documents
          </Link>
        </p>
      )}

      <div className="flex items-end gap-2">
        <label htmlFor="chat-message" className="sr-only">
          Your question
        </label>
        <Textarea
          id="chat-message"
          ref={textareaRef}
          rows={1}
          value={draft}
          disabled={workspaceId === null || sending || blocked}
          placeholder={workspaceId === null ? "Choose a workspace to ask about…" : "Ask a question about your documents…"}
          onChange={(event) => onDraftChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault();
              submit();
            }
          }}
        />
        <Button type="submit" size="icon" aria-label="Send message" loading={sending} disabled={!canSend}>
          {!sending && <SendHorizontal />}
        </Button>
      </div>
      <p className="text-xs text-muted-foreground">Enter to send · Shift+Enter for a new line</p>
    </form>
  );
}
