import { execFile } from "child_process";
import fs from "fs/promises";
import path from "path";
import { promisify } from "util";
import { glob } from "glob";

const execFileAsync = promisify(execFile);

const MAX_FILE_BYTES = 256 * 1024; // 256 KB per file read
const MAX_GREP_RESULTS = 40;
const MAX_LIST_FILES = 500;

function assertInsideRepo(repoPath: string, filePath: string): string {
  const abs = path.resolve(repoPath, filePath);
  const base = path.resolve(repoPath);
  if (abs !== base && !abs.startsWith(base + path.sep)) {
    throw new Error(`Security: path "${filePath}" escapes repo root`);
  }
  return abs;
}

export async function readFile(repoPath: string, filePath: string): Promise<string> {
  const abs = assertInsideRepo(repoPath, filePath);
  const stat = await fs.stat(abs).catch(() => null);
  if (!stat) return `(file not found: ${filePath})`;
  if (stat.size > MAX_FILE_BYTES) {
    const handle = await fs.open(abs, "r");
    const buf = Buffer.alloc(MAX_FILE_BYTES);
    await handle.read(buf, 0, MAX_FILE_BYTES, 0);
    await handle.close();
    return `[truncated — file is ${stat.size} bytes, showing first 256KB]\n` + buf.toString("utf-8");
  }
  return fs.readFile(abs, "utf-8");
}

export async function listFiles(repoPath: string, pattern = "**/*"): Promise<string[]> {
  const files = await glob(pattern, {
    cwd: repoPath,
    ignore: ["node_modules/**", ".git/**", "dist/**", ".next/**", "*.lock", "pnpm-lock.yaml", ".turbo/**"],
    nodir: true,
    maxDepth: 10,
  });
  return files.sort().slice(0, MAX_LIST_FILES);
}

export interface GrepResult {
  file: string;
  line: number;
  content: string;
}

export async function grepFiles(
  repoPath: string,
  query: string,
  fileGlob = "**/*.{ts,tsx,js,jsx,json,md,sql,yaml,yml,env.example}",
): Promise<GrepResult[]> {
  const files = await listFiles(repoPath, fileGlob);
  const results: GrepResult[] = [];
  const queryLower = query.toLowerCase();

  for (const file of files) {
    if (results.length >= MAX_GREP_RESULTS) break;
    try {
      const content = await readFile(repoPath, file);
      const lines = content.split("\n");
      for (let i = 0; i < lines.length; i++) {
        const line = lines[i];
        if (line !== undefined && line.toLowerCase().includes(queryLower)) {
          results.push({ file, line: i + 1, content: line.trim().slice(0, 200) });
          if (results.length >= MAX_GREP_RESULTS) break;
        }
      }
    } catch {
      // skip unreadable files
    }
  }
  return results;
}

export async function gitLog(repoPath: string, n = 20): Promise<string> {
  try {
    const { stdout } = await execFileAsync("git", ["log", "--oneline", `-${n}`], { cwd: repoPath });
    return stdout || "(no commits)";
  } catch {
    return "(git log unavailable)";
  }
}

export async function gitDiff(repoPath: string, ref = "HEAD"): Promise<string> {
  try {
    const { stdout } = await execFileAsync("git", ["diff", ref], {
      cwd: repoPath,
      maxBuffer: 2 * 1024 * 1024,
    });
    return stdout.trim() || "(no uncommitted changes)";
  } catch {
    return "(git diff unavailable)";
  }
}

export async function gitWorktreeDiff(repoPath: string, branch: string): Promise<string> {
  try {
    const { stdout } = await execFileAsync("git", ["diff", `HEAD..${branch}`], {
      cwd: repoPath,
      maxBuffer: 4 * 1024 * 1024,
    });
    return stdout.trim() || "(no changes between HEAD and branch)";
  } catch {
    return "(worktree diff unavailable)";
  }
}
