import type {
  GoogleAuthRequest,
  GoogleAuthResponse,
  UserResponse,
} from "@/types/api";
import { apiFetch } from "@/lib/api/client";

/** Exchange a Google ID token for a Lumora access token. */
export function loginWithGoogle(googleToken: string) {
  const body: GoogleAuthRequest = { google_token: googleToken };
  return apiFetch<GoogleAuthResponse>("/api/v1/auth/google", {
    method: "POST",
    body,
    auth: false,
  });
}

export function getCurrentUser(signal?: AbortSignal) {
  return apiFetch<UserResponse>("/api/v1/auth/me", { signal });
}

/** The backend is stateless; this only confirms the session. Callers must clear it locally. */
export function logout() {
  return apiFetch<{ message: string }>("/api/v1/auth/logout", { method: "POST" });
}
