import { useEffect } from "react";
import { describe, expect, it } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import { AuthProvider } from "@/components/providers/auth-provider";
import { QueryProvider } from "@/components/providers/query-provider";
import { useAuth } from "@/hooks/use-auth";
import { useKnowledgeSearch } from "@/hooks/use-search";
import { setAccessToken } from "@/lib/auth/session";
import { json, USER } from "./helpers";
import { createFakeBackend, uuid, workspace } from "./fake-backend";

const BOB = { ...USER, id: "22222222-2222-4222-8222-222222222222", email: "bob@example.com", name: "Bob" };
const holder: { auth?: ReturnType<typeof useAuth> } = {};
const params = { query: "auth", workspaceId: uuid(1), documentId: null, topK: 5 };

function Probe() {
  const auth = useAuth();
  useEffect(() => {
    holder.auth = auth;
  });
  const query = useKnowledgeSearch(params);
  return (
    <p data-testid="state">
      {query.data ? `results:${query.data.sources.length}` : query.isError ? "error" : "none"}
    </p>
  );
}

describe("search across sessions", () => {
  it("never reuses one user's cached results for the next user", async () => {
    const backend = createFakeBackend({
      users: { "token-ada": USER, "token-bob": BOB },
      workspaces: [workspace(1, "Ada WS", USER.id)],
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
    await waitFor(() => expect(screen.getByTestId("state").textContent).toBe("results:2"));

    await act(() => holder.auth!.signOut());
    expect(screen.getByTestId("state").textContent).toBe("none");

    // Bob asks for Ada's workspace with identical inputs: the server refuses; nothing cached leaks.
    await act(() => holder.auth!.signIn("google-id-token"));
    await waitFor(() => expect(screen.getByTestId("state").textContent).toBe("error"));
    expect(backend.callsTo("POST", "/api/v1/search")).toHaveLength(2);
  });
});
