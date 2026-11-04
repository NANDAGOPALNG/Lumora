"use client";

import Link from "next/link";
import { motion } from "motion/react";
import { cn } from "@/lib/utils";
import type { NavItem } from "@/config/navigation";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";

interface SidebarNavLinkProps {
  item: NavItem;
  active: boolean;
  collapsed: boolean;
  /** Unique per rendered sidebar so the active marker never animates between instances. */
  indicatorId: string;
  onNavigate?: () => void;
}

export function SidebarNavLink({
  item,
  active,
  collapsed,
  indicatorId,
  onNavigate,
}: SidebarNavLinkProps) {
  const Icon = item.icon;

  const link = (
    <Link
      href={item.href}
      onClick={onNavigate}
      aria-current={active ? "page" : undefined}
      className={cn(
        "group relative flex h-9 items-center gap-3 rounded-md px-2.5 text-sm font-medium transition-colors",
        collapsed && "justify-center px-0",
        active
          ? "text-foreground"
          : "text-sidebar-foreground/80 hover:bg-sidebar-accent/60 hover:text-foreground",
      )}
    >
      {active && (
        <motion.span
          layoutId={indicatorId}
          transition={{ type: "spring", stiffness: 500, damping: 40 }}
          className="absolute inset-0 rounded-md bg-sidebar-accent"
        >
          <span className="absolute inset-y-2 left-0 w-0.5 rounded-full bg-brand" />
        </motion.span>
      )}
      <Icon className="relative size-[18px] shrink-0" aria-hidden />
      <span className={cn("relative truncate", collapsed && "sr-only")}>
        {item.title}
      </span>
    </Link>
  );

  if (!collapsed) return link;

  return (
    <Tooltip>
      <TooltipTrigger asChild>{link}</TooltipTrigger>
      <TooltipContent side="right">{item.title}</TooltipContent>
    </Tooltip>
  );
}
