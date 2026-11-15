"use client";

import { TriangleAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useDashboardSummary } from "@/hooks/use-dashboard";
import { describeApiError } from "@/lib/api/errors";
import type { DashboardStats } from "@/types/api";

const stats: ReadonlyArray<{ key: keyof DashboardStats; label: string; hint: string }> = [
  { key: "workspaces", label: "Workspaces", hint: "Spaces you've created" },
  { key: "documents", label: "Documents", hint: "Files across all workspaces" },
  { key: "indexed_chunks", label: "Indexed chunks", hint: "Passages available to search" },
  { key: "conversations", label: "Conversations", hint: "Chats with your knowledge base" },
];

const formatCount = (value: number) => new Intl.NumberFormat("en").format(value);

/**
 * One divided panel rather than a row of separate cards. Values come from the backend's
 * per-user dashboard summary; the panel keeps its height while loading to avoid layout shift.
 */
export function OverviewStats() {
  const query = useDashboardSummary();
  const summary = query.data?.stats;

  return (
    <section aria-labelledby="overview-heading">
      <h2 id="overview-heading" className="sr-only">
        Overview
      </h2>
      <dl
        className="grid grid-cols-2 overflow-hidden rounded-xl border bg-card lg:grid-cols-4"
        aria-busy={query.isPending}
      >
        {stats.map((stat, index) => (
          <div
            key={stat.key}
            className={[
              "p-5",
              index % 2 === 1 ? "border-l" : "",
              index >= 2 ? "border-t lg:border-t-0" : "",
              index >= 1 ? "lg:border-l" : "",
            ].join(" ")}
          >
            <dt className="text-sm text-muted-foreground">{stat.label}</dt>
            <dd className="mt-2 flex h-9 items-center font-serif text-3xl font-medium tracking-tight">
              {summary ? (
                formatCount(summary[stat.key])
              ) : query.isError ? (
                <span className="text-muted-foreground/60" aria-label="Unavailable">
                  —
                </span>
              ) : (
                <Skeleton className="h-7 w-14" />
              )}
            </dd>
            <p className="mt-1 text-xs text-muted-foreground">{stat.hint}</p>
          </div>
        ))}
      </dl>
      {query.isPending && (
        <p role="status" className="sr-only">
          Loading overview
        </p>
      )}
      {query.isError && !summary && (
        <div
          role="alert"
          className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-2 text-sm text-muted-foreground"
        >
          <TriangleAlert className="size-4 shrink-0" aria-hidden />
          <span>Couldn’t load your overview. {describeApiError(query.error)}</span>
          <Button
            variant="outline"
            size="sm"
            onClick={() => void query.refetch()}
            loading={query.isFetching}
          >
            Try again
          </Button>
        </div>
      )}
    </section>
  );
}
