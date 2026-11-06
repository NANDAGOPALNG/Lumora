import { describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { WorkspaceDocuments } from "@/components/documents/workspace-documents";
import { createFakeBackend, document, uuid, workspace } from "./fake-backend";
import { renderApp } from "./render-app";
import { statusOf } from "./ui-helpers";

// Keep the real "poll only while Processing" decision, but shrink the interval so the test is fast.
vi.mock("@/lib/documents", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/documents")>();
  return {
    ...original,
    documentsRefetchInterval: (docs: Parameters<typeof original.documentsRefetchInterval>[0], count: number) =>
      original.documentsRefetchInterval(docs, count) === false ? false : 30,
  };
});
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() }, Toaster: () => null }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn(), push: vi.fn() }) }));

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
const listCalls = (backend: ReturnType<typeof createFakeBackend>) => backend.callsTo("GET", "/api/v1/documents").length;

describe("polling while documents are processing", () => {
  it("polls until a Processing document finishes, then stops", async () => {
    const backend = createFakeBackend({
      workspaces: [workspace(1, "Alpha")],
      documents: [document(1, 1, "busy.txt", "Processing", { chunk_count: 0 })],
    });
    backend.state.indexedAfterListCalls[uuid(1001)] = 3; // becomes Indexed on the 3rd list request
    renderApp(<WorkspaceDocuments workspaceId={uuid(1)} />);

    await waitFor(() => expect(statusOf(screen.getByText("busy.txt").closest("li")!)).toBe("Indexed"), {
      timeout: 3000,
    });

    const settled = listCalls(backend);
    await sleep(250); // several poll intervals
    expect(listCalls(backend)).toBe(settled); // no polling once nothing is processing
  });

  it("never polls when no document is processing", async () => {
    const backend = createFakeBackend({
      workspaces: [workspace(1, "Alpha")],
      documents: [document(1, 1, "a.txt", "Indexed"), document(2, 1, "b.txt", "Uploaded"), document(3, 1, "c.txt", "Failed")],
    });
    renderApp(<WorkspaceDocuments workspaceId={uuid(1)} />);
    await screen.findByText("a.txt");
    await sleep(250);
    expect(listCalls(backend)).toBe(1);
  });
});
