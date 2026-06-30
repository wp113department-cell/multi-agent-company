import type { TaskStatus } from "@gridiron/shared-types";

/**
 * Valid next states per current state. Pure logic, no I/O — unit tested directly
 * per 20_Testing_Strategy.md ("Zod schema validation, Policy Engine rule matching,
 * Context Builder assembly logic" as the kind of business logic that gets unit tests).
 *
 * Encodes the Stage 1 + Stage 2-lite lifecycle from 06_Agent_SDK_Specification.md
 * (created → planning → coding → testing → blocked|completed|failed), with
 * `ready_for_review` as the human checkpoint before coding starts (plan review)
 * and again before a patch is merged (diff review) — see shared-types/src/dev-task.ts.
 */
const TRANSITIONS: Record<TaskStatus, TaskStatus[]> = {
  pending: ["planning", "blocked"],
  planning: ["ready_for_review", "blocked", "failed"],
  ready_for_review: ["coding", "completed", "rejected", "blocked"],
  rejected: ["planning", "blocked"],
  coding: ["testing", "blocked", "failed"],
  testing: ["ready_for_review", "coding", "blocked", "failed"],
  blocked: ["planning", "coding", "failed"],
  completed: [],
  failed: [],
};

export function isValidTransition(from: TaskStatus, to: TaskStatus): boolean {
  if (from === to) return true;
  return TRANSITIONS[from].includes(to);
}

export function nextValidStatuses(from: TaskStatus): TaskStatus[] {
  return TRANSITIONS[from];
}

export class InvalidTransitionError extends Error {
  constructor(from: TaskStatus, to: TaskStatus) {
    super(`Invalid task status transition: ${from} -> ${to}`);
    this.name = "InvalidTransitionError";
  }
}

export function assertValidTransition(from: TaskStatus, to: TaskStatus): void {
  if (!isValidTransition(from, to)) {
    throw new InvalidTransitionError(from, to);
  }
}
