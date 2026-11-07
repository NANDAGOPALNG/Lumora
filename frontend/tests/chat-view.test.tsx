import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { ChatView } from "@/components/chat/chat-view";
import { getAccessToken } from "@/lib/auth/session";
import { apiError } from "./helpers";
import { conversation, createFakeBackend, document, source, uuid, workspace } from "./fake-backend";
import { currentSearch, resetNavigation, setNavigationDelay, setSearch } from "./navigation-mock";
import { renderApp } from "./render-app";
import { deferred, dialog } from "./ui-helpers";

vi.mock("next/navigation", async () => await import("./navigation-mock"));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() }, Toaster: () => null }));

beforeEach(() => resetNavigation());

type Options = Parameters<typeof createFakeBackend>[0];
const workspaces = () => [workspace(1, "Alpha"), workspace(2, "Beta"), workspace(3, "Foreign", "someone-else")];
const documents = () => [
  document(1, 1, "indexed.txt", "Indexed"),
  document(2, 1, "waiting.txt", "Uploaded", { chunk_count: 0 }),
  document(3, 1, "broken.txt", "Failed", { chunk_count: 0 }),
  document(4, 2, "beta.pdf", "Indexed"),
];
const history = () => [
  conversation(1, [["old question", "old answer"]], undefined, "2026-10-01T09:00:00+00:00"),
  conversation(3, [["newer question", "newer answer"]], undefined, "2026-10-03T09:00:00+00:00"),
  conversation(9, [["someone else's question", "secret"]], "someone-else"),
];

function setup(options: Options = {}) {
  const backend = createFakeBackend({ workspaces: workspaces(), documents: documents(), ...options });
  renderApp(<ChatView />);
  return backend;
}

const question = () => screen.getByLabelText("Your question") as HTMLTextAreaElement;
const sendButton = () => screen.getByRole("button", { name: "Send message" }) as HTMLButtonElement;
const selectWorkspace = async (id: string) => {
  await screen.findByRole("option", { name: "Alpha" });
  fireEvent.change(screen.getByLabelText("Workspace"), { target: { value: id } });
};
const ask = (text: string) => {
  fireEvent.change(question(), { target: { value: text } });
  fireEvent.click(sendButton());
};
// hidden: true so rows stay queryable while a modal dialog hides the page behind it.
const rows = () =>
  within(screen.getByRole("list", { name: "Conversations", hidden: true })).getAllByRole("listitem", { hidden: true });
const openRow = (index: number) =>
  fireEvent.click(within(rows()[index]).getAllByRole("button", { hidden: true })[0]);
const rowActions = (index: number) =>
  within(rows()[index]).getByRole("button", { name: /^Actions for/, hidden: true });
const posts = (backend: ReturnType<typeof createFakeBackend>) => backend.callsTo("POST", "/api/v1/chat");

describe("rendering", () => {
  it("renders the chat page with an empty conversation, history area and composer", async () => {
    setup();
    expect(screen.getByRole("heading", { level: 1, name: "AI Chat" })).toBeTruthy();
    expect(await screen.findByText("Ask your documents")).toBeTruthy();
    expect(screen.getByRole("button", { name: /New conversation/ })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Conversations" })).toBeTruthy();
    expect(sendButton().disabled).toBe(true);
  });

  it("explains that a workspace is needed when the user has none", async () => {
    setup({ workspaces: [] });
    expect(await screen.findByText("Create a workspace first")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Go to workspaces" }).getAttribute("href")).toBe("/workspaces");
  });
});

describe("workspace and document selection", () => {
  it("requires choosing a workspace when there are several, and only offers the user's own", async () => {
    setup();
    await screen.findByRole("option", { name: "Alpha" });
    expect(screen.getByRole("option", { name: "Beta" })).toBeTruthy();
    expect(screen.queryByRole("option", { name: "Foreign" })).toBeNull();
    expect(question().disabled).toBe(true);
    expect(question().placeholder).toMatch(/Choose a workspace/);
    expect(sendButton().disabled).toBe(true);

    fireEvent.change(screen.getByLabelText("Workspace"), { target: { value: uuid(1) } });
    expect(question().disabled).toBe(false);
    fireEvent.change(question(), { target: { value: "hello" } });
    expect(sendButton().disabled).toBe(false);
  });

  it("preselects the only workspace", async () => {
    setup({ workspaces: [workspace(1, "Solo")] });
    await waitFor(() => expect((screen.getByLabelText("Workspace") as HTMLSelectElement).value).toBe(uuid(1)));
    expect(question().disabled).toBe(false);
  });

  it("offers only indexed documents of the chosen workspace, and resets the choice when the workspace changes", async () => {
    setup();
    await selectWorkspace(uuid(1));
    await screen.findByRole("option", { name: "indexed.txt" });
    expect(screen.queryByRole("option", { name: "waiting.txt" })).toBeNull();
    expect(screen.queryByRole("option", { name: "broken.txt" })).toBeNull();
    expect(screen.queryByRole("option", { name: "beta.pdf" })).toBeNull();

    fireEvent.change(screen.getByLabelText("Document"), { target: { value: uuid(1001) } });
    expect((screen.getByLabelText("Document") as HTMLSelectElement).value).toBe(uuid(1001));

    fireEvent.change(screen.getByLabelText("Workspace"), { target: { value: uuid(2) } });
    await screen.findByRole("option", { name: "beta.pdf" });
    expect((screen.getByLabelText("Document") as HTMLSelectElement).value).toBe("");
  });

  it("warns when the workspace has no indexed documents", async () => {
    setup({ documents: [document(2, 1, "waiting.txt", "Uploaded", { chunk_count: 0 })] });
    await selectWorkspace(uuid(1));
    expect(await screen.findByText(/no indexed documents yet/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "Add documents" }).getAttribute("href")).toBe(`/workspaces/${uuid(1)}`);
  });
});

describe("sending a new message", () => {
  it("shows the question at once, then the answer, and records the conversation", async () => {
    const backend = setup();
    const gate = deferred();
    backend.state.chatGate = () => gate.promise;
    await selectWorkspace(uuid(1));

    ask("What is the leave policy?");
    expect(await screen.findByText("What is the leave policy?")).toBeTruthy();
    expect(screen.getByText(/Searching your documents/)).toBeTruthy();
    expect(question().value).toBe(""); // cleared once sent
    expect(sendButton().disabled).toBe(true);

    gate.resolve();
    expect(await screen.findByText("Answer to: What is the leave policy?")).toBeTruthy();
    expect(screen.queryByText(/Searching your documents/)).toBeNull();
    expect(posts(backend)[0].body).toEqual({ query: "What is the leave policy?", workspace_id: uuid(1) });
    await waitFor(() => expect(currentSearch()).toBe(uuid(8500)));
    expect(rows()).toHaveLength(1); // it now appears in the history without a refetch
    expect(backend.callsTo("GET", "/api/v1/chat/history")).toHaveLength(1);
  });

  it("keeps showing the conversation while the URL catches up (no empty-state flash)", async () => {
    setNavigationDelay(60);
    setup();
    await selectWorkspace(uuid(1));
    ask("Quick question");
    expect(await screen.findByText("Answer to: Quick question")).toBeTruthy();
    expect(currentSearch()).toBeNull(); // the URL hasn't changed yet
    expect(screen.queryByText("Ask your documents")).toBeNull();
    await waitFor(() => expect(currentSearch()).toBe(uuid(8500)));
    expect(screen.getByText("Answer to: Quick question")).toBeTruthy();
  });

  it("restricts the question to the chosen document", async () => {
    const backend = setup();
    await selectWorkspace(uuid(1));
    await screen.findByRole("option", { name: "indexed.txt" });
    fireEvent.change(screen.getByLabelText("Document"), { target: { value: uuid(1001) } });
    ask("About this file");
    await screen.findByText("Answer to: About this file");
    expect(posts(backend)[0].body).toEqual({ query: "About this file", workspace_id: uuid(1), document_id: uuid(1001) });
  });

  it("sends with Enter, keeps Shift+Enter for new lines, and ignores blank messages", async () => {
    const backend = setup({ workspaces: [workspace(1, "Solo")] });
    await waitFor(() => expect(question().disabled).toBe(false));

    fireEvent.change(question(), { target: { value: "   " } });
    expect(sendButton().disabled).toBe(true);
    fireEvent.keyDown(question(), { key: "Enter" });
    expect(posts(backend)).toHaveLength(0);

    fireEvent.change(question(), { target: { value: "line one" } });
    fireEvent.keyDown(question(), { key: "Enter", shiftKey: true });
    expect(posts(backend)).toHaveLength(0);

    fireEvent.keyDown(question(), { key: "Enter" });
    await screen.findByText("Answer to: line one");
    expect(posts(backend)).toHaveLength(1);
  });

  it("never sends a second request while one is in flight", async () => {
    const backend = setup({ workspaces: [workspace(1, "Solo")] });
    const gate = deferred();
    backend.state.chatGate = () => gate.promise;
    await waitFor(() => expect(question().disabled).toBe(false));
    ask("Only once");
    await screen.findByText(/Searching your documents/);
    expect(question().disabled).toBe(true);
    fireEvent.click(sendButton());
    fireEvent.keyDown(question(), { key: "Enter" });
    gate.resolve();
    await screen.findByText("Answer to: Only once");
    expect(posts(backend)).toHaveLength(1);
  });
});

describe("failures", () => {
  it("explains a rate limit, lets the user retry, and never duplicates the question", async () => {
    const backend = setup({ workspaces: [workspace(1, "Solo")] });
    backend.state.override = (call) =>
      call.path === "/api/v1/chat" ? apiError(429, "TOO_MANY_REQUESTS", "The language model is temporarily rate-limited.") : null;
    await waitFor(() => expect(question().disabled).toBe(false));
    ask("Will it work?");

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toMatch(/busy right now/);
    expect(alert.textContent).toMatch(/Nothing was saved/);
    expect(screen.getAllByText("Will it work?", { selector: "p" })).toHaveLength(1);

    backend.state.override = null;
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("Answer to: Will it work?")).toBeTruthy();
    // One message bubble (the sidebar also labels the conversation with this question).
    expect(screen.getAllByText("Will it work?", { selector: "p" })).toHaveLength(1);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(backend.state.conversations).toHaveLength(1);
  });

  it("restores the message for editing", async () => {
    const backend = setup({ workspaces: [workspace(1, "Solo")] });
    backend.state.override = (call) =>
      call.path === "/api/v1/chat" ? apiError(500, "LLM_GENERATION_FAILED", "Failed to generate an answer. Please try again.") : null;
    await waitFor(() => expect(question().disabled).toBe(false));
    ask("Edit me");
    expect((await screen.findByRole("alert")).textContent).toMatch(/couldn’t generate an answer/);
    fireEvent.click(screen.getByRole("button", { name: "Edit message" }));
    expect(question().value).toBe("Edit me");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("reports an unreachable server without logging out", async () => {
    const backend = setup({ workspaces: [workspace(1, "Solo")] });
    await waitFor(() => expect(question().disabled).toBe(false));
    backend.state.down = true;
    ask("Anyone there?");
    expect((await screen.findByRole("alert")).textContent).toMatch(/Can’t reach the Lumora server/);
    expect(getAccessToken()).toBe("token-ada");
  });

  it("ends the session when the chat endpoint answers 401", async () => {
    const backend = setup({ workspaces: [workspace(1, "Solo")] });
    await waitFor(() => expect(question().disabled).toBe(false));
    backend.state.override = (call) =>
      call.path === "/api/v1/chat" ? apiError(401, "UNAUTHORIZED", "Invalid or expired authentication token") : null;
    ask("Expired?");
    await waitFor(() => expect(getAccessToken()).toBeNull());
  });
});

describe("conversation history", () => {
  it("shows a skeleton, then the user's own conversations newest first", async () => {
    setup({ conversations: history() });
    expect(screen.getByRole("status", { name: "Loading conversations" })).toBeTruthy();
    await screen.findByRole("list", { name: "Conversations" });
    expect(rows()).toHaveLength(2); // the other user's conversation is never listed
    expect(rows()[0].querySelector("time")?.getAttribute("datetime")).toBe("2026-10-03T09:00:00+00:00");
    expect(rows()[1].querySelector("time")?.getAttribute("datetime")).toBe("2026-10-01T09:00:00+00:00");
  });

  it("shows an empty state when there are no conversations", async () => {
    setup();
    expect(await screen.findByText("No conversations yet")).toBeTruthy();
  });

  it("shows an error with retry when history can't be loaded", async () => {
    const backend = setup({ conversations: history() });
    backend.state.override = (call) =>
      call.path === "/api/v1/chat/history" ? apiError(500, "INTERNAL_SERVER_ERROR", "An unexpected error occurred") : null;
    expect(await screen.findByText(/our side/)).toBeTruthy();
    backend.state.override = null;
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await screen.findByRole("list", { name: "Conversations" });
    expect(rows()).toHaveLength(2);
  });
});

describe("opening and continuing conversations", () => {
  it("loads a past conversation, without inventing sources for it", async () => {
    const backend = setup({ conversations: history() });
    await screen.findByRole("list", { name: "Conversations" });
    openRow(0);
    expect(await screen.findByText("newer answer")).toBeTruthy();
    expect(screen.getByText("newer question", { selector: "p" })).toBeTruthy();
    expect(currentSearch()).toBe(uuid(8003));
    expect(screen.getByText(/Sources are only shown for answers received in this session/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /^Sources/ })).toBeNull();
    expect(backend.callsTo("GET", `/api/v1/chat/${uuid(8003)}`)).toHaveLength(1);
  });

  it("switches between conversations without mixing their messages", async () => {
    setup({ conversations: history() });
    await screen.findByRole("list", { name: "Conversations" });
    openRow(0);
    await screen.findByText("newer answer");
    openRow(1);
    expect(await screen.findByText("old answer")).toBeTruthy();
    expect(screen.queryByText("newer answer")).toBeNull();
    expect(currentSearch()).toBe(uuid(8001));
    // Opened conversations are labelled by their first question.
    expect(within(screen.getByRole("list", { name: "Conversations" })).getByText("old question")).toBeTruthy();
  });

  it("continues an existing conversation using its id, and keeps the earlier messages", async () => {
    const backend = setup({ conversations: history() });
    backend.state.chatAnswer = () => ({ answer: "Fresh answer", sources: [source(1, "doc.pdf", { score: 0.8 })] });
    await screen.findByRole("list", { name: "Conversations" });
    openRow(1);
    await screen.findByText("old answer");
    await selectWorkspace(uuid(1));

    ask("A follow-up");
    expect(await screen.findByText("Fresh answer")).toBeTruthy();
    expect(posts(backend)[0].body).toEqual({ query: "A follow-up", workspace_id: uuid(1), conversation_id: uuid(8001) });
    expect(screen.getByText("old answer")).toBeTruthy();
    expect(currentSearch()).toBe(uuid(8001)); // stays in the same conversation
    expect(backend.state.conversations.find((c) => c.id === uuid(8001))!.messages).toHaveLength(4);
    expect(rows()).toHaveLength(2); // no duplicate conversation was created
    // Sources belong only to the answer that actually received them.
    expect(screen.getAllByRole("button", { name: /^Sources \(1\)/ })).toHaveLength(1);
  });

  it("starts a fresh conversation from the New conversation button", async () => {
    setup({ conversations: history() });
    await screen.findByRole("list", { name: "Conversations" });
    openRow(0);
    await screen.findByText("newer answer");
    fireEvent.click(screen.getByRole("button", { name: /New conversation/ }));
    expect(await screen.findByText("Ask your documents")).toBeTruthy();
    expect(screen.queryByText("newer answer")).toBeNull();
    await waitFor(() => expect(currentSearch()).toBeNull());
  });

  it("restores the conversation named in the URL (refresh)", async () => {
    setSearch(`c=${uuid(8003)}`);
    setup({ conversations: history() });
    expect(await screen.findByText("newer answer")).toBeTruthy();
  });

  it("says so when the conversation doesn't exist or isn't the user's", async () => {
    setSearch(`c=${uuid(8009)}`); // belongs to another user
    setup({ conversations: history() });
    expect(await screen.findByText("Conversation not found")).toBeTruthy();
    expect(screen.queryByText("secret")).toBeNull();
    expect(question().disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Start a new conversation" }));
    await screen.findByText("Ask your documents");
  });

  it("handles a malformed conversation id in the URL", async () => {
    setSearch("c=not-a-uuid");
    const backend = setup({ conversations: history() });
    expect(await screen.findByText("Conversation not found")).toBeTruthy();
    expect(backend.callsTo("GET", /chat\/(?!history)/.source)).toHaveLength(0);
  });
});

describe("source citations", () => {
  const answerWithSources = () => ({
    answer: "Revenue grew [1] while costs fell [2]. Unsupported [9].",
    sources: [
      source(1, "report.pdf", { chunk_index: 3, score: 0.874, content: "Revenue grew 10% year on year." }),
      source(2, "notes.md", { chunk_index: 0, score: 0.412, content: null }),
    ],
  });

  async function askWithSources() {
    const backend = setup({ workspaces: [workspace(1, "Solo")] });
    backend.state.chatAnswer = answerWithSources;
    await waitFor(() => expect(question().disabled).toBe(false));
    ask("How did we do?");
    await screen.findByText(/Revenue grew/);
    return backend;
  }

  it("lists the sources the backend returned, with filename, chunk and score", async () => {
    await askWithSources();
    const toggle = screen.getByRole("button", { name: "Sources (2)" });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByText("report.pdf")).toBeNull(); // collapsed by default

    fireEvent.click(toggle);
    const list = screen.getByRole("list", { name: "Sources" });
    expect(within(list).getByText("report.pdf")).toBeTruthy();
    expect(within(list).getByText("Chunk 3")).toBeTruthy();
    expect(within(list).getByText("Score 0.87")).toBeTruthy();
    expect(within(list).getByText("notes.md")).toBeTruthy();
    expect(within(list).getAllByRole("listitem")).toHaveLength(2); // no extra, invented sources
  });

  it("expands and collapses a source's content", async () => {
    await askWithSources();
    fireEvent.click(screen.getByRole("button", { name: "Sources (2)" }));
    const [first, second] = screen.getAllByRole("button", { name: "Show excerpt" });
    fireEvent.click(first);
    expect(screen.getByText("Revenue grew 10% year on year.")).toBeTruthy();
    fireEvent.click(second);
    expect(screen.getByText("The excerpt isn’t available for this source.")).toBeTruthy();
    fireEvent.click(screen.getAllByRole("button", { name: "Hide excerpt" })[0]);
    expect(screen.queryByText("Revenue grew 10% year on year.")).toBeNull();
  });

  it("turns [n] markers into links to real sources only", async () => {
    await askWithSources();
    expect(screen.queryByRole("button", { name: "Show source 9" })).toBeNull();
    expect(screen.getByText(/Unsupported \[9\]/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Show source 1" }));
    expect(screen.getByRole("list", { name: "Sources" })).toBeTruthy();
    expect(screen.getByText("Revenue grew 10% year on year.")).toBeTruthy();
  });

  it("says when an answer had no sources, instead of showing any", async () => {
    const backend = setup({ workspaces: [workspace(1, "Solo")] });
    backend.state.chatAnswer = () => ({ answer: "I couldn't find that.", sources: [] });
    await waitFor(() => expect(question().disabled).toBe(false));
    ask("Anything?");
    await screen.findByText("I couldn't find that.");
    expect(screen.getByText("No sources were found for this answer.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /^Sources/ })).toBeNull();
  });

  it("keeps sources when switching away and back within the session", async () => {
    await askWithSources();
    fireEvent.click(screen.getByRole("button", { name: /New conversation/ }));
    await screen.findByText("Ask your documents");
    openRow(0);
    expect(await screen.findByRole("button", { name: "Sources (2)" })).toBeTruthy();
  });
});

describe("deleting conversations", () => {
  const confirmDelete = async (index: number) => {
    fireEvent.keyDown(rowActions(index), { key: "Enter" });
    fireEvent.click(await screen.findByRole("menuitem", { name: /Delete/ }));
    return dialog();
  };

  it("asks first, deletes on confirmation, and removes it from the list", async () => {
    const backend = setup({ conversations: history() });
    await screen.findByRole("list", { name: "Conversations" });
    const confirm = await confirmDelete(1);
    expect(confirm.textContent).toMatch(/permanently deletes/);
    expect(confirm.textContent).toMatch(/all of its messages/);
    expect(backend.callsTo("DELETE", `/api/v1/chat/${uuid(8001)}`)).toHaveLength(0);

    fireEvent.click(within(confirm).getByRole("button", { name: "Delete conversation" }));
    await waitFor(() => expect(rows()).toHaveLength(1));
    expect(backend.state.conversations.some((c) => c.id === uuid(8001))).toBe(false);
    expect(backend.callsTo("DELETE", `/api/v1/chat/${uuid(8001)}`)).toHaveLength(1);
  });

  it("does nothing when cancelled", async () => {
    const backend = setup({ conversations: history() });
    await screen.findByRole("list", { name: "Conversations" });
    const confirm = await confirmDelete(0);
    fireEvent.click(within(confirm).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(rows()).toHaveLength(2);
    expect(backend.callsTo("DELETE", `/api/v1/chat/${uuid(8003)}`)).toHaveLength(0);
  });

  it("returns to a new conversation when the open one is deleted, and leaves the view alone otherwise", async () => {
    setup({ conversations: history() });
    await screen.findByRole("list", { name: "Conversations" });
    openRow(0);
    await screen.findByText("newer answer");

    // Deleting a different conversation keeps the open one.
    fireEvent.click(within(await confirmDelete(1)).getByRole("button", { name: "Delete conversation" }));
    await waitFor(() => expect(rows()).toHaveLength(1));
    expect(screen.getByText("newer answer")).toBeTruthy();
    expect(currentSearch()).toBe(uuid(8003));

    // Deleting the open one starts fresh.
    fireEvent.click(within(await confirmDelete(0)).getByRole("button", { name: "Delete conversation" }));
    expect(await screen.findByText("Ask your documents")).toBeTruthy();
    expect(screen.queryByText("newer answer")).toBeNull();
    await waitFor(() => expect(currentSearch()).toBeNull());
  });

  it("sends a single DELETE for repeated clicks", async () => {
    const backend = setup({ conversations: history() });
    await screen.findByRole("list", { name: "Conversations" });
    const button = within(await confirmDelete(1)).getByRole("button", { name: "Delete conversation" });
    fireEvent.click(button);
    fireEvent.click(button);
    await waitFor(() => expect(rows()).toHaveLength(1));
    expect(backend.callsTo("DELETE", `/api/v1/chat/${uuid(8001)}`)).toHaveLength(1);
  });

  it("keeps the conversation and shows the error when deletion fails", async () => {
    const backend = setup({ conversations: history() });
    await screen.findByRole("list", { name: "Conversations" });
    backend.state.override = (call) =>
      call.method === "DELETE" ? apiError(500, "INTERNAL_SERVER_ERROR", "An unexpected error occurred") : null;
    const confirm = await confirmDelete(1);
    fireEvent.click(within(confirm).getByRole("button", { name: "Delete conversation" }));
    expect((await within(confirm).findByRole("alert")).textContent).toMatch(/our side/);
    expect(rows()).toHaveLength(2);
  });

  it("reconciles when the conversation was already deleted elsewhere", async () => {
    const backend = setup({ conversations: history() });
    await screen.findByRole("list", { name: "Conversations" });
    backend.state.conversations = backend.state.conversations.filter((c) => c.id !== uuid(8001));
    const confirm = await confirmDelete(1);
    fireEvent.click(within(confirm).getByRole("button", { name: "Delete conversation" }));
    expect((await within(confirm).findByRole("alert")).textContent).toMatch(/no longer exists/);
    await act(async () => {});
    await waitFor(() => expect(rows()).toHaveLength(1));
  });
});
