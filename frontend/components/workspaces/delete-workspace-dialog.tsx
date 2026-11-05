"use client";

import { useRef, useState } from "react";
import { toast } from "sonner";
import type { WorkspaceResponse } from "@/types/api";
import { useDeleteWorkspace } from "@/hooks/use-workspaces";
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
  workspace: WorkspaceResponse;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Called after the server confirms the deletion (e.g. to leave the detail page). */
  onDeleted?: () => void;
}

export function DeleteWorkspaceDialog({ workspace, open, onOpenChange, onDeleted }: Props) {
  const remove = useDeleteWorkspace();
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
      await remove.mutateAsync(workspace.id);
      toast.success(`Workspace “${workspace.name}” deleted`);
      close();
      onDeleted?.();
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
          <DialogTitle>Delete workspace?</DialogTitle>
          <DialogDescription>
            This permanently deletes{" "}
            <span className="font-medium text-foreground [overflow-wrap:anywhere]">
              {workspace.name}
            </span>{" "}
            and everything in it: its documents, their stored files and search data, and any
            connected sources. This can’t be undone.
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
            Delete workspace
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
