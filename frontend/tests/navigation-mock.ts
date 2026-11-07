import { useSyncExternalStore } from "react";

/** A tiny stand-in for next/navigation that keeps the URL's query string in memory. */
let search = new URLSearchParams();
const listeners = new Set<() => void>();
export const navigations: string[] = [];

export function setSearch(query: string) {
  search = new URLSearchParams(query);
  listeners.forEach((listener) => listener());
}
export const currentSearch = () => search.get("c");
export function resetNavigation() {
  navigations.length = 0;
  delayMs = 0;
  setSearch("");
}

/** Simulates a slow route transition: the URL changes only after this many milliseconds. */
let delayMs = 0;
export const setNavigationDelay = (ms: number) => {
  delayMs = ms;
};

const go = (url: string) => {
  navigations.push(url);
  const apply = () => setSearch(url.includes("?") ? url.slice(url.indexOf("?") + 1) : "");
  if (delayMs > 0) setTimeout(apply, delayMs);
  else apply();
};
const router = { replace: go, push: go };

export const useRouter = () => router;
export const usePathname = () => "/chat";
export function useSearchParams() {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => search,
    () => search,
  );
}
