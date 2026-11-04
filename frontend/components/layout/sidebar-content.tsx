"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { LayoutGroup } from "motion/react";
import {
  isNavItemActive,
  primaryNav,
  secondaryNav,
  type NavItem,
} from "@/config/navigation";
import { Logo } from "@/components/layout/logo";
import { SidebarNavLink } from "@/components/layout/sidebar-nav-link";
import { UserMenu } from "@/components/layout/user-menu";
import { cn } from "@/lib/utils";

interface SidebarContentProps {
  collapsed?: boolean;
  /** "desktop" | "mobile": keeps animation layout groups separate. */
  instance: string;
  onNavigate?: () => void;
}

export function SidebarContent({
  collapsed = false,
  instance,
  onNavigate,
}: SidebarContentProps) {
  const pathname = usePathname();

  const renderList = (items: NavItem[], label: string) => (
    <nav aria-label={label}>
      <ul className="flex flex-col gap-0.5">
        {items.map((item) => (
          <li key={item.href}>
            <SidebarNavLink
              item={item}
              active={isNavItemActive(pathname, item)}
              collapsed={collapsed}
              indicatorId={`${instance}-nav-indicator`}
              onNavigate={onNavigate}
            />
          </li>
        ))}
      </ul>
    </nav>
  );

  return (
    <LayoutGroup id={instance}>
      <div className="flex h-full flex-col bg-sidebar text-sidebar-foreground">
        <div
          className={cn(
            "flex h-14 shrink-0 items-center px-4",
            collapsed && "justify-center px-0",
          )}
        >
          <Link
            href="/"
            onClick={onNavigate}
            aria-label="Lumora dashboard"
            className="rounded-md"
          >
            <Logo showWordmark={!collapsed} />
          </Link>
        </div>

        <div className="flex-1 overflow-y-auto px-3 py-2">
          {renderList(primaryNav, "Primary")}
        </div>

        <div className="px-3 pb-2">{renderList(secondaryNav, "Secondary")}</div>

        <div className="border-t border-sidebar-border p-3">
          <UserMenu collapsed={collapsed} />
        </div>
      </div>
    </LayoutGroup>
  );
}
