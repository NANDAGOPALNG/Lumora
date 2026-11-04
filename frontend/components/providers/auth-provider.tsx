"use client";

import {
  createContext,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { UserResponse } from "@/types/api";
import * as authApi from "@/lib/api/auth";
import { ApiError, NETWORK_ERROR, setUnauthorizedHandler } from "@/lib/api/client";
import {
  clearAccessToken,
  getAccessToken,
  getTokenExpiryMs,
  isTokenExpired,
  setAccessToken,
} from "@/lib/auth/session";

export type AuthStatus =
  | "loading"
  | "authenticated"
  | "unauthenticated"
  /** A session token exists but the backend could not be reached to verify it. */
  | "unavailable";

export interface AuthContextValue {
  status: AuthStatus;
  user: UserResponse | null;
  /** Set when a session ended because it expired or was rejected. */
  sessionExpired: boolean;
  /** Exchange a Google ID token for a Lumora session. Throws ApiError on failure. */
  signIn: (googleIdToken: string) => Promise<void>;
  signOut: () => Promise<void>;
  /** Re-check the stored session (used by the "unavailable" retry screen). */
  retry: () => void;
}

export const AuthContext = createContext<AuthContextValue | null>(null);

// setTimeout overflows above ~24.8 days; tokens are far shorter, but be safe.
const MAX_TIMER_MS = 2 ** 31 - 1;

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [user, setUser] = useState<UserResponse | null>(null);
  const [sessionExpired, setSessionExpired] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const signingIn = useRef(false);

  const endSession = useCallback((expired: boolean) => {
    clearAccessToken();
    setUser(null);
    setSessionExpired(expired);
    setStatus("unauthenticated");
  }, []);

  // The API client reports a rejected session (401) here.
  useEffect(() => {
    setUnauthorizedHandler(() => endSession(true));
    return () => setUnauthorizedHandler(null);
  }, [endSession]);

  // Restore the session on load: validate the stored token against /auth/me.
  useEffect(() => {
    const controller = new AbortController();

    async function restore() {
      const token = getAccessToken();
      if (!token) {
        setStatus("unauthenticated");
        return;
      }
      if (isTokenExpired(token)) {
        endSession(true);
        return;
      }
      setStatus("loading");
      try {
        const profile = await authApi.getCurrentUser(controller.signal);
        setUser(profile);
        setStatus("authenticated");
      } catch (error) {
        if (controller.signal.aborted) return;
        // A 401 has already been handled by the client (session cleared).
        if (error instanceof ApiError && error.code === NETWORK_ERROR) {
          setStatus("unavailable");
        } else if (!(error instanceof ApiError && error.status === 401)) {
          // Any other failure: do not trust or keep a session we cannot verify.
          endSession(false);
        }
      }
    }

    void restore();
    return () => controller.abort();
  }, [attempt, endSession]);

  // Clean logout at the token's own expiry time.
  useEffect(() => {
    if (status !== "authenticated") return;
    const token = getAccessToken();
    const expiry = token ? getTokenExpiryMs(token) : null;
    if (expiry === null) return;
    const delay = Math.min(Math.max(expiry - Date.now(), 0), MAX_TIMER_MS);
    const timer = window.setTimeout(() => endSession(true), delay);
    return () => window.clearTimeout(timer);
  }, [status, endSession]);

  const signIn = useCallback(
    async (googleIdToken: string) => {
      if (signingIn.current) return;
      signingIn.current = true;
      try {
        const result = await authApi.loginWithGoogle(googleIdToken);
        setAccessToken(result.access_token);
        // Always load the full profile from the backend rather than trusting the login summary.
        const profile = await authApi.getCurrentUser();
        setUser(profile);
        setSessionExpired(false);
        setStatus("authenticated");
      } catch (error) {
        clearAccessToken();
        throw error;
      } finally {
        signingIn.current = false;
      }
    },
    [],
  );

  const signOut = useCallback(async () => {
    try {
      await authApi.logout();
    } catch {
      // The backend is stateless; the local session is removed regardless.
    }
    endSession(false);
  }, [endSession]);

  const retry = useCallback(() => setAttempt((n) => n + 1), []);

  const value = useMemo<AuthContextValue>(
    () => ({ status, user, sessionExpired, signIn, signOut, retry }),
    [status, user, sessionExpired, signIn, signOut, retry],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
