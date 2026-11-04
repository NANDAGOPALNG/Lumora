import type { Metadata } from "next";
import { Cloud, GitBranch } from "lucide-react";
import { PageHeader } from "@/components/shared/page-header";
import { Badge } from "@/components/ui/badge";

export const metadata: Metadata = { title: "Integrations" };

const integrations = [
  {
    name: "GitHub",
    description: "Sync files from a repository and keep them up to date.",
    icon: GitBranch,
  },
  {
    name: "Google Drive",
    description: "Import files from a Drive folder and keep them up to date.",
    icon: Cloud,
  },
] as const;

export default function IntegrationsPage() {
  return (
    <>
      <PageHeader
        title="Integrations"
        description="Bring knowledge in from the tools your team already uses."
      />
      <ul className="grid max-w-3xl gap-4 sm:grid-cols-2">
        {integrations.map(({ name, description, icon: Icon }) => (
          <li key={name} className="flex gap-4 rounded-xl border bg-card p-5">
            <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-secondary text-muted-foreground">
              <Icon className="size-5" aria-hidden />
            </span>
            <div className="min-w-0 space-y-1.5">
              <div className="flex items-center gap-2">
                <h2 className="text-[15px] font-semibold">{name}</h2>
                <Badge variant="outline">Not available yet</Badge>
              </div>
              <p className="text-sm leading-relaxed text-muted-foreground">
                {description}
              </p>
            </div>
          </li>
        ))}
      </ul>
    </>
  );
}
