"use client";

import { FileText, TriangleAlert } from "lucide-react";
import { useWorkspaceDocuments } from "@/hooks/use-documents";
import { describeApiError } from "@/lib/api/errors";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/shared/empty-state";
import { DocumentList } from "@/components/documents/document-list";
import { DocumentListSkeleton } from "@/components/documents/document-skeletons";
import { DocumentUploader } from "@/components/documents/document-uploader";

/** The documents section of a workspace's detail page. */
export function WorkspaceDocuments({ workspaceId }: { workspaceId: string }) {
  const query = useWorkspaceDocuments(workspaceId);

  let list: React.ReactNode;
  if (query.data) {
    list =
      query.data.length === 0 ? (
        <EmptyState
          icon={FileText}
          title="No documents yet"
          description="Upload PDF, Word, text or Markdown files above to build this workspace’s knowledge base."
          className="py-10"
        />
      ) : (
        <DocumentList documents={query.data} />
      );
  } else if (query.isError) {
    list = (
      <EmptyState
        icon={TriangleAlert}
        title="Couldn’t load documents"
        description={describeApiError(query.error)}
        className="py-10"
        action={
          <Button onClick={() => void query.refetch()} loading={query.isFetching}>
            Try again
          </Button>
        }
      />
    );
  } else {
    list = <DocumentListSkeleton />;
  }

  return (
    <section aria-labelledby="documents-heading" className="space-y-4">
      <h2 id="documents-heading" className="text-[15px] font-semibold">
        Documents
        {query.data && query.data.length > 0 && (
          <span className="ml-2 font-normal text-muted-foreground">{query.data.length}</span>
        )}
      </h2>
      <DocumentUploader workspaceId={workspaceId} />
      {list}
    </section>
  );
}
