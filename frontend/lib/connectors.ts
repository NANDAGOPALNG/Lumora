import type { ConnectorResponse } from "@/types/api";

/** Mirrors the backend's repository check (backend/app/schemas/connector.py). */
const REPO_PATTERN = /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/;

/**
 * Accepts "owner/repo" and also tidies a pasted GitHub URL
 * ("https://github.com/owner/repo", ".git" suffix, trailing slash) into that form.
 */
export function normaliseRepoInput(raw: string): string {
  return raw
    .trim()
    .replace(/^(https?:\/\/)?(www\.)?github\.com\//i, "")
    .replace(/\/+$/, "")
    .replace(/\.git$/i, "");
}

export function validateRepoFullName(raw: string): string | null {
  const repo = normaliseRepoInput(raw);
  if (!repo) return "Enter the repository as owner/repository.";
  if (!REPO_PATTERN.test(repo)) {
    return "Use the form owner/repository, for example octocat/Hello-World.";
  }
  return null;
}

export function validateToken(raw: string): string | null {
  return raw.trim() ? null : "Enter a GitHub token.";
}

export const isGitHubConnector = (connector: ConnectorResponse) => connector.type === "github";

/** A GitHub connector created before the repository was stored can't be synced; it must be reconnected. */
export const needsReconnect = (connector: ConnectorResponse) =>
  isGitHubConnector(connector) && !connector.github_repo;
