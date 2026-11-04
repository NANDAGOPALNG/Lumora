"use client";

import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetTitle,
} from "@/components/ui/sheet";
import { SidebarContent } from "@/components/layout/sidebar-content";

interface MobileNavProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function MobileNav({ open, onOpenChange }: MobileNavProps) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="lg:hidden">
        <SheetTitle className="sr-only">Navigation</SheetTitle>
        <SheetDescription className="sr-only">
          Browse Lumora sections
        </SheetDescription>
        <SidebarContent instance="mobile" onNavigate={() => onOpenChange(false)} />
      </SheetContent>
    </Sheet>
  );
}
