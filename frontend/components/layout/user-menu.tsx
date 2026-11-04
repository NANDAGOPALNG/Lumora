"use client";

import Link from "next/link";
import { ChevronsUpDown, LogIn, Settings, User } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

/**
 * Profile section. Authentication is not wired up yet, so this renders the
 * signed-out state; it will read the real user once sign-in lands.
 */
export function UserMenu({ collapsed }: { collapsed: boolean }) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        aria-label="Account menu"
        className={cn(
          "flex w-full items-center gap-3 rounded-md p-2 text-left transition-colors hover:bg-sidebar-accent/60 data-[state=open]:bg-sidebar-accent/60",
          collapsed && "justify-center",
        )}
      >
        <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-sidebar-accent text-muted-foreground">
          <User className="size-4" aria-hidden />
        </span>
        {!collapsed && (
          <>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm font-medium">Guest</span>
              <span className="block truncate text-xs text-muted-foreground">
                Not signed in
              </span>
            </span>
            <ChevronsUpDown className="size-4 shrink-0 text-muted-foreground" aria-hidden />
          </>
        )}
      </DropdownMenuTrigger>
      <DropdownMenuContent side={collapsed ? "right" : "top"} align="start" className="w-56">
        <DropdownMenuLabel>Not signed in</DropdownMenuLabel>
        <DropdownMenuItem asChild>
          <Link href="/settings">
            <Settings /> Settings
          </Link>
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem disabled>
          <LogIn /> Sign in with Google
          <span className="ml-auto text-xs text-muted-foreground">Soon</span>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
