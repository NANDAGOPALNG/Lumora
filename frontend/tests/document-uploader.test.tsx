import { describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { toast } from "sonner";
import { WorkspaceDocuments } from "@/components/documents/workspace-documents";
import { apiError } from "./helpers";
import { createFakeBackend, uuid, workspace } from "./fake-backend";
import { renderApp } from "./render-app";
import { chooseFiles, deferred, makeFile, statusOf, withSize } from "./ui-helpers";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() }, Toaster: () => null }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn(), push: vi.fn() }) }));

const WS = uuid(1);
const setup = (opts: Parameters<typeof createFakeBackend>[0] = {}) => {
  const backend = createFakeBackend({ workspaces: [workspace(1, "Alpha")], ...opts });
  renderApp(<WorkspaceDocuments workspaceId={WS} />);
  return backend;
};
const row = (name: string) => screen.getByText(name, { selector: "ul[aria-label='Documents'] p" }).closest("li")!;
const queueItem = (name: string) =>
  within(screen.getByRole("list", { name: "Upload queue" })).getByText(name).closest("li")!;

describe("successful upload", () => {
  it("uploads, then indexes automatically, and the document appears Indexed", async () => {
    const backend = setup();
    await screen.findByText("No documents yet");

    chooseFiles(makeFile("notes.md", "# Notes"));

    await waitFor(() => expect(within(row("notes.md")).getByText("Indexed")).toBeTruthy());
    const [upload] = backend.callsTo("POST", "/api/v1/documents/upload");
    expect(upload.form?.get("workspace_id")).toBe(WS);
    expect((upload.form?.get("file") as File).name).toBe("notes.md");
    expect(backend.callsTo("POST", `/api/v1/documents/${uuid(5000)}/reindex`)).toHaveLength(1);
    expect(within(queueItem("notes.md")).getByText("Uploaded and indexed")).toBeTruthy();
    expect(within(row("notes.md")).getByText(/3 chunks/)).toBeTruthy();
  });

  it("accepts files dropped onto the zone", async () => {
    const backend = setup();
    await screen.findByText("No documents yet");
    const zone = screen.getByText(/Drag files here/).closest("div[class*='border-dashed']")!;
    fireEvent.drop(zone, { dataTransfer: { files: [makeFile("dropped.txt")] } });
    await waitFor(() => expect(within(row("dropped.txt")).getByText("Indexed")).toBeTruthy());
    expect(backend.callsTo("POST", "/api/v1/documents/upload")).toHaveLength(1);
  });

  it("with auto-index off, only uploads and leaves the document Uploaded until indexed manually", async () => {
    const backend = setup();
    await screen.findByText("No documents yet");
    fireEvent.click(screen.getByLabelText(/Index automatically after upload/));

    chooseFiles(makeFile("manual.txt"));

    await waitFor(() => expect(statusOf(row("manual.txt"))).toBe("Uploaded"));
    expect(within(queueItem("manual.txt")).getByText(/not indexed yet/)).toBeTruthy();
    expect(backend.callsTo("POST", `/api/v1/documents/${uuid(5000)}/reindex`)).toHaveLength(0);

    fireEvent.click(within(row("manual.txt")).getByRole("button", { name: "Index" }));
    await waitFor(() => expect(within(row("manual.txt")).getByText("Indexed")).toBeTruthy());
  });

  it("handles several files one after another", async () => {
    const backend = setup();
    await screen.findByText("No documents yet");
    const gate = deferred();
    backend.state.uploadGate = () => gate.promise;

    chooseFiles(makeFile("first.txt", "1"), makeFile("second.txt", "22"));
    await waitFor(() => expect(within(queueItem("first.txt")).getByText(/Uploading/)).toBeTruthy());
    expect(within(queueItem("second.txt")).getByText("Waiting to upload")).toBeTruthy();
    expect(backend.callsTo("POST", "/api/v1/documents/upload")).toHaveLength(1);

    backend.state.uploadGate = null;
    gate.resolve();
    await waitFor(() => expect(within(row("second.txt")).getByText("Indexed")).toBeTruthy());
    expect(within(row("first.txt")).getByText("Indexed")).toBeTruthy();
  });
});

describe("client-side validation (nothing is sent)", () => {
  it.each([
    ["photo.png", makeFile("photo.png", "x"), /Unsupported file type/],
    ["empty.txt", makeFile("empty.txt", ""), "This file is empty."],
    ["huge.pdf", withSize(makeFile("huge.pdf"), 21 * 1024 * 1024), /over the 20 MB limit/],
  ])("rejects %s with a clear reason", async (name, file, message) => {
    const backend = setup();
    await screen.findByText("No documents yet");
    chooseFiles(file);
    expect(within(queueItem(name)).getByText(message)).toBeTruthy();
    expect(backend.callsTo("POST", "/api/v1/documents/upload")).toHaveLength(0);
    expect(screen.getByText("No documents yet")).toBeTruthy();
  });

  it("uploads the valid files from a mixed selection and explains the rest", async () => {
    const backend = setup();
    await screen.findByText("No documents yet");
    chooseFiles(makeFile("ok.pdf", "x", "application/pdf"), makeFile("bad.exe", "x"));
    await waitFor(() => expect(within(row("ok.pdf")).getByText("Indexed")).toBeTruthy());
    expect(within(queueItem("bad.exe")).getByText(/Unsupported file type/)).toBeTruthy();
    expect(backend.callsTo("POST", "/api/v1/documents/upload")).toHaveLength(1);
  });
});

describe("failures", () => {
  it("shows the server's file-size limit when it rejects an upload (413)", async () => {
    const backend = setup();
    await screen.findByText("No documents yet");
    backend.state.maxUploadBytes = 2 * 1024 * 1024;
    chooseFiles(makeFile("big.txt", "x".repeat(3 * 1024 * 1024)));
    expect(await within(queueItem("big.txt")).findByText(/limit 2 MB/)).toBeTruthy();
    expect(screen.getByText("No documents yet")).toBeTruthy();
  });

  it("explains an unsupported type reported by the server (415)", async () => {
    const backend = setup();
    await screen.findByText("No documents yet");
    backend.state.override = (call) =>
      call.path === "/api/v1/documents/upload"
        ? apiError(415, "UNSUPPORTED_FILE_TYPE", "Content-Type 'x' does not match file extension '.md'")
        : null;
    chooseFiles(makeFile("odd.md"));
    expect(await within(queueItem("odd.md")).findByText(/PDF, DOCX, TXT or MD/)).toBeTruthy();
  });

  it("survives a network failure and succeeds on retry", async () => {
    const backend = setup();
    await screen.findByText("No documents yet");
    backend.state.down = true;
    chooseFiles(makeFile("flaky.txt"));
    expect(await within(queueItem("flaky.txt")).findByText(/Can’t reach the Lumora server/)).toBeTruthy();

    backend.state.down = false;
    fireEvent.click(screen.getByRole("button", { name: "Retry upload" }));
    await waitFor(() => expect(within(row("flaky.txt")).getByText("Indexed")).toBeTruthy());
  });

  it("keeps an uploaded document when indexing fails, shows it Failed, and can retry indexing", async () => {
    const backend = setup();
    await screen.findByText("No documents yet");
    backend.state.failReindex.add(uuid(5000));
    chooseFiles(makeFile("scan.txt"));

    expect(await within(queueItem("scan.txt")).findByText(/Indexing failed/)).toBeTruthy();
    await waitFor(() => expect(within(row("scan.txt")).getByText("Failed")).toBeTruthy());

    backend.state.failReindex.clear();
    fireEvent.click(within(queueItem("scan.txt")).getByRole("button", { name: "Retry indexing" }));
    await waitFor(() => expect(within(row("scan.txt")).getByText("Indexed")).toBeTruthy());
    expect(backend.callsTo("POST", "/api/v1/documents/upload")).toHaveLength(1); // not uploaded twice
  });
});

describe("duplicate and in-flight handling", () => {
  it("ignores the same file added again while it is still being uploaded", async () => {
    const backend = setup();
    await screen.findByText("No documents yet");
    const gate = deferred();
    backend.state.uploadGate = () => gate.promise;
    const file = makeFile("once.txt");

    chooseFiles(file);
    await waitFor(() => expect(within(queueItem("once.txt")).getByText(/Uploading/)).toBeTruthy());
    chooseFiles(file);
    expect(toast.info).toHaveBeenCalledWith("That file is already being uploaded.");

    backend.state.uploadGate = null;
    gate.resolve();
    await waitFor(() => expect(within(row("once.txt")).getByText("Indexed")).toBeTruthy());
    expect(backend.callsTo("POST", "/api/v1/documents/upload")).toHaveLength(1);
    expect(screen.getAllByText("once.txt", { selector: "span" })).toHaveLength(1);
  });

  it("cancels an upload in progress without creating a document", async () => {
    const backend = setup();
    await screen.findByText("No documents yet");
    const gate = deferred();
    backend.state.uploadGate = () => gate.promise;
    chooseFiles(makeFile("cancelme.txt"));
    await waitFor(() => expect(within(queueItem("cancelme.txt")).getByText(/Uploading/)).toBeTruthy());

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("list", { name: "Upload queue" })).toBeNull());
    gate.resolve();
    expect(backend.state.documents).toHaveLength(0);
    expect(screen.getByText("No documents yet")).toBeTruthy();
  });

  it("shows the in-progress state and a determinate progress bar while uploading", async () => {
    const backend = setup();
    await screen.findByText("No documents yet");
    const gate = deferred();
    backend.state.uploadGate = () => gate.promise;
    chooseFiles(makeFile("progress.txt"));
    const bar = await screen.findByRole("progressbar", { name: "Uploading progress.txt" });
    expect(bar.getAttribute("aria-valuemin")).toBe("0");
    expect(bar.getAttribute("aria-valuemax")).toBe("100");
    backend.state.uploadGate = null;
    gate.resolve();
    await waitFor(() => expect(within(row("progress.txt")).getByText("Indexed")).toBeTruthy());
  });

  it("lets finished items be cleared", async () => {
    setup();
    await screen.findByText("No documents yet");
    chooseFiles(makeFile("done.txt"));
    await waitFor(() => expect(within(row("done.txt")).getByText("Indexed")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "Clear finished" }));
    expect(screen.queryByRole("list", { name: "Upload queue" })).toBeNull();
    expect(row("done.txt")).toBeTruthy(); // the document itself stays
  });
});
