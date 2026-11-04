import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { AuthContext, type AuthContextValue } from "@/components/providers/auth-provider";
import { AuthGuard, GuestGuard } from "@/components/auth/auth-guard";

const replace = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace }) }));

const baseValue: AuthContextValue = {
  status: "loading",
  user: null,
  sessionExpired: false,
  signIn: vi.fn(),
  signOut: vi.fn(),
  retry: vi.fn(),
};

const withAuth = (value: Partial<AuthContextValue>, ui: React.ReactNode) =>
  render(<AuthContext.Provider value={{ ...baseValue, ...value }}>{ui}</AuthContext.Provider>);

beforeEach(() => replace.mockClear());

describe("AuthGuard (protected routes)", () => {
  it("redirects guests to /login and never renders protected content", () => {
    withAuth({ status: "unauthenticated" }, <AuthGuard>secret dashboard</AuthGuard>);
    expect(replace).toHaveBeenCalledWith("/login");
    expect(screen.queryByText("secret dashboard")).toBeNull();
  });

  it("shows a loading screen while the session is checked, with no redirect and no content", () => {
    withAuth({ status: "loading" }, <AuthGuard>secret dashboard</AuthGuard>);
    expect(screen.getByText(/Checking your session/)).toBeTruthy();
    expect(replace).not.toHaveBeenCalled();
    expect(screen.queryByText("secret dashboard")).toBeNull();
  });

  it("renders content for an authenticated user", () => {
    withAuth({ status: "authenticated" }, <AuthGuard>secret dashboard</AuthGuard>);
    expect(screen.getByText("secret dashboard")).toBeTruthy();
    expect(replace).not.toHaveBeenCalled();
  });

  it("shows a retry screen (not a logout) when the backend is unreachable", () => {
    const retry = vi.fn();
    withAuth({ status: "unavailable", retry }, <AuthGuard>secret dashboard</AuthGuard>);
    expect(screen.queryByText("secret dashboard")).toBeNull();
    expect(replace).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(retry).toHaveBeenCalledOnce();
  });
});

describe("GuestGuard (login route)", () => {
  it("sends signed-in users to the dashboard", () => {
    withAuth({ status: "authenticated" }, <GuestGuard>login form</GuestGuard>);
    expect(replace).toHaveBeenCalledWith("/");
    expect(screen.queryByText("login form")).toBeNull();
  });

  it("shows the login form to guests without redirecting (no loop)", () => {
    withAuth({ status: "unauthenticated" }, <GuestGuard>login form</GuestGuard>);
    expect(screen.getByText("login form")).toBeTruthy();
    expect(replace).not.toHaveBeenCalled();
  });
});
