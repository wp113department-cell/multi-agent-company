import { describe, expect, it } from "vitest";
import { activityFor, describeTool } from "./chatActivity";

describe("C5 live activity line", () => {
  it("names the file being read or edited", () => {
    expect(describeTool("read_file", { path: "app/page.tsx" })).toBe("Reading app/page.tsx");
    expect(describeTool("edit_file", { path: "calc.py" })).toBe("Editing calc.py");
  });

  it("describes commands, tests, searches and git in plain words", () => {
    expect(describeTool("bash", { command: "npm run build" })).toBe("Running: npm run build");
    expect(describeTool("run_tests", {})).toBe("Running tests");
    expect(describeTool("search_code", { query: "TODO" })).toBe("Searching for “TODO”");
    expect(describeTool("git_status", {})).toBe("Working with git (status)");
    expect(describeTool("some_new_tool", {})).toBe("Using some new tool");
  });

  it("shortens very long paths and commands", () => {
    const long = "a/".repeat(60) + "file.ts";
    expect(describeTool("read_file", { path: long }).length).toBeLessThanOrEqual(68);
  });

  it("follows the stream from start to finish", () => {
    let a: string | null = null;
    a = activityFor({ type: "thinking" }, a);
    expect(a).toBe("Thinking…");
    a = activityFor({ type: "tool_call", tool_name: "read_file", tool_input: { path: "x.py" } }, a);
    expect(a).toBe("Reading x.py…");
    a = activityFor({ type: "confirmation_required" }, a);
    expect(a).toBe("Waiting for your approval");
    a = activityFor({ type: "text_delta" }, a);
    expect(a).toBe("Writing the answer…");
    a = activityFor({ type: "terminal_output" }, a);
    expect(a).toBe("Writing the answer…");
    expect(activityFor({ type: "done" }, a)).toBeNull();
    expect(activityFor({ type: "error" }, "Thinking…")).toBeNull();
  });
});
