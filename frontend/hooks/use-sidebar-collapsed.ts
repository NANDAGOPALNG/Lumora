"use client";

import { useCallback, useSyncExternalStore } from "react";

const STORAGE_KEY = "lumora:sidebar-collapsed";
const listeners = new Set<() => void>();
let current: boolean | null = null;

function read(): boolean {
  if (current === null) {
    try {
      current = window.localStorage.getItem(STORAGE_KEY) === "1";
    } catch {
      current = false;
    }
  }
  return current;
}

function write(next: boolean) {
  current = next;
  try {
    window.localStorage.setItem(STORAGE_KEY, next ? "1" : "0");
  } catch {
    // Storage can be unavailable (private mode); the in-memory value still works.
  }
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  const onStorage = (event: StorageEvent) => {
    if (event.key === STORAGE_KEY) {
      current = event.newValue === "1";
      listener();
    }
  };
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", onStorage);
  };
}

/** Sidebar collapsed preference, persisted in localStorage and SSR-safe. */
export function useSidebarCollapsed() {
  const collapsed = useSyncExternalStore(subscribe, read, () => false);
  const setCollapsed = useCallback((next: boolean) => write(next), []);
  const toggle = useCallback(() => write(!read()), []);
  return { collapsed, setCollapsed, toggle };
}
