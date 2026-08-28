import { CircleAlert, Inbox, LoaderCircle } from "lucide-react";
import { ApiError } from "@/api/types";
import { cn } from "@/lib/utils";

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: string;
  actions?: React.ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
      <div className="min-w-0">
        <h2 className="text-2xl font-bold text-gray-900 dark:text-gray-100">{title}</h2>
        {description && (
          <p className="mt-1 text-sm text-gray-600 dark:text-gray-400">{description}</p>
        )}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Panel({
  title,
  action,
  children,
  bodyClassName,
  className,
}: {
  title?: string;
  action?: React.ReactNode;
  children: React.ReactNode;
  bodyClassName?: string;
  className?: string;
}) {
  return (
    <section
      className={cn(
        "rounded-xl border border-gray-200 bg-white shadow-sm dark:border-gray-800 dark:bg-gray-900",
        className,
      )}
    >
      {title && (
        <div className="flex items-center justify-between gap-3 px-5 py-4">
          <h3 className="truncate text-base font-semibold text-gray-900 dark:text-gray-100">
            {title}
          </h3>
          {action}
        </div>
      )}
      <div className={cn(title ? "px-5 pb-5" : "p-5", bodyClassName)}>{children}</div>
    </section>
  );
}

export function LoadingState({ label = "Se încarcă…" }: { label?: string }) {
  return (
    <div
      role="status"
      className="flex items-center justify-center gap-2 py-12 text-sm text-gray-500 dark:text-gray-400"
    >
      <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden="true" />
      {label}
    </div>
  );
}

export function ErrorState({ error }: { error: unknown }) {
  const message =
    error instanceof ApiError
      ? error.message
      : error instanceof Error
        ? error.message
        : "A apărut o eroare neașteptată.";
  const details = error instanceof ApiError ? error.details : null;

  return (
    <div
      role="alert"
      className="flex flex-col items-center gap-2 rounded-lg bg-red-50 px-4 py-10 text-center text-sm text-red-700 dark:bg-red-900/20 dark:text-red-300"
    >
      <CircleAlert className="h-5 w-5" aria-hidden="true" />
      <p className="font-medium">{message}</p>
      {details && (
        <ul className="mt-1 space-y-0.5 text-xs">
          {Object.entries(details).flatMap(([field, messages]) =>
            messages.map((detail) => <li key={`${field}-${detail}`}>{detail}</li>),
          )}
        </ul>
      )}
    </div>
  );
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center gap-2 px-4 py-12 text-center">
      <div className="grid h-10 w-10 place-content-center rounded-lg bg-gray-100 text-gray-400 dark:bg-gray-800 dark:text-gray-500">
        <Inbox className="h-5 w-5" aria-hidden="true" />
      </div>
      <p className="text-sm font-medium text-gray-900 dark:text-gray-100">{title}</p>
      {description && <p className="max-w-sm text-xs text-gray-500 dark:text-gray-400">{description}</p>}
      {action}
    </div>
  );
}

/** Randează starea corectă pentru o interogare, ca ecranele să nu repete același `if`. */
export function QueryBoundary({
  isLoading,
  error,
  isEmpty,
  emptyTitle = "Niciun rezultat",
  emptyDescription,
  children,
}: {
  isLoading: boolean;
  error: unknown;
  isEmpty?: boolean;
  emptyTitle?: string;
  emptyDescription?: string;
  children: React.ReactNode;
}) {
  if (isLoading) return <LoadingState />;
  if (error) return <ErrorState error={error} />;
  if (isEmpty) return <EmptyState title={emptyTitle} description={emptyDescription} />;
  return <>{children}</>;
}
