/**
 * Fetch wrapper for the shop API.
 * - Same-origin requests, so the HttpOnly session cookie rides along automatically.
 * - Echoes the readable CSRF cookie in X-CSRF-Token on every state-changing request.
 * - Turns the API's error shape into an ApiError with a message written for the mechanic.
 */

export type FieldError = { field: string; message: string };

export class ApiError extends Error {
  status: number;
  code: string;
  details: FieldError[];
  constructor(status: number, code: string, message: string, details: FieldError[] = []) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

function csrfToken(): string | null {
  const m = document.cookie.match(/(?:^|;\s*)shop_csrf=([^;]+)/);
  return m ? decodeURIComponent(m[1]) : null;
}

let onUnauthorized: (() => void) | null = null;
export function setUnauthorizedHandler(fn: () => void) {
  onUnauthorized = fn;
}

type Query = Record<string, string | number | boolean | null | undefined | string[]>;

function buildUrl(path: string, query?: Query): string {
  const url = new URL(`/api${path}`, window.location.origin);
  for (const [k, v] of Object.entries(query ?? {})) {
    if (v === undefined || v === null || v === "") continue;
    if (Array.isArray(v)) v.forEach((x) => url.searchParams.append(k, x));
    else url.searchParams.set(k, String(v));
  }
  return url.pathname + url.search;
}

async function request<T>(method: string, path: string, body?: unknown, query?: Query): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET") {
    const token = csrfToken();
    if (token) headers["X-CSRF-Token"] = token;
  }
  let res: Response;
  try {
    res = await fetch(buildUrl(path, query), {
      method,
      headers,
      credentials: "same-origin",
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, "network", "Can't reach the shop server. Check your connection and try again.");
  }
  if (res.status === 204) return undefined as T;
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const err = data?.error ?? {};
    if (res.status === 401 && path !== "/auth/login") onUnauthorized?.();
    throw new ApiError(
      res.status,
      err.code ?? "error",
      err.message ?? `Request failed (${res.status}). Nothing was saved.`,
      err.details ?? [],
    );
  }
  return data as T;
}

export const api = {
  get: <T>(path: string, query?: Query) => request<T>("GET", path, undefined, query),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body ?? {}),
  put: <T>(path: string, body: unknown) => request<T>("PUT", path, body),
  patch: <T>(path: string, body: unknown) => request<T>("PATCH", path, body),
  del: <T>(path: string) => request<T>("DELETE", path),
};

/** Field-level message for a form input, from a 422 response. */
export function fieldError(err: unknown, field: string): string | undefined {
  if (!(err instanceof ApiError)) return undefined;
  return err.details.find((d) => d.field === field || d.field.startsWith(`${field}.`))?.message;
}
