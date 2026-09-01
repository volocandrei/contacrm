/**
 * Client HTTP unic pentru întreaga aplicație.
 *
 * `VITE_API_MODE=mock` (implicit în development) rutează cererile către backend-ul
 * simulat din `api/mock`. `VITE_API_MODE=http` le trimite către API-ul real, la
 * `VITE_API_BASE_URL`. Restul aplicației nu știe care dintre ele răspunde.
 *
 * Baza implicită este **relativă** (`/api/v1`): în development, `vite.config.ts`
 * proxy-ază `/api` către backend, deci browserul vede o singură origine. Asta nu e
 * comoditate, ci condiția ca sesiunea să funcționeze: cookie-ul este `SameSite=Lax`,
 * iar de pe altă origine nu ar fi trimis deloc la `<img>` sau `<object>` — adică
 * exact la previzualizarea documentului.
 */
import { mockRequest } from "@/api/mock/router";
import { ApiError, type ApiErrorCode, type QueryParams } from "@/api/types";

type Mode = "mock" | "http";

const MODE: Mode = import.meta.env.VITE_API_MODE === "http" ? "http" : "mock";
const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";

/** Latență simulată, ca stările de încărcare să fie vizibile în development. */
const MOCK_LATENCY_MS = import.meta.env.MODE === "test" ? 0 : 140;

export function apiMode(): Mode {
  return MODE;
}

export function apiBaseUrl(): string {
  return BASE_URL;
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

/**
 * Tokenul purtat în antet există doar pentru clienți programatici și pentru modul
 * mock. În `http`, sesiunea reală stă într-un cookie httpOnly pe care JavaScript-ul
 * paginii nu îl poate citi — deci nici un XSS nu îl poate fura.
 */
let authToken: string | null = null;

export function setAuthToken(token: string | null) {
  authToken = token;
}

/** Ce se întâmplă când sesiunea a expirat definitiv — o setează `AuthProvider`. */
let onSessionLost: (() => void) | null = null;

export function setSessionLostHandler(handler: (() => void) | null) {
  onSessionLost = handler;
}

type RequestOptions = {
  params?: QueryParams;
  body?: Record<string, unknown>;
  signal?: AbortSignal;
};

function authHeaders(): Record<string, string> {
  return authToken ? { Authorization: `Bearer ${authToken}` } : {};
}

async function toApiError(response: Response): Promise<ApiError> {
  const payload: unknown = await response.json().catch(() => null);
  const detail = (payload ?? {}) as { code?: string; message?: string; details?: unknown };
  return new ApiError(
    (detail.code as ApiErrorCode) ?? "INTERNAL_ERROR",
    detail.message ?? "A apărut o eroare neașteptată.",
    response.status,
    (detail.details as Record<string, string[]> | undefined) ?? null,
  );
}

/* ─── Reîmprospătarea sesiunii ─────────────────────────────────────────────── */

/**
 * Tokenul de acces trăiește 15 minute. Un operator care verifică documente stă mai
 * mult de-atât pe același ecran, așa că un 401 nu înseamnă „ieși din aplicație", ci
 * „cere un token nou și încearcă din nou".
 *
 * Un singur apel de refresh în zbor: la reîncărcarea unui ecran pleacă mai multe
 * cereri deodată, iar rotația familiilor de refresh-token le-ar invalida reciproc
 * dacă fiecare ar cere propriul token.
 */
let refreshInFlight: Promise<boolean> | null = null;

async function refreshSession(): Promise<boolean> {
  refreshInFlight ??= (async () => {
    try {
      const response = await fetch(`${BASE_URL}/auth/refresh`, {
        method: "POST",
        credentials: "include",
      });
      return response.ok;
    } catch {
      return false;
    } finally {
      // Toți cei care așteptau împart aceeași promisiune, deci pot citi rezultatul
      // și după ce steagul a căzut. Un 401 ulterior pornește o încercare nouă.
      refreshInFlight = null;
    }
  })();
  return refreshInFlight;
}

/** Rutele pe care un 401 este răspunsul corect, nu un motiv de reîncercare. */
function isAuthRoute(path: string): boolean {
  return path.startsWith("/auth/");
}

async function sendOnce(method: string, path: string, options: RequestOptions): Promise<Response> {
  return fetch(`${BASE_URL}${path}${buildQueryString(options.params)}`, {
    method,
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(),
    },
    body: options.body ? JSON.stringify(options.body) : undefined,
    signal: options.signal,
    credentials: "include",
  });
}

async function httpRequest<T>(
  method: string,
  path: string,
  options: RequestOptions,
): Promise<T> {
  let response = await sendOnce(method, path, options);

  if (response.status === 401 && !isAuthRoute(path)) {
    if (await refreshSession()) {
      response = await sendOnce(method, path, options);
    } else {
      onSessionLost?.();
    }
  }

  if (response.status === 204) return undefined as T;
  if (!response.ok) throw await toApiError(response);

  return (await response.json().catch(() => null)) as T;
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

/* ─── Fișiere ──────────────────────────────────────────────────────────────── */

export type FetchedFile = {
  blob: Blob;
  /** Numele standardizat propus de server, din `Content-Disposition`. */
  filename: string | null;
};

/**
 * Descarcă un document autentificat, ca `Blob`.
 *
 * Un `<img src>` sau `<object data>` nu poate trimite antetul `Authorization`, iar
 * un token în query string este interzis (§27): ar ajunge în logurile serverului, în
 * istoricul browserului și în antetul `Referer`. Așa că citim conținutul cu `fetch`
 * — care duce și cookie-ul, și antetul — și dăm elementului un `blob:` URL.
 *
 * Cine îl cheamă răspunde de `URL.revokeObjectURL`, altfel fișierul rămâne în
 * memoria filei.
 */
export async function fetchFile(path: string, signal?: AbortSignal): Promise<FetchedFile> {
  let response = await fetch(`${BASE_URL}${path}`, {
    headers: authHeaders(),
    credentials: "include",
    signal,
  });

  if (response.status === 401 && (await refreshSession())) {
    response = await fetch(`${BASE_URL}${path}`, {
      headers: authHeaders(),
      credentials: "include",
      signal,
    });
  }

  if (!response.ok) throw await toApiError(response);

  return {
    blob: await response.blob(),
    filename: filenameFromDisposition(response.headers.get("Content-Disposition")),
  };
}

/**
 * Numele din `Content-Disposition`.
 *
 * `filename*` (RFC 5987) primul: acolo stau diacriticele. `filename` este varianta
 * ASCII de rezervă, pentru clienții care nu înțeleg codarea.
 */
export function filenameFromDisposition(header: string | null): string | null {
  if (!header) return null;

  const encoded = /filename\*=(?:UTF-8|utf-8)''([^;]+)/.exec(header);
  if (encoded?.[1]) {
    try {
      return decodeURIComponent(encoded[1].trim());
    } catch {
      // Antet stricat: mai bine numele ASCII decât nimic.
    }
  }

  const plain = /filename="([^"]*)"/.exec(header) ?? /filename=([^;]+)/.exec(header);
  return plain?.[1]?.trim() || null;
}

export const api = {
  get: <T>(path: string, params?: QueryParams) => request<T>("GET", path, { params }),
  post: <T>(path: string, body?: Record<string, unknown>) => request<T>("POST", path, { body }),
  patch: <T>(path: string, body?: Record<string, unknown>) => request<T>("PATCH", path, { body }),
  delete: <T>(path: string) => request<T>("DELETE", path),
};
