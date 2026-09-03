import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { CircleCheck, Copy, FileStack, RefreshCw, ShieldCheck, X } from "lucide-react";
import { useBulkDocuments, useClients, useDocumentTypes, useDocuments } from "@/api/hooks";
import type { BulkPayload, BulkResult } from "@/api/endpoints";
import { MonthFilter, Pagination, SearchInput, SelectFilter } from "@/components/form-controls";
import { EmptyState, ErrorState, LoadingState, PageHeader, Panel } from "@/components/page";
import { ConfidenceBadge, DocumentStatusBadge } from "@/components/status-badge";
import { useFilterParams } from "@/hooks/use-filter-params";
import { useHasPermission } from "@/features/auth/use-auth";
import { UploadPanel } from "@/features/documents/upload-panel";
import { formatDate, formatDateTime, formatMoney } from "@/lib/format";
import { cn } from "@/lib/utils";
import { DOCUMENT_SOURCE, DOCUMENT_STATUS, type DocumentSource } from "@/types/domain";

export type DocumentsPreset = "inbox" | "processing" | "review" | "archive" | "all";

const PRESET_STATUS: Record<DocumentsPreset, string> = {
  inbox: "RECEIVED,PROCESSING,REVIEW_REQUIRED,UNMATCHED,ERROR,DUPLICATE",
  processing: "RECEIVED,PROCESSING",
  review: "REVIEW_REQUIRED,UNMATCHED",
  archive: "ARCHIVED,APPROVED",
  all: "",
};

const STATUS_LABEL: Record<string, string> = {
  RECEIVED: "Recepționat",
  PROCESSING: "În procesare",
  REVIEW_REQUIRED: "Necesită verificare",
  APPROVED: "Aprobat",
  ARCHIVED: "Arhivat",
  ERROR: "Eroare",
  DUPLICATE: "Duplicat",
  REJECTED: "Respins",
  UNMATCHED: "Client neidentificat",
};

const SOURCE_LABEL: Record<DocumentSource, string> = {
  EMAIL: "Email",
  WHATSAPP: "WhatsApp",
  UPLOAD: "Încărcare",
  API: "API",
};

const CONFIDENCE_OPTIONS = [
  { value: "high", label: "Peste 90%" },
  { value: "medium", label: "70–89%" },
  { value: "low", label: "Sub 70%" },
];

const DEFAULTS = {
  q: "",
  clientId: "",
  status: "",
  source: "",
  type: "",
  referenceMonth: "",
  confidence: "",
  duplicatesOnly: "",
  page: "1",
};

export function DocumentsPage({
  preset,
  title,
  description,
}: {
  preset: DocumentsPreset;
  title: string;
  description: string;
}) {
  const { values, setValue, reset, activeCount } = useFilterParams(DEFAULTS);
  const [selected, setSelected] = useState<string[]>([]);
  const [bulkResult, setBulkResult] = useState<BulkResult | null>(null);

  const canWrite = useHasPermission("documents:write");
  const canApprove = useHasPermission("documents:approve");

  const { data: clientsPage } = useClients({ pageSize: 200 });
  const { data: documentTypes } = useDocumentTypes();
  const bulk = useBulkDocuments();

  const confidenceRange = useMemo(() => {
    if (values.confidence === "high") return { minConfidence: "0.9" };
    if (values.confidence === "medium") return { minConfidence: "0.7", maxConfidence: "0.8999" };
    if (values.confidence === "low") return { maxConfidence: "0.6999" };
    return {};
  }, [values.confidence]);

  const queryParams = {
    q: values.q,
    clientId: values.clientId,
    status: values.status || PRESET_STATUS[preset],
    source: values.source,
    type: values.type,
    referenceMonth: values.referenceMonth,
    duplicatesOnly: values.duplicatesOnly,
    ...confidenceRange,
    page: Number(values.page) || 1,
    pageSize: 25,
  };

  const { data, isLoading, error, isFetching } = useDocuments(queryParams);
  const items = data?.items ?? [];

  const allSelected = items.length > 0 && items.every((item) => selected.includes(item.id));

  function toggleAll() {
    setSelected(allSelected ? [] : items.map((item) => item.id));
  }

  function toggleOne(id: string) {
    setSelected((current) =>
      current.includes(id) ? current.filter((value) => value !== id) : [...current, id],
    );
  }

  async function runBulk(payload: BulkPayload) {
    const result = await bulk.mutateAsync({ ids: selected, payload });
    setBulkResult(result);
    setSelected([]);
  }

  const statusOptions = (values.status || PRESET_STATUS[preset] || DOCUMENT_STATUS.join(","))
    .split(",")
    .filter(Boolean);

  return (
    <div>
      <PageHeader
        title={title}
        description={description}
        actions={
          activeCount > 0 ? (
            <button
              type="button"
              onClick={reset}
              className="flex h-9 items-center gap-1.5 rounded-lg border border-gray-200 px-3 text-sm font-medium text-gray-600 transition-colors hover:bg-gray-50 dark:border-gray-700 dark:text-gray-300 dark:hover:bg-gray-800"
            >
              <X className="h-4 w-4" aria-hidden="true" />
              Șterge filtrele ({activeCount})
            </button>
          ) : undefined
        }
      />

      {/* Singurul drum prin care un document intră azi: email și WhatsApp sunt
          Faza 2. Stă pe inbox, pentru că acolo ajunge oricum după încărcare. */}
      {preset === "inbox" && canWrite && <UploadPanel />}

      {/* Filtre (§25) */}
      <div className="mb-4 grid grid-cols-2 gap-2 md:grid-cols-3 xl:grid-cols-7">
        <SearchInput
          label="Caută documente"
          value={values.q}
          onChange={(value) => setValue("q", value)}
          placeholder="Fișier, furnizor, număr…"
          className="col-span-2 xl:col-span-2"
        />
        <SelectFilter
          label="Client"
          allLabel="Toți clienții"
          value={values.clientId}
          onChange={(value) => setValue("clientId", value)}
          options={(clientsPage?.items ?? []).map((client) => ({
            value: client.id,
            label: client.name,
          }))}
        />
        <SelectFilter
          label="Status"
          allLabel="Toate statusurile"
          value={values.status}
          onChange={(value) => setValue("status", value)}
          options={statusOptions.map((status) => ({
            value: status,
            label: STATUS_LABEL[status] ?? status,
          }))}
        />
        <SelectFilter
          label="Tip document"
          allLabel="Toate tipurile"
          value={values.type}
          onChange={(value) => setValue("type", value)}
          options={(documentTypes ?? []).map((type) => ({ value: type.code, label: type.label }))}
        />
        <SelectFilter
          label="Sursă"
          allLabel="Toate sursele"
          value={values.source}
          onChange={(value) => setValue("source", value)}
          options={DOCUMENT_SOURCE.map((source) => ({ value: source, label: SOURCE_LABEL[source] }))}
        />
        <MonthFilter
          label="Perioadă"
          value={values.referenceMonth}
          onChange={(value) => setValue("referenceMonth", value)}
        />
        <SelectFilter
          label="Încredere"
          allLabel="Orice încredere"
          value={values.confidence}
          onChange={(value) => setValue("confidence", value)}
          options={CONFIDENCE_OPTIONS}
        />
      </div>

      {/* Acțiuni în masă (§60) */}
      {selected.length > 0 && (
        <div className="mb-3 flex flex-wrap items-center gap-2 rounded-lg border border-blue-200 bg-blue-50 px-4 py-2.5 text-sm dark:border-blue-900 dark:bg-blue-900/20">
          <span className="font-medium text-blue-900 dark:text-blue-200">
            {selected.length} selectate
          </span>
          <div className="ml-auto flex flex-wrap gap-2">
            {canApprove && (
              <BulkButton
                icon={CircleCheck}
                label="Aprobă"
                disabled={bulk.isPending}
                onClick={() => runBulk({ action: "approve" })}
              />
            )}
            {canWrite && (
              <>
                <BulkButton
                  icon={Copy}
                  label="Marchează duplicat"
                  disabled={bulk.isPending}
                  onClick={() => runBulk({ action: "markDuplicate" })}
                />
                <BulkButton
                  icon={RefreshCw}
                  label="Reprocesează"
                  disabled={bulk.isPending}
                  onClick={() => runBulk({ action: "reprocess" })}
                />
              </>
            )}
            <BulkButton icon={X} label="Anulează" onClick={() => setSelected([])} />
          </div>
        </div>
      )}

      {bulkResult && (
        <div
          role="status"
          className="mb-3 rounded-lg border border-gray-200 bg-white px-4 py-3 text-sm dark:border-gray-800 dark:bg-gray-900"
        >
          <div className="flex items-center justify-between gap-3">
            <p className="text-gray-700 dark:text-gray-300">
              {bulkResult.succeeded.length} reușite, {bulkResult.failed.length} eșuate.
            </p>
            <button
              type="button"
              onClick={() => setBulkResult(null)}
              className="text-xs font-medium text-gray-500 hover:text-gray-800 dark:hover:text-gray-200"
            >
              Închide
            </button>
          </div>
          {bulkResult.failed.length > 0 && (
            <ul className="mt-2 space-y-0.5 text-xs text-red-600 dark:text-red-400">
              {bulkResult.failed.slice(0, 5).map((failure) => (
                <li key={failure.id}>
                  {failure.id}: {failure.message}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <Panel bodyClassName="p-0" className={cn(isFetching && "opacity-70 transition-opacity")}>
        {isLoading ? (
          <LoadingState />
        ) : error ? (
          <ErrorState error={error} />
        ) : items.length === 0 ? (
          <EmptyState
            title="Niciun document"
            description="Modifică filtrele sau așteaptă documente noi din email/WhatsApp."
          />
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="border-b border-gray-200 text-xs tracking-wide text-gray-500 uppercase dark:border-gray-800 dark:text-gray-400">
                  <tr>
                    <th scope="col" className="w-10 px-4 py-3">
                      <input
                        type="checkbox"
                        checked={allSelected}
                        onChange={toggleAll}
                        aria-label="Selectează toate documentele de pe pagină"
                        className="h-4 w-4 cursor-pointer rounded border-gray-300 accent-blue-600"
                      />
                    </th>
                    <th scope="col" className="px-4 py-3 font-medium">Document</th>
                    <th scope="col" className="px-4 py-3 font-medium">Client</th>
                    <th scope="col" className="px-4 py-3 font-medium">Furnizor / Număr</th>
                    <th scope="col" className="px-4 py-3 font-medium">Dată</th>
                    <th scope="col" className="px-4 py-3 font-medium">Total</th>
                    <th scope="col" className="px-4 py-3 font-medium">Sursă</th>
                    <th scope="col" className="px-4 py-3 font-medium">Status</th>
                    <th scope="col" className="px-4 py-3 font-medium">Încredere</th>
                    <th scope="col" className="px-4 py-3 font-medium">Acțiune</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                  {items.map((doc) => (
                    <tr
                      key={doc.id}
                      className={cn(
                        "transition-colors hover:bg-gray-50 dark:hover:bg-gray-800/60",
                        selected.includes(doc.id) && "bg-blue-50/60 dark:bg-blue-900/10",
                      )}
                    >
                      <td className="px-4 py-3">
                        <input
                          type="checkbox"
                          checked={selected.includes(doc.id)}
                          onChange={() => toggleOne(doc.id)}
                          aria-label={`Selectează ${doc.originalFilename}`}
                          className="h-4 w-4 cursor-pointer rounded border-gray-300 accent-blue-600"
                        />
                      </td>
                      <td className="px-4 py-3">
                        <div className="max-w-56 truncate font-medium text-gray-900 dark:text-gray-100">
                          {doc.storedFilename ?? doc.originalFilename}
                        </div>
                        <div className="text-xs text-gray-500 dark:text-gray-400">
                          {doc.documentTypeLabel ?? "Tip neidentificat"} ·{" "}
                          {formatDateTime(doc.receivedAt)}
                        </div>
                      </td>
                      <td className="px-4 py-3 text-gray-700 dark:text-gray-300">
                        {doc.clientId ? (
                          <Link
                            to={`/crm/clienti/${doc.clientId}`}
                            className="hover:text-blue-600 hover:underline dark:hover:text-blue-400"
                          >
                            {doc.clientName}
                          </Link>
                        ) : (
                          <span className="text-red-600 dark:text-red-400">Neidentificat</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-gray-600 dark:text-gray-400">
                        <div className="max-w-44 truncate">{doc.supplierName ?? "—"}</div>
                        <div className="text-xs">{doc.documentNumber ?? "—"}</div>
                      </td>
                      <td className="px-4 py-3 whitespace-nowrap text-gray-600 dark:text-gray-400">
                        {doc.documentDate ? formatDate(doc.documentDate) : "—"}
                      </td>
                      <td className="px-4 py-3 whitespace-nowrap text-gray-900 dark:text-gray-100">
                        {doc.totalAmount ? formatMoney(doc.totalAmount, doc.currency ?? "RON") : "—"}
                      </td>
                      <td className="px-4 py-3 text-gray-600 dark:text-gray-400">
                        {SOURCE_LABEL[doc.source]}
                      </td>
                      <td className="px-4 py-3">
                        <DocumentStatusBadge status={doc.status} />
                      </td>
                      <td className="px-4 py-3">
                        <ConfidenceBadge confidence={doc.confidence} />
                      </td>
                      <td className="px-4 py-3">
                        <Link
                          to={`/documente/verificare/${doc.id}`}
                          className="text-sm font-medium text-blue-600 hover:text-blue-700 dark:text-blue-400"
                        >
                          {doc.status === "REVIEW_REQUIRED" || doc.status === "UNMATCHED"
                            ? "Verifică"
                            : "Deschide"}
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {data && (
              <Pagination
                page={data.page}
                totalPages={data.totalPages}
                total={data.total}
                pageSize={data.pageSize}
                onPageChange={(page) => setValue("page", String(page))}
              />
            )}
          </>
        )}
      </Panel>
    </div>
  );
}

function BulkButton({
  icon: Icon,
  label,
  onClick,
  disabled,
}: {
  icon: typeof FileStack;
  label: string;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="flex h-8 items-center gap-1.5 rounded-md bg-white px-2.5 text-xs font-medium text-gray-700 ring-1 ring-gray-200 transition-colors hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-gray-900 dark:text-gray-200 dark:ring-gray-700 dark:hover:bg-gray-800"
    >
      <Icon className="h-3.5 w-3.5" aria-hidden="true" />
      {label}
    </button>
  );
}

export function ReviewQueueBanner({ count }: { count: number }) {
  if (count === 0) return null;
  return (
    <div className="mb-4 flex items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 px-4 py-2.5 text-sm text-amber-800 dark:border-amber-800 dark:bg-amber-900/20 dark:text-amber-200">
      <ShieldCheck className="h-4 w-4" aria-hidden="true" />
      {count} documente așteaptă verificare.
    </div>
  );
}
