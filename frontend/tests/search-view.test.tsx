import { describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { SearchView } from "@/components/search/search-view";
import { getAccessToken } from "@/lib/auth/session";
import { apiError } from "./helpers";
import { createFakeBackend, document, source, uuid, workspace } from "./fake-backend";
import { renderApp } from "./render-app";
import { deferred } from "./ui-helpers";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() }, Toaster: () => null }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn(), push: vi.fn() }) }));

type Options = Parameters<typeof createFakeBackend>[0];
const workspaces = () => [workspace(1, "Alpha"), workspace(2, "Beta"), workspace(3, "Foreign", "someone-else")];
const documents = () => [
  document(1, 1, "alpha.pdf", "Indexed"),
  document(2, 1, "beta.md", "Indexed"),
  document(3, 1, "waiting.txt", "Uploaded", { chunk_count: 0 }),
  document(4, 1, "broken.txt", "Failed", { chunk_count: 0 }),
  document(5, 2, "other-workspace.pdf", "Indexed"),
];

function setup(options: Options = {}) {
  const backend = createFakeBackend({ workspaces: workspaces(), documents: documents(), ...options });
  const view = renderApp(<SearchView />);
  return { backend, ...view };
}

const input = () => screen.getByLabelText("Search query") as HTMLInputElement;
// While a search runs the shared Button adds its spinner's label, so the name becomes "LoadingSearch".
const searchButton = () => screen.getByRole("button", { name: /^(Loading)?Search$/ }) as HTMLButtonElement;
const workspaceSelect = () => screen.getByLabelText("Workspace") as HTMLSelectElement;
const documentSelect = () => screen.getByLabelText("Document") as HTMLSelectElement;
const chooseWorkspace = async (id: string) => {
  await screen.findByRole("option", { name: "Alpha" });
  fireEvent.change(workspaceSelect(), { target: { value: id } });
};
const type = (text: string) => fireEvent.change(input(), { target: { value: text } });
const search = (text: string) => {
  type(text);
  fireEvent.click(searchButton());
};
const posts = (backend: ReturnType<typeof createFakeBackend>) => backend.callsTo("POST", "/api/v1/search");
const cards = () => within(screen.getByRole("list", { name: "Search results" })).getAllByRole("listitem");

describe("rendering", () => {
  it("renders the search form, filters and the empty state before any search", async () => {
    const { backend } = setup();
    expect(screen.getByRole("heading", { level: 1, name: "Search" })).toBeTruthy();
    expect(screen.getByRole("search")).toBeTruthy();
    expect(input().placeholder).toMatch(/How does authentication work/);
    expect(searchButton()).toBeTruthy();
    expect(await screen.findByText("Search your knowledge")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Clear search" })).toBeNull();
    expect(posts(backend)).toHaveLength(0); // nothing runs until the user submits
  });
});

describe("workspace selection", () => {
  it("offers only the user's workspaces and requires a choice when there are several", async () => {
    const { backend } = setup();
    await screen.findByRole("option", { name: "Alpha" });
    expect(screen.getByRole("option", { name: "Beta" })).toBeTruthy();
    expect(screen.queryByRole("option", { name: "Foreign" })).toBeNull();
    expect(workspaceSelect().value).toBe("");

    search("auth");
    expect(screen.getByRole("alert").textContent).toMatch(/Choose a workspace/);
    expect(posts(backend)).toHaveLength(0);

    fireEvent.change(workspaceSelect(), { target: { value: uuid(1) } });
    expect(screen.queryByRole("alert")).toBeNull();
    fireEvent.click(searchButton());
    await screen.findByRole("heading", { name: /2 results/ });
    expect(posts(backend)).toHaveLength(1);
  });

  it("preselects the only workspace", async () => {
    setup({ workspaces: [workspace(1, "Solo")] });
    await waitFor(() => expect(workspaceSelect().value).toBe(uuid(1)));
    expect(screen.queryByRole("option", { name: "Choose a workspace…" })).toBeNull();
  });
});

describe("document selector", () => {
  it("lists only indexed documents of the selected workspace", async () => {
    setup();
    await chooseWorkspace(uuid(1));
    await screen.findByRole("option", { name: "alpha.pdf" });
    expect(screen.getByRole("option", { name: "beta.md" })).toBeTruthy();
    expect(screen.queryByRole("option", { name: "waiting.txt" })).toBeNull(); // not indexed yet
    expect(screen.queryByRole("option", { name: "broken.txt" })).toBeNull(); // failed
    expect(screen.queryByRole("option", { name: "other-workspace.pdf" })).toBeNull(); // another workspace
    expect(screen.getByRole("option", { name: "All indexed documents" })).toBeTruthy();
  });

  it("is disabled until a workspace is chosen, and shows loading while documents load", async () => {
    setup();
    await screen.findByRole("option", { name: "Alpha" });
    expect(documentSelect().disabled).toBe(true);
    fireEvent.change(workspaceSelect(), { target: { value: uuid(1) } });
    expect(screen.getByRole("option", { name: "Loading documents…" })).toBeTruthy();
    await screen.findByRole("option", { name: "alpha.pdf" });
  });

  it("resets the document when the workspace changes", async () => {
    setup();
    await chooseWorkspace(uuid(1));
    await screen.findByRole("option", { name: "alpha.pdf" });
    fireEvent.change(documentSelect(), { target: { value: uuid(1001) } });
    expect(documentSelect().value).toBe(uuid(1001));

    fireEvent.change(workspaceSelect(), { target: { value: uuid(2) } });
    await screen.findByRole("option", { name: "other-workspace.pdf" });
    expect(documentSelect().value).toBe("");
    expect(screen.queryByRole("option", { name: "alpha.pdf" })).toBeNull();
  });

  it("explains an empty document list", async () => {
    setup({ documents: [document(3, 1, "waiting.txt", "Uploaded", { chunk_count: 0 })] });
    await chooseWorkspace(uuid(1));
    expect(await screen.findByText(/no indexed documents yet/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "Add documents" }).getAttribute("href")).toBe(`/workspaces/${uuid(1)}`);
  });
});

describe("running a search", () => {
  it("sends the right request and lists each returned source as a result", async () => {
    const { backend } = setup();
    await chooseWorkspace(uuid(1));
    search("How does authentication work?");

    expect(await screen.findByRole("heading", { name: /2 results/ })).toBeTruthy();
    expect(posts(backend)).toHaveLength(1);
    expect(posts(backend)[0].body).toEqual({ query: "How does authentication work?", workspace_id: uuid(1), top_k: 5 });
    expect("document_id" in (posts(backend)[0].body as object)).toBe(false);

    const [first, second] = cards();
    expect(within(first).getByText("alpha.pdf")).toBeTruthy();
    expect(within(first).getByText("pdf")).toBeTruthy();
    expect(within(first).getByText("Chunk 2")).toBeTruthy();
    expect(within(first).getByText("Score 0.873")).toBeTruthy();
    expect(within(first).getByText("Alpha passage about authentication.")).toBeTruthy();
    expect(within(second).getByText("beta.md")).toBeTruthy();
    expect(within(second).getByText("Score 0.412")).toBeTruthy();
    expect(screen.queryByText(/%/)).toBeNull(); // scores are never shown as percentages
    expect(screen.queryByText(/assembled context text/)).toBeNull(); // context isn't a result
  });

  it("submits with Enter (form submit) and trims the query", async () => {
    const { backend } = setup({ workspaces: [workspace(1, "Solo")] });
    await waitFor(() => expect(workspaceSelect().value).toBe(uuid(1)));
    type("   padded query   ");
    fireEvent.submit(screen.getByRole("search"));
    await screen.findByRole("heading", { name: /2 results/ });
    expect(posts(backend)[0].body).toMatchObject({ query: "padded query" });
    expect(input().value).toBe("padded query");
  });

  it("restricts the search to the chosen document", async () => {
    const { backend } = setup();
    await chooseWorkspace(uuid(1));
    await screen.findByRole("option", { name: "beta.md" });
    fireEvent.change(documentSelect(), { target: { value: uuid(1002) } });
    search("only this file");
    await screen.findByRole("heading", { name: /1 result/ });
    expect(posts(backend)[0].body).toEqual({ query: "only this file", workspace_id: uuid(1), document_id: uuid(1002), top_k: 5 });
    expect(cards()).toHaveLength(1);
    expect(within(cards()[0]).getByText("beta.md")).toBeTruthy();
  });

  it("uses the chosen number of results", async () => {
    const { backend } = setup({ workspaces: [workspace(1, "Solo")] });
    await waitFor(() => expect(workspaceSelect().value).toBe(uuid(1)));
    fireEvent.change(screen.getByLabelText("Results"), { target: { value: "20" } });
    search("many");
    await screen.findByRole("heading", { name: /2 results/ });
    expect(posts(backend)[0].body).toMatchObject({ top_k: 20 });
  });

  it("notes when the result limit may be hiding more passages", async () => {
    const { backend } = setup({ workspaces: [workspace(1, "Solo")] });
    backend.state.searchResults = () => Array.from({ length: 5 }, (_, i) => source(i + 1, `f${i + 1}.txt`));
    await waitFor(() => expect(workspaceSelect().value).toBe(uuid(1)));
    search("lots");
    expect(await screen.findByText(/Showing the top 5/)).toBeTruthy();
  });

  it("tells the user when the backend normalised their query", async () => {
    setup({ workspaces: [workspace(1, "Solo")] });
    await waitFor(() => expect(workspaceSelect().value).toBe(uuid(1)));
    search("a    b");
    expect(await screen.findByText("Searched as “a b”.")).toBeTruthy();
  });

  it("shows a skeleton while searching, and the same search can be run again", async () => {
    const { backend } = setup({ workspaces: [workspace(1, "Solo")] });
    const gate = deferred();
    backend.state.searchGate = () => gate.promise;
    await waitFor(() => expect(workspaceSelect().value).toBe(uuid(1)));
    search("slow");
    expect(await screen.findByRole("status", { name: "Searching" })).toBeTruthy();
    gate.resolve();
    await screen.findByRole("heading", { name: /2 results/ });
    backend.state.searchGate = null;

    fireEvent.click(searchButton()); // identical search again
    await waitFor(() => expect(posts(backend)).toHaveLength(2));
  });
});

describe("validation", () => {
  it.each([["empty", ""], ["whitespace", "    "]])("makes no request for an %s query", async (_label, value) => {
    const { backend } = setup({ workspaces: [workspace(1, "Solo")] });
    await waitFor(() => expect(workspaceSelect().value).toBe(uuid(1)));
    type(value);
    fireEvent.click(searchButton());
    expect(screen.getByRole("alert").textContent).toMatch(/Enter something to search for/);
    expect(posts(backend)).toHaveLength(0);
    type("now valid");
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

describe("no results", () => {
  it("shows a clear message when a successful search returns nothing", async () => {
    const { backend } = setup({ workspaces: [workspace(1, "Solo")] });
    backend.state.searchResults = () => [];
    await waitFor(() => expect(workspaceSelect().value).toBe(uuid(1)));
    search("nothing matches");
    expect(await screen.findByText("No results found")).toBeTruthy();
    expect(screen.getByText(/matched “nothing matches”/)).toBeTruthy();
    expect(screen.queryByRole("list", { name: "Search results" })).toBeNull();
  });
});

describe("passage expand and collapse", () => {
  const longPassage = `${"Authentication uses signed tokens. ".repeat(20)}END-OF-PASSAGE`;

  async function searchWith(content: string | null) {
    const { backend } = setup({ workspaces: [workspace(1, "Solo")] });
    backend.state.searchResults = () => [source(1, "long.pdf", { content })];
    await waitFor(() => expect(workspaceSelect().value).toBe(uuid(1)));
    search("tokens");
    await screen.findByText("long.pdf");
  }

  it("previews a long passage and expands it fully, then collapses again", async () => {
    await searchWith(longPassage);
    const toggle = screen.getByRole("button", { name: "Show full passage" });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByText(/END-OF-PASSAGE/)).toBeNull();
    expect(screen.getByText(/Authentication uses signed tokens/).textContent!.endsWith("…")).toBe(true);

    fireEvent.click(toggle);
    expect(screen.getByText(/END-OF-PASSAGE/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Show less" }).getAttribute("aria-expanded")).toBe("true");

    fireEvent.click(screen.getByRole("button", { name: "Show less" }));
    expect(screen.queryByText(/END-OF-PASSAGE/)).toBeNull();
  });

  it("offers no toggle for a short passage", async () => {
    await searchWith("Short passage.");
    expect(screen.getByText("Short passage.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /full passage/ })).toBeNull();
  });

  it("says so when the backend returns no passage text, instead of inventing a preview", async () => {
    await searchWith(null);
    expect(screen.getByText("The passage text isn’t available for this result.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /full passage/ })).toBeNull();
  });
});

describe("errors", () => {
  it("shows the failure with a retry that works", async () => {
    const { backend } = setup({ workspaces: [workspace(1, "Solo")] });
    backend.state.override = (call) =>
      call.path === "/api/v1/search" ? apiError(500, "INTERNAL_SERVER_ERROR", "An unexpected error occurred") : null;
    await waitFor(() => expect(workspaceSelect().value).toBe(uuid(1)));
    search("will fail");
    expect(await screen.findByText("The search failed")).toBeTruthy();
    expect(screen.getByText(/our side/)).toBeTruthy();

    backend.state.override = null;
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("heading", { name: /2 results/ })).toBeTruthy();
    expect(screen.queryByText("The search failed")).toBeNull();
  });

  it("explains an unreachable server without logging out", async () => {
    const { backend } = setup({ workspaces: [workspace(1, "Solo")] });
    await waitFor(() => expect(workspaceSelect().value).toBe(uuid(1)));
    backend.state.down = true;
    search("offline");
    expect(await screen.findByText(/Can’t reach the Lumora server/)).toBeTruthy();
    expect(getAccessToken()).toBe("token-ada");
  });

  it("explains a workspace that disappeared", async () => {
    const { backend } = setup({ workspaces: [workspace(1, "Solo")] });
    await waitFor(() => expect(workspaceSelect().value).toBe(uuid(1)));
    backend.state.workspaces = [];
    search("gone");
    expect(await screen.findByText(/no longer exists/)).toBeTruthy();
  });

  it("ends the session when the search endpoint answers 401", async () => {
    const { backend } = setup({ workspaces: [workspace(1, "Solo")] });
    await waitFor(() => expect(workspaceSelect().value).toBe(uuid(1)));
    backend.state.override = (call) =>
      call.path === "/api/v1/search" ? apiError(401, "UNAUTHORIZED", "Invalid or expired authentication token") : null;
    search("expired");
    await waitFor(() => expect(getAccessToken()).toBeNull());
  });
});

describe("duplicate submissions", () => {
  it("sends a single request however many times submit is triggered while one is in flight", async () => {
    const { backend } = setup({ workspaces: [workspace(1, "Solo")] });
    const gate = deferred();
    backend.state.searchGate = () => gate.promise;
    await waitFor(() => expect(workspaceSelect().value).toBe(uuid(1)));
    search("only once");
    await screen.findByRole("status", { name: "Searching" });
    expect(searchButton().disabled).toBe(true);
    fireEvent.click(searchButton());
    fireEvent.submit(screen.getByRole("search"));
    fireEvent.submit(screen.getByRole("search"));
    gate.resolve();
    await screen.findByRole("heading", { name: /2 results/ });
    expect(posts(backend)).toHaveLength(1);
  });
});

describe("stale results", () => {
  async function withResults() {
    const ctx = setup();
    await chooseWorkspace(uuid(1));
    await screen.findByRole("option", { name: "alpha.pdf" });
    search("auth");
    await screen.findByRole("heading", { name: /2 results/ });
    return ctx;
  }

  it("hides results when the workspace changes, and never shows them under the new one", async () => {
    const { backend } = await withResults();
    fireEvent.change(workspaceSelect(), { target: { value: uuid(2) } });
    expect(await screen.findByText("Filters changed")).toBeTruthy();
    expect(screen.queryByRole("list", { name: "Search results" })).toBeNull();
    expect(screen.queryByText("alpha.pdf", { selector: "h3 span" })).toBeNull();
    expect(posts(backend)).toHaveLength(1); // changing a filter never searches by itself
  });

  it("hides results when the document filter changes", async () => {
    await withResults();
    fireEvent.change(documentSelect(), { target: { value: uuid(1001) } });
    expect(screen.getByText("Filters changed")).toBeTruthy();
    expect(screen.queryByRole("list", { name: "Search results" })).toBeNull();
  });

  it("hides results when the number of results changes", async () => {
    await withResults();
    fireEvent.change(screen.getByLabelText("Results"), { target: { value: "10" } });
    expect(screen.getByText("Filters changed")).toBeTruthy();
  });

  it("shows the earlier results again, from the cache, when the selection is restored", async () => {
    const { backend } = await withResults();
    fireEvent.change(documentSelect(), { target: { value: uuid(1001) } });
    expect(screen.queryByRole("list", { name: "Search results" })).toBeNull();
    fireEvent.change(documentSelect(), { target: { value: "" } });
    expect(await screen.findByRole("heading", { name: /2 results/ })).toBeTruthy();
    expect(posts(backend)).toHaveLength(1);
  });

  it("runs a fresh search for the new selection when asked", async () => {
    const { backend } = await withResults();
    fireEvent.change(workspaceSelect(), { target: { value: uuid(2) } });
    fireEvent.click(searchButton());
    await screen.findByRole("heading", { name: /2 results/ });
    expect(posts(backend)).toHaveLength(2);
    expect(posts(backend)[1].body).toMatchObject({ workspace_id: uuid(2) });
    expect(screen.getByRole("heading", { name: /in Beta/ })).toBeTruthy();
  });
});

describe("clearing", () => {
  it("clears the text and results without searching", async () => {
    const { backend } = setup({ workspaces: [workspace(1, "Solo")] });
    await waitFor(() => expect(workspaceSelect().value).toBe(uuid(1)));
    search("something");
    await screen.findByRole("heading", { name: /2 results/ });

    fireEvent.click(screen.getByRole("button", { name: "Clear search" }));
    expect(input().value).toBe("");
    expect(screen.queryByRole("list", { name: "Search results" })).toBeNull();
    expect(screen.getByText("Search your knowledge")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Clear search" })).toBeNull();
    expect(posts(backend)).toHaveLength(1);
  });
});

describe("cancellation", () => {
  it("aborts the request if the page is left while searching", async () => {
    const { backend, unmount } = setup({ workspaces: [workspace(1, "Solo")] });
    backend.state.searchGate = () => new Promise<void>(() => {}); // never answers
    await waitFor(() => expect(workspaceSelect().value).toBe(uuid(1)));
    search("abandoned");
    await waitFor(() => expect(posts(backend)).toHaveLength(1));
    const call = vi.mocked(fetch).mock.calls.find(([url]) => String(url).endsWith("/api/v1/search"))!;
    const signal = (call[1] as RequestInit).signal as AbortSignal;
    expect(signal.aborted).toBe(false);
    unmount();
    await waitFor(() => expect(signal.aborted).toBe(true));
  });
});
