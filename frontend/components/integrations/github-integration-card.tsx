"use client";

import { useState } from "react";
import Link from "next/link";
import { FolderKanban, GitBranch, Plus, TriangleAlert } from "lucide-react";
import type { ConnectorResponse } from "@/types/api";
import { useConnectors } from "@/hooks/use-connectors";
import { useWorkspaces } from "@/hooks/use-workspaces";
import { describeApiError } from "@/lib/api/errors";
import { isGitHubConnector } from "@/lib/connectors";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/shared/empty-state";
import { ConnectGitHubDialog } from "@/components/integrations/connect-github-dialog";
import { ConnectorRow } from "@/components/integrations/connector-row";
import { DisconnectConnectorDialog } from "@/components/integrations/disconnect-connector-dialog";
import { SyncGitHubDialog } from "@/components/integrations/sync-github-dialog";

export function GitHubIntegrationCard() {
  const workspacesQuery = useWorkspaces();
  const workspaces = workspacesQuery.data ?? [];
  const [workspaceChoice, setWorkspaceChoice] = useState<string | null>(null);

  // A single workspace is chosen for you; with several, the user picks one.
  const workspaceId =
    (workspaceChoice && workspaces.some((w) => w.id === workspaceChoice) ? workspaceChoice : null) ??
    (workspaces.length === 1 ? workspaces[0].id : null);
  const workspaceName = workspaces.find((w) => w.id === workspaceId)?.name;

  const connectorsQuery = useConnectors(workspaceId);
  const connectors = (connectorsQuery.data ?? []).filter(isGitHubConnector);

  const [connectOpen, setConnectOpen] = useState(false);
  // Targets are kept after closing so dialogs keep their content while animating out.
  const [syncTarget, setSyncTarget] = useState<ConnectorResponse | null>(null);
  const [syncOpen, setSyncOpen] = useState(false);
  const [disconnectTarget, setDisconnectTarget] = useState<ConnectorResponse | null>(null);
  const [disconnectOpen, setDisconnectOpen] = useState(false);

  const connectButton = (
    <Button onClick={() => setConnectOpen(true)} disabled={workspaces.length === 0}>
      <Plus /> Connect repository
    </Button>
  );

  let body: React.ReactNode;
  if (workspacesQuery.isError && !workspacesQuery.data) {
    body = (
      <EmptyState
        icon={TriangleAlert}
        title="Couldn’t load your workspaces"
        description={describeApiError(workspacesQuery.error)}
        className="py-8"
        action={
          <Button onClick={() => void workspacesQuery.refetch()} loading={workspacesQuery.isFetching}>
            Try again
          </Button>
        }
      />
    );
  } else if (!workspacesQuery.data) {
    body = <Skeleton className="h-24 w-full rounded-xl" role="status" aria-label="Loading workspaces" />;
  } else if (workspaces.length === 0) {
    body = (
      <EmptyState
        icon={FolderKanban}
        title="Create a workspace first"
        description="Repositories are imported into a workspace."
        className="py-8"
        action={
          <Button asChild>
            <Link href="/workspaces">Go to workspaces</Link>
          </Button>
        }
      />
    );
  } else if (workspaceId === null) {
    body = (
      <p className="rounded-lg border border-dashed px-4 py-6 text-center text-sm text-muted-foreground">
        Choose a workspace to see its connected repositories.
      </p>
    );
  } else if (connectorsQuery.isError && !connectorsQuery.data) {
    body = (
      <EmptyState
        icon={TriangleAlert}
        title="Couldn’t load connections"
        description={describeApiError(connectorsQuery.error)}
        className="py-8"
        action={
          <Button onClick={() => void connectorsQuery.refetch()} loading={connectorsQuery.isFetching}>
            Try again
          </Button>
        }
      />
    );
  } else if (!connectorsQuery.data) {
    body = <Skeleton className="h-20 w-full rounded-xl" role="status" aria-label="Loading connections" />;
  } else if (connectors.length === 0) {
    body = (
      <EmptyState
        icon={GitBranch}
        title="No repositories connected"
        description={`Connect a GitHub repository to import its documentation into ${workspaceName}.`}
        className="py-8"
      />
    );
  } else {
    body = (
      <ul aria-label="Connected repositories" className="divide-y overflow-hidden rounded-xl border">
        {connectors.map((connector) => (
          <ConnectorRow
            key={connector.id}
            connector={connector}
            onSync={(target) => {
              setSyncTarget(target);
              setSyncOpen(true);
            }}
            onDisconnect={(target) => {
              setDisconnectTarget(target);
              setDisconnectOpen(true);
            }}
          />
        ))}
      </ul>
    );
  }

  return (
    <section aria-labelledby="github-heading" className="space-y-5 rounded-xl border bg-card p-5">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex gap-4">
          <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-secondary text-muted-foreground">
            <GitBranch className="size-5" aria-hidden />
          </span>
          <div className="space-y-1.5">
            <div className="flex flex-wrap items-center gap-2">
              <h2 id="github-heading" className="text-[15px] font-semibold">
                GitHub
              </h2>
              <Badge variant="outline">Token needed for each sync</Badge>
            </div>
            <p className="max-w-prose text-sm leading-relaxed text-muted-foreground">
              Import a repository’s documentation and text files, then re-sync to pick up changes. Lumora
              doesn’t store your GitHub token, so you enter it each time.
            </p>
          </div>
        </div>
        {/* Always available once a workspace exists: the dialog has its own workspace selector. */}
        <div className="shrink-0">{connectButton}</div>
      </div>

      {workspaces.length > 0 && (
        <div className="grid max-w-xs gap-1.5">
          <label htmlFor="integrations-workspace" className="text-xs font-medium text-muted-foreground">
            Workspace
          </label>
          <Select
            id="integrations-workspace"
            value={workspaceId ?? ""}
            onChange={(event) => setWorkspaceChoice(event.target.value || null)}
          >
            {workspaceId === null && <option value="">Choose a workspace…</option>}
            {workspaces.map((workspace) => (
              <option key={workspace.id} value={workspace.id}>
                {workspace.name}
              </option>
            ))}
          </Select>
        </div>
      )}

      {body}

      <ConnectGitHubDialog
        open={connectOpen}
        onOpenChange={setConnectOpen}
        workspaces={workspaces}
        defaultWorkspaceId={workspaceId}
        onConnected={(connector) => setWorkspaceChoice(connector.workspace_id)}
      />
      {syncTarget && <SyncGitHubDialog connector={syncTarget} open={syncOpen} onOpenChange={setSyncOpen} />}
      {disconnectTarget && (
        <DisconnectConnectorDialog
          connector={disconnectTarget}
          open={disconnectOpen}
          onOpenChange={setDisconnectOpen}
        />
      )}
    </section>
  );
}
