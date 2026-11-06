"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft, Pencil, SearchX, Trash2, TriangleAlert } from "lucide-react";
import { useWorkspace } from "@/hooks/use-workspaces";
import { describeApiError } from "@/lib/api/errors";
import { formatDateTime } from "@/lib/format";
import { isUuid } from "@/lib/workspaces";
import { Button } from "@/components/ui/button";
import { CopyButton } from "@/components/shared/copy-button";
import { EmptyState } from "@/components/shared/empty-state";
import { PageHeader } from "@/components/shared/page-header";
import { DeleteWorkspaceDialog } from "@/components/workspaces/delete-workspace-dialog";
import { RenameWorkspaceDialog } from "@/components/workspaces/rename-workspace-dialog";
import { WorkspaceDetailSkeleton } from "@/components/workspaces/workspace-skeletons";
import { WorkspaceDocuments } from "@/components/documents/workspace-documents";

function BackLink() {
  return (
    <Link
      href="/workspaces"
      className="mb-6 inline-flex items-center gap-1.5 rounded-sm text-sm text-muted-foreground transition-colors hover:text-foreground"
    >
      <ArrowLeft className="size-4" aria-hidden /> All workspaces
    </Link>
  );
}

export function WorkspaceDetailView({ workspaceId }: { workspaceId: string }) {
  const router = useRouter();
  const validId = isUuid(workspaceId);
  const query = useWorkspace(workspaceId, { enabled: validId });
  const [renameOpen, setRenameOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);

  if (!validId) {
    return (
      <>
        <BackLink />
        <EmptyState
          icon={SearchX}
          title="Invalid workspace link"
          description="That address doesn’t contain a valid workspace ID."
        />
      </>
    );
  }

  if (query.isError) {
    return (
      <>
        <BackLink />
        <EmptyState
          icon={TriangleAlert}
          title="Couldn’t load this workspace"
          description={describeApiError(query.error)}
          action={
            <Button onClick={() => void query.refetch()} loading={query.isFetching}>
              Try again
            </Button>
          }
        />
      </>
    );
  }

  if (query.data === undefined) return <WorkspaceDetailSkeleton />;

  const workspace = query.data;
  if (workspace === null) {
    // The list only contains the signed-in user's workspaces, so a workspace that
    // doesn't exist and one owned by someone else look the same, as on the backend.
    return (
      <>
        <BackLink />
        <EmptyState
          icon={SearchX}
          title="Workspace not found"
          description="It may have been deleted, or it isn’t in your account."
          action={
            <Button asChild variant="outline">
              <Link href="/workspaces">View your workspaces</Link>
            </Button>
          }
        />
      </>
    );
  }

  return (
    <>
      <BackLink />
      <PageHeader
        title={workspace.name}
        description="Workspace overview"
        actions={
          <>
            <Button variant="outline" onClick={() => setRenameOpen(true)}>
              <Pencil /> Rename
            </Button>
            <Button
              variant="outline"
              className="text-destructive hover:text-destructive"
              onClick={() => setDeleteOpen(true)}
            >
              <Trash2 /> Delete
            </Button>
          </>
        }
      />

      <div className="space-y-10">
        <dl className="divide-y overflow-hidden rounded-xl border bg-card text-sm">
          <div className="flex items-center justify-between gap-4 px-5 py-3.5">
            <dt className="text-muted-foreground">Created</dt>
            <dd>
              <time dateTime={workspace.created_at}>{formatDateTime(workspace.created_at)}</time>
            </dd>
          </div>
          <div className="flex items-center justify-between gap-4 px-5 py-2.5">
            <dt className="shrink-0 text-muted-foreground">Workspace ID</dt>
            <dd className="flex min-w-0 items-center gap-1">
              <code className="truncate font-mono text-xs">{workspace.id}</code>
              <CopyButton value={workspace.id} label="Copy workspace ID" />
            </dd>
          </div>
        </dl>

        <WorkspaceDocuments workspaceId={workspace.id} />
      </div>

      <RenameWorkspaceDialog workspace={workspace} open={renameOpen} onOpenChange={setRenameOpen} />
      <DeleteWorkspaceDialog
        workspace={workspace}
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        onDeleted={() => router.replace("/workspaces")}
      />
    </>
  );
}
