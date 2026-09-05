import { useState } from "react";
import { Link } from "react-router-dom";
import { CalendarClock, Plus, User } from "lucide-react";
import { useClients, useCreateTask, useTasks, useUpdateTaskStatus } from "@/api/hooks";
import { ErrorState, LoadingState, PageHeader, Panel } from "@/components/page";
import { useHasPermission } from "@/features/auth/use-auth";
import { describeError } from "@/lib/errors";
import { formatDate } from "@/lib/format";
import { buttonPrimary, buttonSecondary, inputField, pillClass, surface, type Tone } from "@/lib/ui";
import { cn } from "@/lib/utils";
import {
  TASK_PRIORITY,
  TASK_STATUS,
  type Task,
  type TaskPriority,
  type TaskStatus,
} from "@/types/domain";

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
      <PageHeader
        title="Sarcini"
        description="Activitățile interne ale echipei"
        actions={canWrite && <NewTaskButton />}
      />

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


/**
 * O sarcină nouă.
 *
 * **Ce lipsea.** Kanbanul putea muta sarcini, dar nu putea adăuga niciuna:
 * singurele existente veneau din setul de development. Un cabinet care își nota
 * „de sunat la Alfa până vineri" nu avea unde.
 *
 * Formularul cere doar titlul. Restul — clientul, colegul, termenul — se poate
 * pune, dar nu se cere: o sarcină pe care nu o poți nota în trei secunde nu se
 * notează deloc, iar una fără termen este oricum mai bună decât una uitată.
 */
function NewTaskButton() {
  const create = useCreateTask();
  const { data: clientsPage } = useClients({ pageSize: 200, status: "ACTIVE" });
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ title: "", clientId: "", dueDate: "", priority: "NORMAL" });
  const [problem, setProblem] = useState<string | null>(null);

  function submit(event: React.FormEvent) {
    event.preventDefault();
    setProblem(null);
    create.mutate(
      {
        title: form.title,
        clientId: form.clientId || null,
        dueDate: form.dueDate || null,
        priority: form.priority as Task["priority"],
      },
      {
        onSuccess: () => {
          setForm({ title: "", clientId: "", dueDate: "", priority: "NORMAL" });
          setOpen(false);
        },
        onError: (caught) => setProblem(describeError(caught)),
      },
    );
  }

  if (!open) {
    return (
      <button type="button" onClick={() => setOpen(true)} className={cn(buttonPrimary, "h-9")}>
        <Plus className="h-4 w-4" aria-hidden="true" />
        Sarcină nouă
      </button>
    );
  }

  return (
    <form onSubmit={submit} className={cn(surface, "flex flex-wrap items-end gap-2 p-3")}>
      <div>
        <label htmlFor="task-title" className="mb-1 block text-xs font-medium">
          Ce trebuie făcut
        </label>
        <input
          id="task-title"
          value={form.title}
          onChange={(event) => setForm({ ...form, title: event.target.value })}
          required
          autoFocus
          placeholder="Ex. De sunat la Alfa"
          className={cn(inputField, "w-64")}
        />
      </div>
      <div>
        <label htmlFor="task-client" className="mb-1 block text-xs font-medium">
          Client
        </label>
        <select
          id="task-client"
          value={form.clientId}
          onChange={(event) => setForm({ ...form, clientId: event.target.value })}
          className={cn(inputField, "w-48")}
        >
          <option value="">—</option>
          {clientsPage?.items.map((client) => (
            <option key={client.id} value={client.id}>
              {client.name}
            </option>
          ))}
        </select>
      </div>
      <div>
        <label htmlFor="task-due" className="mb-1 block text-xs font-medium">
          Termen
        </label>
        <input
          id="task-due"
          type="date"
          value={form.dueDate}
          onChange={(event) => setForm({ ...form, dueDate: event.target.value })}
          className={cn(inputField, "w-40")}
        />
      </div>
      <div>
        <label htmlFor="task-priority" className="mb-1 block text-xs font-medium">
          Prioritate
        </label>
        <select
          id="task-priority"
          value={form.priority}
          onChange={(event) => setForm({ ...form, priority: event.target.value })}
          className={cn(inputField, "w-32")}
        >
          {TASK_PRIORITY.map((priority) => (
            <option key={priority} value={priority}>
              {PRIORITY_META[priority].label}
            </option>
          ))}
        </select>
      </div>
      <button type="submit" disabled={create.isPending} className={cn(buttonPrimary, "h-9")}>
        Adaugă
      </button>
      <button
        type="button"
        onClick={() => setOpen(false)}
        className={cn(buttonSecondary, "h-9")}
      >
        Renunță
      </button>
      {problem && (
        <p role="alert" className="w-full text-xs text-red-600 dark:text-red-400">
          {problem}
        </p>
      )}
    </form>
  );
}
