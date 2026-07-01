import { NextResponse } from "next/server";
import path from "path";

export async function GET() {
  try {
    const { getPool } = await import("@gridiron/shared-db");
    const db = getPool();
    const res = await db.query<{ latest: Date | null }>(
      `SELECT MAX(updated_at) AS latest FROM code_embeddings`,
    );
    const latest = res.rows[0]?.latest ?? null;
    return NextResponse.json({
      lastIndexedAt: latest ? latest.toISOString() : null,
      message: latest ? "Embeddings exist" : "No embeddings yet — run POST /api/repo/reindex",
    });
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    return NextResponse.json({ error: msg }, { status: 500 });
  }
}

export async function POST() {
  const repoPath = path.resolve(process.env["TARGET_REPO_PATH"] ?? process.cwd() + "/../../");

  setImmediate(() => {
    void (async () => {
      try {
        const { indexRepository, generateEmbeddings } = await import("@gridiron/repo-intelligence");
        const { invalidateContextCache } = await import("@gridiron/context-builder");
        const { getPool } = await import("@gridiron/shared-db");

        console.log(`[reindex] Starting full reindex of ${repoPath}`);
        invalidateContextCache(repoPath);

        const index = await indexRepository(repoPath);
        console.log(`[reindex] Indexed ${index.files.length} files, ${index.symbols.length} symbols`);

        const db = getPool();
        await generateEmbeddings(index, db);
        console.log(`[reindex] Complete`);
      } catch (err) {
        console.error("[reindex] Error:", err instanceof Error ? err.message : err);
      }
    })();
  });

  return NextResponse.json(
    { message: "Reindex started", repoPath },
    { status: 202 },
  );
}
