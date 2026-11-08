import { useSyncExternalStore } from "react";

/**
 * Which connectors have a sync running. Module-level so it survives leaving and returning to the
 * page while a request is still open, which stops a second sync starting on the same connector.
 * Holds only connector ids, never a credential.
 */
let syncing: ReadonlySet<string> = new Set();
const listeners = new Set<() => void>();

function set(next: Set<string>) {
  syncing = next;
  listeners.forEach((listener) => listener());
}

/** Returns false (and changes nothing) if this connector is already syncing. */
export function beginSync(connectorId: string): boolean {
  if (syncing.has(connectorId)) return false;
  set(new Set(syncing).add(connectorId));
  return true;
}

export function endSync(connectorId: string) {
  if (!syncing.has(connectorId)) return;
  const next = new Set(syncing);
  next.delete(connectorId);
  set(next);
}

export function useIsSyncing(connectorId: string): boolean {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => syncing.has(connectorId),
    () => false,
  );
}
