import type { Metadata } from "next";
import Link from "next/link";
import { ChevronRight, FileText, MessageSquare, Search } from "lucide-react";
import { PageHeader } from "@/components/shared/page-header";
import { Badge } from "@/components/ui/badge";

export const metadata: Metadata = { title: "Workspace overview" };

const sections = [
  { title: "Documents", href: "/documents", icon: FileText },
  { title: "AI Chat", href: "/chat", icon: MessageSquare },
  { title: "Search", href: "/search", icon: Search },
] as const;

export default async function WorkspaceOverviewPage({
  params,
}: {
  params: Promise<{ workspaceId: string }>;
}) {
  const { workspaceId } = await params;

  return (
    <>
      <PageHeader
        title="Workspace overview"
        description="Details, documents and activity for this workspace will appear here."
        actions={<Badge variant="outline">Not available yet</Badge>}
      />
      <div className="max-w-2xl space-y-8">
        <div className="rounded-xl border bg-card p-5">
          <p className="text-sm text-muted-foreground">Workspace ID</p>
          <p className="mt-1 break-all font-mono text-sm">{workspaceId}</p>
          <p className="mt-3 text-xs text-muted-foreground">
            The workspace name and statistics load once Lumora is connected to your account.
          </p>
        </div>

        <ul className="divide-y overflow-hidden rounded-xl border bg-card">
          {sections.map(({ title, href, icon: Icon }) => (
            <li key={href}>
              <Link
                href={href}
                className="group flex items-center gap-3 px-4 py-3 text-sm font-medium transition-colors hover:bg-accent/60"
              >
                <Icon className="size-[18px] text-muted-foreground" aria-hidden />
                <span className="flex-1">{title}</span>
                <ChevronRight className="size-4 text-muted-foreground" aria-hidden />
              </Link>
            </li>
          ))}
        </ul>
      </div>
    </>
  );
}
