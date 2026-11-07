"use client";

import { useRef, useState } from "react";
import Link from "next/link";
import { Search, SearchX, SlidersHorizontal, TriangleAlert, X } from "lucide-react";
import { useKnowledgeSearch } from "@/hooks/use-search";
import { useSearchScope } from "@/hooks/use-search-scope";
import { describeApiError } from "@/lib/api/errors";
import { DEFAULT_TOP_K, TOP_K_OPTIONS, sameSearch, sameSelection, type SearchParams } from "@/lib/search";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { EmptyState } from "@/components/shared/empty-state";
import { PageHeader } from "@/components/shared/page-header";
import { SearchResultCard } from "@/components/search/search-result-card";
import { SearchResultsSkeleton } from "@/components/search/search-skeleton";

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

export function SearchView() {
  const scope = useSearchScope();
  const [text, setText] = useState("");
  const [topK, setTopK] = useState<number>(DEFAULT_TOP_K);
  const [submitted, setSubmitted] = useState<SearchParams | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const { workspaceId, documentId } = scope;

  // Results belong to the selection they were searched with. If the workspace, document or result
  // count has since changed, nothing is shown for them (never stale results under a new selection).
  const active =
    submitted && workspaceId && sameSelection(submitted, { workspaceId, documentId, topK }) ? submitted : null;
  const selectionChanged = submitted !== null && active === null;
  const search = useKnowledgeSearch(active);

  function submit() {
    if (search.isFetching) return; // one search at a time
    const query = text.trim();
    if (!workspaceId) {
      setFormError("Choose a workspace to search in.");
      return;
    }
    if (!query) {
      setFormError("Enter something to search for.");
      return;
    }
    setFormError(null);
    setText(query);
    const params: SearchParams = { query, workspaceId, documentId, topK };
    if (active && sameSearch(active, params)) void search.refetch(); // same search again: run it again
    else setSubmitted(params);
  }

  function clear() {
    setText("");
    setSubmitted(null);
    setFormError(null);
    inputRef.current?.focus();
  }

  const workspaceName = scope.workspaces.find((w) => w.id === workspaceId)?.name;
  const documentName = scope.indexedDocuments?.find((d) => d.id === documentId)?.filename;
  const where = documentName ? `${documentName} in ${workspaceName}` : (workspaceName ?? "this workspace");
  const documentsLoading = workspaceId !== null && scope.documentsQuery.isPending;
  const noIndexed =
    workspaceId !== null && scope.indexedDocuments !== undefined && scope.indexedDocuments.length === 0;

  let results: React.ReactNode;
  if (active === null) {
    results = selectionChanged ? (
      <EmptyState
        icon={SlidersHorizontal}
        title="Filters changed"
        description="Press Search to see results for the new selection."
      />
    ) : (
      <EmptyState
        icon={Search}
        title="Search your knowledge"
        description="Find the exact passages across your indexed documents. Choose a workspace, then enter your question or keywords."
      />
    );
  } else if (search.isError && !search.data) {
    results = (
      <EmptyState
        icon={TriangleAlert}
        title="The search failed"
        description={describeApiError(search.error)}
        action={
          <Button onClick={() => void search.refetch()} loading={search.isFetching}>
            Try again
          </Button>
        }
      />
    );
  } else if (!search.data) {
    results = <SearchResultsSkeleton />;
  } else if (search.data.sources.length === 0) {
    results = (
      <EmptyState
        icon={SearchX}
        title="No results found"
        description={`Nothing in ${where} matched “${active.query}”. Only indexed documents are searched, so check that your documents show Indexed, or try different words.`}
      />
    );
  } else {
    const { sources, query: normalised } = search.data;
    results = (
      <section aria-labelledby="results-heading" className="space-y-4">
        <div className="space-y-1">
          <h2 id="results-heading" className="text-[15px] font-semibold">
            {sources.length} {sources.length === 1 ? "result" : "results"}
            <span className="ml-2 font-normal text-muted-foreground [overflow-wrap:anywhere]">
              for “{active.query}” in {where}
            </span>
          </h2>
          {normalised.trim().toLowerCase() !== active.query.toLowerCase() && (
            <p className="text-xs text-muted-foreground">Searched as “{normalised}”.</p>
          )}
          {sources.length >= active.topK && (
            <p className="text-xs text-muted-foreground">
              Showing the top {active.topK}. Raise “Results” to see more passages.
            </p>
          )}
        </div>
        <ol aria-label="Search results" className="space-y-3">
          {sources.map((source, index) => (
            <SearchResultCard key={`${source.chunk_id}-${index}`} result={source} rank={index + 1} />
          ))}
        </ol>
      </section>
    );
  }

  return (
    <>
      <PageHeader title="Search" description="Find the exact passage across everything you've indexed." />

      <div className="space-y-8">
        <form
          role="search"
          onSubmit={(event) => {
            event.preventDefault();
            submit();
          }}
          className="space-y-4 rounded-2xl border bg-card p-4 sm:p-5"
        >
          <div className="flex flex-col gap-2 sm:flex-row">
            <div className="relative flex-1">
              <label htmlFor="search-query" className="sr-only">
                Search query
              </label>
              <Search
                className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
                aria-hidden
              />
              <Input
                id="search-query"
                ref={inputRef}
                value={text}
                autoComplete="off"
                placeholder="Search your documents, e.g. “How does authentication work?”"
                className="h-10 pl-9 pr-9"
                aria-invalid={formError !== null}
                aria-describedby={formError ? "search-error" : undefined}
                onChange={(event) => {
                  setText(event.target.value);
                  setFormError(null);
                }}
              />
              {(text !== "" || submitted !== null) && (
                <button
                  type="button"
                  onClick={clear}
                  aria-label="Clear search"
                  className="absolute right-2 top-1/2 flex size-6 -translate-y-1/2 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                >
                  <X className="size-4" />
                </button>
              )}
            </div>
            <Button type="submit" size="lg" loading={search.isFetching}>
              Search
            </Button>
          </div>
          {formError && (
            <p id="search-error" role="alert" className="text-sm text-destructive">
              {formError}
            </p>
          )}

          <div className="grid gap-3 sm:grid-cols-3">
            <Field label="Workspace" htmlFor="search-workspace">
              <Select
                id="search-workspace"
                value={workspaceId ?? ""}
                disabled={scope.workspacesQuery.isPending || scope.workspaces.length === 0}
                onChange={(event) => {
                  scope.selectWorkspace(event.target.value || null);
                  setFormError(null);
                }}
              >
                {workspaceId === null && <option value="">Choose a workspace…</option>}
                {scope.workspaces.map((workspace) => (
                  <option key={workspace.id} value={workspace.id}>
                    {workspace.name}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Document" htmlFor="search-document">
              <Select
                id="search-document"
                value={documentId ?? ""}
                disabled={workspaceId === null || scope.indexedDocuments === undefined}
                onChange={(event) => scope.selectDocument(event.target.value || null)}
              >
                {documentsLoading ? (
                  <option value="">Loading documents…</option>
                ) : (
                  <option value="">All indexed documents</option>
                )}
                {(scope.indexedDocuments ?? []).map((document) => (
                  <option key={document.id} value={document.id}>
                    {document.filename}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Results" htmlFor="search-top-k">
              <Select
                id="search-top-k"
                value={topK}
                onChange={(event) => setTopK(Number(event.target.value))}
              >
                {TOP_K_OPTIONS.map((option) => (
                  <option key={option} value={option}>
                    Top {option}
                  </option>
                ))}
              </Select>
            </Field>
          </div>

          {scope.workspacesQuery.isError && !scope.workspacesQuery.data && (
            <p role="alert" className="text-xs text-destructive">
              {describeApiError(scope.workspacesQuery.error)}{" "}
              <button type="button" className="font-medium underline" onClick={() => void scope.workspacesQuery.refetch()}>
                Retry
              </button>
            </p>
          )}
          {workspaceId !== null && scope.documentsQuery.isError && !scope.documentsQuery.data && (
            <p role="alert" className="text-xs text-destructive">
              Couldn’t load documents, so you can only search the whole workspace.{" "}
              <button type="button" className="font-medium underline" onClick={() => void scope.documentsQuery.refetch()}>
                Retry
              </button>
            </p>
          )}
          {noIndexed && (
            <p className="text-xs text-muted-foreground">
              This workspace has no indexed documents yet, so searches won’t find anything.{" "}
              <Link href={`/workspaces/${workspaceId}`} className="font-medium text-foreground underline-offset-2 hover:underline">
                Add documents
              </Link>
            </p>
          )}
        </form>

        {/* A short announcement for screen readers instead of reading the whole list aloud. */}
        <p role="status" className="sr-only">
          {active === null || search.isError
            ? ""
            : search.isFetching && !search.data
              ? "Searching…"
              : search.data
                ? `${search.data.sources.length} ${search.data.sources.length === 1 ? "result" : "results"} found`
                : ""}
        </p>
        {results}
      </div>
    </>
  );
}
