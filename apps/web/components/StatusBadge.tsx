import type { TaskStatus } from "@gridiron/shared-types";

// Consistent color coding across every page per 15_Mission_Control_Dashboard_Specification.md
// ("amber for blocked/in-review, green for completed, red for failed").
const STYLES: Record<TaskStatus, string> = {
  pending: "bg-slate-100 text-slate-700",
  planning: "bg-blue-100 text-blue-700",
  ready_for_review: "bg-amber-100 text-amber-800",
  coding: "bg-blue-100 text-blue-700",
  testing: "bg-indigo-100 text-indigo-700",
  blocked: "bg-amber-100 text-amber-800",
  completed: "bg-green-100 text-green-700",
  failed: "bg-red-100 text-red-700",
  rejected: "bg-red-100 text-red-700",
};

export function StatusBadge({ status }: { status: TaskStatus }) {
  return (
    <span
      className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium ${STYLES[status]}`}
    >
      {status.replace(/_/g, " ")}
    </span>
  );
}
