import { History } from "lucide-react";
import { EmptyState } from "@/components/shared/empty-state";

export function RecentActivity() {
  return (
    <section aria-labelledby="recent-activity-heading">
      <h2 id="recent-activity-heading" className="mb-3 text-[15px] font-semibold">
        Recent activity
      </h2>
      <EmptyState
        icon={History}
        title="No activity to show"
        description="Uploads, indexing results and conversations will be listed here once Lumora is connected to your account."
        className="py-10"
      />
    </section>
  );
}
