"use client";

import { useState } from "react";
import Link from "next/link";
import { FileText, MoreHorizontal, RefreshCw, Trash2 } from "lucide-react";
import { toast } from "sonner";
import type { DocumentResponse } from "@/types/api";
import { useReindexDocument, useReindexingIds } from "@/hooks/use-documents";
import { describeApiError } from "@/lib/api/errors";
import { formatDate } from "@/lib/format";
import { formatFileSize } from "@/lib/documents";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { DeleteDocumentDialog } from "@/components/documents/delete-document-dialog";
import { DocumentStatusBadge } from "@/components/documents/document-status-badge";

interface DocumentListProps {
  documents: DocumentResponse[];
  /** When given, each row shows which workspace the document belongs to. */
  workspaceNames?: Record<string, string>;
}

function indexLabel(document: DocumentResponse): string {
  if (document.status === "Uploaded") return "Index";
  if (document.status === "Failed") return "Retry indexing";
  return "Reindex";
}

export function DocumentList({ documents, workspaceNames }: DocumentListProps) {
  const reindex = useReindexDocument();
  const reindexingIds = useReindexingIds();
  // The target is kept after closing so the dialog keeps its content while it animates out.
  const [deleteTarget, setDeleteTarget] = useState<DocumentResponse | null>(null);
  const [deleteOpen, setDeleteOpen] = useState(false);

  function startReindex(document: DocumentResponse) {
    reindex.mutate(
      { id: document.id, workspaceId: document.workspace_id },
      {
        onSuccess: (updated) =>
          toast.success(`“${updated.filename}” indexed (${updated.chunk_count} chunks)`),
        onError: (error) => toast.error(describeApiError(error)),
      },
    );
  }

  return (
    <>
      <ul aria-label="Documents" className="divide-y overflow-hidden rounded-xl border bg-card">
        {documents.map((document) => {
          const indexing = reindexingIds.includes(document.id);
          const needsIndex = document.status === "Uploaded" || document.status === "Failed";
          const workspaceName = workspaceNames?.[document.workspace_id];

          return (
            <li
              key={document.id}
              className="flex flex-col gap-3 px-4 py-3.5 sm:flex-row sm:items-center sm:justify-between"
            >
              <div className="flex min-w-0 items-center gap-3">
                <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-secondary text-muted-foreground">
                  <FileText className="size-[18px]" aria-hidden />
                </span>
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium" title={document.filename}>
                    {document.filename}
                  </p>
                  <p className="flex flex-wrap items-center gap-x-1.5 text-xs text-muted-foreground">
                    <span className="uppercase">{document.file_type}</span>
                    <span aria-hidden>·</span>
                    <span>{formatFileSize(document.file_size)}</span>
                    <span aria-hidden>·</span>
                    <span>
                      Uploaded{" "}
                      <time dateTime={document.uploaded_at}>{formatDate(document.uploaded_at)}</time>
                    </span>
                    {document.status === "Indexed" && document.chunk_count > 0 && (
                      <>
                        <span aria-hidden>·</span>
                        <span>{document.chunk_count} chunks</span>
                      </>
                    )}
                    {workspaceName && (
                      <>
                        <span aria-hidden>·</span>
                        <Link
                          href={`/workspaces/${document.workspace_id}`}
                          className="rounded-sm text-foreground underline-offset-2 hover:underline"
                        >
                          {workspaceName}
                        </Link>
                      </>
                    )}
                  </p>
                </div>
              </div>

              <div className="flex shrink-0 items-center gap-2 pl-12 sm:pl-0">
                <DocumentStatusBadge status={document.status} indexing={indexing} />
                {needsIndex && (
                  <Button
                    variant="outline"
                    size="sm"
                    loading={indexing}
                    onClick={() => startReindex(document)}
                  >
                    {!indexing && <RefreshCw />}
                    {indexLabel(document)}
                  </Button>
                )}
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      aria-label={`Actions for ${document.filename}`}
                    >
                      <MoreHorizontal />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end" className="w-48">
                    {!needsIndex && (
                      <DropdownMenuItem
                        disabled={indexing || document.status === "Processing"}
                        onSelect={() => startReindex(document)}
                      >
                        <RefreshCw /> Reindex
                      </DropdownMenuItem>
                    )}
                    <DropdownMenuItem
                      className="text-destructive [&_svg]:text-destructive!"
                      onSelect={() => {
                        setDeleteTarget(document);
                        setDeleteOpen(true);
                      }}
                    >
                      <Trash2 /> Delete
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              </div>
            </li>
          );
        })}
      </ul>

      {deleteTarget && (
        <DeleteDocumentDialog document={deleteTarget} open={deleteOpen} onOpenChange={setDeleteOpen} />
      )}
    </>
  );
}
