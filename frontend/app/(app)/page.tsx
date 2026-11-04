import type { Metadata } from "next";
import { PageHeader } from "@/components/shared/page-header";
import { OverviewStats } from "@/components/dashboard/overview-stats";
import { QuickActions } from "@/components/dashboard/quick-actions";
import { RecentActivity } from "@/components/dashboard/recent-activity";

export const metadata: Metadata = { title: "Dashboard" };

export default function DashboardPage() {
  return (
    <>
      <PageHeader
        title="Dashboard"
        description="Your workspaces, documents and conversations at a glance."
      />
      <div className="space-y-10">
        <OverviewStats />
        <div className="grid gap-10 lg:grid-cols-2">
          <QuickActions />
          <RecentActivity />
        </div>
      </div>
    </>
  );
}
