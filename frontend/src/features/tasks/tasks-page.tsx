import { Link } from "react-router-dom";
import { CalendarClock, User } from "lucide-react";
import { useTasks, useUpdateTaskStatus } from "@/api/hooks";
import { ErrorState, LoadingState, PageHeader, Panel } from "@/components/page";
import { useHasPermission } from "@/features/auth/use-auth";
import { formatDate } from "@/lib/format";
import { pillClass, type Tone } from "@/lib/ui";
import { cn } from "@/lib/utils";
import { TASK_STATUS, type Task, type TaskPriority, type TaskStatus } from "@/types/domain";

const STATUS_LABEL: Record<TaskStatus, string> = {
  TODO: "De făcut",
  IN_PROGRESS: "În lucru",
  BLOCKED: "Blocat",
  DONE: "Finalizat",
};

const PRIORITY_META: Record<TaskPriority, { label: string; tone: Tone }> = {
  LOW: { label: "Scăzută", tone: "slate" },
  NORMAL: { label: "Normală", tone: "blue" },
  HIGH: { label: "Ridicată", tone: "amber" },
  URGENT: { label: "Urgentă", tone: "red" },
};

/**
 * Banda de sus a coloanei.
 *
 * Patru panouri identice ca formă și culoare se citeau ca patru liste
 * oarecare. Culoarea spune ce înseamnă coloana înainte de a citi titlul: albastru
 * lucrează, chihlimbariu așteaptă ceva, verde s-a terminat.
 */
const COLUMN_ACCENT: Record<TaskStatus, string> = {
  TODO: "bg-slate-300 dark:bg-slate-600",
  IN_PROGRESS: "bg-blue-500",
  BLOCKED: "bg-amber-500",
  DONE: "bg-emerald-500",
};

export function TasksPage() {
  const { data, isLoading, error } = useTasks({});
  const canWrite = useHasPermission("tasks:write");
  const updateStatus = useUpdateTaskStatus();

  if (isLoading) return <LoadingState />;
  if (error) return <ErrorState error={error} />;

  const columns = TASK_STATUS.map((status) => ({
    status,
    tasks: (data ?? []).filter((task) => task.status === status),
  }));

  return (
    <div>
      <PageHeader title="Sarcini" description="Activitățile interne ale echipei" />

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
        {columns.map((column) => (
          <Panel
            key={column.status}
            title={STATUS_LABEL[column.status]}
            className="relative overflow-hidden"
            action={<span className={pillClass("slate")}>{column.tasks.length}</span>}
          >
            <span
              className={cn("absolute inset-x-0 top-0 h-1", COLUMN_ACCENT[column.status])}
              aria-hidden="true"
            />
            <ul className="space-y-3">
              {column.tasks.map((task) => (
                <TaskCard
                  key={task.id}
                  task={task}
                  canWrite={canWrite}
                  onStatusChange={(status) => updateStatus.mutate({ id: task.id, status })}
                />
              ))}
              {column.tasks.length === 0 && (
                <li className="py-4 text-center text-xs text-slate-400 dark:text-slate-500">
                  Nicio sarcină
                </li>
              )}
            </ul>
          </Panel>
        ))}
      </div>
    </div>
  );
}

function TaskCard({
  task,
  canWrite,
  onStatusChange,
}: {
  task: Task;
  canWrite: boolean;
  onStatusChange: (status: TaskStatus) => void;
}) {
  const priority = PRIORITY_META[task.priority];

  return (
    <li
      className={cn(
        "rounded-lg border border-slate-200 p-3 transition-colors hover:border-slate-300 hover:bg-slate-50 dark:border-slate-800 dark:hover:border-slate-700 dark:hover:bg-slate-800/50",
        // Urgentul se vede din capătul celălalt al ecranului. Restul nu are
        // nevoie: dacă totul strigă, nimic nu strigă.
        task.priority === "URGENT" && "border-l-2 border-l-red-500",
      )}
    >
      <div className="mb-1.5 flex items-start justify-between gap-2">
        <p className="text-sm font-medium text-slate-900 dark:text-slate-100">{task.title}</p>
        <span className={cn("shrink-0", pillClass(priority.tone))}>{priority.label}</span>
      </div>

      {task.clientId && (
        <Link
          to={`/crm/clienti/${task.clientId}`}
          className="text-xs text-blue-600 hover:underline dark:text-blue-400"
        >
          {task.clientName}
        </Link>
      )}

      <p className="mt-1 flex flex-wrap items-center gap-x-1.5 text-xs text-slate-500 dark:text-slate-400">
        <span className="inline-flex items-center gap-1">
          <User className="h-3 w-3" aria-hidden="true" />
          {task.assignedToName ?? "Nealocat"}
        </span>
        {task.dueDate && (
          <span
            className={cn(
              "inline-flex items-center gap-1",
              // Un termen trecut într-un text gri nu se vede niciodată.
              isOverdue(task) && "font-medium text-red-600 dark:text-red-400",
            )}
          >
            <CalendarClock className="h-3 w-3" aria-hidden="true" />
            {formatDate(task.dueDate)}
          </span>
        )}
      </p>

      {canWrite && (
        <label className="mt-2 block">
          <span className="sr-only">Schimbă statusul sarcinii {task.title}</span>
          <select
            value={task.status}
            onChange={(event) => onStatusChange(event.target.value as TaskStatus)}
            className="h-8 w-full cursor-pointer rounded-md border border-slate-200 bg-white px-2 text-xs dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
          >
            {TASK_STATUS.map((status) => (
              <option key={status} value={status}>
                {STATUS_LABEL[status]}
              </option>
            ))}
          </select>
        </label>
      )}
    </li>
  );
}

/** Termenul a trecut, iar sarcina nu este gata. */
function isOverdue(task: Task): boolean {
  if (!task.dueDate || task.status === "DONE") return false;
  return task.dueDate < new Date().toISOString().slice(0, 10);
}
