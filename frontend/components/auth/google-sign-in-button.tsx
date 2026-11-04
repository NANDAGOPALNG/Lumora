"use client";

import { useEffect, useRef, useState } from "react";
import Script from "next/script";
import { useTheme } from "next-themes";
import { cn } from "@/lib/utils";

interface GoogleSignInButtonProps {
  clientId: string;
  /** Called with the Google ID token after the user completes Google sign-in. */
  onCredential: (idToken: string) => void;
  /** Called if Google's script cannot be loaded. */
  onLoadError: () => void;
  className?: string;
}

const GSI_SRC = "https://accounts.google.com/gsi/client";

/**
 * Renders Google's own sign-in button (popup flow). If the user closes the
 * Google popup, GIS reports nothing back, so the button simply stays usable.
 */
export function GoogleSignInButton({
  clientId,
  onCredential,
  onLoadError,
  className,
}: GoogleSignInButtonProps) {
  const { resolvedTheme } = useTheme();
  const containerRef = useRef<HTMLDivElement>(null);
  const callbackRef = useRef(onCredential);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    callbackRef.current = onCredential;
  }, [onCredential]);

  // Initialise GIS once the script is available.
  useEffect(() => {
    if (!ready || !window.google) return;
    window.google.accounts.id.initialize({
      client_id: clientId,
      ux_mode: "popup",
      auto_select: false,
      callback: (response) => callbackRef.current(response.credential),
    });
  }, [ready, clientId]);

  // (Re)render the button, matching the current theme.
  useEffect(() => {
    const container = containerRef.current;
    if (!ready || !window.google || !container) return;
    container.innerHTML = "";
    window.google.accounts.id.renderButton(container, {
      type: "standard",
      theme: resolvedTheme === "dark" ? "filled_black" : "outline",
      size: "large",
      text: "signin_with",
      shape: "rectangular",
      logo_alignment: "left",
      width: 320,
    });
  }, [ready, resolvedTheme, clientId]);

  return (
    <>
      <Script
        src={GSI_SRC}
        strategy="afterInteractive"
        onReady={() => setReady(true)}
        onError={onLoadError}
      />
      <div
        ref={containerRef}
        className={cn("flex min-h-10 justify-center", className)}
        aria-label="Sign in with Google"
      />
    </>
  );
}
