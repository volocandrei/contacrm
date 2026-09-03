/**
 * Dispecer de rute pentru backend-ul simulat.
 * Căile sunt identice cu cele ale API-ului real (§38), astfel încât trecerea la
 * backend să însemne doar schimbarea `VITE_API_MODE`.
 */
import { ApiError } from "@/api/types";
import * as store from "@/api/mock/store";

type Ctx = {
  params: Record<string, string>;
  query: Record<string, string>;
  body: Record<string, unknown>;
};

type Handler = (ctx: Ctx) => unknown;

type Route = {
  method: "GET" | "POST" | "PATCH" | "DELETE";
  /** Segmentele care încep cu ":" sunt parametri. */
  pattern: string;
  handler: Handler;
};

function num(value: string | undefined): number | undefined {
  return value === undefined ? undefined : Number(value);
}

function str(body: Record<string, unknown>, key: string): string {
  const value = body[key];
  if (typeof value !== "string") {
    throw new ApiError("VALIDATION_ERROR", `Câmp lipsă sau invalid: ${key}`, 422, {
      [key]: ["Câmp obligatoriu."],
    });
  }
  return value;
}

const routes: Route[] = [
  /* Auth */
  { method: "POST", pattern: "/auth/login", handler: ({ body }) => store.mockLogin(str(body, "email")) },
  { method: "POST", pattern: "/auth/logout", handler: () => ({ ok: true }) },
  { method: "GET", pattern: "/me", handler: () => store.mockCurrentUser() },

  /* Dashboard */
  { method: "GET", pattern: "/dashboard", handler: () => store.getDashboard() },
  { method: "GET", pattern: "/dashboard/counts", handler: () => store.getSidebarCounts() },

  /* Clienți */
  {
    method: "GET",
    pattern: "/clients",
    handler: ({ query }) =>
      store.listClients({ ...query, page: num(query.page), pageSize: num(query.pageSize) }),
  },
  { method: "GET", pattern: "/clients/:id", handler: ({ params }) => store.getClient(params.id!) },
  {
    method: "GET",
    pattern: "/clients/:id/contacts",
    handler: ({ params }) => store.listContacts(params.id!),
  },
  { method: "GET", pattern: "/clients/:id/notes", handler: ({ params }) => store.listNotes(params.id!) },
  {
    method: "GET",
    pattern: "/clients/:id/periods",
    handler: ({ params }) => store.listClientPeriods(params.id!),
  },
  {
    method: "GET",
    pattern: "/clients/:id/messages",
    handler: ({ params }) => store.listClientMessages(params.id!),
  },

  /* Documente */
  {
    method: "GET",
    pattern: "/documents",
    handler: ({ query }) =>
      store.listDocuments({
        ...query,
        page: num(query.page),
        pageSize: num(query.pageSize),
        order: query.order === "asc" ? "asc" : "desc",
      }),
  },
  {
    method: "GET",
    pattern: "/documents/next-review",
    handler: ({ query }) => store.nextReviewDocument(query.after),
  },
  { method: "GET", pattern: "/documents/:id", handler: ({ params }) => store.toDetail(store.getDocument(params.id!)) },
  {
    method: "PATCH",
    pattern: "/documents/:id",
    handler: ({ params, body }) =>
      store.toDetail(store.updateDocumentFields(params.id!, body.updates as store.FieldUpdate[])),
  },
  {
    method: "POST",
    pattern: "/documents/:id/assign-client",
    handler: ({ params, body }) => store.toDetail(store.assignClient(params.id!, str(body, "clientId"))),
  },
  {
    method: "POST",
    pattern: "/documents/:id/approve",
    handler: ({ params }) => store.toDetail(store.approveDocument(params.id!)),
  },
  {
    method: "POST",
    pattern: "/documents/:id/reject",
    handler: ({ params, body }) => store.toDetail(store.rejectDocument(params.id!, str(body, "reason"))),
  },
  {
    method: "POST",
    pattern: "/documents/:id/duplicate",
    handler: ({ params, body }) =>
      store.toDetail(store.markDuplicate(params.id!, (body.duplicateOfId as string | undefined) ?? null)),
  },
  {
    method: "POST",
    pattern: "/documents/:id/reprocess",
    handler: ({ params }) => store.toDetail(store.reprocessDocument(params.id!)),
  },
  {
    method: "POST",
    pattern: "/documents/bulk",
    handler: ({ body }) => store.bulkDocuments(body.ids as string[], body.payload as store.BulkAction),
  },
  { method: "GET", pattern: "/document-types", handler: () => store.listDocumentTypes() },

  /* Contabilitate */
  { method: "GET", pattern: "/periods", handler: ({ query }) => store.listPeriods(query) },
  {
    method: "GET",
    pattern: "/periods/missing",
    handler: ({ query }) => store.listMissingDocuments(query.referenceMonth ?? "2026-08"),
  },

  {
    method: "GET",
    pattern: "/reports/summary",
    handler: ({ query }) => store.reportSummary(query),
  },

  /* Sarcini */
  { method: "GET", pattern: "/tasks", handler: ({ query }) => store.listTasks(query) },
  {
    method: "PATCH",
    pattern: "/tasks/:id",
    handler: ({ params, body }) =>
      store.updateTaskStatus(params.id!, str(body, "status") as "TODO" | "IN_PROGRESS" | "BLOCKED" | "DONE"),
  },

  /* Comunicare, audit, administrare */
  { method: "GET", pattern: "/settings", handler: () => store.listSettings() },
  { method: "GET", pattern: "/messages", handler: ({ query }) => store.listMessages(query) },
  {
    method: "GET",
    pattern: "/audit-logs",
    handler: ({ query }) =>
      store.listAudit({ ...query, page: num(query.page), pageSize: num(query.pageSize) }),
  },
  { method: "GET", pattern: "/users", handler: () => store.listUsers() },
];

function matchRoute(method: string, path: string): { route: Route; params: Record<string, string> } | null {
  const segments = path.split("/").filter(Boolean);
  for (const route of routes) {
    if (route.method !== method) continue;
    const patternSegments = route.pattern.split("/").filter(Boolean);
    if (patternSegments.length !== segments.length) continue;
    const params: Record<string, string> = {};
    let ok = true;
    for (let i = 0; i < patternSegments.length; i += 1) {
      const expected = patternSegments[i]!;
      const actual = segments[i]!;
      if (expected.startsWith(":")) {
        params[expected.slice(1)] = decodeURIComponent(actual);
      } else if (expected !== actual) {
        ok = false;
        break;
      }
    }
    if (ok) return { route, params };
  }
  return null;
}

export function mockRequest(
  method: string,
  path: string,
  query: Record<string, string>,
  body: Record<string, unknown>,
): unknown {
  const match = matchRoute(method, path);
  if (!match) {
    throw new ApiError("NOT_FOUND", `Ruta ${method} ${path} nu există.`, 404);
  }
  return match.route.handler({ params: match.params, query, body });
}
