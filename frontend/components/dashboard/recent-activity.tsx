"use client";

import Link from "next/link";
import { History, TriangleAlert } from "lucide-react";
import { EmptyState } from "@/components/shared/empty-state";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useDashboardSummary } from "@/hooks/use-dashboard";
import { describeApiError } from "@/lib/api/errors";
import { ACTIVITY_ICONS, ACTIVITY_LABELS, safeInternalLink } from "@/lib/dashboard";
import { formatDateTime, formatRelativeTime } from "@/lib/format";
import type { DashboardActivity } from "@/types/api";

function ActivityRow({ activity }: { activity: DashboardActivity }) {
  const Icon = ACTIVITY_ICONS[activity.type];
  const href = safeInternalLink(activity.link);
  const body = (
    <>
      <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-secondary text-muted-foreground">
        <Icon className="size-[18px]" aria-hidden />
        <span className="sr-only">{ACTIVITY_LABELS[activity.type]}: </span>
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-medium">{activity.title}</span>
        <span className="block truncate text-sm text-muted-foreground">{activity.description}</span>
      </span>
      <time
        dateTime={activity.created_at}
        title={formatDateTime(activity.created_at)}
        className="shrink-0 text-xs text-muted-foreground"
      >
        {formatRelativeTime(activity.created_at)}
      </time>
    </>
  );

  return (
    <li>
      {href ? (
        <Link
          href={href}
          className="flex items-center gap-4 px-4 py-3.5 transition-colors hover:bg-accent/60"
        >
          {body}
        </Link>
      ) : (
        <div className="flex items-center gap-4 px-4 py-3.5">{body}</div>
      )}
    </li>
  );
}

function ActivitySkeleton() {
  return (
    <ul
      role="status"
      aria-label="Loading recent activity"
      className="divide-y overflow-hidden rounded-xl border bg-card"
    >
      {[0, 1, 2, 3].map((item) => (
        <li key={item} className="flex items-center gap-4 px-4 py-3.5">
          <Skeleton className="size-9 shrink-0 rounded-lg" />
          <div className="flex-1 space-y-2">
            <Skeleton className="h-4 w-2/3" />
            <Skeleton className="h-3.5 w-1/2" />
          </div>
          <Skeleton className="h-3.5 w-14" />
        </li>
      ))}
    </ul>
  );
}

export function RecentActivity() {
  const query = useDashboardSummary();
  const activity = query.data?.recent_activity;

  let content: React.ReactNode;
  if (activity && activity.length > 0) {
    content = (
      <ul className="divide-y overflow-hidden rounded-xl border bg-card">
        {activity.map((item) => (
          <ActivityRow key={item.id} activity={item} />
        ))}
      </ul>
    );
  } else if (activity) {
    content = (
      <EmptyState
        icon={History}
        title="No activity yet"
        description="Uploads, connector syncs and new conversations will show up here."
        className="py-10"
      />
    );
  } else if (query.isError) {
    content = (
      <EmptyState
        icon={TriangleAlert}
        title="Couldn’t load recent activity"
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
    content = <ActivitySkeleton />;
  }

  return (
    <section aria-labelledby="recent-activity-heading">
      <h2 id="recent-activity-heading" className="mb-3 text-[15px] font-semibold">
        Recent activity
      </h2>
      {content}
    </section>
  );
}
