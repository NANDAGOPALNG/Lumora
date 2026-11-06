"use client";

import { CircleAlert, CircleCheck, FileText, RotateCcw, X } from "lucide-react";
import type { UploadItem } from "@/hooks/use-upload-queue";
import { formatFileSize } from "@/lib/documents";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { cn } from "@/lib/utils";

interface UploadQueueListProps {
  items: UploadItem[];
  workspaceNames?: Record<string, string>;
  onRetry: (id: string) => void;
  onCancel: (id: string) => void;
  onRemove: (id: string) => void;
  onClearFinished: () => void;
}

function statusText(item: UploadItem): string {
  switch (item.status) {
    case "queued":
      return "Waiting to upload";
    case "uploading":
      return `Uploading ${Math.round(item.progress * 100)}%`;
    case "indexing":
      return "Uploaded. Indexing, which can take a while for large files…";
    case "uploaded":
      return "Uploaded, not indexed yet. Use Index on the document to make it searchable.";
    case "indexed":
      return "Uploaded and indexed";
    case "failed":
    case "rejected":
      return item.error ?? "Something went wrong.";
  }
}

export function UploadQueueList({
  items,
  workspaceNames,
  onRetry,
  onCancel,
  onRemove,
  onClearFinished,
}: UploadQueueListProps) {
  const hasFinished = items.some((item) => !["queued", "uploading", "indexing"].includes(item.status));

  return (
    <div className="space-y-2">
      <ul aria-label="Upload queue" className="divide-y overflow-hidden rounded-xl border bg-card">
        {items.map((item) => {
          const problem = item.status === "failed" || item.status === "rejected";
          const busy = item.status === "uploading" || item.status === "indexing";
          const workspaceName = workspaceNames?.[item.workspaceId];

          return (
            <li key={item.id} className="flex items-start gap-3 px-4 py-3">
              <span className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg bg-secondary text-muted-foreground">
                {item.status === "indexed" ? (
                  <CircleCheck className="size-4" aria-hidden />
                ) : problem ? (
                  <CircleAlert className="size-4 text-destructive" aria-hidden />
                ) : busy ? (
                  <Spinner className="size-4" aria-label={undefined} aria-hidden />
                ) : (
                  <FileText className="size-4" aria-hidden />
                )}
              </span>

              <div className="min-w-0 flex-1 space-y-1.5">
                <p className="flex items-baseline gap-2 text-sm">
                  <span className="truncate font-medium" title={item.file.name}>
                    {item.file.name}
                  </span>
                  <span className="shrink-0 text-xs text-muted-foreground">
                    {formatFileSize(item.file.size)}
                    {workspaceName && ` · ${workspaceName}`}
                  </span>
                </p>
                <p
                  className={cn("text-xs text-muted-foreground", problem && "text-destructive")}
                  aria-live="polite"
                >
                  {statusText(item)}
                </p>
                {item.status === "uploading" && (
                  <div
                    role="progressbar"
                    aria-label={`Uploading ${item.file.name}`}
                    aria-valuemin={0}
                    aria-valuemax={100}
                    aria-valuenow={Math.round(item.progress * 100)}
                    className="h-1 overflow-hidden rounded-full bg-secondary"
                  >
                    <div
                      className="h-full rounded-full bg-foreground transition-[width]"
                      style={{ width: `${Math.round(item.progress * 100)}%` }}
                    />
                  </div>
                )}
                {item.status === "indexing" && (
                  <div className="h-1 overflow-hidden rounded-full bg-secondary" aria-hidden>
                    <div className="h-full w-1/3 animate-pulse rounded-full bg-brand" />
                  </div>
                )}
              </div>

              <div className="flex shrink-0 items-center gap-1">
                {item.status === "failed" && (
                  <Button variant="outline" size="sm" onClick={() => onRetry(item.id)}>
                    <RotateCcw /> {item.failedStage === "index" ? "Retry indexing" : "Retry upload"}
                  </Button>
                )}
                {item.status === "uploading" ? (
                  <Button variant="ghost" size="sm" onClick={() => onCancel(item.id)}>
                    Cancel
                  </Button>
                ) : (
                  !busy && (
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      aria-label={`Remove ${item.file.name} from the list`}
                      onClick={() => onRemove(item.id)}
                    >
                      <X />
                    </Button>
                  )
                )}
              </div>
            </li>
          );
        })}
      </ul>
      {hasFinished && (
        <div className="flex justify-end">
          <Button variant="ghost" size="sm" onClick={onClearFinished}>
            Clear finished
          </Button>
        </div>
      )}
    </div>
  );
}
