/**
 * Dispecer de rute pentru backend-ul simulat.
 * Căile sunt identice cu cele ale API-ului real (§38), astfel încât trecerea la
 * backend să însemne doar schimbarea `VITE_API_MODE`.
 */
import { ApiError } from "@/api/types";
import type { RoleCode } from "@/types/domain";
import * as store from "@/api/mock/store";

type Ctx = {
  params: Record<string, string>;
  query: Record<string, string>;
  body: Record<string, unknown>;
};

type Handler = (ctx: Ctx) => unknown;

type Route = {
  method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
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
  { method: "POST", pattern: "/clients", handler: ({ body }) => store.createClient(body) },
  {
    method: "PATCH",
    pattern: "/clients/:id",
    handler: ({ params, body }) => store.updateClient(params.id!, body),
  },
  {
    method: "POST",
    pattern: "/clients/:id/contacts",
    handler: ({ params, body }) => store.createContact(params.id!, body),
  },
  {
    method: "PATCH",
    pattern: "/clients/:id/contacts/:contactId",
    handler: ({ params, body }) =>
      store.updateContact(params.id!, params.contactId!, body),
  },
  {
    method: "GET",
    pattern: "/contacts",
    handler: ({ query }) =>
      store.listAllContacts({
        ...query,
        includeInactive: query.includeInactive === "true",
        page: num(query.page),
        pageSize: num(query.pageSize),
      }),
  },
  {
    method: "GET",
    pattern: "/clients/:id/aliases",
    handler: ({ params }) => store.listClientAliases(params.id!),
  },
  {
    method: "DELETE",
    pattern: "/clients/:id/aliases/:aliasId",
    handler: ({ params }) => store.forgetAlias(params.aliasId!),
  },
  {
    method: "GET",
    pattern: "/clients/:id/document-request",
    handler: ({ params, query }) => ({
      message: store.buildDocumentRequest(params.id!, query.referenceMonth ?? ""),
    }),
  },
  {
    method: "GET",
    pattern: "/clients/:id/contacts",
    handler: ({ params }) => store.listContacts(params.id!),
  },
  { method: "GET", pattern: "/clients/:id/notes", handler: ({ params }) => store.listNotes(params.id!) },
  {
    method: "GET",
    pattern: "/clients/:id/expectations",
    handler: ({ params }) => store.listExpectations(params.id!),
  },
  {
    method: "PUT",
    pattern: "/clients/:id/expectations",
    handler: ({ params, body }) =>
      store.setExpectations(
        params.id!,
        body.expectations as Array<{ documentTypeCode: string; expectedMinCount: number }>,
      ),
  },
  {
    method: "POST",
    pattern: "/clients/:id/notes",
    handler: ({ params, body }) => store.createNote(params.id!, str(body, "body")),
  },
  {
    method: "GET",
    pattern: "/clients/:id/periods",
    handler: ({ params }) => store.listClientPeriods(params.id!),
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
    // Ruta stă înaintea lui `/documents/:id`: altfel „upload" ar fi citit ca
    // identificator de document.
    method: "POST",
    pattern: "/documents/upload",
    handler: ({ body }) =>
      store.toDetail(
        store.uploadDocument({
          filename: str(body, "filename"),
          size: Number(body.size ?? 0),
          mimeType: typeof body.mimeType === "string" ? body.mimeType : "",
        }),
      ),
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

  /* Recepții (M12) */
  { method: "GET", pattern: "/intakes", handler: ({ query }) => store.listIntakes(query) },
  {
    method: "GET",
    pattern: "/clients/:id/intakes",
    handler: ({ params, query }) => store.listIntakes({ ...query, clientId: params.id! }),
  },

  /* Integrare OneDrive (M9). Rutele fixe stau înaintea celor cu parametru. */
  { method: "GET", pattern: "/integrations/onedrive", handler: () => store.getDriveStatus() },
  {
    method: "POST",
    pattern: "/integrations/onedrive/authorize",
    handler: () => store.driveAuthorizeUrl(),
  },
  {
    method: "POST",
    pattern: "/integrations/onedrive/connect",
    handler: () => store.connectDrive(),
  },
  {
    method: "DELETE",
    pattern: "/integrations/onedrive",
    handler: () => store.disconnectDrive(),
  },
  {
    method: "GET",
    pattern: "/integrations/onedrive/browse",
    handler: ({ query }) => store.browseDrive(query.parentId),
  },
  {
    method: "POST",
    pattern: "/integrations/onedrive/sync",
    handler: () => store.syncDrive(),
  },
  {
    method: "GET",
    pattern: "/integrations/onedrive/mail-folders",
    handler: () => store.browseMailFolders(),
  },
  {
    method: "POST",
    pattern: "/integrations/onedrive/mail-folders",
    handler: ({ body }) =>
      store.trackMailFolder({
        folderId: str(body, "folderId"),
        displayName: str(body, "displayName"),
      }),
  },
  {
    method: "PATCH",
    pattern: "/integrations/onedrive/mail-folders/:id",
    handler: ({ params, body }) => store.updateMailFolder(params.id!, body.isActive as boolean),
  },
  {
    method: "DELETE",
    pattern: "/integrations/onedrive/mail-folders/:id",
    handler: ({ params }) => store.untrackMailFolder(params.id!),
  },
  {
    method: "POST",
    pattern: "/integrations/onedrive/folders",
    handler: ({ body }) =>
      store.trackDriveFolder({
        driveId: str(body, "driveId"),
        itemId: str(body, "itemId"),
        path: str(body, "path"),
        clientId: (body.clientId as string | null | undefined) ?? null,
      }),
  },
  {
    method: "PATCH",
    pattern: "/integrations/onedrive/folders/:id",
    handler: ({ params, body }) =>
      store.updateDriveFolder(params.id!, {
        clientId: (body.clientId as string | null | undefined) ?? null,
        isActive: body.isActive as boolean | undefined,
      }),
  },
  {
    method: "DELETE",
    pattern: "/integrations/onedrive/folders/:id",
    handler: ({ params }) => store.untrackDriveFolder(params.id!),
  },

  /* Integrare e-Factura / SPV ANAF (M11). Rutele fixe înaintea celor cu parametru. */
  { method: "GET", pattern: "/integrations/anaf", handler: () => store.getAnafStatus() },
  {
    method: "POST",
    pattern: "/integrations/anaf/authorize",
    handler: () => store.anafAuthorizeUrl(),
  },
  {
    method: "POST",
    pattern: "/integrations/anaf/connect",
    handler: ({ body }) => store.connectAnaf(body.certificateHolder as string | null | undefined),
  },
  { method: "DELETE", pattern: "/integrations/anaf", handler: () => store.disconnectAnaf() },
  { method: "POST", pattern: "/integrations/anaf/sync", handler: () => store.syncAnaf() },
  {
    method: "POST",
    pattern: "/integrations/anaf/mandates",
    handler: ({ body }) => store.addAnafMandate(str(body, "clientId")),
  },
  {
    method: "PATCH",
    pattern: "/integrations/anaf/mandates/:id",
    handler: ({ params, body }) => store.updateAnafMandate(params.id!, body.isActive as boolean),
  },
  {
    method: "DELETE",
    pattern: "/integrations/anaf/mandates/:id",
    handler: ({ params }) => store.removeAnafMandate(params.id!),
  },

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
    method: "POST",
    pattern: "/tasks",
    handler: ({ body }) => store.createTask(body),
  },
  {
    method: "PATCH",
    pattern: "/tasks/:id",
    handler: ({ params, body }) =>
      store.updateTaskStatus(params.id!, str(body, "status") as "TODO" | "IN_PROGRESS" | "BLOCKED" | "DONE"),
  },

  /* Comunicare, audit, administrare */
  { method: "GET", pattern: "/settings", handler: () => store.listSettings() },
  {
    method: "GET",
    pattern: "/audit-logs",
    handler: ({ query }) =>
      store.listAudit({ ...query, page: num(query.page), pageSize: num(query.pageSize) }),
  },
  {
    method: "POST",
    pattern: "/assistant/chat",
    handler: ({ body }) => store.assistantAnswer(str(body, "message")),
  },
  { method: "GET", pattern: "/roles", handler: () => store.listRoles() },
  { method: "GET", pattern: "/users", handler: () => store.listUsers() },
  {
    method: "POST",
    pattern: "/users",
    handler: ({ body }) =>
      store.createUser({
        email: str(body, "email"),
        fullName: str(body, "fullName"),
        role: body.role as RoleCode,
        password: str(body, "password"),
      }),
  },
  {
    method: "PATCH",
    pattern: "/users/:id",
    handler: ({ params, body }) =>
      store.updateUser(params.id!, {
        fullName: body.fullName as string | undefined,
        role: body.role as RoleCode | undefined,
        isActive: body.isActive as boolean | undefined,
      }),
  },
  {
    method: "POST",
    pattern: "/users/:id/password",
    handler: ({ params, body }) => store.resetUserPassword(params.id!, str(body, "password")),
  },
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
