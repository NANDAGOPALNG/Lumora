"use client";

import { useRef, useState } from "react";
import { toast } from "sonner";
import type { DocumentResponse } from "@/types/api";
import { useDeleteDocument } from "@/hooks/use-documents";
import { describeApiError } from "@/lib/api/errors";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

interface Props {
  document: DocumentResponse;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function DeleteDocumentDialog({ document, open, onOpenChange }: Props) {
  const remove = useDeleteDocument();
  const inFlight = useRef(false);
  const [error, setError] = useState<string | null>(null);

  function close() {
    setError(null);
    onOpenChange(false);
  }

  async function confirm() {
    if (inFlight.current) return; // never send a second delete
    inFlight.current = true;
    setError(null);
    try {
      await remove.mutateAsync({ id: document.id, workspaceId: document.workspace_id });
      toast.success(`“${document.filename}” deleted`);
      close();
    } catch (err) {
      setError(describeApiError(err));
    } finally {
      inFlight.current = false;
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next && remove.isPending) return;
        if (next) onOpenChange(true);
        else close();
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Delete document?</DialogTitle>
          <DialogDescription>
            This permanently deletes{" "}
            <span className="font-medium text-foreground [overflow-wrap:anywhere]">{document.filename}</span>
            , including its stored file and search data. This can’t be undone.
          </DialogDescription>
        </DialogHeader>
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={close} disabled={remove.isPending}>
            Cancel
          </Button>
          <Button variant="destructive" loading={remove.isPending} onClick={() => void confirm()}>
            Delete document
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
