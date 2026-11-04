"use client";

import { useEffect, useState } from "react";
import { motion } from "motion/react";
import { TooltipProvider } from "@/components/ui/tooltip";
import { MobileNav } from "@/components/layout/mobile-nav";
import { SidebarContent } from "@/components/layout/sidebar-content";
import { Topbar } from "@/components/layout/topbar";
import { useSidebarCollapsed } from "@/hooks/use-sidebar-collapsed";

const SIDEBAR_EXPANDED = 260;
const SIDEBAR_COLLAPSED = 68;

export function AppShell({ children }: { children: React.ReactNode }) {
  const { collapsed, toggle } = useSidebarCollapsed();
  const [mobileOpen, setMobileOpen] = useState(false);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "b") {
        event.preventDefault();
        toggle();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [toggle]);

  return (
    <TooltipProvider delayDuration={200}>
      <div className="flex h-dvh overflow-hidden bg-background">
        <a
          href="#main-content"
          className="sr-only z-50 rounded-md bg-primary px-3 py-2 text-sm text-primary-foreground focus:not-sr-only focus:fixed focus:left-3 focus:top-3"
        >
          Skip to content
        </a>

        <motion.aside
          initial={false}
          animate={{ width: collapsed ? SIDEBAR_COLLAPSED : SIDEBAR_EXPANDED }}
          transition={{ duration: 0.2, ease: [0.4, 0, 0.2, 1] }}
          className="hidden shrink-0 overflow-hidden border-r border-sidebar-border lg:block"
        >
          <SidebarContent instance="desktop" collapsed={collapsed} />
        </motion.aside>

        <MobileNav open={mobileOpen} onOpenChange={setMobileOpen} />

        <div className="flex min-w-0 flex-1 flex-col">
          <Topbar
            sidebarCollapsed={collapsed}
            onToggleSidebar={toggle}
            onOpenMobileNav={() => setMobileOpen(true)}
          />
          <main id="main-content" className="flex-1 overflow-y-auto">
            <div className="mx-auto w-full max-w-6xl px-4 py-8 sm:px-6 lg:px-8 lg:py-10">
              {children}
            </div>
          </main>
        </div>
      </div>
    </TooltipProvider>
  );
}
