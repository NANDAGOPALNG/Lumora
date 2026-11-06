import { describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { DocumentsView } from "@/components/documents/documents-view";
import { apiError } from "./helpers";
import { createFakeBackend, document, uuid, workspace } from "./fake-backend";
import { renderApp } from "./render-app";
import { chooseFiles, makeFile, statusOf } from "./ui-helpers";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() }, Toaster: () => null }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn(), push: vi.fn() }) }));

const seed = () => ({
  workspaces: [
    workspace(1, "Alpha"),
    workspace(2, "Beta"),
    workspace(3, "Gamma", "someone-else"),
  ],
  documents: [
    document(1, 1, "alpha-indexed.txt", "Indexed"),
    document(2, 1, "alpha-failed.txt", "Failed", { chunk_count: 0 }),
    document(3, 2, "beta-uploaded.md", "Uploaded", { chunk_count: 0 }),
    document(4, 3, "gamma-secret.txt", "Indexed"),
  ],
});
const names = () =>
  within(screen.getByRole("list", { name: "Documents" }))
    .getAllByRole("listitem")
    .map((li) => li.querySelector("p")?.textContent);
const row = (name: string) => screen.getByText(name, { selector: "ul[aria-label='Documents'] p" }).closest("li")!;
const pick = (label: string, value: string) =>
  fireEvent.change(screen.getByLabelText(label), { target: { value } });

describe("documents across workspaces", () => {
  it("lists documents from every workspace the user owns, labelled by workspace, and none from others", async () => {
    const backend = createFakeBackend(seed());
    renderApp(<DocumentsView />);
    await screen.findByText("alpha-indexed.txt");
    await screen.findByText("beta-uploaded.md");

    expect(names().sort()).toEqual(["alpha-failed.txt", "alpha-indexed.txt", "beta-uploaded.md"]);
    expect(within(row("alpha-indexed.txt")).getByRole("link", { name: "Alpha" }).getAttribute("href")).toBe(
      `/workspaces/${uuid(1)}`,
    );
    expect(within(row("beta-uploaded.md")).getByRole("link", { name: "Beta" })).toBeTruthy();
    expect(screen.queryByText("gamma-secret.txt")).toBeNull();

    // One list request per owned workspace (the backend has no global listing); never the foreign one.
    const asked = backend.callsTo("GET", "/api/v1/documents").map((c) => c.query.get("workspace_id"));
    expect(asked.sort()).toEqual([uuid(1), uuid(2)]);
  });

  it("filters by workspace", async () => {
    createFakeBackend(seed());
    renderApp(<DocumentsView />);
    await screen.findByText("beta-uploaded.md");
    pick("Workspace", uuid(2));
    await waitFor(() => expect(names()).toEqual(["beta-uploaded.md"]));
  });

  it("filters by status and offers to clear filters when nothing matches", async () => {
    createFakeBackend(seed());
    renderApp(<DocumentsView />);
    await screen.findByText("beta-uploaded.md");

    pick("Status", "Failed");
    await waitFor(() => expect(names()).toEqual(["alpha-failed.txt"]));

    pick("Workspace", uuid(2)); // Beta has no failed documents
    expect(await screen.findByText("No documents match these filters")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    await waitFor(() => expect(names()).toHaveLength(3));
  });

  it("shows a skeleton while loading", async () => {
    createFakeBackend(seed());
    renderApp(<DocumentsView />);
    expect(screen.getByRole("status", { name: "Loading documents" })).toBeTruthy();
    await screen.findByText("alpha-indexed.txt");
  });

  it("tells users with no workspaces to create one first", async () => {
    createFakeBackend();
    renderApp(<DocumentsView />);
    expect(await screen.findByText("Create a workspace first")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Go to workspaces" }).getAttribute("href")).toBe("/workspaces");
  });

  it("explains when there are workspaces but no documents", async () => {
    createFakeBackend({ workspaces: [workspace(1, "Alpha"), workspace(2, "Beta")] });
    renderApp(<DocumentsView />);
    expect(await screen.findByText("No documents yet")).toBeTruthy();
  });

  it("shows an error with retry when workspaces can't be loaded", async () => {
    const backend = createFakeBackend(seed());
    backend.state.down = true;
    renderApp(<DocumentsView />);
    expect(await screen.findByText("Couldn’t load your workspaces")).toBeTruthy();
    backend.state.down = false;
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("alpha-indexed.txt")).toBeTruthy();
  });

  it("still shows what loaded when one workspace's documents fail, with a retry", async () => {
    const backend = createFakeBackend(seed());
    backend.state.override = (call) =>
      call.path === "/api/v1/documents" && call.query.get("workspace_id") === uuid(2)
        ? apiError(500, "INTERNAL_SERVER_ERROR", "An unexpected error occurred")
        : null;
    renderApp(<DocumentsView />);
    await screen.findByText("alpha-indexed.txt");
    expect((await screen.findByRole("alert")).textContent).toMatch(/Couldn’t load documents for Beta/);

    backend.state.override = null;
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("beta-uploaded.md")).toBeTruthy();
  });
});

describe("choosing a workspace to upload into", () => {
  it("requires choosing a workspace when there are several, then uploads into it", async () => {
    const backend = createFakeBackend(seed());
    renderApp(<DocumentsView />);
    await screen.findByText("alpha-indexed.txt");

    const picker = screen.getByLabelText("Upload to") as HTMLSelectElement;
    expect(picker.value).toBe("");
    expect((screen.getByLabelText("Choose documents to upload") as HTMLInputElement).disabled).toBe(true);
    expect(screen.getByText("Choose a workspace to upload into first.")).toBeTruthy();

    pick("Upload to", uuid(2));
    expect((screen.getByLabelText("Choose documents to upload") as HTMLInputElement).disabled).toBe(false);
    chooseFiles(makeFile("fresh.txt"));

    await waitFor(() => expect(statusOf(row("fresh.txt"))).toBe("Indexed"));
    const [upload] = backend.callsTo("POST", "/api/v1/documents/upload");
    expect(upload.form?.get("workspace_id")).toBe(uuid(2));
    expect(within(row("fresh.txt")).getByRole("link", { name: "Beta" })).toBeTruthy();
  });

  it("defaults the upload target to the filtered workspace", async () => {
    createFakeBackend(seed());
    renderApp(<DocumentsView />);
    await screen.findByText("alpha-indexed.txt");
    pick("Workspace", uuid(1));
    expect((screen.getByLabelText("Upload to") as HTMLSelectElement).value).toBe(uuid(1));
  });

  it("preselects the only workspace", async () => {
    createFakeBackend({ workspaces: [workspace(1, "Solo")] });
    renderApp(<DocumentsView />);
    await screen.findByText("No documents yet");
    expect((screen.getByLabelText("Upload to") as HTMLSelectElement).value).toBe(uuid(1));
    expect((screen.getByLabelText("Choose documents to upload") as HTMLInputElement).disabled).toBe(false);
  });
});

describe("actions from the global list", () => {
  it("reindexes and deletes documents from any workspace", async () => {
    const backend = createFakeBackend(seed());
    renderApp(<DocumentsView />);
    await screen.findByText("beta-uploaded.md");

    fireEvent.click(within(row("beta-uploaded.md")).getByRole("button", { name: "Index" }));
    await waitFor(() => expect(statusOf(row("beta-uploaded.md"))).toBe("Indexed"));
    expect(backend.callsTo("POST", `/api/v1/documents/${uuid(1003)}/reindex`)).toHaveLength(1);

    const trigger = screen.getByRole("button", { name: "Actions for alpha-failed.txt" });
    fireEvent.keyDown(trigger, { key: "Enter" });
    fireEvent.click(await screen.findByRole("menuitem", { name: /Delete/ }));
    fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Delete document" }));
    await waitFor(() => expect(screen.queryByText("alpha-failed.txt", { selector: "p" })).toBeNull());
    expect(backend.state.documents.some((d) => d.filename === "alpha-failed.txt")).toBe(false);
  });
});
