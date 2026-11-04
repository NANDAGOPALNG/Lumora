import type { Metadata } from "next";
import { FolderKanban } from "lucide-react";
import { PageHeader } from "@/components/shared/page-header";
import { FeaturePlaceholder } from "@/components/shared/feature-placeholder";

export const metadata: Metadata = { title: "Workspaces" };

export default function WorkspacesPage() {
  return (
    <>
      <PageHeader
        title="Workspaces"
        description="Keep each project's documents, searches and conversations together."
      />
      <FeaturePlaceholder
        icon={FolderKanban}
        title="Workspace management"
        description="Workspaces will be created and listed here once Lumora is connected to your account."
        capabilities={[
          "Create a workspace with a name of up to 100 characters",
          "Rename or delete a workspace (deleting also removes its documents and connections)",
          "Open a workspace to see its documents and start a chat",
        ]}
      />
    </>
  );
}
