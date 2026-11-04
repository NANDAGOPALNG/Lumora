import { allNav } from "@/config/navigation";

export interface Breadcrumb {
  label: string;
  href?: string;
}

/**
 * Derive breadcrumbs from the current pathname. Top-level segments use the
 * navigation titles; the dynamic workspace segment is labelled generically
 * until real workspace names are available from the API.
 */
export function buildBreadcrumbs(pathname: string): Breadcrumb[] {
  const segments = pathname.split("/").filter(Boolean);
  if (segments.length === 0) return [{ label: "Dashboard" }];

  const [root, second] = segments;
  const rootItem = allNav.find((item) => item.href === `/${root}`);
  const rootLabel = rootItem?.title ?? "Not found";

  if (segments.length === 1) return [{ label: rootLabel }];

  if (root === "workspaces" && second) {
    return [
      { label: rootLabel, href: `/${root}` },
      { label: "Workspace overview" },
    ];
  }

  return [{ label: rootLabel, href: `/${root}` }, { label: second }];
}
