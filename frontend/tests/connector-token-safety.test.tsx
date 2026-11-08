import { useEffect } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import type { QueryClient } from "@tanstack/react-query";
import { IntegrationsView } from "@/components/integrations/integrations-view";
import { SyncAlreadyRunningError, useGitHubConnectorActions } from "@/hooks/use-connectors";
import { endSync } from "@/lib/sync-tracker";
import { connector, createFakeBackend, uuid, workspace } from "./fake-backend";
import { renderApp } from "./render-app";
import { deferred, dialog } from "./ui-helpers";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() }, Toaster: () => null }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn(), push: vi.fn() }) }));

const GOOD = "ghp_valid"; // the only token the fake backend accepts
const BAD = "ghp_rejected_secret_value";

afterEach(() => {
  for (let n = 1; n <= 10; n++) endSync(uuid(6000 + n));
});

const seed = () => ({
  workspaces: [workspace(1, "Solo")],
  connectors: [connector(1, 1, "acme/docs")],
});

/** Every place a credential must never end up. Returns the places where `token` was found. */
function whereLeaked(token: string, client: QueryClient, backend: ReturnType<typeof createFakeBackend>, consoleCalls: unknown[][]) {
  const found: string[] = [];
  const has = (haystack: string) => haystack.includes(token);

  if (has(JSON.stringify(client.getQueryCache().getAll().map((q) => ({ k: q.queryKey, d: q.state.data, e: String(q.state.error) }))))) found.push("query cache");
  if (has(JSON.stringify(client.getMutationCache().getAll().map((m) => ({ k: m.options.mutationKey, v: m.state.variables, d: m.state.data }))))) found.push("mutation cache");
  if (has(JSON.stringify({ ...window.localStorage }))) found.push("localStorage");
  if (has(JSON.stringify({ ...window.sessionStorage }))) found.push("sessionStorage");
  if (has(document.body.innerHTML)) found.push("DOM markup");
  if ([...document.querySelectorAll("input")].some((input) => has(input.value))) found.push("an input field");
  if (has(window.location.href)) found.push("page URL");
  if (backend.state.calls.some((c) => has(c.path) || has(c.query.toString()))) found.push("a request URL");
  if (has(JSON.stringify(consoleCalls))) found.push("console output");
  return found;
}

function setup() {
  const consoleCalls: unknown[][] = [];
  for (const method of ["log", "info", "warn", "error", "debug"] as const) {
    vi.spyOn(console, method).mockImplementation((...args) => void consoleCalls.push(args));
  }
  const backend = createFakeBackend(seed());
  const view = renderApp(<IntegrationsView />);
  return { backend, consoleCalls, ...view };
}

const connectForm = async () => {
  await screen.findByRole("list", { name: "Connected repositories" });
  fireEvent.click(screen.getByRole("button", { name: "Connect repository" }));
  return dialog();
};
const tokenInput = (form: HTMLElement) => within(form).getByLabelText("GitHub personal access token") as HTMLInputElement;
const fillAndConnect = (form: HTMLElement, token: string) => {
  fireEvent.change(within(form).getByLabelText("Repository"), { target: { value: "octocat/Hello-World" } });
  fireEvent.change(tokenInput(form), { target: { value: token } });
  fireEvent.click(within(form).getByRole("button", { name: "Connect repository" }));
};
const syncDialog = async (repo = "acme/docs") => {
  await screen.findByRole("list", { name: "Connected repositories" });
  fireEvent.click(screen.getByRole("button", { name: `Sync ${repo}` }));
  return dialog();
};

describe("the GitHub token is never kept", () => {
  it("leaves no trace after a successful connect", async () => {
    const { backend, client, consoleCalls } = setup();
    const form = await connectForm();
    fillAndConnect(form, GOOD);
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(await screen.findByText("octocat/Hello-World", { selector: "span" })).toBeTruthy();
    expect(whereLeaked(GOOD, client, backend, consoleCalls)).toEqual([]);
  });

  it("leaves no trace after a rejected connect, and empties the field", async () => {
    const { backend, client, consoleCalls } = setup();
    const form = await connectForm();
    fillAndConnect(form, BAD);
    await within(form).findByText(/GitHub didn’t accept the token/);
    expect(tokenInput(form).value).toBe("");
    expect(whereLeaked(BAD, client, backend, consoleCalls)).toEqual([]);
  });

  it("leaves no trace after a successful sync, and removes the token field", async () => {
    const { backend, client, consoleCalls } = setup();
    const sync = await syncDialog();
    fireEvent.change(tokenInput(sync), { target: { value: GOOD } });
    fireEvent.click(within(sync).getByRole("button", { name: "Start sync" }));
    await within(sync).findByText("completed");
    expect(within(sync).queryByLabelText("GitHub personal access token")).toBeNull();
    expect(whereLeaked(GOOD, client, backend, consoleCalls)).toEqual([]);
  });

  it("leaves no trace after a failed sync, and empties the field", async () => {
    const { backend, client, consoleCalls } = setup();
    const sync = await syncDialog();
    fireEvent.change(tokenInput(sync), { target: { value: BAD } });
    fireEvent.click(within(sync).getByRole("button", { name: "Start sync" }));
    await within(sync).findByText(/GitHub didn’t accept the token/);
    expect(tokenInput(sync).value).toBe("");
    expect(whereLeaked(BAD, client, backend, consoleCalls)).toEqual([]);
  });

  it("forgets a token typed into a dialog that is then cancelled", async () => {
    const { backend, client, consoleCalls } = setup();
    const sync = await syncDialog();
    fireEvent.change(tokenInput(sync), { target: { value: GOOD } });
    fireEvent.click(within(sync).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(whereLeaked(GOOD, client, backend, consoleCalls)).toEqual([]);

    fireEvent.click(screen.getByRole("button", { name: "Sync acme/docs" }));
    expect(tokenInput(await dialog()).value).toBe(""); // reopening starts empty
    expect(backend.callsTo("POST", `/api/v1/connectors/${uuid(6001)}/sync`)).toHaveLength(0);
  });

  it("only ever sends the token in the request body", async () => {
    const { backend } = setup();
    const sync = await syncDialog();
    fireEvent.change(tokenInput(sync), { target: { value: GOOD } });
    fireEvent.click(within(sync).getByRole("button", { name: "Start sync" }));
    await within(sync).findByText("completed");
    const [call] = backend.callsTo("POST", `/api/v1/connectors/${uuid(6001)}/sync`);
    expect(call.body).toEqual({ github_token: GOOD });
    expect(Object.values(call.headers).join(" ")).not.toContain(GOOD);
  });
});

const holder: { actions?: ReturnType<typeof useGitHubConnectorActions> } = {};
function Probe() {
  const actions = useGitHubConnectorActions();
  useEffect(() => {
    holder.actions = actions;
  });
  return null;
}

describe("concurrent syncs", () => {
  it("refuses a second sync of the same connector while one is running", async () => {
    const backend = createFakeBackend(seed());
    const gate = deferred();
    backend.state.syncGate = () => gate.promise;
    renderApp(<Probe />);
    await waitFor(() => expect(holder.actions).toBeDefined());

    const target = connector(1, 1, "acme/docs");
    const first = holder.actions!.sync(target, GOOD);
    await expect(holder.actions!.sync(target, GOOD)).rejects.toBeInstanceOf(SyncAlreadyRunningError);
    gate.resolve();
    await expect(first).resolves.toMatchObject({ status: "completed" });
    expect(backend.callsTo("POST", `/api/v1/connectors/${uuid(6001)}/sync`)).toHaveLength(1);

    // Once finished, the connector can be synced again.
    backend.state.syncGate = null;
    await expect(holder.actions!.sync(target, GOOD)).resolves.toMatchObject({ status: "completed" });
  });
});
