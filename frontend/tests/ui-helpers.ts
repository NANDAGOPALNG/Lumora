import { fireEvent, screen } from "@testing-library/react";

/** Open a workspace card's actions menu and choose an item (Radix opens on Enter). */
export async function chooseCardAction(workspaceName: string, item: RegExp) {
  const trigger = await screen.findByRole("button", { name: `Actions for ${workspaceName}` });
  fireEvent.keyDown(trigger, { key: "Enter" });
  fireEvent.click(await screen.findByRole("menuitem", { name: item }));
}

export const dialog = () => screen.findByRole("dialog");
export const nameInput = () => screen.getByLabelText("Workspace name") as HTMLInputElement;
export const type = (input: HTMLElement, value: string) =>
  fireEvent.change(input, { target: { value } });

export function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>((r) => (resolve = r));
  return { promise, resolve };
}

export function makeFile(name: string, content = "hello world", type = "text/plain") {
  return new File([content], name, { type });
}

/** Pretend a file has a given size without allocating that much memory. */
export function withSize(file: File, size: number) {
  Object.defineProperty(file, "size", { value: size });
  return file;
}

export function chooseFiles(...files: File[]) {
  const input = screen.getByLabelText("Choose documents to upload") as HTMLInputElement;
  fireEvent.change(input, { target: { files } });
}

/** The status shown by a document row's badge ("Indexing" counts as Processing). */
export const statusOf = (row: HTMLElement) =>
  row.querySelector("[data-status]")?.getAttribute("data-status") ?? null;
