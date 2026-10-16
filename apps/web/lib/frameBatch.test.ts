import { afterEach, describe, expect, it, vi } from "vitest";
import { createFrameBatcher } from "./frameBatch";

describe("createFrameBatcher (Sol A38)", () => {
  afterEach(() => vi.useRealTimers());

  it("many pieces in one frame cause a single render", () => {
    vi.useFakeTimers({ toFake: ["requestAnimationFrame", "cancelAnimationFrame"] });
    const flush = vi.fn();
    const batch = createFrameBatcher(flush);
    for (let i = 0; i < 500; i++) batch.schedule();
    expect(flush).not.toHaveBeenCalled();
    vi.advanceTimersToNextFrame();
    expect(flush).toHaveBeenCalledTimes(1);
  });

  it("flushNow shows pending text before the next event", () => {
    vi.useFakeTimers({ toFake: ["requestAnimationFrame", "cancelAnimationFrame"] });
    const flush = vi.fn();
    const batch = createFrameBatcher(flush);
    batch.schedule();
    batch.flushNow();
    expect(flush).toHaveBeenCalledTimes(1);
    vi.advanceTimersToNextFrame();
    expect(flush).toHaveBeenCalledTimes(1); // no second, late render
    batch.flushNow();
    expect(flush).toHaveBeenCalledTimes(1); // nothing pending, nothing to do
  });
});
