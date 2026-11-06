"use client";

import { useState } from "react";
import { toast } from "sonner";
import { useUploadQueue } from "@/hooks/use-upload-queue";
import { FileDropzone } from "@/components/documents/file-dropzone";
import { UploadQueueList } from "@/components/documents/upload-queue-list";

interface DocumentUploaderProps {
  /** Target workspace; null disables uploading until one is chosen. */
  workspaceId: string | null;
  /** Used to label queue items on pages that mix workspaces. */
  workspaceNames?: Record<string, string>;
}

export function DocumentUploader({ workspaceId, workspaceNames }: DocumentUploaderProps) {
  const [autoIndex, setAutoIndex] = useState(true);
  const queue = useUploadQueue({ autoIndex });

  function handleFiles(files: File[]) {
    if (!workspaceId || files.length === 0) return;
    const duplicates = queue.addFiles(files, workspaceId);
    if (duplicates > 0) {
      toast.info(
        duplicates === 1 ? "That file is already being uploaded." : `${duplicates} files are already being uploaded.`,
      );
    }
  }

  return (
    <div className="space-y-3">
      <FileDropzone
        onFiles={handleFiles}
        disabled={workspaceId === null}
        disabledHint="Choose a workspace to upload into first."
      />
      <label className="flex items-start gap-2.5 text-sm">
        <input
          type="checkbox"
          checked={autoIndex}
          onChange={(event) => setAutoIndex(event.target.checked)}
          className="mt-0.5 size-4 accent-primary"
        />
        <span>
          <span className="font-medium">Index automatically after upload</span>
          <span className="block text-xs text-muted-foreground">
            Uploading only stores the file. Indexing makes it searchable and can take a while for large
            files. If you turn this off, use Index on the document later.
          </span>
        </span>
      </label>
      {queue.items.length > 0 && (
        <UploadQueueList
          items={queue.items}
          workspaceNames={workspaceNames}
          onRetry={queue.retry}
          onCancel={queue.cancel}
          onRemove={queue.remove}
          onClearFinished={queue.clearFinished}
        />
      )}
    </div>
  );
}
