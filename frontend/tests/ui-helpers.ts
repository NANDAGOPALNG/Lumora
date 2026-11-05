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
