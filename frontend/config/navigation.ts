import {
  LayoutDashboard,
  FolderKanban,
  FileText,
  MessageSquare,
  Search,
  Plug,
  Settings,
  type LucideIcon,
} from "lucide-react";

export interface NavItem {
  title: string;
  href: string;
  icon: LucideIcon;
}

export const primaryNav: NavItem[] = [
  { title: "Dashboard", href: "/", icon: LayoutDashboard },
  { title: "Workspaces", href: "/workspaces", icon: FolderKanban },
  { title: "Documents", href: "/documents", icon: FileText },
  { title: "AI Chat", href: "/chat", icon: MessageSquare },
  { title: "Search", href: "/search", icon: Search },
];

export const secondaryNav: NavItem[] = [
  { title: "Integrations", href: "/integrations", icon: Plug },
  { title: "Settings", href: "/settings", icon: Settings },
];

export const allNav: NavItem[] = [...primaryNav, ...secondaryNav];

/** The dashboard only matches "/" exactly; other items match their subtree. */
export function isNavItemActive(pathname: string, item: NavItem): boolean {
  if (item.href === "/") return pathname === "/";
  return pathname === item.href || pathname.startsWith(`${item.href}/`);
}
