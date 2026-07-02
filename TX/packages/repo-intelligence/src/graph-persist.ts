import crypto from "crypto";
import type { RepoIndex, CallGraph } from "./types";

interface DbClient {
  query<T extends object>(sql: string, params?: unknown[]): Promise<{ rows: T[] }>;
}

function fileHash(content: string): string {
  return crypto.createHash("sha256").update(content).digest("hex").slice(0, 16);
}

export async function persistGraphToDb(
  index: RepoIndex,
  graph: CallGraph,
  db: DbClient,
): Promise<{ filesUpserted: number; filesSkipped: number }> {
  let filesUpserted = 0;
  let filesSkipped = 0;

  // Fetch existing file hashes for this repo
  const existing = await db.query<{ file_path: string; file_id: string; content_hash: string }>(
    `SELECT file_path, file_id, content_hash FROM indexed_files WHERE repo_path = $1`,
    [index.repoPath],
  );
  const existingMap = new Map(existing.rows.map((r) => [r.file_path, r]));

  for (const file of index.files) {
    const content = `${file.filePath}|${file.lines}|${file.symbols.map((s) => s.name).join(",")}`;
    const hash = fileHash(content);
    const ex = existingMap.get(file.filePath);

    if (ex && ex.content_hash === hash) {
      filesSkipped++;
      continue;
    }

    // Upsert file record
    const fileResult = await db.query<{ file_id: string }>(
      `INSERT INTO indexed_files (repo_path, file_path, content_hash, last_indexed_at)
       VALUES ($1, $2, $3, now())
       ON CONFLICT (repo_path, file_path)
       DO UPDATE SET content_hash = EXCLUDED.content_hash, last_indexed_at = now()
       RETURNING file_id`,
      [index.repoPath, file.filePath, hash],
    );
    const fileId = fileResult.rows[0]?.file_id;
    if (!fileId) continue;

    // Delete existing symbols for this file (cascade deletes edges too)
    await db.query(`DELETE FROM symbols WHERE file_id = $1`, [fileId]);

    // Insert symbols
    for (const sym of file.symbols) {
      const symKind = ["function", "class", "interface", "type"].includes(sym.kind)
        ? sym.kind
        : "function";
      const symResult = await db.query<{ symbol_id: string }>(
        `INSERT INTO symbols (file_id, name, kind, line_start)
         VALUES ($1, $2, $3, $4)
         RETURNING symbol_id`,
        [fileId, sym.name, symKind, sym.line],
      );
      const symbolId = symResult.rows[0]?.symbol_id;
      if (!symbolId) continue;

      // Insert call edges where this symbol is the caller
      const callEdges = graph.edges.filter(
        (e) => e.callerFile === file.filePath && e.callerFn === sym.name,
      );
      for (const edge of callEdges) {
        await db.query(
          `INSERT INTO call_edges (caller_id, callee_name, callee_file)
           VALUES ($1, $2, $3)`,
          [symbolId, edge.calleeFn, edge.calleeFile],
        );
      }
    }

    filesUpserted++;
  }

  return { filesUpserted, filesSkipped };
}
