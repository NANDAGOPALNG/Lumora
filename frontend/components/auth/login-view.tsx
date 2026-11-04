"use client";

import { useCallback, useState } from "react";
import { FileSearch, MessageSquareQuote, TriangleAlert } from "lucide-react";
import { useAuth } from "@/hooks/use-auth";
import { ApiError, NETWORK_ERROR } from "@/lib/api/client";
import { Logo } from "@/components/layout/logo";
import { GoogleSignInButton } from "@/components/auth/google-sign-in-button";
import { Button } from "@/components/ui/button";

const highlights = [
  {
    icon: FileSearch,
    title: "Search everything you've indexed",
    text: "Find the exact passage across your documents in seconds.",
  },
  {
    icon: MessageSquareQuote,
    title: "Answers that show their sources",
    text: "Every reply points back to the files it came from.",
  },
] as const;

function describeError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === NETWORK_ERROR) {
      return "Can't reach the Lumora server. Check that it's running and try again.";
    }
    if (error.code === "INVALID_GOOGLE_TOKEN") {
      return "Google sign-in couldn't be verified. Please try again.";
    }
    if (error.status === 0) return error.message;
    if (error.status >= 500) return "Something went wrong on our side. Please try again shortly.";
    return error.message;
  }
  return "Sign-in failed. Please try again.";
}

export function LoginView() {
  const { signIn, sessionExpired } = useAuth();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Next.js inlines this at build time; it must be referenced literally.
  const clientId = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID;
  const apiConfigured = Boolean(process.env.NEXT_PUBLIC_API_BASE_URL);

  const handleCredential = useCallback(
    async (idToken: string) => {
      setError(null);
      setPending(true);
      try {
        await signIn(idToken);
        // The guest guard redirects to the dashboard once the session is established.
      } catch (err) {
        setError(describeError(err));
        setPending(false);
      }
    },
    [signIn],
  );

  const configError = !clientId
    ? "Google sign-in isn't configured. Set NEXT_PUBLIC_GOOGLE_CLIENT_ID in frontend/.env.local and restart the dev server."
    : !apiConfigured
      ? "The API address isn't configured. Set NEXT_PUBLIC_API_BASE_URL in frontend/.env.local and restart the dev server."
      : null;

  const notice = error ?? configError;

  return (
    <main className="grid min-h-dvh lg:grid-cols-[1.1fr_1fr]">
      <section className="hidden flex-col justify-between border-r border-sidebar-border bg-sidebar p-12 lg:flex">
        <Logo />
        <div className="max-w-md space-y-10">
          <h1 className="font-serif text-5xl font-medium leading-[1.08] tracking-tight text-balance">
            Answers from your own documents.
          </h1>
          <ul className="space-y-6">
            {highlights.map(({ icon: Icon, title, text }) => (
              <li key={title} className="flex gap-4">
                <span className="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-lg bg-sidebar-accent text-muted-foreground">
                  <Icon className="size-[18px]" aria-hidden />
                </span>
                <div>
                  <p className="text-sm font-medium">{title}</p>
                  <p className="text-sm text-muted-foreground">{text}</p>
                </div>
              </li>
            ))}
          </ul>
        </div>
        <p className="text-xs text-muted-foreground">Lumora knowledge platform</p>
      </section>

      <section className="flex flex-col px-6 py-8 sm:px-12">
        <div className="lg:hidden">
          <Logo />
        </div>
        <div className="mx-auto flex w-full max-w-sm flex-1 flex-col justify-center py-12">
          <div className="space-y-2">
            <h2 className="font-serif text-3xl font-medium tracking-tight">Sign in</h2>
            <p className="text-sm text-muted-foreground">
              Use your Google account to open your workspaces.
            </p>
          </div>

          {sessionExpired && !notice && (
            <p className="mt-6 rounded-lg border bg-secondary px-3.5 py-3 text-sm" role="status">
              Your session ended. Please sign in again.
            </p>
          )}

          {notice && (
            <div
              role="alert"
              className="mt-6 flex gap-3 rounded-lg border border-destructive/30 bg-destructive/5 px-3.5 py-3 text-sm"
            >
              <TriangleAlert className="mt-0.5 size-4 shrink-0 text-destructive" aria-hidden />
              <p>{notice}</p>
            </div>
          )}

          <div className="mt-8">
            {pending && (
              <Button loading disabled className="w-full" size="lg">
                Signing you in
              </Button>
            )}
            {clientId && apiConfigured && (
              <GoogleSignInButton
                clientId={clientId}
                onCredential={(token) => void handleCredential(token)}
                onLoadError={() =>
                  setError(
                    "Couldn't load Google sign-in. Check your connection or ad blocker, then reload.",
                  )
                }
                className={pending ? "hidden" : undefined}
              />
            )}
          </div>

          <p className="mt-8 text-xs leading-relaxed text-muted-foreground">
            We only receive your name, email and profile picture from Google.
          </p>
        </div>
      </section>
    </main>
  );
}
