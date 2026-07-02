import crypto from "crypto";
import type { RepoIndex, SemanticSearchResult } from "./types";

// Duck-typed DB client — avoids pg dependency in this package
interface DbClient {
  query<T extends object>(sql: string, params?: unknown[]): Promise<{ rows: T[] }>;
}

const VOYAGE_API_URL = "https://api.voyageai.com/v1/embeddings";
const VOYAGE_MODEL = "voyage-code-2";
const VOYAGE_BATCH_SIZE = 20;
const MAX_CONTENT_CHARS = 2000;

function buildFileContent(filePath: string, summary: string, symbolNames: string[]): string {
  const symbols = symbolNames.slice(0, 30).join(", ");
  return `${filePath}\n${summary}${symbols ? `\n${symbols}` : ""}`.slice(0, MAX_CONTENT_CHARS);
}

function contentHash(text: string): string {
  return crypto.createHash("sha256").update(text).digest("hex").slice(0, 16);
}

async function embedBatch(texts: string[], apiKey: string): Promise<number[][]> {
  const res = await fetch(VOYAGE_API_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${apiKey}` },
    body: JSON.stringify({ model: VOYAGE_MODEL, input: texts }),
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`Voyage API error ${res.status}: ${body}`);
  }
  const json = (await res.json()) as { data: { embedding: number[] }[] };
  return json.data.map((d) => d.embedding);
}

export async function generateEmbeddings(index: RepoIndex, db: DbClient): Promise<void> {
  const apiKey = process.env["VOYAGE_API_KEY"];
  if (!apiKey) {
    console.warn("[embeddings] VOYAGE_API_KEY not set — skipping embedding generation");
    return;
  }

  const rows: { filePath: string; content: string; hash: string }[] = index.files.map((f) => ({
    filePath: f.filePath,
    content: buildFileContent(f.filePath, f.summary, f.symbols.map((s) => s.name)),
    hash: contentHash(buildFileContent(f.filePath, f.summary, f.symbols.map((s) => s.name))),
  }));

  // Find which files already have up-to-date embeddings
  const existingRes = await db.query<{ file_path: string; content_hash: string }>(
    `SELECT file_path, content_hash FROM code_embeddings WHERE repo_path = $1`,
    [index.repoPath],
  );
  const existingMap = new Map(existingRes.rows.map((r) => [r.file_path, r.content_hash]));

  const toEmbed = rows.filter((r) => existingMap.get(r.filePath) !== r.hash);
  if (toEmbed.length === 0) {
    console.log("[embeddings] All files up to date — nothing to embed");
    return;
  }

  console.log(`[embeddings] Embedding ${toEmbed.length} file(s) via Voyage AI…`);

  for (let i = 0; i < toEmbed.length; i += VOYAGE_BATCH_SIZE) {
    const batch = toEmbed.slice(i, i + VOYAGE_BATCH_SIZE);
    const vectors = await embedBatch(batch.map((r) => r.content), apiKey);

    for (let j = 0; j < batch.length; j++) {
      const row = batch[j]!;
      const vec = vectors[j]!;
      const pgVec = `[${vec.join(",")}]`;
      await db.query(
        `INSERT INTO code_embeddings (repo_path, file_path, content, content_hash, embedding)
         VALUES ($1, $2, $3, $4, $5::vector)
         ON CONFLICT (repo_path, file_path)
         DO UPDATE SET content = $3, content_hash = $4, embedding = $5::vector, updated_at = now()`,
        [index.repoPath, row.filePath, row.content, row.hash, pgVec],
      );
    }
    console.log(`[embeddings] Batch ${Math.floor(i / VOYAGE_BATCH_SIZE) + 1} done (${batch.length} files)`);
  }

  console.log(`[embeddings] Done — ${toEmbed.length} file(s) embedded`);
}

export async function semanticSearch(
  query: string,
  repoPath: string,
  db: DbClient,
  limit = 10,
): Promise<SemanticSearchResult[]> {
  const apiKey = process.env["VOYAGE_API_KEY"];
  if (!apiKey) return [];

  const [queryVec] = await embedBatch([query], apiKey);
  if (!queryVec) return [];

  const pgVec = `[${queryVec.join(",")}]`;
  const res = await db.query<{ file_path: string; content: string; similarity: number }>(
    `SELECT file_path, content,
            1 - (embedding <=> $1::vector) AS similarity
     FROM code_embeddings
     WHERE repo_path = $2
     ORDER BY embedding <=> $1::vector
     LIMIT $3`,
    [pgVec, repoPath, limit],
  );

  return res.rows.map((r) => ({
    filePath: r.file_path,
    similarity: Number(r.similarity),
    content: r.content,
  }));
}
