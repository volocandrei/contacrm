import { Link } from "react-router-dom";
import { useTasks, useUpdateTaskStatus } from "@/api/hooks";
import { ErrorState, LoadingState, PageHeader, Panel } from "@/components/page";
import { useHasPermission } from "@/features/auth/use-auth";
import { formatDate } from "@/lib/format";
import { cn } from "@/lib/utils";
import { TASK_STATUS, type Task, type TaskPriority, type TaskStatus } from "@/types/domain";

const STATUS_LABEL: Record<TaskStatus, string> = {
  TODO: "De făcut",
  IN_PROGRESS: "În lucru",
  BLOCKED: "Blocat",
  DONE: "Finalizat",
};

const PRIORITY_META: Record<TaskPriority, { label: string; className: string }> = {
  LOW: { label: "Scăzută", className: "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-300" },
  NORMAL: { label: "Normală", className: "bg-blue-50 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300" },
  HIGH: {
    label: "Ridicată",
    className: "bg-amber-50 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300",
  },
  URGENT: { label: "Urgentă", className: "bg-red-50 text-red-700 dark:bg-red-900/30 dark:text-red-300" },
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
            action={
              <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-600 dark:bg-gray-800 dark:text-gray-300">
                {column.tasks.length}
              </span>
            }
          >
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
                <li className="py-4 text-center text-xs text-gray-400 dark:text-gray-500">
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
    <li className="rounded-lg border border-gray-200 p-3 dark:border-gray-800">
      <div className="mb-1.5 flex items-start justify-between gap-2">
        <p className="text-sm font-medium text-gray-900 dark:text-gray-100">{task.title}</p>
        <span className={cn("rounded-full px-2 py-0.5 text-[10px] font-medium", priority.className)}>
          {priority.label}
        </span>
      </div>

      {task.clientId && (
        <Link
          to={`/crm/clienti/${task.clientId}`}
          className="text-xs text-blue-600 hover:underline dark:text-blue-400"
        >
          {task.clientName}
        </Link>
      )}

      <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
        {task.assignedToName ?? "Nealocat"}
        {task.dueDate && ` · termen ${formatDate(task.dueDate)}`}
      </p>

      {canWrite && (
        <label className="mt-2 block">
          <span className="sr-only">Schimbă statusul sarcinii {task.title}</span>
          <select
            value={task.status}
            onChange={(event) => onStatusChange(event.target.value as TaskStatus)}
            className="h-8 w-full cursor-pointer rounded-md border border-gray-200 bg-white px-2 text-xs dark:border-gray-700 dark:bg-gray-950 dark:text-gray-100"
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
