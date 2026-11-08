"use client";

import { useRef, useState } from "react";
import { toast } from "sonner";
import type { ConnectorResponse } from "@/types/api";
import { useDisconnectConnector } from "@/hooks/use-connectors";
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
  connector: ConnectorResponse;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function DisconnectConnectorDialog({ connector, open, onOpenChange }: Props) {
  const disconnect = useDisconnectConnector();
  const inFlight = useRef(false);
  const [error, setError] = useState<string | null>(null);

  function close() {
    setError(null);
    onOpenChange(false);
  }

  async function confirm() {
    if (inFlight.current) return; // never send a second request
    inFlight.current = true;
    setError(null);
    try {
      await disconnect.mutateAsync({ id: connector.id, workspaceId: connector.workspace_id });
      toast.success(`Disconnected ${connector.connection_name}`);
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
        if (!next && disconnect.isPending) return;
        if (next) onOpenChange(true);
        else close();
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Disconnect this repository?</DialogTitle>
          <DialogDescription>
            This removes the connection to{" "}
            <span className="font-medium text-foreground [overflow-wrap:anywhere]">
              {connector.github_repo ?? connector.connection_name}
            </span>
            . Documents already imported stay in the workspace as ordinary documents, but they will no
            longer be updated from GitHub. Connecting the same repository again imports its files again as
            new documents.
          </DialogDescription>
        </DialogHeader>
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={close} disabled={disconnect.isPending}>
            Cancel
          </Button>
          <Button variant="destructive" loading={disconnect.isPending} onClick={() => void confirm()}>
            Disconnect
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
