"use client";

import { PageHeader } from "@/components/shared/page-header";
import { GitHubIntegrationCard } from "@/components/integrations/github-integration-card";
import { GoogleDriveCard } from "@/components/integrations/google-drive-card";

export function IntegrationsView() {
  return (
    <>
      <PageHeader
        title="Integrations"
        description="Bring knowledge in from the tools your team already uses."
      />
      <div className="max-w-4xl space-y-6">
        <GitHubIntegrationCard />
        <GoogleDriveCard />
      </div>
    </>
  );
}
