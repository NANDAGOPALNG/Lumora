import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { AuthContext, type AuthContextValue } from "@/components/providers/auth-provider";
import { LoginView } from "@/components/auth/login-view";
import { ApiError } from "@/lib/api/client";

// The real button loads Google's script; replace it with a stand-in that
// delivers a credential the same way GIS does.
vi.mock("@/components/auth/google-sign-in-button", () => ({
  GoogleSignInButton: ({ onCredential, onLoadError }: { onCredential: (t: string) => void; onLoadError: () => void }) => (
    <div>
      <button onClick={() => onCredential("google-id-token")}>Google button</button>
      <button onClick={onLoadError}>Script failed</button>
    </div>
  ),
}));

const value = (overrides: Partial<AuthContextValue> = {}): AuthContextValue => ({
  status: "unauthenticated",
  user: null,
  sessionExpired: false,
  signIn: vi.fn().mockResolvedValue(undefined),
  signOut: vi.fn(),
  retry: vi.fn(),
  ...overrides,
});

const renderLogin = (overrides?: Partial<AuthContextValue>) => {
  const ctx = value(overrides);
  render(
    <AuthContext.Provider value={ctx}>
      <LoginView />
    </AuthContext.Provider>,
  );
  return ctx;
};

describe("LoginView", () => {
  it("renders branding, description and the Google button", () => {
    renderLogin();
    expect(screen.getAllByText("Lumora").length).toBeGreaterThan(0);
    expect(screen.getByText("Answers from your own documents.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Google button" })).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("passes the Google credential to signIn and shows a loading state", async () => {
    let resolve!: () => void;
    const signIn = vi.fn(() => new Promise<void>((r) => (resolve = r)));
    renderLogin({ signIn });
    fireEvent.click(screen.getByRole("button", { name: "Google button" }));
    expect(signIn).toHaveBeenCalledWith("google-id-token");
    await waitFor(() => expect(screen.getByRole("button", { name: /Signing you in/ })).toBeTruthy());
    resolve();
  });

  it("stays idle when the user cancels Google sign-in (no credential delivered)", () => {
    const ctx = renderLogin();
    expect(screen.queryByRole("button", { name: /Signing you in/ })).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(ctx.signIn).not.toHaveBeenCalled();
  });

  it("explains an unreachable backend and lets the user retry", async () => {
    const signIn = vi.fn().mockRejectedValue(new ApiError(0, "NETWORK_ERROR", "x"));
    renderLogin({ signIn });
    fireEvent.click(screen.getByRole("button", { name: "Google button" }));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Can't reach the Lumora server");
    expect(screen.getByRole("button", { name: "Google button" })).toBeTruthy();
  });

  it("explains a rejected Google token", async () => {
    const signIn = vi.fn().mockRejectedValue(new ApiError(401, "INVALID_GOOGLE_TOKEN", "Google authentication failed"));
    renderLogin({ signIn });
    fireEvent.click(screen.getByRole("button", { name: "Google button" }));
    expect((await screen.findByRole("alert")).textContent).toContain("couldn't be verified");
  });

  it("reports when Google's script fails to load", async () => {
    renderLogin();
    fireEvent.click(screen.getByRole("button", { name: "Script failed" }));
    expect((await screen.findByRole("alert")).textContent).toContain("Couldn't load Google sign-in");
  });

  it("tells the user when their session ended", () => {
    renderLogin({ sessionExpired: true });
    expect(screen.getByRole("status").textContent).toContain("session ended");
  });

  it("shows a configuration error instead of a broken button when the client ID is missing", () => {
    vi.stubEnv("NEXT_PUBLIC_GOOGLE_CLIENT_ID", "");
    renderLogin();
    expect(screen.getByRole("alert").textContent).toContain("NEXT_PUBLIC_GOOGLE_CLIENT_ID");
    expect(screen.queryByRole("button", { name: "Google button" })).toBeNull();
  });
});
