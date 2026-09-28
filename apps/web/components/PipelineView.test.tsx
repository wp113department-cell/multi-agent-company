import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { PipelineView, type SubtaskEdit } from "./PipelineView";

// #227 (2026-09-28, GRIDIRON_PARTIAL "Take over a task / edit plan /
// reject one step and resume exactly there") — the real per-step
// edit/reject controls this item's frontend half added. Backend
// correctness (apply_subtask_edits' position-based semantics, the
// dependency-graph safety check) is covered separately in
// backend/tests/test_subtask_plan_edits.py and
// test_pipeline_approve_subtask_edits.py; this file covers the UI's own
// state management and the shape of what it reports back to the parent.

const basePipeline = {
  taskId: 1,
  stage: "awaiting_approval",
  pmBrief: null,
  architectPlan: null,
  approved: false,
  subtasks: [
    { type: "backend", title: "Add model", description: "d0" },
    { type: "backend", title: "Add endpoint", description: "d1", depends_on: [0] },
  ],
};

function renderPipeline(overrides: Partial<typeof basePipeline> = {}, onSubtaskEditsChange?: (e: SubtaskEdit[]) => void) {
  const pipeline = { ...basePipeline, ...overrides } as unknown as Parameters<typeof PipelineView>[0]["pipeline"];
  return render(<PipelineView pipeline={pipeline} onSubtaskEditsChange={onSubtaskEditsChange} />);
}

describe("PipelineView subtask edit/reject controls", () => {
  it("shows Edit/Reject buttons when awaiting approval", () => {
    renderPipeline();
    expect(screen.getAllByText("Edit").length).toBe(2);
    expect(screen.getAllByText("Reject").length).toBe(2);
  });

  it("hides Edit/Reject buttons when not awaiting approval", () => {
    renderPipeline({ stage: "done" });
    expect(screen.queryByText("Edit")).toBeNull();
    expect(screen.queryByText("Reject")).toBeNull();
  });

  it("editing a title reports a real edit entry with the right index", () => {
    const onChange = vi.fn();
    renderPipeline({}, onChange);

    fireEvent.click(screen.getAllByText("Edit")[0]);
    const titleInput = screen.getByDisplayValue("Add model");
    fireEvent.change(titleInput, { target: { value: "Add renamed model" } });

    const lastCall = onChange.mock.calls[onChange.mock.calls.length - 1][0] as SubtaskEdit[];
    expect(lastCall).toEqual([
      { index: 0, action: "edit", title: "Add renamed model", description: "d0" },
    ]);
  });

  it("rejecting a step reports a reject entry and can be undone", () => {
    const onChange = vi.fn();
    renderPipeline({}, onChange);

    fireEvent.click(screen.getAllByText("Reject")[1]);
    let lastCall = onChange.mock.calls[onChange.mock.calls.length - 1][0] as SubtaskEdit[];
    expect(lastCall).toEqual([{ index: 1, action: "reject" }]);

    fireEvent.click(screen.getByText("Undo reject"));
    lastCall = onChange.mock.calls[onChange.mock.calls.length - 1][0] as SubtaskEdit[];
    expect(lastCall).toEqual([]);
  });

  it("a rejected subtask's own stale edit is not also reported", () => {
    const onChange = vi.fn();
    renderPipeline({}, onChange);

    fireEvent.click(screen.getAllByText("Edit")[0]);
    fireEvent.change(screen.getByDisplayValue("Add model"), {
      target: { value: "edited then rejected" },
    });
    fireEvent.click(screen.getByText("Done"));
    fireEvent.click(screen.getAllByText("Reject")[0]);

    const lastCall = onChange.mock.calls[onChange.mock.calls.length - 1][0] as SubtaskEdit[];
    expect(lastCall).toEqual([{ index: 0, action: "reject" }]);
  });

  it("resets local edits when the underlying plan changes", () => {
    const onChange = vi.fn();
    const { rerender } = renderPipeline({}, onChange);

    fireEvent.click(screen.getAllByText("Reject")[0]);
    expect(onChange.mock.calls[onChange.mock.calls.length - 1][0]).toEqual([
      { index: 0, action: "reject" },
    ]);

    rerender(
      <PipelineView
        pipeline={{
          ...basePipeline,
          taskId: 2,
          subtasks: [{ type: "backend", title: "Different plan", description: "x" }],
        } as unknown as Parameters<typeof PipelineView>[0]["pipeline"]}
        onSubtaskEditsChange={onChange}
      />,
    );

    expect(onChange.mock.calls[onChange.mock.calls.length - 1][0]).toEqual([]);
  });
});
