import { useEffect } from "react";
import { describe, expect, it } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import { AuthProvider } from "@/components/providers/auth-provider";
import { useAuth } from "@/hooks/use-auth";
import { ApiError } from "@/lib/api/client";
import { getAccessToken, setAccessToken } from "@/lib/auth/session";
import { apiError, headerOf, inMinutes, json, makeJwt, mockBackend, USER } from "./helpers";

const holder: { value?: ReturnType<typeof useAuth> } = {};
const auth = () => holder.value!;

function Probe() {
  const current = useAuth();
  useEffect(() => {
    holder.value = current;
  });
  return (
    <div>
      <span data-testid="status">{current.status}</span>
      <span data-testid="name">{current.user?.name ?? "none"}</span>
      <span data-testid="expired">{String(current.sessionExpired)}</span>
    </div>
  );
}

const renderProvider = () =>
  render(
    <AuthProvider>
      <Probe />
    </AuthProvider>,
  );

const status = () => screen.getByTestId("status").textContent;

describe("AuthProvider: session restoration", () => {
  it("is unauthenticated without a stored token and makes no request", async () => {
    const { fetchMock } = mockBackend({});
    renderProvider();
    await waitFor(() => expect(status()).toBe("unauthenticated"));
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("validates a stored token with /auth/me and restores the user", async () => {
    const token = makeJwt(inMinutes(20));
    setAccessToken(token);
    const { calls } = mockBackend({ "/api/v1/auth/me": () => json(200, USER) });
    renderProvider();
    await waitFor(() => expect(status()).toBe("authenticated"));
    expect(screen.getByTestId("name").textContent).toBe("Ada Lovelace");
    expect(headerOf(calls[0].init, "Authorization")).toBe(`Bearer ${token}`);
  });

  it("logs out cleanly when the backend rejects the stored token", async () => {
    setAccessToken(makeJwt(inMinutes(20)));
    mockBackend({ "/api/v1/auth/me": () => apiError(401, "UNAUTHORIZED", "Invalid or expired authentication token") });
    renderProvider();
    await waitFor(() => expect(status()).toBe("unauthenticated"));
    expect(getAccessToken()).toBeNull();
    expect(screen.getByTestId("expired").textContent).toBe("true");
  });

  it("drops an already-expired token without calling the backend", async () => {
    setAccessToken(makeJwt(inMinutes(-1)));
    const { fetchMock } = mockBackend({});
    renderProvider();
    await waitFor(() => expect(status()).toBe("unauthenticated"));
    expect(fetchMock).not.toHaveBeenCalled();
    expect(getAccessToken()).toBeNull();
  });

  it("keeps the session and offers a retry when the backend is unreachable", async () => {
    const token = makeJwt(inMinutes(20));
    setAccessToken(token);
    let up = false;
    mockBackend({
      "/api/v1/auth/me": () => {
        if (!up) throw new TypeError("Failed to fetch");
        return json(200, USER);
      },
    });
    renderProvider();
    await waitFor(() => expect(status()).toBe("unavailable"));
    expect(getAccessToken()).toBe(token);

    up = true;
    act(() => auth().retry());
    await waitFor(() => expect(status()).toBe("authenticated"));
  });

  it("logs out automatically when the token reaches its expiry time", async () => {
    setAccessToken(makeJwt(Math.floor(Date.now() / 1000) + 2));
    mockBackend({ "/api/v1/auth/me": () => json(200, USER) });
    renderProvider();
    await waitFor(() => expect(status()).toBe("authenticated"));
    await waitFor(() => expect(status()).toBe("unauthenticated"), { timeout: 4000 });
    expect(getAccessToken()).toBeNull();
  });
});

describe("AuthProvider: sign in and sign out", () => {
  it("exchanges the Google token, loads /auth/me and stores only the Lumora token", async () => {
    const lumoraToken = makeJwt(inMinutes(30));
    const { calls } = mockBackend({
      "/api/v1/auth/google": () =>
        json(200, { access_token: lumoraToken, user: { id: USER.id, name: USER.name, email: USER.email } }),
      "/api/v1/auth/me": () => json(200, USER),
    });
    renderProvider();
    await waitFor(() => expect(status()).toBe("unauthenticated"));

    await act(() => auth().signIn("google-id-token"));

    expect(status()).toBe("authenticated");
    expect(JSON.parse(calls[0].init.body as string)).toEqual({ google_token: "google-id-token" });
    expect(headerOf(calls[0].init, "Authorization")).toBeUndefined();
    expect(headerOf(calls[1].init, "Authorization")).toBe(`Bearer ${lumoraToken}`);
    expect(getAccessToken()).toBe(lumoraToken);
    expect(JSON.stringify({ ...window.sessionStorage })).not.toContain("google-id-token");
  });

  it("surfaces a rejected Google token and stays signed out", async () => {
    mockBackend({
      "/api/v1/auth/google": () => apiError(401, "INVALID_GOOGLE_TOKEN", "Google authentication failed"),
    });
    renderProvider();
    await waitFor(() => expect(status()).toBe("unauthenticated"));

    let caught: unknown;
    await act(async () => {
      caught = await auth().signIn("bad").catch((e) => e);
    });
    expect(caught).toBeInstanceOf(ApiError);
    expect((caught as ApiError).code).toBe("INVALID_GOOGLE_TOKEN");
    expect(status()).toBe("unauthenticated");
    expect(getAccessToken()).toBeNull();
  });

  it("reports an unreachable backend during sign-in without leaving a session behind", async () => {
    mockBackend({
      "/api/v1/auth/google": () => {
        throw new TypeError("Failed to fetch");
      },
    });
    renderProvider();
    await waitFor(() => expect(status()).toBe("unauthenticated"));

    let caught: unknown;
    await act(async () => {
      caught = await auth().signIn("token").catch((e) => e);
    });
    expect((caught as ApiError).code).toBe("NETWORK_ERROR");
    expect(getAccessToken()).toBeNull();
  });

  it("removes the local session on sign out even if the backend logout fails", async () => {
    setAccessToken(makeJwt(inMinutes(20)));
    mockBackend({
      "/api/v1/auth/me": () => json(200, USER),
      "/api/v1/auth/logout": () => {
        throw new TypeError("Failed to fetch");
      },
    });
    renderProvider();
    await waitFor(() => expect(status()).toBe("authenticated"));

    await act(() => auth().signOut());

    expect(status()).toBe("unauthenticated");
    expect(getAccessToken()).toBeNull();
    expect(window.sessionStorage.length).toBe(0);
    expect(screen.getByTestId("expired").textContent).toBe("false");
  });
});
