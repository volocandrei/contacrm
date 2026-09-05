/** Hook-uri TanStack Query. Cheile de cache stau într-un singur loc, ca invalidarea să fie sigură. */
import { useCallback } from "react";
import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationOptions,
} from "@tanstack/react-query";
import type { QueryParams } from "@/api/types";
import {
  administration,
  assistant,
  clients,
  contacts,
  dashboard,
  documents,
  anaf,
  drive,
  intakes,
  periods,
  reports,
  tasks,
  type BulkPayload,
  type ClientInput,
  type ContactInput,
  type TaskInput,
} from "@/api/endpoints";
import type { DocumentDetail, DocumentFieldName, RoleCode, TaskStatus } from "@/types/domain";

export const queryKeys = {
  dashboard: ["dashboard"] as const,
  sidebarCounts: ["dashboard", "counts"] as const,
  clients: (params: QueryParams) => ["clients", params] as const,
  client: (id: string) => ["clients", id] as const,
  clientContacts: (id: string) => ["clients", id, "contacts"] as const,
  contacts: (params: QueryParams) => ["contacts", params] as const,
  clientNotes: (id: string) => ["clients", id, "notes"] as const,
  clientExpectations: (id: string) => ["clients", id, "expectations"] as const,
  clientAliases: (id: string) => ["clients", id, "aliases"] as const,
  clientUploadLinks: (id: string) => ["clients", id, "upload-links"] as const,
  intakes: (params: QueryParams) => ["intakes", params] as const,
  clientPeriods: (id: string) => ["clients", id, "periods"] as const,
  documents: (params: QueryParams) => ["documents", params] as const,
  document: (id: string) => ["documents", id] as const,
  documentTypes: ["document-types"] as const,
  nextReview: (after?: string) => ["documents", "next-review", after ?? null] as const,
  periods: (params: QueryParams) => ["periods", params] as const,
  missingDocuments: (referenceMonth: string) => ["periods", "missing", referenceMonth] as const,
  tasks: (params: QueryParams) => ["tasks", params] as const,
  reportSummary: (params: QueryParams) => ["reports", "summary", params] as const,
  auditLogs: (params: QueryParams) => ["audit-logs", params] as const,
  users: ["users"] as const,
  roles: ["roles"] as const,
  settings: ["settings"] as const,
  driveStatus: ["drive", "status"] as const,
  anafStatus: ["anaf", "status"] as const,
  driveBrowse: (parentId?: string) => ["drive", "browse", parentId ?? null] as const,
  driveMailFolders: ["drive", "mail-folders"] as const,
};

/* ─── Interogări ───────────────────────────────────────────────────────────── */

export function useDashboard() {
  return useQuery({ queryKey: queryKeys.dashboard, queryFn: dashboard.get });
}

export function useReportSummary(params: QueryParams) {
  return useQuery({
    queryKey: queryKeys.reportSummary(params),
    queryFn: () => reports.summary(params),
  });
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

/** Agenda întreagă, căutabilă. */
export function useContacts(params: QueryParams) {
  return useQuery({
    queryKey: queryKeys.contacts(params),
    queryFn: () => contacts.list(params),
  });
}

/** Ce a învățat sistemul despre expeditorii acestui client. */
export function useClientAliases(id: string) {
  return useQuery({
    queryKey: queryKeys.clientAliases(id),
    queryFn: () => clients.aliases(id),
  });
}

export function useForgetAlias(clientId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (aliasId: string) => clients.forgetAlias(clientId, aliasId),
    onSuccess: () =>
      void queryClient.invalidateQueries({ queryKey: queryKeys.clientAliases(clientId) }),
  });
}

/** Drumurile deschise prin care clientul își poate trimite documentele. */
export function useUploadLinks(id: string) {
  return useQuery({
    queryKey: queryKeys.clientUploadLinks(id),
    queryFn: () => clients.uploadLinks(id),
  });
}

export function useCreateUploadLink(clientId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => clients.createUploadLink(clientId),
    onSuccess: () =>
      void queryClient.invalidateQueries({ queryKey: queryKeys.clientUploadLinks(clientId) }),
  });
}

export function useRevokeUploadLink(clientId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (linkId: string) => clients.revokeUploadLink(clientId, linkId),
    onSuccess: () =>
      void queryClient.invalidateQueries({ queryKey: queryKeys.clientUploadLinks(clientId) }),
  });
}

export function useClientNotes(id: string) {
  return useQuery({ queryKey: queryKeys.clientNotes(id), queryFn: () => clients.notes(id) });
}

export function useClientPeriods(id: string) {
  return useQuery({ queryKey: queryKeys.clientPeriods(id), queryFn: () => clients.periods(id) });
}

/**
 * Scrierea unui client. La succes se invalidează lista **și** fișa: un client
 * redenumit trebuie să apară schimbat în amândouă, nu doar acolo unde s-a salvat.
 */
export function useSaveClient() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, input }: { id?: string; input: ClientInput }) =>
      id ? clients.update(id, input) : clients.create(input),
    onSuccess: (client) => {
      queryClient.invalidateQueries({ queryKey: ["clients"] });
      queryClient.setQueryData(queryKeys.client(client.id), client);
    },
  });
}

export function useSaveContact(clientId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, input }: { id?: string; input: ContactInput }) =>
      id
        ? clients.updateContact(clientId, id, input)
        : clients.createContact(clientId, input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.clientContacts(clientId) });
    },
  });
}

export function useClientExpectations(id: string) {
  return useQuery({
    queryKey: queryKeys.clientExpectations(id),
    queryFn: () => clients.expectations(id),
  });
}

/**
 * Salvarea așteptărilor lunare.
 *
 * Se invalidează și perioadele: checklistul fiecărei luni se derivă din lista
 * asta, deci ecranul de contabilitate trebuie să se schimbe odată cu ea. La fel
 * panoul principal, care numără clienții în întârziere.
 */
export function useSaveExpectations(clientId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (expectations: Array<{ documentTypeCode: string; expectedMinCount: number }>) =>
      clients.setExpectations(clientId, expectations),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.clientExpectations(clientId) });
      queryClient.invalidateQueries({ queryKey: queryKeys.clientPeriods(clientId) });
      queryClient.invalidateQueries({ queryKey: ["periods"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
}

/** Scrierea unei notițe. Lista se reîncarcă: nota nouă trebuie să apară acolo. */
export function useCreateNote(clientId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: string) => clients.createNote(clientId, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.clientNotes(clientId) });
    },
  });
}

/** Orice atingere a conturilor schimbă lista afișată. */
function useUserMutation<TArgs, TResult>(mutationFn: (args: TArgs) => Promise<TResult>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.users });
      // Contul curent poate fi cel schimbat: rolul din antet trebuie să urmeze.
      void queryClient.invalidateQueries({ queryKey: ["me"] });
    },
  });
}

export function useCreateUser() {
  return useUserMutation(administration.createUser);
}

export function useUpdateUser() {
  return useUserMutation(
    ({ id, input }: { id: string; input: { fullName?: string; role?: RoleCode; isActive?: boolean } }) =>
      administration.updateUser(id, input),
  );
}

export function useResetPassword() {
  return useUserMutation(({ id, password }: { id: string; password: string }) =>
    administration.resetPassword(id, password),
  );
}

/** Cronologia recepțiilor: ce a sosit, de la cine și când. */
export function useIntakes(params: QueryParams) {
  return useQuery({ queryKey: queryKeys.intakes(params), queryFn: () => intakes.list(params) });
}

export function useDocuments(params: QueryParams) {
  return useQuery({ queryKey: queryKeys.documents(params), queryFn: () => documents.list(params) });
}

/** Cât de des reîntrebăm cât timp workerul încă lucrează la document. */
const PROCESSING_POLL_MS = 1500;

export function useDocument(id: string | undefined) {
  return useQuery({
    queryKey: queryKeys.document(id ?? ""),
    queryFn: () => documents.get(id!),
    enabled: !!id,
    // Procesarea se întâmplă în afara cererii (§38): ecranul nu are cum să afle că
    // s-a terminat decât întrebând. Interogarea se oprește singură când documentul
    // ajunge într-o stare care așteaptă un om.
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "RECEIVED" || status === "PROCESSING" ? PROCESSING_POLL_MS : false;
    },
  });
}

export function useDocumentTypes() {
  return useQuery({ queryKey: queryKeys.documentTypes, queryFn: documents.types, staleTime: Infinity });
}

export function useNextReviewDocument(after?: string) {
  return useQuery({ queryKey: queryKeys.nextReview(after), queryFn: () => documents.nextReview(after) });
}

/**
 * Următorul document din coadă, cerut la comandă.
 *
 * `useNextReviewDocument` este o interogare: se potrivește unui ecran care
 * *afișează* coada. După o aprobare avem nevoie de altceva — o singură întrebare,
 * pusă în momentul potrivit, al cărei răspuns nu are de ce să rămână în cache:
 * data viitoare coada arată deja altfel.
 */
export function useNextReviewAfter() {
  return useCallback(
    (after: string) => documents.nextReview(after),
    [],
  );
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

export function useAuditLogs(params: QueryParams) {
  return useQuery({
    queryKey: queryKeys.auditLogs(params),
    queryFn: () => administration.auditLogs(params),
  });
}

export function useUsers() {
  return useQuery({ queryKey: queryKeys.users, queryFn: administration.users });
}

/** Matricea de permisiuni. Se schimbă doar la deploy, deci nu are rost reîmprospătată. */
export function useRoles() {
  return useQuery({
    queryKey: queryKeys.roles,
    queryFn: administration.roles,
    staleTime: Infinity,
  });
}

/**
 * O întrebare către asistent.
 *
 * `useMutation`, nu `useQuery`: o întrebare nu se reîmprospătează singură și nu
 * se pune de două ori pentru că a revenit focalizarea în fereastră.
 */
export function useAssistant() {
  return useMutation({ mutationFn: (message: string) => assistant.ask(message) });
}

export function useSettings() {
  return useQuery({ queryKey: queryKeys.settings, queryFn: administration.settings });
}

/* ─── OneDrive (M9) ────────────────────────────────────────────────────────── */

export function useDriveStatus() {
  return useQuery({ queryKey: queryKeys.driveStatus, queryFn: drive.status });
}

/**
 * Dosarele de pe drive, la răsfoire.
 *
 * `enabled` pe conexiune: fără cont conectat, cererea ar întoarce 409 la fiecare
 * randare, iar ecranul ar clipi cu o eroare care nu este a utilizatorului.
 */
export function useDriveBrowse(parentId: string | undefined, enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.driveBrowse(parentId),
    queryFn: () => drive.browse(parentId),
    enabled,
    // Structura dosarelor cuiva nu se schimbă cât ține un dialog deschis.
    staleTime: 60_000,
  });
}

/** Orice atingere a integrării schimbă starea afișată. */
function useDriveMutation<TArgs, TResult>(mutationFn: (args: TArgs) => Promise<TResult>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["drive"] });
      // Documentele aduse din OneDrive apar în liste și în contoare.
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
      void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
}

export function useConnectDrive() {
  return useDriveMutation(({ code, state }: { code: string; state: string }) =>
    drive.connect(code, state),
  );
}

export function useDisconnectDrive() {
  return useDriveMutation(() => drive.disconnect());
}

export function useTrackFolder() {
  return useDriveMutation(drive.trackFolder);
}

export function useUpdateDriveFolder() {
  return useDriveMutation(
    ({ id, ...input }: { id: string; clientId?: string | null; isActive?: boolean }) =>
      drive.updateFolder(id, input),
  );
}

export function useUntrackFolder() {
  return useDriveMutation((id: string) => drive.untrackFolder(id));
}

export function useMailFolders(enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.driveMailFolders,
    queryFn: drive.browseMail,
    enabled,
    staleTime: 60_000,
  });
}

export function useTrackMailFolder() {
  return useDriveMutation(drive.trackMailFolder);
}

export function useUpdateMailFolder() {
  return useDriveMutation(({ id, isActive }: { id: string; isActive: boolean }) =>
    drive.updateMailFolder(id, isActive),
  );
}

export function useUntrackMailFolder() {
  return useDriveMutation((id: string) => drive.untrackMailFolder(id));
}

export function useSyncDrive() {
  return useDriveMutation(() => drive.sync());
}

/* ─── e-Factura / SPV ANAF (M11) ──────────────────────────────────────────── */

export function useAnafStatus() {
  return useQuery({ queryKey: queryKeys.anafStatus, queryFn: anaf.status });
}

/** Orice atingere a integrării schimbă starea afișată. */
function useAnafMutation<TArgs, TResult>(mutationFn: (args: TArgs) => Promise<TResult>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["anaf"] });
      // Facturile aduse din SPV apar în liste și în contoare.
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
      void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
}

export function useConnectAnaf() {
  return useAnafMutation(
    ({ code, state, holder }: { code: string; state: string; holder?: string }) =>
      anaf.connect(code, state, holder),
  );
}

export function useDisconnectAnaf() {
  return useAnafMutation(() => anaf.disconnect());
}

export function useAddAnafMandate() {
  return useAnafMutation((clientId: string) => anaf.addMandate(clientId));
}

export function useUpdateAnafMandate() {
  return useAnafMutation(({ id, isActive }: { id: string; isActive: boolean }) =>
    anaf.updateMandate(id, isActive),
  );
}

export function useRemoveAnafMandate() {
  return useAnafMutation((id: string) => anaf.removeMandate(id));
}

export function useSyncAnaf() {
  return useAnafMutation(() => anaf.sync());
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

/**
 * Încarcă un fișier.
 *
 * Un `useMutation` per fișier ar fi cerut o componentă per fișier. Aici mutația
 * este pentru **un** fișier, iar panoul o cheamă de câte ori trebuie și își ține
 * singur lista de rezultate: un lot în care al treilea fișier eșuează nu are voie
 * să ascundă că primele două au reușit.
 */
export function useUploadDocument() {
  return useDocumentMutation(({ file, clientId }: { file: File; clientId?: string }) =>
    documents.upload(file, clientId),
  );
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

/** O sarcină nouă. Invalidează listele: kanbanul trebuie să o arate imediat. */
export function useCreateTask() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: TaskInput) => tasks.create(input),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["tasks"] });
      void client.invalidateQueries({ queryKey: queryKeys.sidebarCounts });
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
