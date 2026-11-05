import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { WorkspaceDetailView } from "@/components/workspaces/workspace-detail-view";
import { createFakeBackend, uuid, workspace } from "./fake-backend";
import { renderApp } from "./render-app";
import { dialog, nameInput, type } from "./ui-helpers";

const { replace } = vi.hoisted(() => ({ replace: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace, push: vi.fn() }) }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() }, Toaster: () => null }));

const seed = () => [
  workspace(1, "Personal Workspace"),
  workspace(3, "Research"),
  workspace(9, "Not mine", "another-user-id"),
];

beforeEach(() => replace.mockClear());

describe("workspace detail", () => {
  it("shows the real name, creation date and a way back", async () => {
    createFakeBackend({ workspaces: seed() });
    renderApp(<WorkspaceDetailView workspaceId={uuid(3)} />);
    expect(await screen.findByRole("heading", { level: 1, name: "Research" })).toBeTruthy();
    expect(screen.getByText(uuid(3))).toBeTruthy();
    expect(document.querySelector("time")?.getAttribute("datetime")).toBe("2026-10-03T10:00:00+00:00");
    expect(screen.getByRole("link", { name: /All workspaces/ }).getAttribute("href")).toBe("/workspaces");
  });

  it("does not claim the workspace has no documents (listing isn't connected yet)", async () => {
    createFakeBackend({ workspaces: seed() });
    renderApp(<WorkspaceDetailView workspaceId={uuid(3)} />);
    await screen.findByRole("heading", { level: 1, name: "Research" });
    expect(screen.getByText("Documents aren’t shown here yet")).toBeTruthy();
    expect(screen.queryByText(/no documents/i)).toBeNull();
  });

  it("handles a malformed workspace ID without calling the workspace API", async () => {
    const backend = createFakeBackend({ workspaces: seed() });
    renderApp(<WorkspaceDetailView workspaceId="not-a-uuid" />);
    expect(await screen.findByText("Invalid workspace link")).toBeTruthy();
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(backend.callsTo("GET", "/api/v1/workspaces")).toHaveLength(0);
  });

  it("shows not-found for a well-formed ID that isn't in the list", async () => {
    createFakeBackend({ workspaces: seed() });
    renderApp(<WorkspaceDetailView workspaceId={uuid(77)} />);
    expect(await screen.findByText("Workspace not found")).toBeTruthy();
  });

  it("treats another user's workspace exactly like a missing one", async () => {
    createFakeBackend({ workspaces: seed() }); // workspace 9 belongs to someone else
    renderApp(<WorkspaceDetailView workspaceId={uuid(9)} />);
    expect(await screen.findByText("Workspace not found")).toBeTruthy();
    expect(screen.queryByText("Not mine")).toBeNull();
  });

  it("shows an error with retry when the backend can't be reached", async () => {
    const backend = createFakeBackend({ workspaces: seed() });
    backend.state.down = true;
    renderApp(<WorkspaceDetailView workspaceId={uuid(3)} />);
    expect(await screen.findByText(/Can’t reach the Lumora server/)).toBeTruthy();
    backend.state.down = false;
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("heading", { level: 1, name: "Research" })).toBeTruthy();
  });

  it("renames in place and updates the heading", async () => {
    createFakeBackend({ workspaces: seed() });
    renderApp(<WorkspaceDetailView workspaceId={uuid(3)} />);
    await screen.findByRole("heading", { level: 1, name: "Research" });
    fireEvent.click(screen.getByRole("button", { name: /Rename/ }));
    const form = await dialog();
    type(nameInput(), "Research 2027");
    fireEvent.click(within(form).getByRole("button", { name: "Save name" }));
    expect(await screen.findByRole("heading", { level: 1, name: "Research 2027" })).toBeTruthy();
  });

  it("deletes after confirmation and returns to the list", async () => {
    const backend = createFakeBackend({ workspaces: seed() });
    renderApp(<WorkspaceDetailView workspaceId={uuid(3)} />);
    await screen.findByRole("heading", { level: 1, name: "Research" });
    fireEvent.click(screen.getByRole("button", { name: /Delete/ }));
    fireEvent.click(within(await dialog()).getByRole("button", { name: "Delete workspace" }));
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/workspaces"));
    expect(backend.callsTo("DELETE", `/api/v1/workspaces/${uuid(3)}`)).toHaveLength(1);
  });
});
