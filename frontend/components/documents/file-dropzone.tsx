"use client";

import { useRef, useState } from "react";
import { CloudUpload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ACCEPT_ATTRIBUTE, formatFileSize, getMaxUploadBytes } from "@/lib/documents";
import { cn } from "@/lib/utils";

interface FileDropzoneProps {
  onFiles: (files: File[]) => void;
  disabled?: boolean;
  /** Shown instead of the default hint, e.g. why the zone is disabled. */
  disabledHint?: string;
}

export function FileDropzone({ onFiles, disabled = false, disabledHint }: FileDropzoneProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  return (
    <div
      onDragEnter={(event) => {
        event.preventDefault();
        if (!disabled) setDragging(true);
      }}
      onDragOver={(event) => event.preventDefault()}
      onDragLeave={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDragging(false);
      }}
      onDrop={(event) => {
        event.preventDefault();
        setDragging(false);
        if (!disabled) onFiles(Array.from(event.dataTransfer.files));
      }}
      className={cn(
        "flex flex-col items-center gap-3 rounded-xl border border-dashed px-6 py-8 text-center transition-colors",
        dragging && "border-foreground/50 bg-accent/60",
        disabled && "opacity-60",
      )}
    >
      <span className="flex size-10 items-center justify-center rounded-lg bg-secondary text-muted-foreground">
        <CloudUpload className="size-5" aria-hidden />
      </span>
      <div className="space-y-1">
        <p className="text-sm font-medium">
          {dragging ? "Drop to upload" : "Drag files here, or choose them"}
        </p>
        <p className="text-xs text-muted-foreground">
          {disabled && disabledHint
            ? disabledHint
            : `PDF, DOCX, TXT or MD · up to ${formatFileSize(getMaxUploadBytes())} each`}
        </p>
      </div>
      <Button variant="outline" disabled={disabled} onClick={() => inputRef.current?.click()}>
        Choose files
      </Button>
      <input
        ref={inputRef}
        type="file"
        multiple
        accept={ACCEPT_ATTRIBUTE}
        disabled={disabled}
        aria-label="Choose documents to upload"
        tabIndex={-1}
        className="sr-only"
        onChange={(event) => {
          onFiles(Array.from(event.target.files ?? []));
          event.target.value = ""; // allow choosing the same file again later
        }}
      />
    </div>
  );
}
