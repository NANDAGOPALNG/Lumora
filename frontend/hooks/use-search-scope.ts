"use client";

import { useState } from "react";
import { useWorkspaceDocuments } from "@/hooks/use-documents";
import { useWorkspaces } from "@/hooks/use-workspaces";

/**
 * Workspace and document selection for scoped searches. A single workspace is chosen for you;
 * with several, the user must pick one. The document list is the chosen workspace's *indexed*
 * documents only (the only ones that can be searched), and the document choice resets whenever
 * the workspace changes, so a document from another workspace can never be selected.
 */
export function useSearchScope() {
  const workspacesQuery = useWorkspaces();
  const workspaces = workspacesQuery.data ?? [];
  const [workspaceChoice, setWorkspaceChoice] = useState<string | null>(null);
  const [documentChoice, setDocumentChoice] = useState<string | null>(null);

  const workspaceId =
    (workspaceChoice && workspaces.some((w) => w.id === workspaceChoice) ? workspaceChoice : null) ??
    (workspaces.length === 1 ? workspaces[0].id : null);

  const documentsQuery = useWorkspaceDocuments(workspaceId ?? "", { enabled: workspaceId !== null });
  const indexedDocuments = documentsQuery.data?.filter((document) => document.status === "Indexed");
  const documentId = indexedDocuments?.some((d) => d.id === documentChoice) ? documentChoice : null;

  return {
    workspacesQuery,
    workspaces,
    workspaceId,
    selectWorkspace: (id: string | null) => {
      setWorkspaceChoice(id);
      setDocumentChoice(null);
    },
    documentsQuery,
    indexedDocuments,
    documentId,
    selectDocument: setDocumentChoice,
  };
}
