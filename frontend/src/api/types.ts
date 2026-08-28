/** Contractul de transport al API-ului (§38, §40, §61). */

export type Paginated<T> = {
  items: T[];
  page: number;
  pageSize: number;
  total: number;
  totalPages: number;
};

/** Codurile de eroare standardizate (§40). */
export const API_ERROR_CODES = [
  "VALIDATION_ERROR",
  "NOT_FOUND",
  "UNAUTHORIZED",
  "FORBIDDEN",
  "CONFLICT",
  "PROCESSING_ERROR",
  "EXTERNAL_SERVICE_ERROR",
  "RATE_LIMITED",
  "INTERNAL_ERROR",
] as const;
export type ApiErrorCode = (typeof API_ERROR_CODES)[number];

export class ApiError extends Error {
  readonly code: ApiErrorCode;
  readonly status: number;
  readonly details: Record<string, string[]> | null;

  constructor(
    code: ApiErrorCode,
    message: string,
    status: number,
    details: Record<string, string[]> | null = null,
  ) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
    this.details = details;
  }
}

export type PageParams = {
  page?: number;
  pageSize?: number;
};

export type SortParams = {
  sort?: string;
  order?: "asc" | "desc";
};

export type QueryParams = Record<string, string | number | boolean | undefined | null | string[]>;
