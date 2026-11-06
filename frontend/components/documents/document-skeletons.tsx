import { Skeleton } from "@/components/ui/skeleton";

export function DocumentListSkeleton() {
  return (
    <ul role="status" aria-label="Loading documents" className="divide-y overflow-hidden rounded-xl border bg-card">
      {[0, 1, 2].map((item) => (
        <li key={item} className="flex items-center justify-between gap-4 px-4 py-3.5">
          <div className="flex items-center gap-3">
            <Skeleton className="size-9 rounded-lg" />
            <div className="space-y-2">
              <Skeleton className="h-4 w-48" />
              <Skeleton className="h-3 w-32" />
            </div>
          </div>
          <Skeleton className="h-6 w-20 rounded-sm" />
        </li>
      ))}
    </ul>
  );
}
