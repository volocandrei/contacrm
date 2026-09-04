import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  Calculator,
  CircleAlert,
  CircleCheck,
  Copy,
  Download,
  History,
  Inbox,
  LoaderCircle,
  Lock,
  Paperclip,
  RefreshCw,
  Save,
  ScanLine,
  Sparkles,
  TriangleAlert,
  UserCheck,
  X,
} from "lucide-react";
import {
  useApproveDocument,
  useAssignClient,
  useClients,
  useDocument,
  useDocumentTypes,
  useMarkDuplicate,
  useNextReviewDocument,
  useRejectDocument,
  useReprocessDocument,
  useUpdateDocumentFields,
} from "@/api/hooks";
import { ApiError } from "@/api/types";
import { ErrorState, LoadingState, Panel } from "@/components/page";
import { ConfidenceBadge, DocumentStatusBadge } from "@/components/status-badge";
import { DocumentPreview } from "@/features/documents/document-preview";
import { useDownloadDocument } from "@/features/documents/use-download";
import { describeError } from "@/lib/errors";
import { formatDateTime, formatFileSize } from "@/lib/format";
import { cn } from "@/lib/utils";
import type {
  DocumentAction,
  DocumentDetail,
  DocumentErrorCode,
  DocumentFieldName,
  ExtractedField,
} from "@/types/domain";

/** Ordinea câmpurilor în formular — aceeași cu ordinea de citire a unei facturi. */
const FIELD_ORDER: Array<{ name: DocumentFieldName; label: string; type?: string }> = [
  { name: "documentType", label: "Tip document" },
  { name: "documentDate", label: "Data documentului", type: "date" },
  { name: "series", label: "Serie" },
  { name: "documentNumber", label: "Număr" },
  { name: "supplierName", label: "Furnizor" },
  { name: "supplierTaxId", label: "CUI furnizor" },
  { name: "customerName", label: "Client" },
  { name: "customerTaxId", label: "CUI client" },
  { name: "currency", label: "Monedă" },
  { name: "subtotal", label: "Subtotal" },
  { name: "vatAmount", label: "TVA" },
  { name: "totalAmount", label: "Total" },
  // Perioada de referință decide în ce lună contabilă intră documentul — se
  // schimbă dintr-un selector de lună, nu prin text liber (§31).
  { name: "referenceMonth", label: "Perioadă de referință", type: "month" },
];

/** Codurile de eroare, în română. Codul se persistă; textul se traduce (§53). */
const ERROR_LABEL: Record<DocumentErrorCode, string> = {
  INVALID_FILE: "Fișierul nu a putut fi citit.",
  UNSUPPORTED_FORMAT: "Formatul nu este acceptat.",
  FILE_TOO_LARGE: "Fișierul depășește dimensiunea maximă.",
  OCR_FAILED: "Recunoașterea textului a eșuat.",
  EXTRACTION_FAILED: "Extragerea datelor a eșuat.",
  CLASSIFICATION_FAILED: "Tipul documentului nu a putut fi stabilit.",
  VALIDATION_FAILED: "Datele extrase nu au trecut validarea.",
  DUPLICATE_DETECTED: "Documentul există deja în sistem.",
  CLIENT_NOT_FOUND: "Clientul nu a putut fi identificat.",
  STORAGE_FAILED: "Fișierul nu a putut fi salvat.",
  ARCHIVE_FAILED: "Arhivarea a eșuat.",
  INTERNAL_ERROR: "Eroare internă la procesare.",
};

type Draft = Partial<Record<DocumentFieldName, string>>;

export function ReviewPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { data: document, isLoading, error } = useDocument(id);

  if (isLoading) return <LoadingState label="Se încarcă documentul…" />;
  if (error) return <ErrorState error={error} />;
  if (!document) return <ErrorState error={new Error("Document inexistent.")} />;

  return (
    <ReviewScreen
      key={document.id}
      document={document}
      onNavigate={(nextId) => navigate(`/documente/verificare/${nextId}`)}
    />
  );
}

function ReviewScreen({
  document,
  onNavigate,
}: {
  document: DocumentDetail;
  onNavigate: (id: string) => void;
}) {
  const [draft, setDraft] = useState<Draft>({});
  const [feedback, setFeedback] = useState<{ tone: "ok" | "error"; message: string } | null>(null);
  const [rejecting, setRejecting] = useState(false);
  const [rejectReason, setRejectReason] = useState("");

  // Ce se poate face îl spune serverul, în starea de acum a documentului și pentru
  // rolul acestui utilizator. Interfața nu recalculează regulile ciclului de viață:
  // o a doua copie ar rămâne în urmă tăcut, iar butoanele ar minți.
  const can = (action: DocumentAction) => document.availableActions.includes(action);
  const canWrite = can("edit");

  const { data: documentTypes } = useDocumentTypes();
  const { data: clientsPage } = useClients({ pageSize: 200, status: "ACTIVE" });

  const updateFields = useUpdateDocumentFields(document.id);
  const approve = useApproveDocument();
  const reject = useRejectDocument();
  const markDuplicate = useMarkDuplicate();
  const reprocess = useReprocessDocument();
  const assignClient = useAssignClient();
  const { download, isPending: downloading } = useDownloadDocument();

  const isProcessing = document.status === "RECEIVED" || document.status === "PROCESSING";

  const dirtyFields = useMemo(
    () =>
      (Object.keys(draft) as DocumentFieldName[]).filter(
        (name) => (draft[name] ?? "") !== (document.fields[name].value ?? ""),
      ),
    [draft, document.fields],
  );
  const isDirty = dirtyFields.length > 0;

  function valueOf(name: DocumentFieldName): string {
    return draft[name] ?? document.fields[name].value ?? "";
  }

  function pendingUpdates() {
    return dirtyFields.map((name) => ({ field: name, value: draft[name] || null }));
  }

  async function handleSave() {
    if (!isDirty) return;
    try {
      await updateFields.mutateAsync(pendingUpdates());
      setDraft({});
      setFeedback({ tone: "ok", message: "Modificările au fost salvate." });
    } catch (caught) {
      setFeedback({ tone: "error", message: describeError(caught) });
    }
  }

  async function handleApprove() {
    try {
      // Corecțiile nesalvate se trimit înainte: altfel aprobarea ar cădea pe câmpuri
      // pe care operatorul tocmai le-a completat.
      if (isDirty) {
        await updateFields.mutateAsync(pendingUpdates());
        setDraft({});
      }
      await approve.mutateAsync(document.id);
      setFeedback({ tone: "ok", message: "Document aprobat și arhivat." });
    } catch (caught) {
      setFeedback({ tone: "error", message: describeError(caught) });
    }
  }

  async function handleReject() {
    try {
      await reject.mutateAsync({ id: document.id, reason: rejectReason });
      setRejecting(false);
      setRejectReason("");
      setFeedback({ tone: "ok", message: "Document respins." });
    } catch (caught) {
      setFeedback({ tone: "error", message: describeError(caught) });
    }
  }

  async function run(action: () => Promise<unknown>, message: string) {
    try {
      await action();
      setFeedback({ tone: "ok", message });
    } catch (caught) {
      setFeedback({ tone: "error", message: describeError(caught) });
    }
  }

  // Scurtături de tastatură — operatorul trebuie să treacă rapid prin sute de documente (§67).
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (!event.altKey) return;
      const key = event.key.toLowerCase();
      if (key === "s" && canWrite) {
        event.preventDefault();
        void handleSave();
      } else if (key === "a" && can("approve")) {
        event.preventDefault();
        void handleApprove();
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  });

  const busy =
    updateFields.isPending ||
    approve.isPending ||
    reject.isPending ||
    markDuplicate.isPending ||
    reprocess.isPending ||
    assignClient.isPending;

  // Aprobarea nu se oferă cât timp serverul are ce reproșa documentului: ar
  // răspunde 422 cu exact lista de mai jos.
  const approvalBlocked = document.approvalBlockers.length > 0;

  return (
    <div className="flex min-h-[calc(100vh-8rem)] flex-col">
      {/* Antet */}
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="truncate text-xl font-bold text-gray-900 dark:text-gray-100">
              {document.storedFilename ?? document.originalFilename}
            </h2>
            <DocumentStatusBadge status={document.status} />
            <ConfidenceBadge confidence={document.confidence} />
          </div>
          <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
            {formatFileSize(document.fileSize)} · {document.mimeType} · recepționat{" "}
            {formatDateTime(document.receivedAt)} · SHA-256 {document.sha256.slice(0, 12)}…
          </p>
        </div>
        <div className="flex items-center gap-2">
          {can("download") && (
            <button
              type="button"
              onClick={() =>
                void run(() => download(document), "Descărcarea a pornit.")
              }
              disabled={downloading}
              className="flex h-9 items-center gap-1.5 rounded-lg border border-gray-200 px-3 text-sm font-medium text-gray-600 transition-colors hover:bg-gray-50 disabled:opacity-50 dark:border-gray-700 dark:text-gray-300 dark:hover:bg-gray-800"
            >
              <Download className="h-4 w-4" aria-hidden="true" />
              Descarcă
            </button>
          )}
          <Link
            to="/documente/verificare"
            className="flex h-9 items-center gap-1.5 rounded-lg border border-gray-200 px-3 text-sm font-medium text-gray-600 transition-colors hover:bg-gray-50 dark:border-gray-700 dark:text-gray-300 dark:hover:bg-gray-800"
          >
            <X className="h-4 w-4" aria-hidden="true" />
            Închide
          </Link>
        </div>
      </div>

      {isProcessing && (
        <div
          role="status"
          className="mb-4 flex items-center gap-2 rounded-lg border border-blue-200 bg-blue-50 px-4 py-2.5 text-sm text-blue-800 dark:border-blue-800 dark:bg-blue-900/20 dark:text-blue-300"
        >
          <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden="true" />
          Documentul este în procesare. Ecranul se actualizează singur când se termină.
        </div>
      )}

      {document.status === "ERROR" && (
        <div className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm dark:border-red-800 dark:bg-red-900/20">
          <p className="flex items-center gap-1.5 font-medium text-red-900 dark:text-red-200">
            <CircleAlert className="h-4 w-4" aria-hidden="true" />
            Procesarea a eșuat
          </p>
          <p className="mt-1 ml-6 text-red-800 dark:text-red-300">
            {document.errorCode ? ERROR_LABEL[document.errorCode] : "Motiv necunoscut."}{" "}
            {document.processingAttempts > 0 && (
              <span className="text-red-700 dark:text-red-400">
                ({document.processingAttempts}{" "}
                {document.processingAttempts === 1 ? "încercare" : "încercări"})
              </span>
            )}
          </p>
        </div>
      )}

      {document.validationIssues.length > 0 && (
        <div className="mb-4 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm dark:border-amber-800 dark:bg-amber-900/20">
          <p className="mb-1 flex items-center gap-1.5 font-medium text-amber-900 dark:text-amber-200">
            <TriangleAlert className="h-4 w-4" aria-hidden="true" />
            De ce a ajuns la verificare
          </p>
          <ul className="ml-6 list-disc space-y-0.5 text-amber-800 dark:text-amber-300">
            {document.validationIssues.map((issue) => (
              <li key={issue}>{issue}</li>
            ))}
          </ul>
        </div>
      )}

      {document.files.length > 0 && <FilesBlock document={document} />}

      {feedback && (
        <div
          role="status"
          className={cn(
            "mb-4 flex items-center justify-between gap-3 rounded-lg px-4 py-2.5 text-sm",
            feedback.tone === "ok"
              ? "bg-green-50 text-green-800 dark:bg-green-900/20 dark:text-green-300"
              : "bg-red-50 text-red-800 dark:bg-red-900/20 dark:text-red-300",
          )}
        >
          <span className="flex items-center gap-2">
            {feedback.tone === "ok" ? (
              <CircleCheck className="h-4 w-4" aria-hidden="true" />
            ) : (
              <CircleAlert className="h-4 w-4" aria-hidden="true" />
            )}
            {feedback.message}
          </span>
          <button
            type="button"
            onClick={() => setFeedback(null)}
            className="text-xs font-medium opacity-70 hover:opacity-100"
          >
            Închide
          </button>
        </div>
      )}

      <div className="grid flex-1 grid-cols-1 gap-4 lg:grid-cols-5">
        {/* Stânga: previzualizare */}
        <div className="lg:col-span-3">
          <div className="h-[70vh] overflow-hidden rounded-xl border border-gray-200 bg-white shadow-sm lg:sticky lg:top-20 dark:border-gray-800 dark:bg-gray-900">
            <DocumentPreview document={document} />
          </div>
        </div>

        {/* Dreapta: câmpuri extrase */}
        <div className="space-y-4 lg:col-span-2">
          {!document.clientId && can("assignClient") && (
            <Panel title="Atribuie client">
              <p className="mb-3 text-xs text-gray-500 dark:text-gray-400">
                Expeditorul nu a putut fi mapat automat. Alege clientul căruia îi aparține documentul.
              </p>
              <select
                defaultValue=""
                disabled={busy}
                onChange={(event) => {
                  if (!event.target.value) return;
                  void run(
                    () =>
                      assignClient.mutateAsync({
                        id: document.id,
                        clientId: event.target.value,
                      }),
                    "Clientul a fost atribuit.",
                  );
                }}
                className="h-9 w-full cursor-pointer rounded-lg border border-gray-200 bg-white px-3 text-sm dark:border-gray-700 dark:bg-gray-950 dark:text-gray-100"
              >
                <option value="">Selectează clientul…</option>
                {(clientsPage?.items ?? []).map((client) => (
                  <option key={client.id} value={client.id}>
                    {client.name} · {client.taxId}
                  </option>
                ))}
              </select>
            </Panel>
          )}

          <Panel
            title="Date extrase"
            action={
              <span className="text-xs text-gray-400 dark:text-gray-500">
                {document.extraction.provider ?? "—"}
                {document.extraction.promptVersion ? ` · ${document.extraction.promptVersion}` : ""}
              </span>
            }
          >
            {/* Un formular blocat fără explicație pare stricat. */}
            {document.status === "ARCHIVED" && (
              <p className="mb-3 flex items-start gap-1.5 rounded-lg bg-gray-50 px-3 py-2 text-xs text-gray-600 dark:bg-gray-800/60 dark:text-gray-400">
                <Lock className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                <span>
                  Documentul este arhivat, iar numele fișierului este format din datele de
                  mai jos. Cere o reprocesare dacă trebuie corectate.
                </span>
              </p>
            )}

            <div className="space-y-3">
              {FIELD_ORDER.map(({ name, label, type }) => (
                <FieldRow
                  key={name}
                  name={name}
                  label={label}
                  type={type}
                  field={document.fields[name]}
                  value={valueOf(name)}
                  disabled={!canWrite || busy}
                  isDirty={dirtyFields.includes(name)}
                  options={
                    name === "documentType"
                      ? (documentTypes ?? []).map((t) => ({ value: t.code, label: t.label }))
                      : undefined
                  }
                  onChange={(value) => setDraft((current) => ({ ...current, [name]: value }))}
                />
              ))}
            </div>
          </Panel>

          {/* Acțiuni */}
          <Panel>
            <div className="flex flex-wrap gap-2">
              {can("approve") && (
                <button
                  type="button"
                  onClick={handleApprove}
                  disabled={busy || (approvalBlocked && !isDirty)}
                  title={
                    approvalBlocked && !isDirty
                      ? document.approvalBlockers.join(" ")
                      : undefined
                  }
                  className="flex h-10 flex-1 items-center justify-center gap-2 rounded-lg bg-green-600 px-4 text-sm font-medium text-white transition-colors hover:bg-green-700 disabled:opacity-60"
                >
                  <CircleCheck className="h-4 w-4" aria-hidden="true" />
                  Aprobă și arhivează
                  <kbd className="ml-1 rounded bg-green-700 px-1 text-[10px]">Alt+A</kbd>
                </button>
              )}
              {canWrite && (
                <button
                  type="button"
                  onClick={handleSave}
                  disabled={!isDirty || busy}
                  className="flex h-10 items-center justify-center gap-2 rounded-lg border border-gray-200 px-4 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50 disabled:opacity-50 dark:border-gray-700 dark:text-gray-200 dark:hover:bg-gray-800"
                >
                  <Save className="h-4 w-4" aria-hidden="true" />
                  Salvează
                  <kbd className="rounded bg-gray-200 px-1 text-[10px] dark:bg-gray-700">Alt+S</kbd>
                </button>
              )}
            </div>

            {can("approve") && approvalBlocked && (
              <ul className="mt-2 ml-1 list-disc space-y-0.5 pl-4 text-xs text-gray-500 dark:text-gray-400">
                {document.approvalBlockers.map((blocker) => (
                  <li key={blocker}>{blocker}</li>
                ))}
              </ul>
            )}

            <div className="mt-2 flex flex-wrap gap-2">
              {can("reject") && (
                <button
                  type="button"
                  onClick={() => setRejecting((value) => !value)}
                  disabled={busy}
                  className="flex h-9 items-center gap-1.5 rounded-lg border border-gray-200 px-3 text-sm text-gray-600 transition-colors hover:bg-gray-50 disabled:opacity-50 dark:border-gray-700 dark:text-gray-300 dark:hover:bg-gray-800"
                >
                  <X className="h-4 w-4" aria-hidden="true" />
                  Respinge
                </button>
              )}
              {can("markDuplicate") && (
                <button
                  type="button"
                  onClick={() =>
                    void run(
                      () =>
                        markDuplicate.mutateAsync({ id: document.id, duplicateOfId: null }),
                      "Documentul a fost marcat ca duplicat.",
                    )
                  }
                  disabled={busy}
                  className="flex h-9 items-center gap-1.5 rounded-lg border border-gray-200 px-3 text-sm text-gray-600 transition-colors hover:bg-gray-50 disabled:opacity-50 dark:border-gray-700 dark:text-gray-300 dark:hover:bg-gray-800"
                >
                  <Copy className="h-4 w-4" aria-hidden="true" />
                  Duplicat
                </button>
              )}
              {can("reprocess") && (
                <button
                  type="button"
                  onClick={() =>
                    void run(
                      () => reprocess.mutateAsync(document.id),
                      "Documentul a fost trimis din nou la procesare.",
                    )
                  }
                  disabled={busy}
                  className="flex h-9 items-center gap-1.5 rounded-lg border border-gray-200 px-3 text-sm text-gray-600 transition-colors hover:bg-gray-50 disabled:opacity-50 dark:border-gray-700 dark:text-gray-300 dark:hover:bg-gray-800"
                >
                  <RefreshCw className="h-4 w-4" aria-hidden="true" />
                  Reprocesează
                </button>
              )}
            </div>

            {/* Când reprocesarea nu se poate, spunem de ce. Un buton care dispare
                fără explicație face documentul să pară pur și simplu uitat. */}
            {canWrite && document.reprocessBlockedReason && (
              <p className="mt-2 text-xs text-gray-500 dark:text-gray-400">
                {document.reprocessBlockedReason}
              </p>
            )}

            {rejecting && (
              <div className="mt-3 space-y-2 rounded-lg bg-gray-50 p-3 dark:bg-gray-800/60">
                <label
                  htmlFor="reject-reason"
                  className="block text-xs font-medium text-gray-700 dark:text-gray-300"
                >
                  Motivul respingerii (obligatoriu, rămâne în audit)
                </label>
                <textarea
                  id="reject-reason"
                  rows={2}
                  value={rejectReason}
                  onChange={(event) => setRejectReason(event.target.value)}
                  className="w-full rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm dark:border-gray-700 dark:bg-gray-950 dark:text-gray-100"
                />
                <button
                  type="button"
                  onClick={handleReject}
                  disabled={!rejectReason.trim() || busy}
                  className="h-9 rounded-lg bg-red-600 px-3 text-sm font-medium text-white transition-colors hover:bg-red-700 disabled:opacity-50"
                >
                  Confirmă respingerea
                </button>
              </div>
            )}
          </Panel>

          {document.duplicateOfId && (
            <Panel title="Posibil duplicat">
              <p className="text-sm text-gray-600 dark:text-gray-400">
                Documentul pare identic cu{" "}
                <button
                  type="button"
                  onClick={() => onNavigate(document.duplicateOfId!)}
                  className="font-medium text-blue-600 hover:underline dark:text-blue-400"
                >
                  {document.duplicateOfId}
                </button>
                . Confirmă înainte de arhivare.
              </p>
            </Panel>
          )}

          <Panel title="Istoric">
            <ol className="space-y-3">
              {document.history.map((entry) => (
                <li key={entry.id} className="flex gap-2.5 text-xs">
                  <History className="mt-0.5 h-3.5 w-3.5 shrink-0 text-gray-400" aria-hidden="true" />
                  <div className="min-w-0">
                    <p className="font-medium text-gray-900 dark:text-gray-100">{entry.action}</p>
                    {entry.detail && (
                      <p className="text-gray-500 dark:text-gray-400">{entry.detail}</p>
                    )}
                    <p className="text-gray-400 dark:text-gray-500">
                      {entry.actor} · {formatDateTime(entry.at)}
                    </p>
                  </div>
                </li>
              ))}
            </ol>
          </Panel>
        </div>
      </div>
    </div>
  );
}

/**
 * Fișierele documentului, când sunt mai multe decât unul.
 *
 * Cazul real este factura electronică: ajunge ca **trei** fișiere — XML-ul
 * (originalul fiscal, cel de la butonul „Descarcă"), arhiva ANAF cu sigiliul de
 * acceptare și PDF-ul tipăribil. La un control, arhiva este dovada că factura a
 * fost acceptată, iar spre deosebire de PDF nu se poate reface. De aceea sunt
 * toate trei scoase de aici, nu doar cea pe care o citește aplicația.
 */
function FilesBlock({ document }: { document: DocumentDetail }) {
  const { downloadFile, isPending } = useDownloadDocument();
  const [problem, setProblem] = useState<string | null>(null);

  return (
    <div className="mb-4 rounded-lg border border-gray-200 px-4 py-3 text-sm dark:border-gray-800">
      <p className="mb-2 flex items-center gap-1.5 font-medium text-gray-900 dark:text-gray-100">
        <Paperclip className="h-4 w-4" aria-hidden="true" />
        Fișierele documentului
      </p>
      {problem && (
        <p role="alert" className="mb-2 text-xs text-red-600 dark:text-red-400">
          {problem}
        </p>
      )}
      <ul className="space-y-1">
        {document.files.map((file) => (
          <li key={file.id} className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              disabled={isPending}
              onClick={() => {
                setProblem(null);
                void downloadFile(document, file).catch((caught: unknown) =>
                  setProblem(
                    caught instanceof ApiError
                      ? caught.message
                      : "Fișierul nu a putut fi descărcat.",
                  ),
                );
              }}
              className="font-medium text-blue-600 hover:underline disabled:opacity-50 dark:text-blue-400"
            >
              {file.label}
            </button>
            <span className="text-xs text-gray-500 dark:text-gray-400">
              {formatFileSize(file.fileSize)}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function FieldRow({
  name,
  label,
  type,
  field,
  value,
  disabled,
  isDirty,
  options,
  onChange,
}: {
  name: DocumentFieldName;
  label: string;
  type?: string;
  field: ExtractedField<string>;
  value: string;
  disabled: boolean;
  isDirty: boolean;
  options?: Array<{ value: string; label: string }>;
  onChange: (value: string) => void;
}) {
  const inputId = `field-${name}`;
  const lowConfidence = field.confidence !== null && field.confidence < 0.7;
  const mediumConfidence = field.confidence !== null && field.confidence >= 0.7 && field.confidence < 0.9;

  return (
    <div>
      <label
        htmlFor={inputId}
        className="mb-1 flex items-center justify-between gap-2 text-xs font-medium text-gray-600 dark:text-gray-400"
      >
        <span>{label}</span>
        <FieldOrigin field={field} isDirty={isDirty} />
      </label>
      {options ? (
        <select
          id={inputId}
          value={value}
          disabled={disabled}
          onChange={(event) => onChange(event.target.value)}
          className={cn(
            "h-9 w-full cursor-pointer rounded-lg border bg-white px-3 text-sm dark:bg-gray-950 dark:text-gray-100",
            fieldBorder(lowConfidence, mediumConfidence, isDirty),
          )}
        >
          <option value="">— neselectat —</option>
          {options.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      ) : (
        <input
          id={inputId}
          type={type ?? "text"}
          value={value}
          disabled={disabled}
          onChange={(event) => onChange(event.target.value)}
          className={cn(
            "h-9 w-full rounded-lg border bg-white px-3 text-sm dark:bg-gray-950 dark:text-gray-100",
            fieldBorder(lowConfidence, mediumConfidence, isDirty),
          )}
        />
      )}
    </div>
  );
}

function fieldBorder(low: boolean, medium: boolean, isDirty: boolean): string {
  if (isDirty) return "border-blue-400 ring-2 ring-blue-500/20";
  if (low) return "border-red-300 dark:border-red-800";
  if (medium) return "border-amber-300 dark:border-amber-800";
  return "border-gray-200 dark:border-gray-700";
}

/** Fiecare câmp arată de unde vine valoarea (§22): AI, corectură manuală sau gol. */
function FieldOrigin({ field, isDirty }: { field: ExtractedField<string>; isDirty: boolean }) {
  if (isDirty) {
    return <span className="text-[10px] font-medium text-blue-600 dark:text-blue-400">nesalvat</span>;
  }
  if (field.source === "MANUAL") {
    return (
      <span className="flex items-center gap-1 text-[10px] font-medium text-blue-600 dark:text-blue-400">
        <UserCheck className="h-3 w-3" aria-hidden="true" />
        corectat manual
      </span>
    );
  }
  if (field.source === "EMPTY" || field.value === null) {
    return <span className="text-[10px] text-gray-400 dark:text-gray-500">lipsă</span>;
  }
  if (field.source === "DERIVED") {
    // Nu a citit-o nimeni de pe document: a calculat-o o regulă (ADR-008).
    return (
      <span className="flex items-center gap-1 text-[10px] font-medium text-gray-500 dark:text-gray-400">
        <Calculator className="h-3 w-3" aria-hidden="true" />
        dedus
      </span>
    );
  }
  const percent = field.confidence !== null ? Math.round(field.confidence * 100) : null;
  // `OCR` înseamnă citit de pe document — o regulă a găsit valoarea lângă eticheta
  // ei. `AI` înseamnă propus de un model. Badge-ul „AI 95%" pe o valoare pe care
  // niciun model nu a produs-o ar fi exact minciuna pe care ecranul ăsta promite
  // să nu o spună (§22); până acum o spunea, pentru că orice provenienţă care nu
  // era MANUAL, EMPTY sau DERIVED ajungea aici.
  const readFromDocument = field.source === "OCR";
  return (
    <span
      className={cn(
        "flex items-center gap-1 text-[10px] font-medium",
        percent !== null && percent < 70
          ? "text-red-600 dark:text-red-400"
          : percent !== null && percent < 90
            ? "text-amber-600 dark:text-amber-400"
            : "text-gray-400 dark:text-gray-500",
      )}
      title={
        readFromDocument
          ? "Valoare citită din textul documentului, lângă eticheta ei"
          : "Valoare propusă de model"
      }
    >
      {readFromDocument ? (
        <ScanLine className="h-3 w-3" aria-hidden="true" />
      ) : (
        <Sparkles className="h-3 w-3" aria-hidden="true" />
      )}
      {readFromDocument ? "citit" : "AI"} {percent !== null ? `${percent}%` : ""}
    </span>
  );
}

/**
 * Ecranul „coada de verificare".
 *
 * Nu este o listă: deschide direct cel mai vechi document care așteaptă un om.
 * Ordinea o dă serverul — documentul uitat la coadă este exact cel care blochează
 * o declarație.
 */
export function ReviewQueuePage() {
  const navigate = useNavigate();
  const { data: next, isLoading, error } = useNextReviewDocument();

  if (isLoading) return <LoadingState label="Se caută următorul document…" />;
  if (error) return <ErrorState error={error} />;

  return (
    <div className="flex min-h-[50vh] items-center justify-center">
      <div className="max-w-md rounded-xl border border-gray-200 bg-white p-8 text-center shadow-sm dark:border-gray-800 dark:bg-gray-900">
        {next ? (
          <>
            <div className="mx-auto mb-3 grid h-11 w-11 place-content-center rounded-lg bg-blue-50 text-blue-600 dark:bg-blue-900/20 dark:text-blue-400">
              <Inbox className="h-5 w-5" aria-hidden="true" />
            </div>
            <p className="mb-4 text-sm text-gray-600 dark:text-gray-400">
              Următorul document care așteaptă verificare:
              <br />
              <span className="font-medium text-gray-900 dark:text-gray-100">
                {next.storedFilename ?? next.originalFilename}
              </span>
            </p>
            <button
              type="button"
              onClick={() => navigate(`/documente/verificare/${next.id}`)}
              className="h-10 rounded-lg bg-blue-600 px-4 text-sm font-medium text-white transition-colors hover:bg-blue-700"
            >
              Deschide pentru verificare
            </button>
          </>
        ) : (
          <>
            <div className="mx-auto mb-3 grid h-11 w-11 place-content-center rounded-lg bg-green-50 text-green-600 dark:bg-green-900/20 dark:text-green-400">
              <CircleCheck className="h-5 w-5" aria-hidden="true" />
            </div>
            <p className="text-sm text-gray-600 dark:text-gray-400">
              Nu mai este niciun document în așteptare. Alege unul din listă dacă vrei să
              revii asupra lui.
            </p>
          </>
        )}
      </div>
    </div>
  );
}
