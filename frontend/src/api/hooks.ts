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
  auth,
  bank,
  clients,
  contacts,
  dashboard,
  documents,
  documentSources,
  expectationTemplates,
  anaf,
  drive,
  intakes,
  obligations,
  fees,
  imap,
  periods,
  reminders,
  reports,
  tasks,
  type BulkPayload,
  type ClientInput,
  type ContactInput,
  type ExpectationInput,
  type TaskInput,
} from "@/api/endpoints";
import type {
  DocumentDetail,
  ImapMailboxInput,
  DocumentFieldName,
  ObligationType,
  RoleCode,
  TaskStatus,
  ManualDocumentSource,
} from "@/types/domain";

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
  clientTimeline: (id: string) => ["clients", id, "timeline"] as const,
  clientUploadLinks: (id: string) => ["clients", id, "upload-links"] as const,
  intakes: (params: QueryParams) => ["intakes", params] as const,
  clientPeriods: (id: string) => ["clients", id, "periods"] as const,
  documents: (params: QueryParams) => ["documents", params] as const,
  processingHealth: ["documents", "processing-health"] as const,
  document: (id: string) => ["documents", id] as const,
  documentTypes: ["document-types"] as const,
  nextReview: (after?: string) => ["documents", "next-review", after ?? null] as const,
  periods: (params: QueryParams) => ["periods", params] as const,
  expectationTemplates: ["expectation-templates"] as const,
  obligations: (params: QueryParams) => ["obligations", params] as const,
  obligationTypes: ["obligations", "types"] as const,
  clientObligations: (id: string) => ["obligations", "clients", id] as const,
  clientFilings: (id: string) => ["obligations", "clients", id, "filings"] as const,
  fees: (referenceMonth: string) => ["fees", referenceMonth] as const,
  clientFee: (id: string) => ["fees", "clients", id] as const,
  clientFeeHistory: (id: string) => ["fees", "clients", id, "history"] as const,
  missingDocuments: (referenceMonth: string) => ["periods", "missing", referenceMonth] as const,
  reminders: ["reminders"] as const,
  tasks: (params: QueryParams) => ["tasks", params] as const,
  reportSummary: (params: QueryParams) => ["reports", "summary", params] as const,
  auditLogs: (params: QueryParams) => ["audit-logs", params] as const,
  users: ["users"] as const,
  roles: ["roles"] as const,
  settings: ["settings"] as const,
  documentSources: ["integrations", "sources"] as const,
  imapMailboxes: ["integrations", "imap"] as const,
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

/**
 * Compune solicitarea de documente și deschide drumul pe care sosește răspunsul.
 *
 * **De ce este mutație și nu un simplu apel.** Deschide un link, deci schimbă
 * două lucruri pe care ecranele le au deja în mână: lista de linkuri a
 * clientului și urma cererii din raportul de documente lipsă. Prima variantă
 * chema ruta direct din buton — textul ajungea corect în clipboard, dar rândul
 * continua să scrie „Necerut" până la o reîncărcare de pagină. Un ecran care
 * arată contrariul a ceea ce tocmai ai făcut este mai rău decât unul care nu
 * arată nimic: te face să o faci a doua oară.
 */
export function useDocumentRequest() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ clientId, referenceMonth }: { clientId: string; referenceMonth: string }) =>
      clients.documentRequest(clientId, referenceMonth),
    onSuccess: (_data, { clientId, referenceMonth }) => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.missingDocuments(referenceMonth),
      });
      void queryClient.invalidateQueries({ queryKey: queryKeys.clientUploadLinks(clientId) });
    },
  });
}

/**
 * Trimite solicitarea din aplicație.
 *
 * Invalidează aceleași liste ca `useDocumentRequest`: rândul de sub buton trece
 * din „Necerut" în „Trimis", iar un ecran care arată contrariul a ceea ce tocmai
 * ai făcut te face să o faci a doua oară.
 */
export function useSendDocumentRequest() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      clientId,
      referenceMonth,
      to,
    }: {
      clientId: string;
      referenceMonth: string;
      to?: string;
    }) => clients.sendDocumentRequest(clientId, referenceMonth, to),
    onSuccess: (_data, { clientId, referenceMonth }) => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.missingDocuments(referenceMonth),
      });
      void queryClient.invalidateQueries({ queryKey: queryKeys.clientUploadLinks(clientId) });
    },
  });
}

/**
 * Cererea către mai mulți clienți deodată.
 *
 * Invalidează raportul lunii: după trimitere, rândurile trec din „Necerut" în
 * „Trimis", iar un ecran care arată contrariul te face să apeși din nou.
 */
export function useSendRequests() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      referenceMonth,
      clientIds,
    }: {
      referenceMonth: string;
      clientIds: string[];
    }) => periods.sendRequests(referenceMonth, clientIds),
    onSuccess: (_data, { referenceMonth }) =>
      void queryClient.invalidateQueries({
        queryKey: queryKeys.missingDocuments(referenceMonth),
      }),
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

/* ─── Profiluri de client ─────────────────────────────────────────────────── */

export function useExpectationTemplates() {
  return useQuery({
    queryKey: queryKeys.expectationTemplates,
    queryFn: () => expectationTemplates.list(),
  });
}

/**
 * Ce se invalidează după ce un șablon atinge clienți.
 *
 * Aplicarea rescrie listele lor, iar din liste se derivă checklistul fiecărei
 * luni, raportul „Documente lipsă" și numărătoarea de pe panoul principal. Un
 * ecran care arată încă starea de dinainte te face să aplici a doua oară.
 */
function invalidateAfterApply(queryClient: ReturnType<typeof useQueryClient>) {
  void queryClient.invalidateQueries({ queryKey: ["clients"] });
  void queryClient.invalidateQueries({ queryKey: ["periods"] });
  void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
}

export function useCreateExpectationTemplate() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      name,
      expectations,
      obligationTypeIds,
    }: {
      name: string;
      expectations: ExpectationInput[];
      obligationTypeIds?: string[];
    }) => expectationTemplates.create(name, expectations, obligationTypeIds),
    onSuccess: () =>
      void queryClient.invalidateQueries({ queryKey: queryKeys.expectationTemplates }),
  });
}

export function useSaveExpectationTemplate() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      name,
      expectations,
      obligationTypeIds,
    }: {
      id: string;
      name: string;
      expectations: ExpectationInput[];
      obligationTypeIds?: string[];
    }) => expectationTemplates.update(id, name, expectations, obligationTypeIds),
    onSuccess: () =>
      void queryClient.invalidateQueries({ queryKey: queryKeys.expectationTemplates }),
  });
}

export function useDeleteExpectationTemplate() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => expectationTemplates.remove(id),
    onSuccess: () =>
      void queryClient.invalidateQueries({ queryKey: queryKeys.expectationTemplates }),
  });
}

export function useTemplateFromClient() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ clientId, name }: { clientId: string; name: string }) =>
      expectationTemplates.fromClient(clientId, name),
    onSuccess: () =>
      void queryClient.invalidateQueries({ queryKey: queryKeys.expectationTemplates }),
  });
}

export function useApplyExpectationTemplate() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, clientIds }: { id: string; clientIds: string[] }) =>
      expectationTemplates.apply(id, clientIds),
    onSuccess: () => invalidateAfterApply(queryClient),
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

/**
 * Ce are cabinetul de depus, pentru cine, până când.
 *
 * Fereastra o alege serverul dacă nu i se dă una: pornește din urmă, ca
 * întârziatele să nu dispară din listă tocmai pentru că au întârziat.
 */
export function useObligations(params: QueryParams = {}) {
  return useQuery({
    queryKey: queryKeys.obligations(params),
    queryFn: () => obligations.upcoming(params),
  });
}

export function useObligationTypes() {
  return useQuery({ queryKey: queryKeys.obligationTypes, queryFn: () => obligations.types() });
}

/**
 * Ce s-a înregistrat deja pentru un client.
 *
 * Cheia stă sub familia „obligations", ca toate celelalte: orice marcare
 * invalidează familia întreagă, deci lista de aici se reîncarcă singură după ce
 * cineva înregistrează o depunere. O cheie în afara familiei ar fi arătat mai
 * departe lista de dinainte.
 */
export function useClientFilings(clientId: string) {
  return useQuery({
    queryKey: queryKeys.clientFilings(clientId),
    queryFn: () => obligations.filingsForClient(clientId),
  });
}

export function useClientObligations(clientId: string) {
  return useQuery({
    queryKey: queryKeys.clientObligations(clientId),
    queryFn: () => obligations.forClient(clientId),
  });
}

/**
 * Toate mutațiile de aici invalidează **întreaga** familie „obligations".
 *
 * Cheia listei conține fereastra, iar ecranul poate avea mai multe ferestre
 * deschise în cache. O invalidare țintită pe una singură ar lăsa restul să arate
 * o depunere care tocmai s-a marcat — exact defectul de la cererea de documente,
 * unde rândul continua să scrie „Necerut" după o copiere reușită.
 */
function useObligationMutation<TInput, TResult>(
  mutationFn: (input: TInput) => Promise<TResult>,
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn,
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["obligations"] }),
  });
}

export function useMarkFiled() {
  return useObligationMutation(obligations.markFiled);
}

export function useUnmarkFiled() {
  return useObligationMutation(obligations.unmarkFiled);
}

export function useMarkManyFiled() {
  return useObligationMutation(obligations.markManyFiled);
}

export function useUpdateObligationType() {
  return useObligationMutation(
    ({ id, changes }: { id: string; changes: Partial<ObligationType> }) =>
      obligations.updateType(id, changes),
  );
}

export function useSetClientObligations() {
  return useObligationMutation(
    ({ clientId, obligationTypeIds }: { clientId: string; obligationTypeIds: string[] }) =>
      obligations.setForClient(clientId, obligationTypeIds),
  );
}

/**
 * Onorariile lunii.
 *
 * O singură cheie pentru tot ecranul: rândurile, cifrele și restanțele vin
 * împreună de la server, deci se și învechesc împreună.
 */
export function useFees(referenceMonth: string) {
  return useQuery({
    queryKey: queryKeys.fees(referenceMonth),
    queryFn: () => fees.month(referenceMonth),
  });
}

/**
 * `enabled` nu este o optimizare: pornită oricum, interogarea ar produce un
 * 403 la fiecare deschidere de fișă pentru cine nu are `fees:read`.
 */
export function useClientFee(clientId: string, enabled = true) {
  return useQuery({
    queryKey: queryKeys.clientFee(clientId),
    queryFn: () => fees.forClient(clientId),
    enabled,
  });
}

export function useClientFeeHistory(clientId: string, enabled = true) {
  return useQuery({
    queryKey: queryKeys.clientFeeHistory(clientId),
    queryFn: () => fees.history(clientId),
    enabled,
  });
}

/**
 * Ca la termene, se invalidează **toată** familia „fees".
 *
 * Marcarea unei încasări schimbă și rândul, și totalurile, și lista de restanțe
 * — iar aceasta din urmă stă sub cheia altei luni.
 */
function useFeeMutation<TInput, TResult>(mutationFn: (input: TInput) => Promise<TResult>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn,
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["fees"] }),
  });
}

export function useGenerateFees() {
  return useFeeMutation((referenceMonth: string) => fees.generate(referenceMonth));
}

export function useMarkFeePaid() {
  return useFeeMutation(fees.markPaid);
}

export function useUnmarkFeePaid() {
  return useFeeMutation(fees.unmarkPaid);
}

export function useSetClientFee() {
  return useFeeMutation(
    ({
      clientId,
      ...input
    }: {
      clientId: string;
      amount: string | null;
      currency?: string;
      startsOn?: string | null;
      note?: string | null;
    }) => fees.setForClient(clientId, input),
  );
}

export function useClientTimeline(clientId: string) {
  return useQuery({
    queryKey: queryKeys.clientTimeline(clientId),
    queryFn: () => clients.timeline(clientId),
  });
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

/**
 * Importă o listă de clienți dintr-un fișier.
 *
 * Invalidează listele doar când chiar a scris: o previzualizare nu schimbă
 * nimic, iar un refetch după ea ar fi doar zgomot.
 */
export function useImportClients() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ file, apply }: { file: File; apply: boolean }) =>
      clients.importClients(file, apply),
    onSuccess: (plan) => {
      if (plan.dryRun) return;
      void queryClient.invalidateQueries({ queryKey: ["clients"] });
      void queryClient.invalidateQueries({ queryKey: queryKeys.dashboard });
    },
  });
}

/**
 * Toate drumurile pe care pot intra documentele, cu starea de acum.
 *
 * Nu înlocuiește `useDriveStatus`: acela configurează OneDrive în amănunt, ăsta
 * răspunde la întrebarea de deasupra — pe unde intră documentele, în general.
 */
export function useDocumentSources() {
  return useQuery({ queryKey: queryKeys.documentSources, queryFn: documentSources.list });
}

/* ─── Cutii poștale IMAP ───────────────────────────────────────────────────── */

export function useImapMailboxes() {
  return useQuery({ queryKey: queryKeys.imapMailboxes, queryFn: imap.list });
}

/**
 * Adaugă o cutie. Serverul o **testează** înainte să o salveze, deci un refuz
 * aici înseamnă că parola chiar nu merge — nu că am scris noi ceva greșit.
 */
/**
 * Orice atingere a unei cutii schimbă și harta surselor de pe același ecran:
 * starea drumului „Email — IMAP" și contorul lui de documente vin de acolo.
 */
function useImapMutation<TArgs, TResult>(mutationFn: (args: TArgs) => Promise<TResult>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.imapMailboxes });
      void queryClient.invalidateQueries({ queryKey: queryKeys.documentSources });
    },
  });
}

/**
 * Adaugă o cutie. Serverul o **testează** înainte să o salveze, deci un refuz
 * aici înseamnă că parola chiar nu merge — nu că am trimis noi ceva greșit.
 */
export function useAddImapMailbox() {
  return useImapMutation((input: ImapMailboxInput) => imap.add(input));
}

export function useRemoveImapMailbox() {
  return useImapMutation((id: string) => imap.remove(id));
}

/** Citește cutia acum, fără să aștepte planificatorul. */
export function useSyncImapMailbox() {
  return useImapMutation((id: string) => imap.sync(id));
}

/* ─── Remindere ──────────────────────────────────────────────────────────── */

/**
 * Cine primește azi o reamintire, și de ce ceilalți nu.
 *
 * Interogare obișnuită, fără efecte: deschiderea ecranului nu trimite nimic și
 * nu deschide niciun link de trimitere.
 */
export function useReminders() {
  return useQuery({ queryKey: queryKeys.reminders, queryFn: reminders.list });
}

/**
 * Trimite acum tot ce era de trimis.
 *
 * Invalidează și lista de documente lipsă și panoul: după apăsare, rândurile
 * trec din „de trimis" în „așteptăm", iar un ecran care arată contrariul a ceea
 * ce tocmai ai făcut te face să apeși a doua oară.
 */
export function useSendReminders() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: reminders.send,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.reminders });
      void queryClient.invalidateQueries({ queryKey: ["periods"] });
      void queryClient.invalidateQueries({ queryKey: queryKeys.dashboard });
    },
  });
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
/**
 * Starea cozii de procesare, reîmprospătată singură.
 *
 * **De ce se reinterogează.** Ecranul acesta răspunde la „merge sau nu merge",
 * iar răspunsul se schimbă fără ca cineva să apese ceva: workerul golește coada
 * sau moare. Un panou care ar arăta cifra de la deschiderea paginii ar spune
 * „opt în așteptare" o oră după ce coada s-a golit — exact felul de informație
 * veche care se citește ca informație.
 *
 * Un minut, nu cinci secunde: o coadă nu se privește ca un cronometru, iar o
 * cerere pe secundă de la fiecare filă deschisă ar fi ea însăși o sarcină.
 */
export function useProcessingHealth() {
  return useQuery({
    queryKey: queryKeys.processingHealth,
    queryFn: () => documents.processingHealth(),
    refetchInterval: 60_000,
  });
}

export function useUploadDocument() {
  return useDocumentMutation(
    ({
      file,
      clientId,
      source,
    }: {
      file: File;
      clientId?: string;
      source?: ManualDocumentSource;
    }) => documents.upload(file, clientId, source),
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

/**
 * Schimbarea propriei parole (§1).
 *
 * La succes se invalidează tot: sesiunea rămâne a mea, dar celelalte s-au închis,
 * iar lista lor este chiar ce se uită omul imediat după.
 */
export function useChangePassword() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      currentPassword,
      newPassword,
    }: {
      currentPassword: string;
      newPassword: string;
    }) => auth.changePassword(currentPassword, newPassword),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["sessions"] });
    },
  });
}

/** Ferestrele deschise pe contul meu. */
export function useSessions() {
  return useQuery({ queryKey: ["sessions"], queryFn: () => auth.sessions() });
}

/** Închide toate celelalte ferestre; a mea rămâne. */
export function useRevokeOtherSessions() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => auth.revokeOtherSessions(),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["sessions"] });
    },
  });
}

// ── Bancă (§11–§15) ──────────────────────────────────────────────────────────

/** Extrasele importate, cel mai recent întâi. */
export function useBankStatements(clientId?: string) {
  return useQuery({
    queryKey: ["bank", "statements", clientId ?? null],
    queryFn: () => bank.statements(clientId),
  });
}

/** Rândurile unui extras, în ordinea din fișier. */
export function useBankTransactions(params: QueryParams) {
  return useQuery({
    queryKey: ["bank", "transactions", params],
    queryFn: () => bank.transactions(params),
  });
}

/**
 * Ce facturi ar putea fi plata asta.
 *
 * `enabled` pe rândul deschis: propunerile costă o interogare cu candidați, iar
 * cerute pentru toate cele trei sute de rânduri deodată ar fi ținut ecranul
 * blocat pentru un răspuns de care omul are nevoie pe unul singur.
 */
export function useMatchSuggestions(transactionId: string | null) {
  return useQuery({
    queryKey: ["bank", "suggestions", transactionId],
    queryFn: () => bank.suggestions(transactionId!),
    enabled: !!transactionId,
  });
}

/** Ce se invalidează după orice schimbare pe o tranzacție. */
function useBankMutation<TArgs>(fn: (args: TArgs) => Promise<unknown>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => {
      // Tot: lista de tranzacții, contorul de pe extras și propunerile — o
      // factură închisă nu mai are voie să apară ca propunere pe alt rând.
      void queryClient.invalidateQueries({ queryKey: ["bank"] });
    },
  });
}

export function useMatchTransaction() {
  return useBankMutation(
    ({
      transactionId,
      documentId,
      amount,
    }: {
      transactionId: string;
      documentId: string;
      amount?: string;
    }) => bank.match(transactionId, documentId, amount),
  );
}

export function useUnmatchTransaction() {
  return useBankMutation(({ transactionId, documentId }: { transactionId: string; documentId: string }) =>
    bank.unmatch(transactionId, documentId),
  );
}

export function useIgnoreTransaction() {
  return useBankMutation(({ transactionId, note }: { transactionId: string; note: string | null }) =>
    bank.ignore(transactionId, note),
  );
}

export function useReopenTransaction() {
  return useBankMutation(({ transactionId }: { transactionId: string }) =>
    bank.reopen(transactionId),
  );
}

/** Importul unui extras. `apply: false` este previzualizarea. */
export function useImportStatement() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ file, params }: { file: File; params: QueryParams }) =>
      bank.importStatement(file, params),
    onSuccess: (_result, variables) => {
      if (variables.params.apply) {
        void queryClient.invalidateQueries({ queryKey: ["bank"] });
      }
    },
  });
}

// ── Desfacerea unui teanc (§8) ───────────────────────────────────────────────

/**
 * Unde s-ar tăia teancul.
 *
 * `enabled` doar pentru PDF-uri: pentru un XML sau o poză nu are ce cere, iar o
 * interogare care întoarce mereu „nu se poate" pe fiecare deschidere de document
 * este o interogare degeaba.
 */
export function useSplitPreview(documentId: string, isPdf: boolean) {
  return useQuery({
    queryKey: ["documents", documentId, "split"],
    queryFn: () => documents.splitPreview(documentId),
    enabled: isPdf,
  });
}

/** Desface teancul. La succes, tot ce ține de documente se reîmprospătează. */
export function useSplitDocument() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (documentId: string) => documents.split(documentId),
    onSuccess: () => {
      // Teancul își schimbă starea, apar documente noi, se schimbă contoarele
      // din bara laterală și coada de verificare.
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
      void queryClient.invalidateQueries({ queryKey: ["sidebar"] });
      void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
}

// ── Perechea XML ↔ PDF (§16, §17) ────────────────────────────────────────────

/** Celălalt exemplar al aceleiași facturi, dacă există. */
export function useDocumentPairing(documentId: string) {
  return useQuery({
    queryKey: ["documents", documentId, "pairing"],
    queryFn: () => documents.pairing(documentId),
  });
}

function usePairingMutation<TArgs>(fn: (args: TArgs) => Promise<unknown>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => {
      // Legătura se scrie pe **amândouă** documentele, deci se invalidează tot ce
      // ține de documente: fișa celuilalt exemplar arată acum altceva.
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
    },
  });
}

export function usePairDocument() {
  return usePairingMutation(({ documentId, otherId }: { documentId: string; otherId: string }) =>
    documents.pair(documentId, otherId),
  );
}

export function useUnpairDocument() {
  return usePairingMutation((documentId: string) => documents.unpair(documentId));
}
