import { cn } from "@/lib/utils";
import type { ClientStatus, DocumentStatus, PeriodStatus } from "@/types/domain";

type Tone = "neutral" | "info" | "warning" | "success" | "danger" | "muted";

const TONE_CLASS: Record<Tone, string> = {
  neutral:
    "bg-slate-100 text-slate-700 ring-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:ring-slate-700",
  info: "bg-blue-50 text-blue-700 ring-blue-200 dark:bg-blue-900/30 dark:text-blue-300 dark:ring-blue-800",
  warning:
    "bg-amber-50 text-amber-700 ring-amber-200 dark:bg-amber-900/30 dark:text-amber-300 dark:ring-amber-800",
  success:
    "bg-green-50 text-green-700 ring-green-200 dark:bg-green-900/30 dark:text-green-300 dark:ring-green-800",
  danger:
    "bg-red-50 text-red-700 ring-red-200 dark:bg-red-900/30 dark:text-red-300 dark:ring-red-800",
  muted:
    "bg-slate-50 text-slate-500 ring-slate-200 dark:bg-slate-900 dark:text-slate-400 dark:ring-slate-800",
};

const DOCUMENT_STATUS_META: Record<DocumentStatus, { label: string; tone: Tone }> = {
  RECEIVED: { label: "Recepționat", tone: "neutral" },
  PROCESSING: { label: "În procesare", tone: "info" },
  REVIEW_REQUIRED: { label: "Necesită verificare", tone: "warning" },
  APPROVED: { label: "Aprobat", tone: "success" },
  ARCHIVED: { label: "Arhivat", tone: "success" },
  ERROR: { label: "Eroare", tone: "danger" },
  DUPLICATE: { label: "Duplicat", tone: "warning" },
  REJECTED: { label: "Respins", tone: "danger" },
  UNMATCHED: { label: "Client neidentificat", tone: "danger" },
};

const PERIOD_STATUS_META: Record<PeriodStatus, { label: string; tone: Tone }> = {
  NOT_STARTED: { label: "Neînceput", tone: "muted" },
  COLLECTING: { label: "În colectare", tone: "info" },
  PARTIAL: { label: "Parțial", tone: "warning" },
  COMPLETE: { label: "Documente complete", tone: "success" },
  PROCESSING: { label: "În procesare", tone: "info" },
  REVIEW: { label: "Verificare", tone: "warning" },
  FINALIZED: { label: "Finalizat", tone: "success" },
};

const CLIENT_STATUS_META: Record<ClientStatus, { label: string; tone: Tone }> = {
  ACTIVE: { label: "Activ", tone: "success" },
  INACTIVE: { label: "Inactiv", tone: "muted" },
  PROSPECT: { label: "Prospect", tone: "info" },
  SUSPENDED: { label: "Suspendat", tone: "danger" },
};

const base =
  "inline-flex items-center whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset";

export function DocumentStatusBadge({ status }: { status: DocumentStatus }) {
  const meta = DOCUMENT_STATUS_META[status];
  return <span className={cn(base, TONE_CLASS[meta.tone])}>{meta.label}</span>;
}

export function PeriodStatusBadge({ status }: { status: PeriodStatus }) {
  const meta = PERIOD_STATUS_META[status];
  return <span className={cn(base, TONE_CLASS[meta.tone])}>{meta.label}</span>;
}

export function ClientStatusBadge({ status }: { status: ClientStatus }) {
  const meta = CLIENT_STATUS_META[status];
  return <span className={cn(base, TONE_CLASS[meta.tone])}>{meta.label}</span>;
}

/**
 * Încrederea extracției. Pragurile sunt configurabile în backend (§16) —
 * aici sunt doar valorile implicite pentru afișare.
 */
export function ConfidenceBadge({
  confidence,
  autoThreshold = 0.9,
  reviewThreshold = 0.7,
}: {
  confidence: number | null;
  autoThreshold?: number;
  reviewThreshold?: number;
}) {
  if (confidence === null) {
    return <span className={cn(base, TONE_CLASS.muted)}>—</span>;
  }
  const tone: Tone =
    confidence >= autoThreshold ? "success" : confidence >= reviewThreshold ? "warning" : "danger";
  return <span className={cn(base, TONE_CLASS[tone])}>{Math.round(confidence * 100)}%</span>;
}
