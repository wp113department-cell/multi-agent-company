import { describe, expect, it } from "vitest";
import { assertValidTransition, InvalidTransitionError, isValidTransition } from "./status-transitions";

describe("status transitions", () => {
  it("allows the standard happy path", () => {
    expect(isValidTransition("pending", "planning")).toBe(true);
    expect(isValidTransition("planning", "ready_for_review")).toBe(true);
    expect(isValidTransition("ready_for_review", "coding")).toBe(true);
    expect(isValidTransition("coding", "testing")).toBe(true);
    expect(isValidTransition("testing", "ready_for_review")).toBe(true);
    expect(isValidTransition("ready_for_review", "completed")).toBe(true);
  });

  it("allows the self-correction retry loop", () => {
    expect(isValidTransition("testing", "coding")).toBe(true);
  });

  it("allows human rejection and re-planning", () => {
    expect(isValidTransition("ready_for_review", "rejected")).toBe(true);
    expect(isValidTransition("rejected", "planning")).toBe(true);
  });

  it("rejects skipping straight from pending to completed", () => {
    expect(isValidTransition("pending", "completed")).toBe(false);
  });

  it("treats completed and failed as terminal", () => {
    expect(isValidTransition("completed", "planning")).toBe(false);
    expect(isValidTransition("failed", "coding")).toBe(false);
  });

  it("assertValidTransition throws InvalidTransitionError on a bad move", () => {
    expect(() => assertValidTransition("pending", "completed")).toThrow(InvalidTransitionError);
  });

  it("allows same-state no-op transitions", () => {
    expect(isValidTransition("coding", "coding")).toBe(true);
  });
});
