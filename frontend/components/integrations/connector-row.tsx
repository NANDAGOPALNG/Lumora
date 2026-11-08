"use client";

import { GitBranch, RefreshCw, Unplug } from "lucide-react";
import type { ConnectorResponse } from "@/types/api";
import { formatDateTime } from "@/lib/format";
import { needsReconnect } from "@/lib/connectors";
import { useIsSyncing } from "@/lib/sync-tracker";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

interface ConnectorRowProps {
  connector: ConnectorResponse;
  onSync: (connector: ConnectorResponse) => void;
  onDisconnect: (connector: ConnectorResponse) => void;
}

export function ConnectorRow({ connector, onSync, onDisconnect }: ConnectorRowProps) {
  const syncing = useIsSyncing(connector.id);
  const reconnect = needsReconnect(connector);
  const repo = connector.github_repo;

  return (
    <li className="flex flex-col gap-3 px-4 py-3.5 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex min-w-0 items-center gap-3">
        <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-secondary text-muted-foreground">
          <GitBranch className="size-[18px]" aria-hidden />
        </span>
        <div className="min-w-0 space-y-0.5">
          <p className="flex items-center gap-2 text-sm font-medium">
            <span className="truncate" title={connector.connection_name}>
              {connector.connection_name}
            </span>
            {!connector.active && <Badge variant="outline">Inactive</Badge>}
            {reconnect && <Badge variant="brand">Reconnect needed</Badge>}
          </p>
          <p className="flex flex-wrap items-center gap-x-1.5 text-xs text-muted-foreground">
            {repo && repo !== connector.connection_name && (
              <>
                <a
                  href={`https://github.com/${repo}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="rounded-sm underline-offset-2 hover:underline [overflow-wrap:anywhere]"
                >
                  {repo}
                </a>
                <span aria-hidden>·</span>
              </>
            )}
            {connector.last_synced ? (
              <span>
                Last synced <time dateTime={connector.last_synced}>{formatDateTime(connector.last_synced)}</time>
              </span>
            ) : (
              <span>Never synced</span>
            )}
          </p>
          {reconnect && (
            <p className="text-xs text-muted-foreground">
              This connection predates stored repositories. Disconnect it and connect the repository again.
            </p>
          )}
        </div>
      </div>

      <div className="flex shrink-0 items-center gap-2 pl-12 sm:pl-0">
        <Button
          variant="outline"
          size="sm"
          loading={syncing}
          disabled={reconnect}
          onClick={() => onSync(connector)}
          aria-label={`Sync ${connector.connection_name}`}
        >
          {!syncing && <RefreshCw />}
          {syncing ? "Syncing…" : "Sync"}
        </Button>
        <Button
          variant="ghost"
          size="sm"
          disabled={syncing}
          onClick={() => onDisconnect(connector)}
          aria-label={`Disconnect ${connector.connection_name}`}
        >
          <Unplug /> Disconnect
        </Button>
      </div>
    </li>
  );
}
