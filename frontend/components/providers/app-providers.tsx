"use client";

import { MotionConfig } from "motion/react";
import { ThemeProvider } from "next-themes";
import { AuthProvider } from "@/components/providers/auth-provider";
import { QueryProvider } from "@/components/providers/query-provider";
import { Toaster } from "@/components/ui/sonner";

export function AppProviders({ children }: { children: React.ReactNode }) {
  return (
    <ThemeProvider
      attribute="class"
      defaultTheme="system"
      enableSystem
      disableTransitionOnChange
    >
      <MotionConfig reducedMotion="user">
        <AuthProvider>
          <QueryProvider>{children}</QueryProvider>
        </AuthProvider>
        <Toaster position="bottom-right" />
      </MotionConfig>
    </ThemeProvider>
  );
}
