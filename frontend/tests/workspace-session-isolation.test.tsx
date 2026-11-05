import { useEffect } from "react";
import { describe, expect, it } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import { useQueryClient, type QueryClient } from "@tanstack/react-query";
import { AuthProvider } from "@/components/providers/auth-provider";
import { QueryProvider } from "@/components/providers/query-provider";
import { useAuth } from "@/hooks/use-auth";
import { useWorkspaces } from "@/hooks/use-workspaces";
import { getAccessToken, setAccessToken } from "@/lib/auth/session";
import { json, USER } from "./helpers";
import { createFakeBackend, workspace } from "./fake-backend";

const BOB = { ...USER, id: "22222222-2222-4222-8222-222222222222", email: "bob@example.com", name: "Bob" };

const holder: { auth?: ReturnType<typeof useAuth>; client?: QueryClient } = {};
const auth = () => holder.auth!;
const client = () => holder.client!;

function Probe() {
  const currentAuth = useAuth();
  const currentClient = useQueryClient();
  useEffect(() => {
    holder.auth = currentAuth;
    holder.client = currentClient;
  });
  const { data } = useWorkspaces();
  return <p data-testid="names">{data ? data.map((w) => w.name).join("|") : "none"}</p>;
}

describe("workspace data across sessions", () => {
  it("clears cached workspaces on sign-out so the next user never sees them", async () => {
    const backend = createFakeBackend({
      users: { "token-ada": USER, "token-bob": BOB },
      workspaces: [workspace(1, "Ada private", USER.id), workspace(2, "Bob private", BOB.id)],
    });
    backend.state.override = (call) =>
      call.path === "/api/v1/auth/google"
        ? json(200, { access_token: "token-bob", user: { id: BOB.id, name: BOB.name, email: BOB.email } })
        : null;

    setAccessToken("token-ada");
    render(
      <AuthProvider>
        <QueryProvider>
          <Probe />
        </QueryProvider>
      </AuthProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("names").textContent).toBe("Ada private"));

    await act(() => auth().signOut());
    expect(getAccessToken()).toBeNull();
    expect(screen.getByTestId("names").textContent).toBe("none");
    // No cached workspace data may survive (a disabled, empty placeholder query is fine).
    await waitFor(() =>
      expect(client().getQueryCache().getAll().every((q) => q.state.data === undefined)).toBe(true),
    );

    await act(() => auth().signIn("google-id-token"));
    await waitFor(() => expect(screen.getByTestId("names").textContent).toBe("Bob private"));
    expect(screen.queryByText(/Ada private/)).toBeNull();
  });
});
