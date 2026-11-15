import { useEffect } from "react";
import { describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClientProvider, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { AuthProvider } from "@/components/providers/auth-provider";
import { createAppQueryClient, QueryProvider } from "@/components/providers/query-provider";
import { OverviewStats } from "@/components/dashboard/overview-stats";
import { RecentActivity } from "@/components/dashboard/recent-activity";
import { useAuth } from "@/hooks/use-auth";
import { dashboardKey } from "@/hooks/use-dashboard";
import { useCreateWorkspace } from "@/hooks/use-workspaces";
import { getAccessToken, setAccessToken } from "@/lib/auth/session";
import type { DashboardActivity, DashboardSummaryResponse } from "@/types/api";
import { apiError, json, USER } from "./helpers";
import { createFakeBackend, uuid } from "./fake-backend";
import { renderApp } from "./render-app";
import { deferred } from "./ui-helpers";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() }, Toaster: () => null }));

const BOB = { ...USER, id: "22222222-2222-4222-8222-222222222222", email: "bob@example.com", name: "Bob" };
const PATH = "/api/v1/dashboard/summary";

const summary = (
  stats: Partial<DashboardSummaryResponse["stats"]> = {},
  recent_activity: DashboardActivity[] = [],
): DashboardSummaryResponse => ({
  stats: { workspaces: 0, documents: 0, indexed_chunks: 0, conversations: 0, ...stats },
  recent_activity,
});

const activity = (over: Partial<DashboardActivity> & Pick<DashboardActivity, "id" | "type" | "title">): DashboardActivity => ({
  description: "Details",
  created_at: new Date(Date.now() - 5 * 60_000).toISOString(),
  workspace_id: null,
  link: null,
  ...over,
});

/** Serve the dashboard summary through the fake backend's override hook. */
function serve(
  respond: (call: { authorization?: string }) => Response | Promise<Response>,
  options: Parameters<typeof createFakeBackend>[0] = {},
) {
  const backend = createFakeBackend(options);
  backend.state.override = (call) => (call.path === PATH ? (respond(call) as Response) : null);
  return backend;
}

const summaryCalls = (backend: ReturnType<typeof createFakeBackend>) =>
  backend.state.calls.filter((c) => c.path === PATH);

function Both() {
  return (
    <>
      <OverviewStats />
      <RecentActivity />
    </>
  );
}

describe("dashboard overview", () => {
  it("shows skeletons while loading, then the real backend values", async () => {
    const gate = deferred();
    serve(async () => {
      await gate.promise;
      return json(200, summary({ workspaces: 3, documents: 12, indexed_chunks: 1234, conversations: 7 }));
    });
    renderApp(<OverviewStats />);

    expect(await screen.findByText("Loading overview")).toBeTruthy();
    expect(screen.queryByText("—")).toBeNull();

    gate.resolve();
    await waitFor(() => expect(screen.getByText("1,234")).toBeTruthy());
    const stats = within(screen.getByRole("region", { name: "Overview" }));
    const value = (label: string) => stats.getByText(label).nextElementSibling?.textContent;
    expect(value("Workspaces")).toBe("3");
    expect(value("Documents")).toBe("12");
    expect(value("Indexed chunks")).toBe("1,234");
    expect(value("Conversations")).toBe("7");
    expect(screen.queryByText(/not connected/i)).toBeNull();
  });

  it("shows genuine zeros, never placeholder dashes, for a user with no data", async () => {
    serve(() => json(200, summary()));
    renderApp(<OverviewStats />);
    await waitFor(() => expect(screen.getAllByText("0")).toHaveLength(4));
    expect(screen.queryByText("—")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("shows an error with a working retry", async () => {
    let fail = true;
    const backend = serve(() =>
      fail ? apiError(500, "INTERNAL_ERROR", "boom") : json(200, summary({ workspaces: 4 })),
    );
    renderApp(<OverviewStats />);

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toMatch(/Couldn’t load your overview/);
    expect(screen.queryByText("4")).toBeNull();
    // values are explicitly "unavailable" (not an endless loading skeleton) while the error shows
    expect(screen.getAllByLabelText("Unavailable")).toHaveLength(4);

    fail = false;
    fireEvent.click(within(alert).getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(screen.getByText("4")).toBeTruthy());
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByLabelText("Unavailable")).toBeNull();
    expect(summaryCalls(backend)).toHaveLength(2);
  });

  it("explains a network failure in plain language", async () => {
    serve(() => {
      throw new TypeError("Failed to fetch");
    });
    renderApp(<OverviewStats />);
    expect((await screen.findByRole("alert")).textContent).toMatch(/Can’t reach the Lumora server/);
  });
});

describe("recent activity", () => {
  it("shows a skeleton, then each activity with its type, text, time and link", async () => {
    const gate = deferred();
    const items = [
      activity({ id: "document:1", type: "document_uploaded", title: "Uploaded report.pdf", description: "Document added to Research", workspace_id: uuid(3), link: `/workspaces/${uuid(3)}` }),
      activity({ id: "connector:1", type: "connector_synced", title: "Synced octo/repo", description: "GitHub repository synced in Research", link: "/integrations" }),
      activity({ id: "conversation:1", type: "conversation_created", title: "Started conversation: Deploy?", description: "New chat with your knowledge base", link: `/chat?c=${uuid(5)}` }),
    ];
    serve(async () => {
      await gate.promise;
      return json(200, summary({}, items));
    });
    renderApp(<RecentActivity />);

    expect(await screen.findByRole("status", { name: "Loading recent activity" })).toBeTruthy();
    gate.resolve();

    const list = await screen.findByRole("list");
    const rows = within(list).getAllByRole("listitem");
    expect(rows).toHaveLength(3);

    const doc = within(rows[0]);
    expect(doc.getByText("Uploaded report.pdf")).toBeTruthy();
    expect(doc.getByText("Document added to Research")).toBeTruthy();
    expect(doc.getByText(/Document upload/)).toBeTruthy(); // accessible type label
    expect(doc.getByText("5 minutes ago")).toBeTruthy();
    expect(doc.getByRole("link").getAttribute("href")).toBe(`/workspaces/${uuid(3)}`);
    expect(rows[0].querySelector("time")?.getAttribute("datetime")).toBe(items[0].created_at);

    expect(within(rows[1]).getByText(/Connector sync/)).toBeTruthy();
    expect(within(rows[1]).getByRole("link").getAttribute("href")).toBe("/integrations");
    expect(within(rows[2]).getByText(/Conversation:/)).toBeTruthy();
    expect(within(rows[2]).getByRole("link").getAttribute("href")).toBe(`/chat?c=${uuid(5)}`);
    expect(screen.queryByText("No activity yet")).toBeNull();
  });

  it("renders unsafe or missing links as plain text, never as links", async () => {
    serve(() =>
      json(
        200,
        summary({}, [
          activity({ id: "a", type: "document_uploaded", title: "No link", link: null }),
          activity({ id: "b", type: "connector_synced", title: "External", link: "https://evil.example" }),
          activity({ id: "c", type: "connector_synced", title: "Protocol relative", link: "//evil.example" }),
        ]),
      ),
    );
    renderApp(<RecentActivity />);
    await screen.findByText("External");
    expect(screen.queryAllByRole("link")).toHaveLength(0);
  });

  it("shows the empty state only when there is genuinely no activity", async () => {
    serve(() => json(200, summary()));
    renderApp(<RecentActivity />);
    expect(await screen.findByText("No activity yet")).toBeTruthy();
    expect(screen.queryByRole("list")).toBeNull();
    expect(screen.queryByText(/Couldn’t load/)).toBeNull();
  });

  it("shows an error state with retry instead of the empty state", async () => {
    let fail = true;
    serve(() =>
      fail
        ? apiError(500, "INTERNAL_ERROR", "boom")
        : json(200, summary({}, [activity({ id: "d", type: "conversation_created", title: "Back again" })])),
    );
    renderApp(<RecentActivity />);
    expect(await screen.findByText("Couldn’t load recent activity")).toBeTruthy();
    expect(screen.queryByText("No activity yet")).toBeNull();

    fail = false;
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("Back again")).toBeTruthy();
  });
});

describe("dashboard data sharing and session behavior", () => {
  it("makes a single request for both panels", async () => {
    const backend = serve(() => json(200, summary({ documents: 2 })));
    renderApp(<Both />);
    await screen.findByText("No activity yet");
    expect(summaryCalls(backend)).toHaveLength(1);
  });

  it("sends only the bearer token and keys the cache by user id, never by token", async () => {
    const backend = serve(() => json(200, summary()));
    const { client } = renderApp(<OverviewStats />);
    await waitFor(() => expect(screen.getAllByText("0")).toHaveLength(4));
    const call = summaryCalls(backend)[0];
    expect(call.authorization).toBe("Bearer token-ada");
    expect(call.query.toString()).toBe("");
    const keys = client.getQueryCache().getAll().map((q) => JSON.stringify(q.queryKey)).join("|");
    expect(keys).toContain(USER.id);
    expect(keys).not.toContain("token-ada");
    expect(dashboardKey(USER.id)).toEqual(["dashboard", USER.id, "summary"]);
    expect(dashboardKey(null)).toEqual(["dashboard", "anonymous", "summary"]);
  });

  it("does not request anything while signed out", async () => {
    const backend = serve(() => json(200, summary()));
    renderApp(<OverviewStats />, { token: null });
    await new Promise((r) => setTimeout(r, 30));
    expect(summaryCalls(backend)).toHaveLength(0);
  });

  it("never shows one user's dashboard to the next user after sign-out and sign-in", async () => {
    const holder: { auth?: ReturnType<typeof useAuth>; client?: QueryClient } = {};
    function Probe() {
      const currentAuth = useAuth();
      const currentClient = useQueryClient();
      useEffect(() => {
        holder.auth = currentAuth;
        holder.client = currentClient;
      });
      return <Both />;
    }

    const backend = serve(
      (call) =>
        call.authorization === "Bearer token-bob"
          ? json(200, summary({ workspaces: 9 }, [activity({ id: "b", type: "document_uploaded", title: "Bob private doc" })]))
          : json(200, summary({ workspaces: 2 }, [activity({ id: "a", type: "document_uploaded", title: "Ada private doc" })])),
      { users: { "token-ada": USER, "token-bob": BOB } },
    );
    const previousOverride = backend.state.override;
    backend.state.override = (call) =>
      call.path === "/api/v1/auth/google"
        ? json(200, { access_token: "token-bob", user: { id: BOB.id, name: BOB.name, email: BOB.email } })
        : previousOverride!(call);

    setAccessToken("token-ada");
    render(
      <AuthProvider>
        <QueryProvider>
          <Probe />
        </QueryProvider>
      </AuthProvider>,
    );
    await screen.findByText("Ada private doc");

    await act(() => holder.auth!.signOut());
    expect(getAccessToken()).toBeNull();
    expect(screen.queryByText("Ada private doc")).toBeNull();
    await waitFor(() =>
      expect(holder.client!.getQueryCache().getAll().every((q) => q.state.data === undefined)).toBe(true),
    );

    await act(() => holder.auth!.signIn("google-id-token"));
    await screen.findByText("Bob private doc");
    expect(screen.queryByText("Ada private doc")).toBeNull();
    expect(screen.getByText("9")).toBeTruthy();
  });

  it("marks the summary stale after any successful mutation so counts refresh", async () => {
    let workspaces = 1;
    const backend = serve(() => json(200, summary({ workspaces })));

    function Probe() {
      const create = useCreateWorkspace();
      return <button onClick={() => create.mutate("New space")}>create</button>;
    }

    setAccessToken("token-ada");
    const client = createAppQueryClient();
    client.setDefaultOptions({ queries: { staleTime: 30_000, retry: false, retryDelay: 0 } });
    render(
      <AuthProvider>
        <QueryClientProvider client={client}>
          <OverviewStats />
          <Probe />
        </QueryClientProvider>
      </AuthProvider>,
    );
    await waitFor(() => expect(screen.getByText("1")).toBeTruthy());
    expect(summaryCalls(backend)).toHaveLength(1);

    workspaces = 2;
    fireEvent.click(screen.getByRole("button", { name: "create" }));
    await waitFor(() => expect(screen.getByText("2")).toBeTruthy());
    expect(summaryCalls(backend)).toHaveLength(2);
  });
});
