import type { ApiErrorEnvelope } from "@/types/api";
import { clearAccessToken, getAccessToken } from "@/lib/auth/session";

/** Error raised for any failed API call, including network failures (status 0). */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

export const NETWORK_ERROR = "NETWORK_ERROR";
export const CONFIG_ERROR = "CONFIG_ERROR";

type UnauthorizedHandler = () => void;
let unauthorizedHandler: UnauthorizedHandler | null = null;

/** The auth provider registers this to react when the backend rejects the session. */
export function setUnauthorizedHandler(handler: UnauthorizedHandler | null) {
  unauthorizedHandler = handler;
}

function getBaseUrl(): string {
  // Must be referenced literally so Next.js can inline it at build time.
  const base = process.env.NEXT_PUBLIC_API_BASE_URL;
  if (!base) {
    throw new ApiError(
      0,
      CONFIG_ERROR,
      "NEXT_PUBLIC_API_BASE_URL is not set. Add it to frontend/.env.local and restart the dev server.",
    );
  }
  return base.replace(/\/+$/, "");
}

interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  body?: unknown;
  /** Attach the Bearer token and treat 401 as an invalid session. Default: true. */
  auth?: boolean;
  signal?: AbortSignal;
}

async function parseError(response: Response): Promise<ApiError> {
  try {
    const data = (await response.json()) as Partial<ApiErrorEnvelope>;
    if (data?.error?.code && data.error.message) {
      return new ApiError(response.status, data.error.code, data.error.message);
    }
  } catch {
    // Non-JSON error body; fall through.
  }
  return new ApiError(
    response.status,
    "UNEXPECTED_RESPONSE",
    `The server returned an unexpected response (${response.status}).`,
  );
}

export async function apiFetch<T>(
  path: string,
  { method = "GET", body, auth = true, signal }: RequestOptions = {},
): Promise<T> {
  const url = `${getBaseUrl()}${path}`;
  const headers: Record<string, string> = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";

  const tokenUsed = auth ? getAccessToken() : null;
  if (tokenUsed) headers.Authorization = `Bearer ${tokenUsed}`;

  let response: Response;
  try {
    response = await fetch(url, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError(
      0,
      NETWORK_ERROR,
      "Can't reach the Lumora server. Check your connection and try again.",
    );
  }

  if (!response.ok) {
    const error = await parseError(response);
    // Only react if the token that was rejected is still the current one, so a
    // late 401 from an old request cannot log out a newer session.
    if (auth && response.status === 401 && getAccessToken() === tokenUsed) {
      clearAccessToken();
      unauthorizedHandler?.();
    }
    throw error;
  }

  try {
    return (await response.json()) as T;
  } catch {
    throw new ApiError(
      response.status,
      "UNEXPECTED_RESPONSE",
      "The server returned an unreadable response.",
    );
  }
}
