import type { Metadata } from "next";
import { WorkspaceDetailView } from "@/components/workspaces/workspace-detail-view";

export const metadata: Metadata = { title: "Workspace" };

export default async function WorkspaceDetailPage({
  params,
}: {
  params: Promise<{ workspaceId: string }>;
}) {
  const { workspaceId } = await params;
  return <WorkspaceDetailView workspaceId={workspaceId} />;
}
