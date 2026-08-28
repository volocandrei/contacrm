/**
 * Client HTTP unic pentru întreaga aplicație.
 *
 * `VITE_API_MODE=mock` (implicit în development) rutează cererile către backend-ul
 * simulat din `api/mock`. `VITE_API_MODE=http` le trimite către API-ul real, la
 * `VITE_API_BASE_URL`. Restul aplicației nu știe care dintre ele răspunde.
 */
import { mockRequest } from "@/api/mock/router";
import { ApiError, type ApiErrorCode, type QueryParams } from "@/api/types";

type Mode = "mock" | "http";

const MODE: Mode = import.meta.env.VITE_API_MODE === "http" ? "http" : "mock";
const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";

/** Latență simulată, ca stările de încărcare să fie vizibile în development. */
const MOCK_LATENCY_MS = import.meta.env.MODE === "test" ? 0 : 140;

export function apiMode(): Mode {
  return MODE;
}

function buildQueryString(params: QueryParams | undefined): string {
  if (!params) return "";
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    search.set(key, Array.isArray(value) ? value.join(",") : String(value));
  }
  const qs = search.toString();
  return qs ? `?${qs}` : "";
}

function queryObject(params: QueryParams | undefined): Record<string, string> {
  const result: Record<string, string> = {};
  for (const [key, value] of Object.entries(params ?? {})) {
    if (value === undefined || value === null || value === "") continue;
    result[key] = Array.isArray(value) ? value.join(",") : String(value);
  }
  return result;
}

let authToken: string | null = null;

export function setAuthToken(token: string | null) {
  authToken = token;
}

type RequestOptions = {
  params?: QueryParams;
  body?: Record<string, unknown>;
  signal?: AbortSignal;
};

async function httpRequest<T>(
  method: string,
  path: string,
  options: RequestOptions,
): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}${buildQueryString(options.params)}`, {
    method,
    headers: {
      "Content-Type": "application/json",
      ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
    },
    body: options.body ? JSON.stringify(options.body) : undefined,
    signal: options.signal,
    credentials: "include",
  });

  if (response.status === 204) return undefined as T;

  const payload: unknown = await response.json().catch(() => null);

  if (!response.ok) {
    const detail = (payload ?? {}) as { code?: string; message?: string; details?: unknown };
    throw new ApiError(
      (detail.code as ApiErrorCode) ?? "INTERNAL_ERROR",
      detail.message ?? "A apărut o eroare neașteptată.",
      response.status,
      (detail.details as Record<string, string[]> | undefined) ?? null,
    );
  }

  return payload as T;
}

async function mockRequestAsync<T>(
  method: string,
  path: string,
  options: RequestOptions,
): Promise<T> {
  if (MOCK_LATENCY_MS > 0) {
    await new Promise((resolve) => setTimeout(resolve, MOCK_LATENCY_MS));
  }
  // Erorile sunt aruncate sincron de store; le lăsăm să se propage ca rejection.
  return mockRequest(method, path, queryObject(options.params), options.body ?? {}) as T;
}

export function request<T>(method: string, path: string, options: RequestOptions = {}): Promise<T> {
  return MODE === "mock"
    ? mockRequestAsync<T>(method, path, options)
    : httpRequest<T>(method, path, options);
}

export const api = {
  get: <T>(path: string, params?: QueryParams) => request<T>("GET", path, { params }),
  post: <T>(path: string, body?: Record<string, unknown>) => request<T>("POST", path, { body }),
  patch: <T>(path: string, body?: Record<string, unknown>) => request<T>("PATCH", path, { body }),
  delete: <T>(path: string) => request<T>("DELETE", path),
};
