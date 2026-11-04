"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { CloudOff } from "lucide-react";
import { useAuth } from "@/hooks/use-auth";
import { AuthLoadingScreen } from "@/components/auth/auth-loading-screen";
import { Button } from "@/components/ui/button";

/**
 * Protects the (app) routes. Children render only once the session has been
 * verified against the backend, so protected UI never flashes for guests.
 */
export function AuthGuard({ children }: { children: React.ReactNode }) {
  const { status, retry } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (status === "unauthenticated") router.replace("/login");
  }, [status, router]);

  if (status === "authenticated") return <>{children}</>;

  if (status === "unavailable") {
    return (
      <div className="flex min-h-dvh flex-col items-center justify-center gap-5 px-6 text-center">
        <span className="flex size-10 items-center justify-center rounded-lg bg-secondary text-muted-foreground">
          <CloudOff className="size-5" aria-hidden />
        </span>
        <div className="space-y-1.5">
          <h1 className="font-serif text-2xl font-medium tracking-tight">
            Can&apos;t reach Lumora
          </h1>
          <p className="max-w-sm text-sm text-muted-foreground">
            We couldn&apos;t verify your session because the server didn&apos;t respond.
            You haven&apos;t been signed out.
          </p>
        </div>
        <Button onClick={retry}>Try again</Button>
      </div>
    );
  }

  // "loading", or "unauthenticated" while the redirect to /login happens.
  return <AuthLoadingScreen label={status === "loading" ? "Checking your session" : "Redirecting to sign in"} />;
}

/** Wraps the login route: signed-in users are sent to the dashboard. */
export function GuestGuard({ children }: { children: React.ReactNode }) {
  const { status } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (status === "authenticated") router.replace("/");
  }, [status, router]);

  if (status === "unauthenticated" || status === "unavailable") return <>{children}</>;

  return <AuthLoadingScreen label={status === "loading" ? "Loading" : "Opening your dashboard"} />;
}
