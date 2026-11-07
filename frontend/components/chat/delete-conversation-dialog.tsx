"use client";

import { useRef, useState } from "react";
import { toast } from "sonner";
import { useDeleteConversation } from "@/hooks/use-chat";
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
  conversationId: string;
  label: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onDeleted?: () => void;
}

export function DeleteConversationDialog({ conversationId, label, open, onOpenChange, onDeleted }: Props) {
  const remove = useDeleteConversation();
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
      await remove.mutateAsync(conversationId);
      toast.success("Conversation deleted");
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
          <DialogTitle>Delete conversation?</DialogTitle>
          <DialogDescription>
            This permanently deletes{" "}
            <span className="font-medium text-foreground [overflow-wrap:anywhere]">{label}</span> and all of its
            messages. This can’t be undone.
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
            Delete conversation
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
