"use client";

import { toast } from "sonner";
import type { WorkspaceResponse } from "@/types/api";
import { useRenameWorkspace } from "@/hooks/use-workspaces";
import { WorkspaceNameDialog } from "@/components/workspaces/workspace-name-dialog";

interface Props {
  workspace: WorkspaceResponse;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function RenameWorkspaceDialog({ workspace, open, onOpenChange }: Props) {
  const rename = useRenameWorkspace();

  return (
    <WorkspaceNameDialog
      // Remount per workspace so the field always starts from that workspace's name.
      key={workspace.id}
      open={open}
      onOpenChange={onOpenChange}
      title="Rename workspace"
      description="Choose a new name. Your documents aren’t affected."
      submitLabel="Save name"
      initialName={workspace.name}
      onSubmit={async (name) => {
        const updated = await rename.mutateAsync({ id: workspace.id, name });
        toast.success(`Renamed to “${updated.name}”`);
        onOpenChange(false);
      }}
    />
  );
}
