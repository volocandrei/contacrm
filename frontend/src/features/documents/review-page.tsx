import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  ArrowRight,
  CircleAlert,
  CircleCheck,
  Copy,
  History,
  RefreshCw,
  Save,
  Sparkles,
  TriangleAlert,
  UserCheck,
  X,
} from "lucide-react";
import { ApiError } from "@/api/types";
import {
  useApproveDocument,
  useAssignClient,
  useClients,
  useDocument,
  useDocumentTypes,
  useMarkDuplicate,
  useRejectDocument,
  useReprocessDocument,
  useUpdateDocumentFields,
} from "@/api/hooks";
import { ErrorState, LoadingState, Panel } from "@/components/page";
import { ConfidenceBadge, DocumentStatusBadge } from "@/components/status-badge";
import { DocumentPreview } from "@/features/documents/document-preview";
import { useHasPermission } from "@/features/auth/use-auth";
import { formatDateTime, formatFileSize } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { DocumentDetail, DocumentFieldName, ExtractedField } from "@/types/domain";

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
  { name: "referenceMonth", label: "Perioadă de referință" },
];

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

  const canWrite = useHasPermission("documents:write");
  const canApprove = useHasPermission("documents:approve");

  const { data: documentTypes } = useDocumentTypes();
  const { data: clientsPage } = useClients({ pageSize: 200, status: "ACTIVE" });

  const updateFields = useUpdateDocumentFields(document.id);
  const approve = useApproveDocument();
  const reject = useRejectDocument();
  const markDuplicate = useMarkDuplicate();
  const reprocess = useReprocessDocument();
  const assignClient = useAssignClient();

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

  async function handleSave() {
    if (!isDirty) return;
    try {
      await updateFields.mutateAsync(
        dirtyFields.map((name) => ({ field: name, value: draft[name] || null })),
      );
      setDraft({});
      setFeedback({ tone: "ok", message: "Modificările au fost salvate." });
    } catch (caught) {
      setFeedback({ tone: "error", message: describeError(caught) });
    }
  }

  async function handleApprove() {
    try {
      if (isDirty) {
        await updateFields.mutateAsync(
          dirtyFields.map((name) => ({ field: name, value: draft[name] || null })),
        );
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

  // Scurtături de tastatură — operatorul trebuie să treacă rapid prin sute de documente (§67).
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (!event.altKey) return;
      const key = event.key.toLowerCase();
      if (key === "s" && canWrite) {
        event.preventDefault();
        void handleSave();
      } else if (key === "a" && canApprove) {
        event.preventDefault();
        void handleApprove();
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  });

  const busy =
    updateFields.isPending || approve.isPending || reject.isPending || markDuplicate.isPending;

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
        <Link
          to="/documente/verificare"
          className="flex h-9 items-center gap-1.5 rounded-lg border border-gray-200 px-3 text-sm font-medium text-gray-600 transition-colors hover:bg-gray-50 dark:border-gray-700 dark:text-gray-300 dark:hover:bg-gray-800"
        >
          <X className="h-4 w-4" aria-hidden="true" />
          Închide
        </Link>
      </div>

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
          {!document.clientId && (
            <Panel title="Atribuie client">
              <p className="mb-3 text-xs text-gray-500 dark:text-gray-400">
                Expeditorul nu a putut fi mapat automat. Alege clientul căruia îi aparține documentul.
              </p>
              <select
                defaultValue=""
                disabled={!canWrite || busy}
                onChange={(event) => {
                  if (!event.target.value) return;
                  void assignClient.mutateAsync({ id: document.id, clientId: event.target.value });
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
                {document.extraction.provider} · {document.extraction.promptVersion}
              </span>
            }
          >
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
              {canApprove && (
                <button
                  type="button"
                  onClick={handleApprove}
                  disabled={busy}
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

            <div className="mt-2 flex flex-wrap gap-2">
              {canApprove && (
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
              {canWrite && (
                <>
                  <button
                    type="button"
                    onClick={() =>
                      void markDuplicate.mutateAsync({ id: document.id, duplicateOfId: null })
                    }
                    disabled={busy}
                    className="flex h-9 items-center gap-1.5 rounded-lg border border-gray-200 px-3 text-sm text-gray-600 transition-colors hover:bg-gray-50 disabled:opacity-50 dark:border-gray-700 dark:text-gray-300 dark:hover:bg-gray-800"
                  >
                    <Copy className="h-4 w-4" aria-hidden="true" />
                    Duplicat
                  </button>
                  <button
                    type="button"
                    onClick={() => void reprocess.mutateAsync(document.id)}
                    disabled={busy}
                    className="flex h-9 items-center gap-1.5 rounded-lg border border-gray-200 px-3 text-sm text-gray-600 transition-colors hover:bg-gray-50 disabled:opacity-50 dark:border-gray-700 dark:text-gray-300 dark:hover:bg-gray-800"
                  >
                    <RefreshCw className="h-4 w-4" aria-hidden="true" />
                    Reprocesează
                  </button>
                </>
              )}
            </div>

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
  const percent = field.confidence !== null ? Math.round(field.confidence * 100) : null;
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
    >
      <Sparkles className="h-3 w-3" aria-hidden="true" />
      AI {percent !== null ? `${percent}%` : ""}
    </span>
  );
}

function describeError(error: unknown): string {
  if (error instanceof ApiError) {
    const details = error.details ? Object.values(error.details).flat() : [];
    return details.length > 0 ? `${error.message} ${details.join(" ")}` : error.message;
  }
  return error instanceof Error ? error.message : "Eroare neașteptată.";
}

/** Ecranul „coada de verificare" — deschide primul document care așteaptă. */
export function ReviewQueuePage() {
  return (
    <div className="flex min-h-[50vh] items-center justify-center">
      <div className="max-w-md rounded-xl border border-gray-200 bg-white p-8 text-center shadow-sm dark:border-gray-800 dark:bg-gray-900">
        <div className="mx-auto mb-3 grid h-11 w-11 place-content-center rounded-lg bg-blue-50 text-blue-600 dark:bg-blue-900/20 dark:text-blue-400">
          <ArrowRight className="h-5 w-5" aria-hidden="true" />
        </div>
        <p className="text-sm text-gray-600 dark:text-gray-400">
          Alege un document din listă pentru a începe verificarea.
        </p>
      </div>
    </div>
  );
}
