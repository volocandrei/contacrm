/** Hook-uri TanStack Query. Cheile de cache stau într-un singur loc, ca invalidarea să fie sigură. */
import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationOptions,
} from "@tanstack/react-query";
import type { QueryParams } from "@/api/types";
import {
  administration,
  clients,
  communication,
  dashboard,
  documents,
  periods,
  tasks,
  type BulkPayload,
} from "@/api/endpoints";
import type { DocumentDetail, DocumentFieldName, TaskStatus } from "@/types/domain";

export const queryKeys = {
  dashboard: ["dashboard"] as const,
  sidebarCounts: ["dashboard", "counts"] as const,
  clients: (params: QueryParams) => ["clients", params] as const,
  client: (id: string) => ["clients", id] as const,
  clientContacts: (id: string) => ["clients", id, "contacts"] as const,
  clientNotes: (id: string) => ["clients", id, "notes"] as const,
  clientPeriods: (id: string) => ["clients", id, "periods"] as const,
  clientMessages: (id: string) => ["clients", id, "messages"] as const,
  documents: (params: QueryParams) => ["documents", params] as const,
  document: (id: string) => ["documents", id] as const,
  documentTypes: ["document-types"] as const,
  nextReview: (after?: string) => ["documents", "next-review", after ?? null] as const,
  periods: (params: QueryParams) => ["periods", params] as const,
  missingDocuments: (referenceMonth: string) => ["periods", "missing", referenceMonth] as const,
  tasks: (params: QueryParams) => ["tasks", params] as const,
  messages: (params: QueryParams) => ["messages", params] as const,
  auditLogs: (params: QueryParams) => ["audit-logs", params] as const,
  users: ["users"] as const,
};

/* ─── Interogări ───────────────────────────────────────────────────────────── */

export function useDashboard() {
  return useQuery({ queryKey: queryKeys.dashboard, queryFn: dashboard.get });
}

export function useSidebarCounts() {
  return useQuery({ queryKey: queryKeys.sidebarCounts, queryFn: dashboard.counts });
}

export function useClients(params: QueryParams) {
  return useQuery({ queryKey: queryKeys.clients(params), queryFn: () => clients.list(params) });
}

export function useClient(id: string) {
  return useQuery({ queryKey: queryKeys.client(id), queryFn: () => clients.get(id), enabled: !!id });
}

export function useClientContacts(id: string) {
  return useQuery({ queryKey: queryKeys.clientContacts(id), queryFn: () => clients.contacts(id) });
}

export function useClientNotes(id: string) {
  return useQuery({ queryKey: queryKeys.clientNotes(id), queryFn: () => clients.notes(id) });
}

export function useClientPeriods(id: string) {
  return useQuery({ queryKey: queryKeys.clientPeriods(id), queryFn: () => clients.periods(id) });
}

export function useClientMessages(id: string) {
  return useQuery({ queryKey: queryKeys.clientMessages(id), queryFn: () => clients.messages(id) });
}

export function useDocuments(params: QueryParams) {
  return useQuery({ queryKey: queryKeys.documents(params), queryFn: () => documents.list(params) });
}

export function useDocument(id: string | undefined) {
  return useQuery({
    queryKey: queryKeys.document(id ?? ""),
    queryFn: () => documents.get(id!),
    enabled: !!id,
  });
}

export function useDocumentTypes() {
  return useQuery({ queryKey: queryKeys.documentTypes, queryFn: documents.types, staleTime: Infinity });
}

export function useNextReviewDocument(after?: string) {
  return useQuery({ queryKey: queryKeys.nextReview(after), queryFn: () => documents.nextReview(after) });
}

export function usePeriods(params: QueryParams) {
  return useQuery({ queryKey: queryKeys.periods(params), queryFn: () => periods.list(params) });
}

export function useMissingDocuments(referenceMonth: string) {
  return useQuery({
    queryKey: queryKeys.missingDocuments(referenceMonth),
    queryFn: () => periods.missing(referenceMonth),
  });
}

export function useTasks(params: QueryParams) {
  return useQuery({ queryKey: queryKeys.tasks(params), queryFn: () => tasks.list(params) });
}

export function useMessages(params: QueryParams) {
  return useQuery({ queryKey: queryKeys.messages(params), queryFn: () => communication.messages(params) });
}

export function useAuditLogs(params: QueryParams) {
  return useQuery({
    queryKey: queryKeys.auditLogs(params),
    queryFn: () => administration.auditLogs(params),
  });
}

export function useUsers() {
  return useQuery({ queryKey: queryKeys.users, queryFn: administration.users });
}

/* ─── Mutații ──────────────────────────────────────────────────────────────── */

/** Orice schimbare pe un document afectează listele, dashboard-ul și perioadele. */
function useDocumentMutation<TArgs>(
  mutationFn: (args: TArgs) => Promise<DocumentDetail>,
  options?: Omit<UseMutationOptions<DocumentDetail, Error, TArgs>, "mutationFn">,
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn,
    ...options,
    onSuccess: (data, variables, onMutateResult, context) => {
      queryClient.setQueryData(queryKeys.document(data.id), data);
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
      void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
      void queryClient.invalidateQueries({ queryKey: ["periods"] });
      options?.onSuccess?.(data, variables, onMutateResult, context);
    },
  });
}

export function useUpdateDocumentFields(id: string) {
  return useDocumentMutation((updates: Array<{ field: DocumentFieldName; value: string | null }>) =>
    documents.updateFields(id, updates),
  );
}

export function useApproveDocument() {
  return useDocumentMutation((id: string) => documents.approve(id));
}

export function useRejectDocument() {
  return useDocumentMutation(({ id, reason }: { id: string; reason: string }) =>
    documents.reject(id, reason),
  );
}

export function useMarkDuplicate() {
  return useDocumentMutation(({ id, duplicateOfId }: { id: string; duplicateOfId?: string | null }) =>
    documents.markDuplicate(id, duplicateOfId),
  );
}

export function useReprocessDocument() {
  return useDocumentMutation((id: string) => documents.reprocess(id));
}

export function useAssignClient() {
  return useDocumentMutation(({ id, clientId }: { id: string; clientId: string }) =>
    documents.assignClient(id, clientId),
  );
}

export function useBulkDocuments() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ ids, payload }: { ids: string[]; payload: BulkPayload }) =>
      documents.bulk(ids, payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
      void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
      void queryClient.invalidateQueries({ queryKey: ["periods"] });
    },
  });
}

export function useUpdateTaskStatus() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, status }: { id: string; status: TaskStatus }) => tasks.updateStatus(id, status),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["tasks"] });
      void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
}
