import { Skeleton } from "@/components/ui/skeleton";

export function WorkspaceGridSkeleton() {
  return (
    <ul role="status" aria-label="Loading workspaces" className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
      {[0, 1, 2].map((item) => (
        <li key={item} className="flex flex-col gap-5 rounded-xl border bg-card p-5">
          <Skeleton className="size-10 rounded-lg" />
          <div className="space-y-2">
            <Skeleton className="h-4 w-2/3" />
            <Skeleton className="h-4 w-1/3" />
          </div>
          <Skeleton className="h-4 w-28" />
        </li>
      ))}
    </ul>
  );
}

export function WorkspaceDetailSkeleton() {
  return (
    <div role="status" aria-label="Loading workspace" className="space-y-8">
      <Skeleton className="h-4 w-32" />
      <div className="space-y-3">
        <Skeleton className="h-10 w-72 max-w-full" />
        <Skeleton className="h-4 w-48" />
      </div>
      <Skeleton className="h-28 w-full rounded-xl" />
      <Skeleton className="h-48 w-full rounded-xl" />
    </div>
  );
}
