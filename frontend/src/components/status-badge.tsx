import {
  CLIENT_STATUS_LABEL,
  DOCUMENT_STATUS_LABEL,
  PERIOD_STATUS_LABEL,
} from "@/lib/labels";
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

// Doar tonul stă aici: eticheta vine din `lib/labels.ts`, ca legenda unui grafic
// și insigna de lângă ea să nu poată spune două lucruri diferite.
const DOCUMENT_STATUS_TONE: Record<DocumentStatus, Tone> = {
  RECEIVED: "neutral",
  PROCESSING: "info",
  REVIEW_REQUIRED: "warning",
  APPROVED: "success",
  ARCHIVED: "success",
  ERROR: "danger",
  DUPLICATE: "warning",
  REJECTED: "danger",
  UNMATCHED: "danger",
};

const PERIOD_STATUS_TONE: Record<PeriodStatus, Tone> = {
  NOT_STARTED: "muted",
  COLLECTING: "info",
  PARTIAL: "warning",
  COMPLETE: "success",
  PROCESSING: "info",
  REVIEW: "warning",
  FINALIZED: "success",
};

const CLIENT_STATUS_TONE: Record<ClientStatus, Tone> = {
  ACTIVE: "success",
  INACTIVE: "muted",
  PROSPECT: "info",
  SUSPENDED: "danger",
};

const base =
  "inline-flex items-center whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset";

export function DocumentStatusBadge({ status }: { status: DocumentStatus }) {
  return (
    <span className={cn(base, TONE_CLASS[DOCUMENT_STATUS_TONE[status]])}>
      {DOCUMENT_STATUS_LABEL[status]}
    </span>
  );
}

export function PeriodStatusBadge({ status }: { status: PeriodStatus }) {
  return (
    <span className={cn(base, TONE_CLASS[PERIOD_STATUS_TONE[status]])}>
      {PERIOD_STATUS_LABEL[status]}
    </span>
  );
}

export function ClientStatusBadge({ status }: { status: ClientStatus }) {
  return (
    <span className={cn(base, TONE_CLASS[CLIENT_STATUS_TONE[status]])}>
      {CLIENT_STATUS_LABEL[status]}
    </span>
  );
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
