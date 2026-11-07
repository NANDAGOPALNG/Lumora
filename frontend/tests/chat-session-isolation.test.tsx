import { useEffect } from "react";
import { describe, expect, it } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import { AuthProvider } from "@/components/providers/auth-provider";
import { QueryProvider } from "@/components/providers/query-provider";
import { useAuth } from "@/hooks/use-auth";
import { useChatSources, useConversations, useSendMessage } from "@/hooks/use-chat";
import { setAccessToken } from "@/lib/auth/session";
import { json, USER } from "./helpers";
import { conversation, createFakeBackend, source, uuid, workspace } from "./fake-backend";

const BOB = { ...USER, id: "22222222-2222-4222-8222-222222222222", email: "bob@example.com", name: "Bob" };
const holder: { auth?: ReturnType<typeof useAuth>; send?: ReturnType<typeof useSendMessage> } = {};

function Probe() {
  const auth = useAuth();
  const send = useSendMessage();
  const history = useConversations();
  const sources = useChatSources();
  useEffect(() => {
    holder.auth = auth;
    holder.send = send;
  });
  return (
    <>
      <p data-testid="history">{history.data ? history.data.map((c) => c.id).join("|") : "none"}</p>
      <p data-testid="sources">{JSON.stringify(Object.keys(sources))}</p>
    </>
  );
}

describe("chat data across sessions", () => {
  it("never shows one user's conversations or cached sources to the next user", async () => {
    const backend = createFakeBackend({
      users: { "token-ada": USER, "token-bob": BOB },
      workspaces: [workspace(1, "Ada WS", USER.id), workspace(2, "Bob WS", BOB.id)],
      conversations: [conversation(1, [["ada q", "ada a"]], USER.id), conversation(2, [["bob q", "bob a"]], BOB.id)],
    });
    backend.state.chatAnswer = () => ({ answer: "ok", sources: [source(1, "a.pdf")] });
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
    await waitFor(() => expect(screen.getByTestId("history").textContent).toBe(uuid(8001)));

    await act(() => holder.send!.mutateAsync({ query: "hello", workspaceId: uuid(1) }));
    await waitFor(() => expect(screen.getByTestId("sources").textContent).not.toBe("[]"));

    await act(() => holder.auth!.signOut());
    expect(screen.getByTestId("history").textContent).toBe("none");
    expect(screen.getByTestId("sources").textContent).toBe("[]");

    await act(() => holder.auth!.signIn("google-id-token"));
    await waitFor(() => expect(screen.getByTestId("history").textContent).toBe(uuid(8002)));
    expect(screen.getByTestId("sources").textContent).toBe("[]");
  });
});
