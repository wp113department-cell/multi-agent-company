/**
 * Sol A38 (2026-10-16): run `flush` at most once per screen frame however
 * often `schedule()` is called — streamed chat text arrives in many small
 * pieces, and re-rendering the whole message list for each one made long
 * answers sluggish. `flushNow()` runs a pending flush immediately (so
 * anything that must appear after the text keeps its order).
 */
export interface FrameBatcher {
  schedule(): void;
  flushNow(): void;
  cancel(): void;
}

export function createFrameBatcher(flush: () => void): FrameBatcher {
  let frame: number | null = null;
  const run = () => {
    frame = null;
    flush();
  };
  return {
    schedule() {
      if (frame === null) frame = requestAnimationFrame(run);
    },
    flushNow() {
      if (frame === null) return;
      cancelAnimationFrame(frame);
      run();
    },
    cancel() {
      if (frame !== null) cancelAnimationFrame(frame);
      frame = null;
    },
  };
}
