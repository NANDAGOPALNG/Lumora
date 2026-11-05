"use client";

import { toast } from "sonner";
import { useCreateWorkspace } from "@/hooks/use-workspaces";
import { WorkspaceNameDialog } from "@/components/workspaces/workspace-name-dialog";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function CreateWorkspaceDialog({ open, onOpenChange }: Props) {
  const create = useCreateWorkspace();

  return (
    <WorkspaceNameDialog
      open={open}
      onOpenChange={onOpenChange}
      title="Create workspace"
      description="Workspaces keep a project’s documents and conversations together."
      submitLabel="Create workspace"
      onSubmit={async (name) => {
        const created = await create.mutateAsync(name);
        toast.success(`Workspace “${created.name}” created`);
        onOpenChange(false);
      }}
    />
  );
}
