import { useEffect } from "react";
import { describe, expect, it } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import { AuthProvider } from "@/components/providers/auth-provider";
import { QueryProvider } from "@/components/providers/query-provider";
import { useAuth } from "@/hooks/use-auth";
import { useWorkspaceDocuments } from "@/hooks/use-documents";
import { setAccessToken } from "@/lib/auth/session";
import { json, USER } from "./helpers";
import { createFakeBackend, document, uuid, workspace } from "./fake-backend";

const BOB = { ...USER, id: "22222222-2222-4222-8222-222222222222", email: "bob@example.com", name: "Bob" };
const holder: { auth?: ReturnType<typeof useAuth> } = {};

function Probe({ workspaceId }: { workspaceId: string }) {
  const current = useAuth();
  useEffect(() => {
    holder.auth = current;
  });
  const { data } = useWorkspaceDocuments(workspaceId);
  return <p data-testid="names">{data ? data.map((d) => d.filename).join("|") : "none"}</p>;
}

describe("documents across sessions", () => {
  it("never shows one user's cached documents to the next user", async () => {
    const backend = createFakeBackend({
      users: { "token-ada": USER, "token-bob": BOB },
      workspaces: [workspace(1, "Ada WS", USER.id), workspace(2, "Bob WS", BOB.id)],
      documents: [document(1, 1, "ada-secret.txt"), document(2, 2, "bob-notes.txt")],
    });
    backend.state.override = (call) =>
      call.path === "/api/v1/auth/google"
        ? json(200, { access_token: "token-bob", user: { id: BOB.id, name: BOB.name, email: BOB.email } })
        : null;

    setAccessToken("token-ada");
    render(
      <AuthProvider>
        <QueryProvider>
          <Probe workspaceId={uuid(1)} />
        </QueryProvider>
      </AuthProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("names").textContent).toBe("ada-secret.txt"));

    await act(() => holder.auth!.signOut());
    expect(screen.getByTestId("names").textContent).toBe("none");

    // Bob signs in on the same tab and asks for Ada's workspace: the server refuses, and nothing cached leaks.
    await act(() => holder.auth!.signIn("google-id-token"));
    await waitFor(() => expect(screen.getByTestId("names").textContent).toBe("none"));
    expect(screen.queryByText(/ada-secret/)).toBeNull();
  });
});
