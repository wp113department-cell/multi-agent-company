/**
 * C5 (2026-10-09): what the chat agent is doing right now, in plain words,
 * for the live status line above the chat input. Built from the same live
 * events the tool cards use (thinking, tool_call, text_delta, ...).
 */

function str(v: unknown): string {
  return typeof v === "string" ? v : "";
}

function short(text: string, max = 60): string {
  const t = text.replace(/\s+/g, " ").trim();
  return t.length > max ? `${t.slice(0, max - 1)}…` : t;
}

export function describeTool(name: string, input: Record<string, unknown> = {}): string {
  const path = str(input.path) || str(input.file_path) || str(input.filename);
  const command = str(input.command) || str(input.cmd);
  const query = str(input.query) || str(input.pattern) || str(input.keyword);
  if (/^(read_file|read_files|file_info|analyze_file)$/.test(name))
    return path ? `Reading ${short(path)}` : "Reading files";
  if (/^(write_file|edit_file|create_file|apply_patch|replace_in_file)$/.test(name))
    return path ? `Editing ${short(path)}` : "Editing files";
  if (/^(delete_file|move_file|rename_file)$/.test(name))
    return path ? `Changing ${short(path)}` : "Changing files";
  if (/(^|_)tests?($|_)|pytest|run_single_test/.test(name)) return "Running tests";
  if (/^(bash|run_command|run_script|run_make|shell|python_snippet|node_snippet)$/.test(name))
    return command ? `Running: ${short(command, 50)}` : "Running a command";
  if (/^(search_code|search_symbols|find_references|search_imports|find_todos|grep)$/.test(name))
    return query ? `Searching for “${short(query, 40)}”` : "Searching the code";
  if (/^(list_files|get_file_tree|file_exists)$/.test(name)) return "Looking through the files";
  if (/^git_/.test(name)) return `Working with git (${name.slice(4).replace(/_/g, " ")})`;
  if (/web_search|fetch_url|browse/.test(name)) return "Looking it up on the web";
  return `Using ${name.replace(/_/g, " ")}`;
}

export type ActivityEvent =
  | { type: "thinking" }
  | { type: "tool_call"; tool_name: string; tool_input?: Record<string, unknown> }
  | { type: "tool_result" }
  | { type: "text_delta" }
  | { type: "confirmation_required" }
  | { type: "done" }
  | { type: "error" }
  | { type: string };

/** The status line for an event; null = nothing is running any more. */
export function activityFor(event: ActivityEvent, current: string | null): string | null {
  switch (event.type) {
    case "thinking":
    case "tool_result":
      return "Thinking…";
    case "tool_call": {
      const e = event as { tool_name: string; tool_input?: Record<string, unknown> };
      return `${describeTool(e.tool_name, e.tool_input ?? {})}…`;
    }
    case "text_delta":
      return "Writing the answer…";
    case "confirmation_required":
      return "Waiting for your approval";
    case "done":
    case "error":
      return null;
    default:
      return current;
  }
}
