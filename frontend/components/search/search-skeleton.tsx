import { Skeleton } from "@/components/ui/skeleton";

export function SearchResultsSkeleton() {
  return (
    <ul role="status" aria-label="Searching" className="space-y-3">
      {[0, 1, 2].map((item) => (
        <li key={item} className="space-y-3 rounded-xl border bg-card p-5">
          <div className="flex items-center gap-3">
            <Skeleton className="size-6 rounded-md" />
            <Skeleton className="h-4 w-56" />
          </div>
          <Skeleton className="h-3 w-40" />
          <Skeleton className="h-16 w-full" />
        </li>
      ))}
    </ul>
  );
}
