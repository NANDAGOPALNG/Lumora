"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { FileText, FolderKanban, SearchX, TriangleAlert } from "lucide-react";
import type { DocumentStatus } from "@/types/api";
import { useMultiWorkspaceDocuments } from "@/hooks/use-documents";
import { useWorkspaces } from "@/hooks/use-workspaces";
import { describeApiError } from "@/lib/api/errors";
import { DOCUMENT_STATUSES, sortDocuments } from "@/lib/documents";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import { EmptyState } from "@/components/shared/empty-state";
import { PageHeader } from "@/components/shared/page-header";
import { DocumentList } from "@/components/documents/document-list";
import { DocumentListSkeleton } from "@/components/documents/document-skeletons";
import { DocumentUploader } from "@/components/documents/document-uploader";

const ALL = "all";

function Field({ label, htmlFor, children }: { label: string; htmlFor: string; children: React.ReactNode }) {
  return (
    <div className="grid gap-1.5">
      <label htmlFor={htmlFor} className="text-xs font-medium text-muted-foreground">
        {label}
      </label>
      {children}
    </div>
  );
}

/** Global documents page. The backend lists documents per workspace, so this fans out per workspace. */
export function DocumentsView() {
  const workspacesQuery = useWorkspaces();
  const workspaces = useMemo(() => workspacesQuery.data ?? [], [workspacesQuery.data]);

  const [workspaceFilter, setWorkspaceFilter] = useState<string>(ALL);
  const [statusFilter, setStatusFilter] = useState<string>(ALL);
  const [uploadChoice, setUploadChoice] = useState<string | null>(null);

  const workspaceNames = useMemo(
    () => Object.fromEntries(workspaces.map((workspace) => [workspace.id, workspace.name])),
    [workspaces],
  );

  // A filter pointing at a workspace that has since been deleted falls back to "all".
  const activeWorkspaceFilter = workspaceNames[workspaceFilter] ? workspaceFilter : ALL;
  const fetchIds = activeWorkspaceFilter === ALL ? workspaces.map((w) => w.id) : [activeWorkspaceFilter];
  const documentQueries = useMultiWorkspaceDocuments(fetchIds);

  const uploadTarget =
    (uploadChoice && workspaceNames[uploadChoice] ? uploadChoice : null) ??
    (activeWorkspaceFilter !== ALL ? activeWorkspaceFilter : workspaces.length === 1 ? workspaces[0].id : null);

  // Cheap enough to derive on each render; no memoisation needed.
  const documents = sortDocuments(
    documentQueries
      .flatMap((query) => query.data ?? [])
      .filter((document) => statusFilter === ALL || document.status === (statusFilter as DocumentStatus)),
  );

  const header = (
    <PageHeader
      title="Documents"
      description="Upload files and make them searchable across your workspaces."
    />
  );

  if (workspacesQuery.isError && !workspacesQuery.data) {
    return (
      <>
        {header}
        <EmptyState
          icon={TriangleAlert}
          title="Couldn’t load your workspaces"
          description={describeApiError(workspacesQuery.error)}
          action={
            <Button onClick={() => void workspacesQuery.refetch()} loading={workspacesQuery.isFetching}>
              Try again
            </Button>
          }
        />
      </>
    );
  }

  if (!workspacesQuery.data) {
    return (
      <>
        {header}
        <DocumentListSkeleton />
      </>
    );
  }

  if (workspaces.length === 0) {
    return (
      <>
        {header}
        <EmptyState
          icon={FolderKanban}
          title="Create a workspace first"
          description="Documents live inside workspaces. Create one, then come back to upload."
          action={
            <Button asChild>
              <Link href="/workspaces">Go to workspaces</Link>
            </Button>
          }
        />
      </>
    );
  }

  const failed = documentQueries
    .map((query, index) => ({ query, id: fetchIds[index] }))
    .filter(({ query }) => query.isError && !query.data);
  const allPending = documentQueries.length > 0 && documentQueries.every((q) => q.isPending && !q.isError);
  const everyFailed = documentQueries.length > 0 && failed.length === documentQueries.length;
  const filtersActive = activeWorkspaceFilter !== ALL || statusFilter !== ALL;

  let list: React.ReactNode;
  if (everyFailed) {
    list = (
      <EmptyState
        icon={TriangleAlert}
        title="Couldn’t load documents"
        description={describeApiError(failed[0].query.error)}
        action={
          <Button onClick={() => failed.forEach(({ query }) => void query.refetch())}>Try again</Button>
        }
      />
    );
  } else if (allPending) {
    list = <DocumentListSkeleton />;
  } else if (documents.length === 0) {
    list = filtersActive ? (
      <EmptyState
        icon={SearchX}
        title="No documents match these filters"
        description="Try a different workspace or status."
        action={
          <Button
            variant="outline"
            onClick={() => {
              setWorkspaceFilter(ALL);
              setStatusFilter(ALL);
            }}
          >
            Clear filters
          </Button>
        }
      />
    ) : (
      <EmptyState
        icon={FileText}
        title="No documents yet"
        description="Choose a workspace above and upload your first file."
      />
    );
  } else {
    list = <DocumentList documents={documents} workspaceNames={workspaceNames} />;
  }

  return (
    <>
      {header}
      <div className="space-y-10">
        <section aria-labelledby="upload-heading" className="space-y-4">
          <h2 id="upload-heading" className="text-[15px] font-semibold">
            Upload
          </h2>
          <div className="max-w-xs">
            <Field label="Upload to" htmlFor="upload-workspace">
              <Select
                id="upload-workspace"
                value={uploadTarget ?? ""}
                onChange={(event) => setUploadChoice(event.target.value || null)}
              >
                {uploadTarget === null && <option value="">Choose a workspace…</option>}
                {workspaces.map((workspace) => (
                  <option key={workspace.id} value={workspace.id}>
                    {workspace.name}
                  </option>
                ))}
              </Select>
            </Field>
          </div>
          <DocumentUploader workspaceId={uploadTarget} workspaceNames={workspaceNames} />
        </section>

        <section aria-labelledby="all-documents-heading" className="space-y-4">
          <div className="flex flex-wrap items-end justify-between gap-4">
            <h2 id="all-documents-heading" className="text-[15px] font-semibold">
              Your documents
              {!allPending && documents.length > 0 && (
                <span className="ml-2 font-normal text-muted-foreground">{documents.length}</span>
              )}
            </h2>
            <div className="flex flex-wrap gap-3">
              <Field label="Workspace" htmlFor="filter-workspace">
                <Select
                  id="filter-workspace"
                  className="min-w-44"
                  value={activeWorkspaceFilter}
                  onChange={(event) => setWorkspaceFilter(event.target.value)}
                >
                  <option value={ALL}>All workspaces</option>
                  {workspaces.map((workspace) => (
                    <option key={workspace.id} value={workspace.id}>
                      {workspace.name}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="Status" htmlFor="filter-status">
                <Select
                  id="filter-status"
                  className="min-w-36"
                  value={statusFilter}
                  onChange={(event) => setStatusFilter(event.target.value)}
                >
                  <option value={ALL}>All statuses</option>
                  {DOCUMENT_STATUSES.map((status) => (
                    <option key={status} value={status}>
                      {status}
                    </option>
                  ))}
                </Select>
              </Field>
            </div>
          </div>

          {failed.length > 0 && !everyFailed && (
            <div
              role="alert"
              className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-destructive/30 bg-destructive/5 px-3.5 py-3 text-sm"
            >
              <p>
                Couldn’t load documents for {failed.map(({ id }) => workspaceNames[id] ?? "a workspace").join(", ")}.
              </p>
              <Button variant="outline" size="sm" onClick={() => failed.forEach(({ query }) => void query.refetch())}>
                Retry
              </Button>
            </div>
          )}

          {list}
        </section>
      </div>
    </>
  );
}
