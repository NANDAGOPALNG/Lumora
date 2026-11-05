import { describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { toast } from "sonner";
import { WorkspacesView } from "@/components/workspaces/workspaces-view";
import { getAccessToken } from "@/lib/auth/session";
import { apiError } from "./helpers";
import { createFakeBackend, uuid, workspace } from "./fake-backend";
import { renderApp } from "./render-app";
import { chooseCardAction, dialog, nameInput, type } from "./ui-helpers";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() }, Toaster: () => null }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn(), push: vi.fn() }) }));

const seed = () => [workspace(1, "Personal Workspace"), workspace(3, "Research"), workspace(2, "Marketing")];
const cardNames = () =>
  screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent);

describe("listing", () => {
  it("shows the signed-in user's workspaces newest first, using only backend data", async () => {
    createFakeBackend({ workspaces: [...seed(), workspace(9, "Someone else's", "other-user-id")] });
    renderApp(<WorkspacesView />);
    await screen.findByText("Research");
    expect(cardNames()).toEqual(["Research", "Marketing", "Personal Workspace"]);
    expect(screen.queryByText("Someone else's")).toBeNull();
    expect(screen.getAllByText(/Created/).length).toBe(3);
    expect(screen.queryByText(uuid(1))).toBeNull(); // IDs aren't shown on cards
  });

  it("shows a loading skeleton while fetching", async () => {
    createFakeBackend({ workspaces: seed() });
    renderApp(<WorkspacesView />);
    expect(screen.getByRole("status", { name: "Loading workspaces" })).toBeTruthy();
    await screen.findByText("Research");
    expect(screen.queryByRole("status", { name: "Loading workspaces" })).toBeNull();
  });

  it("shows an empty state with a create action when there are no workspaces", async () => {
    createFakeBackend();
    renderApp(<WorkspacesView />);
    expect(await screen.findByText("No workspaces yet")).toBeTruthy();
    expect(screen.getAllByRole("button", { name: /New workspace/ })).toHaveLength(1);
  });

  it("links each card to its workspace page", async () => {
    createFakeBackend({ workspaces: seed() });
    renderApp(<WorkspacesView />);
    const link = await screen.findByRole("link", { name: "Research" });
    expect(link.getAttribute("href")).toBe(`/workspaces/${uuid(3)}`);
  });
});

describe("errors", () => {
  it("shows an error with retry when the backend is unreachable, then recovers", async () => {
    const backend = createFakeBackend({ workspaces: seed() });
    backend.state.down = true;
    renderApp(<WorkspacesView />);
    expect(await screen.findByText(/Can’t reach the Lumora server/)).toBeTruthy();
    expect(getAccessToken()).toBe("token-ada"); // an outage must not log the user out

    backend.state.down = false;
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("Research")).toBeTruthy();
  });

  it("ends the session on a 401 from the workspace API and does not retry", async () => {
    const backend = createFakeBackend({ workspaces: seed() });
    backend.state.override = (call) =>
      call.path === "/api/v1/workspaces" ? apiError(401, "UNAUTHORIZED", "Invalid or expired authentication token") : null;
    renderApp(<WorkspacesView />);
    await waitFor(() => expect(getAccessToken()).toBeNull());
    expect(backend.callsTo("GET", "/api/v1/workspaces")).toHaveLength(1);
  });

  it("makes no workspace request without a session", async () => {
    const backend = createFakeBackend({ workspaces: seed() });
    renderApp(<WorkspacesView />, { token: null });
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(backend.state.calls).toHaveLength(0);
  });
});

describe("create", () => {
  it("creates a trimmed workspace that appears immediately, closes the dialog and confirms", async () => {
    const backend = createFakeBackend({ workspaces: seed() });
    renderApp(<WorkspacesView />);
    await screen.findByText("Research");

    fireEvent.click(screen.getByRole("button", { name: /New workspace/ }));
    const form = await dialog();
    type(nameInput(), "   Q4 Planning  ");
    fireEvent.click(within(form).getByRole("button", { name: "Create workspace" }));

    expect(await screen.findByRole("link", { name: "Q4 Planning" })).toBeTruthy();
    expect(backend.callsTo("POST", "/api/v1/workspaces")[0].body).toEqual({ name: "Q4 Planning" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(toast.success).toHaveBeenCalledWith("Workspace “Q4 Planning” created");
    expect(cardNames()[0]).toBe("Q4 Planning"); // newest first
  });

  it("blocks empty and over-long names and shows the limit", async () => {
    const backend = createFakeBackend();
    renderApp(<WorkspacesView />);
    await screen.findByText("No workspaces yet");
    fireEvent.click(screen.getByRole("button", { name: /New workspace/ }));
    const form = await dialog();
    const submit = within(form).getByRole("button", { name: "Create workspace" }) as HTMLButtonElement;

    expect(submit.disabled).toBe(true);
    type(nameInput(), "   ");
    expect(submit.disabled).toBe(true);
    type(nameInput(), "x".repeat(101));
    expect(submit.disabled).toBe(true);
    expect(within(form).getByRole("alert").textContent).toMatch(/100 characters or fewer/);
    type(nameInput(), "x".repeat(100));
    expect(submit.disabled).toBe(false);
    expect(backend.callsTo("POST", "/api/v1/workspaces")).toHaveLength(0);
  });

  it("shows a server rejection inside the dialog and keeps it open", async () => {
    const backend = createFakeBackend();
    backend.state.override = (call) =>
      call.method === "POST" ? apiError(422, "VALIDATION_ERROR", "Invalid request") : null;
    renderApp(<WorkspacesView />);
    await screen.findByText("No workspaces yet");
    fireEvent.click(screen.getByRole("button", { name: /New workspace/ }));
    const form = await dialog();
    type(nameInput(), "Fine name");
    fireEvent.click(within(form).getByRole("button", { name: "Create workspace" }));
    expect((await within(form).findByRole("alert")).textContent).toMatch(/rejected/);
    expect(screen.getByRole("dialog")).toBeTruthy();
  });

  it("sends only one request when submitted twice quickly", async () => {
    const backend = createFakeBackend();
    renderApp(<WorkspacesView />);
    await screen.findByText("No workspaces yet");
    fireEvent.click(screen.getByRole("button", { name: /New workspace/ }));
    const form = await dialog();
    type(nameInput(), "Once");
    const submit = within(form).getByRole("button", { name: "Create workspace" });
    fireEvent.click(submit);
    fireEvent.click(submit);
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(backend.callsTo("POST", "/api/v1/workspaces")).toHaveLength(1);
  });
});

describe("rename", () => {
  it("pre-fills the name, saves the new one and shows it", async () => {
    const backend = createFakeBackend({ workspaces: seed() });
    renderApp(<WorkspacesView />);
    await screen.findByText("Research");

    await chooseCardAction("Research", /Rename/);
    const form = await dialog();
    expect(nameInput().value).toBe("Research");
    const save = within(form).getByRole("button", { name: "Save name" }) as HTMLButtonElement;
    expect(save.disabled).toBe(true); // unchanged

    type(nameInput(), "  Research & Dev ");
    fireEvent.click(save);

    expect(await screen.findByRole("link", { name: "Research & Dev" })).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Research" })).toBeNull();
    expect(backend.callsTo("PATCH", `/api/v1/workspaces/${uuid(3)}`)[0].body).toEqual({ name: "Research & Dev" });
  });

  it("prevents empty names", async () => {
    createFakeBackend({ workspaces: seed() });
    renderApp(<WorkspacesView />);
    await screen.findByText("Research");
    await chooseCardAction("Research", /Rename/);
    const form = await dialog();
    type(nameInput(), "   ");
    expect((within(form).getByRole("button", { name: "Save name" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("explains and reconciles when the workspace no longer exists (or isn't the user's)", async () => {
    const backend = createFakeBackend({ workspaces: seed() });
    renderApp(<WorkspacesView />);
    await screen.findByText("Research");
    // Removed on the server (e.g. in another tab) after this list was loaded.
    backend.state.workspaces = backend.state.workspaces.filter((w) => w.id !== uuid(3));

    await chooseCardAction("Research", /Rename/);
    const form = await dialog();
    type(nameInput(), "Renamed");
    fireEvent.click(within(form).getByRole("button", { name: "Save name" }));

    expect((await within(form).findByRole("alert")).textContent).toMatch(/no longer exists/);
    await waitFor(() => expect(screen.queryByRole("link", { name: "Research" })).toBeNull());
  });
});

describe("delete", () => {
  it("explains the consequences, names the workspace and deletes only after confirmation", async () => {
    const backend = createFakeBackend({ workspaces: seed() });
    renderApp(<WorkspacesView />);
    await screen.findByText("Research");

    await chooseCardAction("Research", /Delete/);
    const confirm = await dialog();
    expect(within(confirm).getByText("Research")).toBeTruthy();
    expect(confirm.textContent).toMatch(/documents, their stored files and search data, and any connected sources/);
    expect(confirm.textContent).toMatch(/can’t be undone/);
    expect(backend.callsTo("DELETE", `/api/v1/workspaces/${uuid(3)}`)).toHaveLength(0); // nothing yet

    fireEvent.click(within(confirm).getByRole("button", { name: "Delete workspace" }));
    await waitFor(() => expect(screen.queryByRole("link", { name: "Research" })).toBeNull());
    expect(cardNames()).toEqual(["Marketing", "Personal Workspace"]);
    expect(toast.success).toHaveBeenCalledWith("Workspace “Research” deleted");
  });

  it("does nothing when cancelled", async () => {
    const backend = createFakeBackend({ workspaces: seed() });
    renderApp(<WorkspacesView />);
    await screen.findByText("Research");
    await chooseCardAction("Research", /Delete/);
    fireEvent.click(within(await dialog()).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(backend.callsTo("DELETE", `/api/v1/workspaces/${uuid(3)}`)).toHaveLength(0);
    expect(screen.getByRole("link", { name: "Research" })).toBeTruthy();
  });

  it("sends a single DELETE for repeated clicks", async () => {
    const backend = createFakeBackend({ workspaces: seed() });
    renderApp(<WorkspacesView />);
    await screen.findByText("Research");
    await chooseCardAction("Research", /Delete/);
    const button = within(await dialog()).getByRole("button", { name: "Delete workspace" });
    fireEvent.click(button);
    fireEvent.click(button);
    fireEvent.click(button);
    await waitFor(() => expect(screen.queryByRole("link", { name: "Research" })).toBeNull());
    expect(backend.callsTo("DELETE", `/api/v1/workspaces/${uuid(3)}`)).toHaveLength(1);
  });

  it("keeps the workspace and shows the error when deletion fails", async () => {
    const backend = createFakeBackend({ workspaces: seed() });
    backend.state.override = (call) =>
      call.method === "DELETE" ? apiError(500, "INTERNAL_SERVER_ERROR", "An unexpected error occurred") : null;
    renderApp(<WorkspacesView />);
    await screen.findByText("Research");
    await chooseCardAction("Research", /Delete/);
    const confirm = await dialog();
    fireEvent.click(within(confirm).getByRole("button", { name: "Delete workspace" }));
    expect((await within(confirm).findByRole("alert")).textContent).toMatch(/our side/);
    expect(screen.getByRole("dialog")).toBeTruthy();
    // Background content is aria-hidden while the modal is open.
    expect(screen.getByRole("link", { name: "Research", hidden: true })).toBeTruthy();
  });
});

describe("persistence", () => {
  it("shows the server's current data after a fresh load (page refresh)", async () => {
    createFakeBackend({ workspaces: seed() });
    const first = renderApp(<WorkspacesView />);
    await screen.findByText("Research");
    await chooseCardAction("Research", /Rename/);
    type(nameInput(), "Renamed once");
    fireEvent.click(within(await dialog()).getByRole("button", { name: "Save name" }));
    await screen.findByRole("link", { name: "Renamed once" });

    first.unmount(); // a refresh discards all client state, including the query cache
    renderApp(<WorkspacesView />);
    expect(await screen.findByRole("link", { name: "Renamed once" })).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Research" })).toBeNull();
  });
});
