"use client";

import { useState } from "react";
import { toast } from "sonner";
import type { ConnectorResponse, GitHubSyncResponse } from "@/types/api";
import { SyncAlreadyRunningError, useGitHubConnectorActions } from "@/hooks/use-connectors";
import { describeApiError } from "@/lib/api/errors";
import { validateToken } from "@/lib/connectors";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Spinner } from "@/components/ui/spinner";
import { SyncSummary } from "@/components/integrations/sync-summary";
import { TokenField } from "@/components/integrations/token-field";

interface SyncGitHubDialogProps {
  connector: ConnectorResponse;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

type Phase = { kind: "form" } | { kind: "running" } | { kind: "done"; summary: GitHubSyncResponse };

function SyncFlow({
  connector,
  onClose,
  onPendingChange,
}: {
  connector: ConnectorResponse;
  onClose: () => void;
  onPendingChange: (pending: boolean) => void;
}) {
  const actions = useGitHubConnectorActions();
  const [token, setToken] = useState(""); // lives only here and is cleared once the request ends
  const [tokenError, setTokenError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [phase, setPhase] = useState<Phase>({ kind: "form" });
  const repo = connector.github_repo ?? connector.connection_name;

  async function start(event: React.FormEvent) {
    event.preventDefault();
    if (phase.kind !== "form") return;
    const problem = validateToken(token);
    setTokenError(problem);
    if (problem) return;

    setError(null);
    setPhase({ kind: "running" });
    onPendingChange(true);
    try {
      const summary = await actions.sync(connector, token.trim());
      toast.success(`Synced ${summary.repository}`);
      setPhase({ kind: "done", summary });
    } catch (err) {
      setError(err instanceof SyncAlreadyRunningError ? err.message : describeApiError(err));
      setPhase({ kind: "form" });
    } finally {
      setToken(""); // the token is never kept after the request, successful or not
      onPendingChange(false);
    }
  }

  if (phase.kind === "running") {
    return (
      <div role="status" className="flex items-start gap-3 rounded-lg border bg-secondary/50 p-4 text-sm">
        <Spinner className="mt-0.5" aria-label={undefined} aria-hidden />
        <div className="space-y-1">
          <p className="font-medium">Syncing {repo}…</p>
          <p className="text-muted-foreground">
            This can take a while for large repositories. Keep this window open. Lumora can’t show live
            progress; you’ll see a summary when it finishes.
          </p>
        </div>
      </div>
    );
  }

  if (phase.kind === "done") {
    return (
      <>
        <SyncSummary summary={phase.summary} />
        <DialogFooter>
          <Button onClick={onClose}>Done</Button>
        </DialogFooter>
      </>
    );
  }

  return (
    <form onSubmit={(event) => void start(event)} className="grid gap-4" noValidate>
      <div className="space-y-2 text-sm leading-relaxed text-muted-foreground">
        <p>
          Enter your GitHub token to sync. Lumora doesn’t store tokens, so it’s needed again every time.
        </p>
        <p>
          Documents imported from files that no longer exist in the repository will be deleted from Lumora.
        </p>
      </div>
      <TokenField id="sync-token" value={token} onChange={setToken} error={tokenError} />
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onClose}>
          Cancel
        </Button>
        <Button type="submit">Start sync</Button>
      </DialogFooter>
    </form>
  );
}

export function SyncGitHubDialog({ connector, open, onOpenChange }: SyncGitHubDialogProps) {
  const [pending, setPending] = useState(false);

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next && pending) return;
        onOpenChange(next);
      }}
    >
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Sync from GitHub</DialogTitle>
          <DialogDescription className="[overflow-wrap:anywhere]">
            {connector.github_repo ?? connector.connection_name}
          </DialogDescription>
        </DialogHeader>
        <SyncFlow
          connector={connector}
          onClose={() => onOpenChange(false)}
          onPendingChange={setPending}
        />
      </DialogContent>
    </Dialog>
  );
}
