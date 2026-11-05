"use client";

import Link from "next/link";
import { ChevronRight, FolderKanban, MoreHorizontal, Pencil, Trash2 } from "lucide-react";
import type { WorkspaceResponse } from "@/types/api";
import { formatDate } from "@/lib/format";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

interface WorkspaceCardProps {
  workspace: WorkspaceResponse;
  onRename: (workspace: WorkspaceResponse) => void;
  onDelete: (workspace: WorkspaceResponse) => void;
}

export function WorkspaceCard({ workspace, onRename, onDelete }: WorkspaceCardProps) {
  return (
    <li className="group relative flex flex-col gap-5 rounded-xl border bg-card p-5 transition-colors hover:border-foreground/25 hover:bg-accent/40">
      <div className="flex items-start justify-between gap-3">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-secondary text-muted-foreground transition-colors group-hover:bg-card group-hover:text-foreground">
          <FolderKanban className="size-5" aria-hidden />
        </span>

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="ghost"
              size="icon-sm"
              className="relative z-10 -mr-2 -mt-1"
              aria-label={`Actions for ${workspace.name}`}
            >
              <MoreHorizontal />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-44">
            <DropdownMenuItem onSelect={() => onRename(workspace)}>
              <Pencil /> Rename
            </DropdownMenuItem>
            <DropdownMenuItem
              className="text-destructive [&_svg]:text-destructive!"
              onSelect={() => onDelete(workspace)}
            >
              <Trash2 /> Delete
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      <div className="min-w-0 space-y-1">
        <h2 className="truncate text-[15px] font-semibold" title={workspace.name}>
          {/* The link stretches over the whole card; the actions menu sits above it. */}
          <Link
            href={`/workspaces/${workspace.id}`}
            className="rounded-sm after:absolute after:inset-0 after:rounded-xl"
          >
            {workspace.name}
          </Link>
        </h2>
        <p className="text-sm text-muted-foreground">
          Created <time dateTime={workspace.created_at}>{formatDate(workspace.created_at)}</time>
        </p>
      </div>

      <span
        aria-hidden
        className="flex items-center gap-1 text-sm font-medium text-muted-foreground transition-colors group-hover:text-foreground"
      >
        Open workspace
        <ChevronRight className="size-4 transition-transform group-hover:translate-x-0.5" />
      </span>
    </li>
  );
}
