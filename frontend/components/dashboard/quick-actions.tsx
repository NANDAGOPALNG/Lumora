import Link from "next/link";
import { ChevronRight, FilePlus2, FolderPlus, MessageSquare, Search } from "lucide-react";

const actions = [
  {
    title: "Create a workspace",
    description: "Group related documents in their own space.",
    href: "/workspaces",
    icon: FolderPlus,
  },
  {
    title: "Add documents",
    description: "Upload PDF, Word, text or Markdown files.",
    href: "/documents",
    icon: FilePlus2,
  },
  {
    title: "Ask a question",
    description: "Get answers grounded in your documents.",
    href: "/chat",
    icon: MessageSquare,
  },
  {
    title: "Search your knowledge",
    description: "Find the exact passage you need.",
    href: "/search",
    icon: Search,
  },
] as const;

export function QuickActions() {
  return (
    <section aria-labelledby="quick-actions-heading">
      <h2 id="quick-actions-heading" className="mb-3 text-[15px] font-semibold">
        Quick actions
      </h2>
      <ul className="divide-y overflow-hidden rounded-xl border bg-card">
        {actions.map(({ title, description, href, icon: Icon }) => (
          <li key={href}>
            <Link
              href={href}
              className="group flex items-center gap-4 px-4 py-3.5 transition-colors hover:bg-accent/60"
            >
              <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-secondary text-muted-foreground transition-colors group-hover:bg-card group-hover:text-foreground">
                <Icon className="size-[18px]" aria-hidden />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block text-sm font-medium">{title}</span>
                <span className="block truncate text-sm text-muted-foreground">
                  {description}
                </span>
              </span>
              <ChevronRight
                className="size-4 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5"
                aria-hidden
              />
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
