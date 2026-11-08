import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { toast } from "sonner";
import { IntegrationsView } from "@/components/integrations/integrations-view";
import { WorkspaceDocuments } from "@/components/documents/workspace-documents";
import { getAccessToken } from "@/lib/auth/session";
import { apiError } from "./helpers";
import { connector, createFakeBackend, document as makeDocument, uuid, workspace } from "./fake-backend";
import { endSync } from "@/lib/sync-tracker";
import { renderApp } from "./render-app";
import { deferred, dialog } from "./ui-helpers";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() }, Toaster: () => null }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn(), push: vi.fn() }) }));

// The sync tracker is module-level state; never let one test's running sync leak into the next.
afterEach(() => {
  for (let n = 1; n <= 10; n++) endSync(uuid(6000 + n));
});

type Options = Parameters<typeof createFakeBackend>[0];
const workspaces = () => [workspace(1, "Alpha"), workspace(2, "Beta"), workspace(3, "Foreign", "someone-else")];
const connectors = () => [
  connector(1, 1, "acme/docs", { last_synced: "2026-10-05T10:30:00+00:00" }),
  connector(2, 1, "acme/api"),
  connector(3, 2, "beta/site"),
  connector(4, 1, "drive-thing", { type: "google-drive", github_repo: null, drive_account_email: "x@example.com" }),
  connector(5, 3, "foreign/secret"),
];

function setup(options: Options = {}, ui: React.ReactNode = <IntegrationsView />) {
  const backend = createFakeBackend({ workspaces: workspaces(), connectors: connectors(), ...options });
  const view = renderApp(ui);
  return { backend, ...view };
}

const page = () => screen.getByLabelText("Workspace", { selector: "#integrations-workspace" }) as HTMLSelectElement;
const chooseWorkspace = async (id: string) => {
  await screen.findByRole("option", { name: "Alpha" });
  fireEvent.change(page(), { target: { value: id } });
};
const list = () => screen.getByRole("list", { name: "Connected repositories", hidden: true });
const rows = () => within(list()).getAllByRole("listitem", { hidden: true });
const rowFor = (name: string) => rows().find((row) => within(row).queryByText(name, { exact: true }))!;
const listCalls = (b: ReturnType<typeof createFakeBackend>) => b.callsTo("GET", "/api/v1/connectors");

async function openConnect() {
  fireEvent.click(screen.getAllByRole("button", { name: "Connect repository" })[0]);
  return dialog();
}
const fillConnect = (form: HTMLElement, values: { repo?: string; token?: string; name?: string; workspace?: string }) => {
  if (values.workspace !== undefined)
    fireEvent.change(within(form).getByLabelText("Workspace"), { target: { value: values.workspace } });
  if (values.repo !== undefined) fireEvent.change(within(form).getByLabelText("Repository"), { target: { value: values.repo } });
  if (values.token !== undefined)
    fireEvent.change(within(form).getByLabelText("GitHub personal access token"), { target: { value: values.token } });
  if (values.name !== undefined) fireEvent.change(within(form).getByLabelText(/Display name/), { target: { value: values.name } });
};
const submitConnect = (form: HTMLElement) => fireEvent.click(within(form).getByRole("button", { name: "Connect repository" }));
const tokenInput = (form: HTMLElement) => within(form).getByLabelText("GitHub personal access token") as HTMLInputElement;

describe("rendering", () => {
  it("shows the GitHub card and a Google Drive card that can't be connected", async () => {
    setup();
    expect(screen.getByRole("heading", { level: 1, name: "Integrations" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "GitHub" })).toBeTruthy();
    expect(screen.getByText("Token needed for each sync")).toBeTruthy();

    const drive = screen.getByRole("heading", { name: "Google Drive" }).closest("section")!;
    expect(within(drive).getByText("OAuth setup required")).toBeTruthy();
    expect(within(drive).getByText(/needs a Google sign-in and authorisation flow/)).toBeTruthy();
    expect(within(drive).queryByRole("button")).toBeNull(); // no connect button, no token form
    expect(within(drive).queryByRole("textbox")).toBeNull();
    expect(within(drive).queryByText(/^connected$/i)).toBeNull(); // no "Connected" state
  });
});

describe("workspace selection and isolation", () => {
  it("asks for a workspace when there are several, offering only the user's own", async () => {
    const { backend } = setup();
    await screen.findByRole("option", { name: "Alpha" });
    expect(screen.queryByRole("option", { name: "Foreign" })).toBeNull();
    expect(page().value).toBe("");
    expect(screen.getByText(/Choose a workspace to see its connected repositories/)).toBeTruthy();
    expect(listCalls(backend)).toHaveLength(0); // nothing is requested without a workspace
  });

  it("preselects a single workspace and lists its connectors", async () => {
    setup({ workspaces: [workspace(1, "Solo")] });
    await waitFor(() => expect(page().value).toBe(uuid(1)));
    await screen.findByRole("list", { name: "Connected repositories" });
  });

  it("explains when the user has no workspace", async () => {
    setup({ workspaces: [] });
    expect(await screen.findByText("Create a workspace first")).toBeTruthy();
  });

  it("shows each workspace's own connectors only, switching on change", async () => {
    const { backend } = setup();
    await chooseWorkspace(uuid(1));
    await screen.findByRole("list", { name: "Connected repositories" });
    expect(rows()).toHaveLength(2);
    expect(screen.queryByText("beta/site")).toBeNull();
    expect(screen.queryByText("foreign/secret")).toBeNull();

    fireEvent.change(page(), { target: { value: uuid(2) } });
    await screen.findByText("beta/site");
    expect(rows()).toHaveLength(1);
    expect(screen.queryByText("acme/docs")).toBeNull();
    expect(listCalls(backend).map((c) => c.query.get("workspace_id"))).toEqual([uuid(1), uuid(2)]);
  });
});

describe("connector list", () => {
  it("shows GitHub connectors with last-sync information and hides other types", async () => {
    setup();
    await chooseWorkspace(uuid(1));
    await screen.findByRole("list", { name: "Connected repositories" });
    expect(rows()).toHaveLength(2); // the Google Drive connector in this workspace isn't listed
    expect(screen.queryByText("drive-thing")).toBeNull();

    const synced = rowFor("acme/docs");
    expect(within(synced).getByText(/Last synced/)).toBeTruthy();
    expect(synced.querySelector("time")?.getAttribute("datetime")).toBe("2026-10-05T10:30:00+00:00");
    expect(within(rowFor("acme/api")).getByText("Never synced")).toBeTruthy();
  });

  it("shows an empty state with a connect action", async () => {
    setup({ connectors: [] });
    await chooseWorkspace(uuid(1));
    expect(await screen.findByText("No repositories connected")).toBeTruthy();
    expect(screen.getAllByRole("button", { name: "Connect repository" })).toHaveLength(1);
  });

  it("shows a skeleton, then an error with retry that recovers", async () => {
    const { backend } = setup();
    backend.state.override = (call) =>
      call.path === "/api/v1/connectors" && call.method === "GET"
        ? apiError(500, "INTERNAL_SERVER_ERROR", "An unexpected error occurred")
        : null;
    await chooseWorkspace(uuid(1));
    expect(await screen.findByText("Couldn’t load connections")).toBeTruthy();
    backend.state.override = null;
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await screen.findByRole("list", { name: "Connected repositories" });
    expect(rows()).toHaveLength(2);
  });

  it("flags a connector that predates stored repositories and blocks syncing it", async () => {
    setup({ connectors: [connector(1, 1, "legacy", { github_repo: null })] });
    await chooseWorkspace(uuid(1));
    await screen.findByText("Reconnect needed");
    expect((screen.getByRole("button", { name: "Sync legacy" }) as HTMLButtonElement).disabled).toBe(true);
  });
});

describe("connecting a repository", () => {
  it("connects with the selected workspace, refreshes the list, confirms and clears the token", async () => {
    const { backend } = setup();
    await chooseWorkspace(uuid(1));
    await screen.findByRole("list", { name: "Connected repositories" });

    const form = await openConnect();
    fillConnect(form, { repo: "  octocat/Hello-World ", token: " ghp_valid ", name: "" });
    submitConnect(form);

    expect(await screen.findByText("octocat/Hello-World", { selector: "span" })).toBeTruthy();
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    const [post] = backend.callsTo("POST", "/api/v1/connectors/github");
    expect(post.body).toEqual({ workspace_id: uuid(1), repo_full_name: "octocat/Hello-World", github_token: "ghp_valid" });
    expect(toast.success).toHaveBeenCalledWith("Connected octocat/Hello-World");
    expect(rows()).toHaveLength(3);
  });

  it("sends the optional display name and shows it", async () => {
    const { backend } = setup();
    await chooseWorkspace(uuid(1));
    await screen.findByRole("list", { name: "Connected repositories" });
    const form = await openConnect();
    fillConnect(form, { repo: "octocat/Hello-World", token: "ghp_valid", name: "Hello docs" });
    submitConnect(form);
    expect(await screen.findByText("Hello docs", { selector: "span" })).toBeTruthy();
    expect(backend.callsTo("POST", "/api/v1/connectors/github")[0].body).toMatchObject({ connection_name: "Hello docs" });
  });

  it("uses the workspace chosen in the dialog and follows it", async () => {
    const { backend } = setup();
    await chooseWorkspace(uuid(1));
    await screen.findByRole("list", { name: "Connected repositories" });
    const form = await openConnect();
    fillConnect(form, { workspace: uuid(2), repo: "octocat/Hello-World", token: "ghp_valid" });
    submitConnect(form);
    await waitFor(() => expect(page().value).toBe(uuid(2)));
    expect(backend.callsTo("POST", "/api/v1/connectors/github")[0].body).toMatchObject({ workspace_id: uuid(2) });
    expect(await screen.findByText("octocat/Hello-World", { selector: "span" })).toBeTruthy();
    expect(screen.getByText("beta/site")).toBeTruthy();
  });

  it("accepts a pasted GitHub URL", async () => {
    const { backend } = setup();
    await chooseWorkspace(uuid(1));
    await screen.findByRole("list", { name: "Connected repositories" });
    const form = await openConnect();
    fillConnect(form, { repo: "https://github.com/octocat/Hello-World.git", token: "ghp_valid" });
    submitConnect(form);
    await waitFor(() => expect(backend.callsTo("POST", "/api/v1/connectors/github")).toHaveLength(1));
    expect(backend.callsTo("POST", "/api/v1/connectors/github")[0].body).toMatchObject({ repo_full_name: "octocat/Hello-World" });
  });

  it.each(["not-a-repo", "owner/", "a/b/c", "has space/repo"])("rejects the repository %j without a request", async (repo) => {
    const { backend } = setup();
    await chooseWorkspace(uuid(1));
    await screen.findByRole("list", { name: "Connected repositories" });
    const form = await openConnect();
    fillConnect(form, { repo, token: "ghp_valid" });
    submitConnect(form);
    expect(within(form).getByText(/owner\/repository/)).toBeTruthy();
    expect(backend.callsTo("POST", "/api/v1/connectors/github")).toHaveLength(0);
    expect(screen.getByRole("dialog")).toBeTruthy();
  });

  it("requires a token, and a workspace when none is chosen", async () => {
    const { backend } = setup();
    await screen.findByRole("option", { name: "Alpha" });
    const form = await openConnect();
    fillConnect(form, { repo: "octocat/Hello-World", token: "   " });
    submitConnect(form);
    expect(within(form).getByText("Enter a GitHub token.")).toBeTruthy();
    expect(within(form).getByText("Choose a workspace.")).toBeTruthy();
    expect(backend.callsTo("POST", "/api/v1/connectors/github")).toHaveLength(0);
  });

  it("keeps the dialog open on a rejected token, with fixed wording and an emptied token field", async () => {
    const { backend } = setup();
    await chooseWorkspace(uuid(1));
    await screen.findByRole("list", { name: "Connected repositories" });
    const form = await openConnect();
    fillConnect(form, { repo: "octocat/Hello-World", token: "ghp_wrong_token" });
    submitConnect(form);
    expect((await within(form).findByText(/GitHub didn’t accept the token/)).textContent).not.toContain("ghp_wrong_token");
    expect(tokenInput(form).value).toBe("");
    expect(screen.getByRole("dialog")).toBeTruthy();
    expect(backend.state.connectors.some((c) => c.github_repo === "octocat/Hello-World")).toBe(false);
  });

  it("explains a repository that can't be found", async () => {
    setup();
    await chooseWorkspace(uuid(1));
    await screen.findByRole("list", { name: "Connected repositories" });
    const form = await openConnect();
    fillConnect(form, { repo: "octocat/missing-repo", token: "ghp_valid" });
    submitConnect(form);
    expect(await within(form).findByText(/couldn’t find that repository/)).toBeTruthy();
  });

  it("ends the session when the API answers 401", async () => {
    const { backend } = setup();
    await chooseWorkspace(uuid(1));
    await screen.findByRole("list", { name: "Connected repositories" });
    const form = await openConnect();
    backend.state.override = (call) =>
      call.path === "/api/v1/connectors/github" ? apiError(401, "UNAUTHORIZED", "Invalid or expired authentication token") : null;
    fillConnect(form, { repo: "octocat/Hello-World", token: "ghp_valid" });
    submitConnect(form);
    await waitFor(() => expect(getAccessToken()).toBeNull());
  });

  it("sends one request however many times it is submitted", async () => {
    const { backend } = setup();
    await chooseWorkspace(uuid(1));
    await screen.findByRole("list", { name: "Connected repositories" });
    const form = await openConnect();
    const gate = deferred();
    backend.state.connectGate = () => gate.promise;
    fillConnect(form, { repo: "octocat/Hello-World", token: "ghp_valid" });
    submitConnect(form);
    await waitFor(() => expect(backend.callsTo("POST", "/api/v1/connectors/github")).toHaveLength(1));
    fireEvent.submit(form.querySelector("form")!);
    fireEvent.submit(form.querySelector("form")!);
    gate.resolve();
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(backend.callsTo("POST", "/api/v1/connectors/github")).toHaveLength(1);
  });
});

describe("synchronising", () => {
  async function openSync(name = "acme/docs") {
    fireEvent.click(within(rowFor(name)).getByRole("button", { name: `Sync ${name}` }));
    return dialog();
  }
  async function ready() {
    const ctx = setup();
    await chooseWorkspace(uuid(1));
    await screen.findByRole("list", { name: "Connected repositories" });
    return ctx;
  }

  it("asks for the token, explaining why and what a sync can delete", async () => {
    const { backend } = await ready();
    const sync = await openSync();
    expect(sync.textContent).toMatch(/doesn’t store tokens, so it’s needed again every time/);
    expect(sync.textContent).toMatch(/no longer exist in the repository will be deleted/);
    expect(tokenInput(sync).type).toBe("password");
    fireEvent.click(within(sync).getByRole("button", { name: "Start sync" }));
    expect(within(sync).getByText("Enter a GitHub token.")).toBeTruthy();
    expect(backend.callsTo("POST", `/api/v1/connectors/${uuid(6001)}/sync`)).toHaveLength(0);
  });

  it("syncs, shows progress without percentages, then every statistic", async () => {
    const { backend } = await ready();
    const gate = deferred();
    backend.state.syncGate = () => gate.promise;
    const sync = await openSync();
    fireEvent.change(tokenInput(sync), { target: { value: " ghp_valid " } });
    fireEvent.click(within(sync).getByRole("button", { name: "Start sync" }));

    expect(await within(sync).findByText(/Syncing acme\/docs…/)).toBeTruthy();
    expect(sync.textContent).toMatch(/can’t show live\s+progress/);
    expect(sync.textContent).not.toMatch(/%/);
    expect(within(sync).queryByLabelText("GitHub personal access token")).toBeNull(); // token field is gone

    gate.resolve();
    expect(await within(sync).findByText("completed")).toBeTruthy();
    const stat = (label: string) => within(sync).getByText(label).nextElementSibling!.textContent;
    expect(stat("Discovered")).toBe("3");
    expect(stat("Added")).toBe("2");
    expect(stat("Updated")).toBe("0");
    expect(stat("Deleted")).toBe("0");
    expect(stat("Unchanged")).toBe("1");
    expect(stat("Skipped")).toBe("0");
    expect(backend.callsTo("POST", `/api/v1/connectors/${uuid(6001)}/sync`)[0].body).toEqual({ github_token: "ghp_valid" });
    expect(toast.success).toHaveBeenCalledWith("Synced acme/docs");

    fireEvent.click(within(sync).getByRole("button", { name: "Done" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("refreshes the connector's last-synced time after a sync", async () => {
    await ready();
    expect(within(rowFor("acme/api")).getByText("Never synced")).toBeTruthy();
    const sync = await openSync("acme/api");
    fireEvent.change(tokenInput(sync), { target: { value: "ghp_valid" } });
    fireEvent.click(within(sync).getByRole("button", { name: "Start sync" }));
    await within(sync).findByText("completed");
    fireEvent.click(within(sync).getByRole("button", { name: "Done" }));
    await waitFor(() => expect(within(rowFor("acme/api")).queryByText("Never synced")).toBeNull());
    expect(within(rowFor("acme/api")).getByText(/Last synced/)).toBeTruthy();
  });

  it("reports a failed sync, empties the token and lets the user retry", async () => {
    await ready();
    const sync = await openSync();
    fireEvent.change(tokenInput(sync), { target: { value: "ghp_expired" } });
    fireEvent.click(within(sync).getByRole("button", { name: "Start sync" }));
    expect((await within(sync).findByText(/GitHub didn’t accept the token/)).textContent).not.toContain("ghp_expired");
    expect(tokenInput(sync).value).toBe("");

    fireEvent.change(tokenInput(sync), { target: { value: "ghp_valid" } });
    fireEvent.click(within(sync).getByRole("button", { name: "Start sync" }));
    expect(await within(sync).findByText("completed")).toBeTruthy();
  });

  it("disables syncing while that connector's sync runs and sends a single request", async () => {
    const { backend } = await ready();
    const gate = deferred();
    backend.state.syncGate = () => gate.promise;
    const sync = await openSync();
    fireEvent.change(tokenInput(sync), { target: { value: "ghp_valid" } });
    fireEvent.click(within(sync).getByRole("button", { name: "Start sync" }));
    await within(sync).findByText(/Syncing acme\/docs…/);

    const row = rowFor("acme/docs");
    const syncButton = within(row).getByRole("button", { name: /Sync acme\/docs/, hidden: true }) as HTMLButtonElement;
    expect(syncButton.disabled).toBe(true);
    expect((within(row).getByRole("button", { name: /Disconnect acme\/docs/, hidden: true }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(syncButton);
    fireEvent.keyDown(document.body, { key: "Escape" }); // can't dismiss mid-sync
    expect(screen.getByRole("dialog")).toBeTruthy();

    gate.resolve();
    await within(sync).findByText("completed");
    expect(backend.callsTo("POST", `/api/v1/connectors/${uuid(6001)}/sync`)).toHaveLength(1);
  });
});

describe("disconnecting", () => {
  async function openDisconnect(name = "acme/docs") {
    const ctx = setup({ documents: [makeDocument(1, 1, "docs/README.md"), makeDocument(2, 1, "manual.txt")] });
    await chooseWorkspace(uuid(1));
    await screen.findByRole("list", { name: "Connected repositories" });
    fireEvent.click(within(rowFor(name)).getByRole("button", { name: `Disconnect ${name}` }));
    return { ...ctx, confirm: await dialog() };
  }

  it("explains that imported documents are kept, and does nothing until confirmed", async () => {
    const { backend, confirm } = await openDisconnect();
    expect(confirm.textContent).toMatch(/Documents already imported stay in the workspace as ordinary documents/);
    expect(confirm.textContent).toMatch(/no\s+longer be updated from GitHub/);
    expect(confirm.textContent).not.toMatch(/delete(s|d)? (all|the) (imported )?documents/i);
    expect(backend.callsTo("DELETE", `/api/v1/connectors/${uuid(6001)}`)).toHaveLength(0);
    fireEvent.click(within(confirm).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(backend.callsTo("DELETE", `/api/v1/connectors/${uuid(6001)}`)).toHaveLength(0);
    expect(rows()).toHaveLength(2);
  });

  it("deletes on confirmation, handles the empty 204 response, and leaves documents alone", async () => {
    const { backend, confirm } = await openDisconnect();
    fireEvent.click(within(confirm).getByRole("button", { name: "Disconnect" }));
    await waitFor(() => expect(rows()).toHaveLength(1));
    expect(screen.queryByText("acme/docs")).toBeNull();
    expect(backend.callsTo("DELETE", `/api/v1/connectors/${uuid(6001)}`)).toHaveLength(1);
    expect(toast.success).toHaveBeenCalledWith("Disconnected acme/docs");
    expect(backend.state.documents).toHaveLength(2); // imported documents are preserved
  });

  it("sends one DELETE for repeated clicks", async () => {
    const { backend, confirm } = await openDisconnect();
    const button = within(confirm).getByRole("button", { name: "Disconnect" });
    fireEvent.click(button);
    fireEvent.click(button);
    await waitFor(() => expect(rows()).toHaveLength(1));
    expect(backend.callsTo("DELETE", `/api/v1/connectors/${uuid(6001)}`)).toHaveLength(1);
  });

  it("keeps the connection and explains when disconnecting fails", async () => {
    const { backend, confirm } = await openDisconnect();
    backend.state.override = (call) =>
      call.method === "DELETE" ? apiError(500, "INTERNAL_SERVER_ERROR", "An unexpected error occurred") : null;
    fireEvent.click(within(confirm).getByRole("button", { name: "Disconnect" }));
    expect((await within(confirm).findByRole("alert")).textContent).toMatch(/our side/);
    expect(rows()).toHaveLength(2);
  });
});

describe("documents after a sync", () => {
  it("refreshes the workspace's document list with the imported files", async () => {
    const backend = createFakeBackend({ workspaces: workspaces(), connectors: connectors() });
    renderApp(
      <>
        <IntegrationsView />
        <WorkspaceDocuments workspaceId={uuid(1)} />
      </>,
    );
    expect(await screen.findByText("No documents yet")).toBeTruthy();
    await chooseWorkspace(uuid(1));
    await screen.findByRole("list", { name: "Connected repositories" });

    fireEvent.click(within(rowFor("acme/docs")).getByRole("button", { name: "Sync acme/docs" }));
    const sync = await dialog();
    fireEvent.change(tokenInput(sync), { target: { value: "ghp_valid" } });
    fireEvent.click(within(sync).getByRole("button", { name: "Start sync" }));
    await within(sync).findByText("completed");
    fireEvent.click(within(sync).getByRole("button", { name: "Done" }));

    // The imported files show up in the existing Documents list without a reload.
    expect(await screen.findByText("docs/README.md", { selector: "ul[aria-label='Documents'] p" })).toBeTruthy();
    expect(screen.getByText("docs/guide.md", { selector: "ul[aria-label='Documents'] p" })).toBeTruthy();
    expect(backend.callsTo("GET", "/api/v1/documents").length).toBeGreaterThan(1);
  });
});
