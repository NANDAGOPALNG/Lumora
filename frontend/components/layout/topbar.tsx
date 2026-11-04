"use client";

import { Menu, PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { Breadcrumbs } from "@/components/layout/breadcrumbs";
import { ThemeToggle } from "@/components/layout/theme-toggle";

interface TopbarProps {
  sidebarCollapsed: boolean;
  onToggleSidebar: () => void;
  onOpenMobileNav: () => void;
}

export function Topbar({
  sidebarCollapsed,
  onToggleSidebar,
  onOpenMobileNav,
}: TopbarProps) {
  const ToggleIcon = sidebarCollapsed ? PanelLeftOpen : PanelLeftClose;
  const toggleLabel = sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar";

  return (
    <header className="flex h-14 shrink-0 items-center gap-2 border-b bg-background px-3 sm:px-4">
      <Button
        variant="ghost"
        size="icon"
        className="lg:hidden"
        aria-label="Open navigation"
        onClick={onOpenMobileNav}
      >
        <Menu />
      </Button>

      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            variant="ghost"
            size="icon"
            className="hidden lg:inline-flex"
            aria-label={toggleLabel}
            onClick={onToggleSidebar}
          >
            <ToggleIcon />
          </Button>
        </TooltipTrigger>
        <TooltipContent>{toggleLabel} (Ctrl/⌘ B)</TooltipContent>
      </Tooltip>

      <Breadcrumbs />

      <div className="ml-auto flex items-center gap-1">
        <ThemeToggle />
      </div>
    </header>
  );
}
