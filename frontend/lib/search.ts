/** Largest page the backend allows (MAX_TOP_K in backend/app/retrieval/validation.py). */
export const MAX_TOP_K = 50;
export const DEFAULT_TOP_K = 5;
export const TOP_K_OPTIONS = [5, 10, 20, MAX_TOP_K] as const;

/** Everything that determines which results are valid, i.e. what a search was run with. */
export interface SearchParams {
  query: string;
  workspaceId: string;
  documentId: string | null;
  topK: number;
}

export function sameSelection(a: SearchParams, b: Omit<SearchParams, "query">): boolean {
  return a.workspaceId === b.workspaceId && a.documentId === b.documentId && a.topK === b.topK;
}

export function sameSearch(a: SearchParams, b: SearchParams): boolean {
  return a.query === b.query && sameSelection(a, b);
}

/** The backend's score scale isn't documented, so show it as a plain number, never a percentage. */
export function formatScore(score: number): string {
  return Number.isFinite(score) ? score.toFixed(3) : "n/a";
}

export const PREVIEW_LENGTH = 280;

export function previewOf(content: string): string {
  const text = content.trim();
  if (text.length <= PREVIEW_LENGTH) return text;
  return `${text.slice(0, PREVIEW_LENGTH).trimEnd()}…`;
}

export function isTruncated(content: string): boolean {
  return content.trim().length > PREVIEW_LENGTH;
}
