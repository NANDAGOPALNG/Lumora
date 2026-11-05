"use client";

import { useState } from "react";
import { FolderKanban, Plus, TriangleAlert } from "lucide-react";
import type { WorkspaceResponse } from "@/types/api";
import { useWorkspaces } from "@/hooks/use-workspaces";
import { describeApiError } from "@/lib/api/errors";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/shared/empty-state";
import { PageHeader } from "@/components/shared/page-header";
import { CreateWorkspaceDialog } from "@/components/workspaces/create-workspace-dialog";
import { DeleteWorkspaceDialog } from "@/components/workspaces/delete-workspace-dialog";
import { RenameWorkspaceDialog } from "@/components/workspaces/rename-workspace-dialog";
import { WorkspaceCard } from "@/components/workspaces/workspace-card";
import { WorkspaceGridSkeleton } from "@/components/workspaces/workspace-skeletons";

export function WorkspacesView() {
  const query = useWorkspaces();
  const [createOpen, setCreateOpen] = useState(false);
  // Targets are kept after closing so the dialogs don't lose their content mid-animation.
  const [renameTarget, setRenameTarget] = useState<WorkspaceResponse | null>(null);
  const [renameOpen, setRenameOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<WorkspaceResponse | null>(null);
  const [deleteOpen, setDeleteOpen] = useState(false);

  const createButton = (
    <Button onClick={() => setCreateOpen(true)}>
      <Plus /> New workspace
    </Button>
  );

  let content: React.ReactNode;
  if (query.data) {
    content =
      query.data.length === 0 ? (
        <EmptyState
          icon={FolderKanban}
          title="No workspaces yet"
          description="Create a workspace to start organising your documents."
          action={createButton}
        />
      ) : (
        <ul className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {query.data.map((workspace) => (
            <WorkspaceCard
              key={workspace.id}
              workspace={workspace}
              onRename={(target) => {
                setRenameTarget(target);
                setRenameOpen(true);
              }}
              onDelete={(target) => {
                setDeleteTarget(target);
                setDeleteOpen(true);
              }}
            />
          ))}
        </ul>
      );
  } else if (query.isError) {
    content = (
      <EmptyState
        icon={TriangleAlert}
        title="Couldn’t load your workspaces"
        description={describeApiError(query.error)}
        action={
          <Button onClick={() => void query.refetch()} loading={query.isFetching}>
            Try again
          </Button>
        }
      />
    );
  } else {
    content = <WorkspaceGridSkeleton />;
  }

  return (
    <>
      <PageHeader
        title="Workspaces"
        description="Keep each project’s documents, searches and conversations together."
        // The empty state carries its own create action, so don't show two.
        actions={query.data && query.data.length > 0 ? createButton : undefined}
      />
      {content}

      <CreateWorkspaceDialog open={createOpen} onOpenChange={setCreateOpen} />
      {renameTarget && (
        <RenameWorkspaceDialog
          workspace={renameTarget}
          open={renameOpen}
          onOpenChange={setRenameOpen}
        />
      )}
      {deleteTarget && (
        <DeleteWorkspaceDialog
          workspace={deleteTarget}
          open={deleteOpen}
          onOpenChange={setDeleteOpen}
        />
      )}
    </>
  );
}
