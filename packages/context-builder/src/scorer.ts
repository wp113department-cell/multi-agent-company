import type { FileEntry } from "@gridiron/repo-intelligence";

export interface ScoredFile {
  filePath: string;
  score: number;
  matchedKeywords: string[];
  importCentrality: number;
}

function tokenize(text: string): string[] {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9_/.-]/g, " ")
    .split(/\s+/)
    .filter((t) => t.length > 2);
}

function extractKeywords(text: string): string[] {
  return [...new Set(tokenize(text))];
}

export function scoreFiles(
  files: FileEntry[],
  taskKeywords: string[],
  importCentrality: Map<string, number>,
): ScoredFile[] {
  const results: ScoredFile[] = [];

  for (const file of files) {
    const pathTokens = tokenize(file.filePath);
    const symbolTokens = file.symbols.flatMap((s) => tokenize(s.name));
    const summaryTokens = tokenize(file.summary);
    const allTokens = [...pathTokens, ...symbolTokens, ...summaryTokens];

    const matchedKeywords = taskKeywords.filter((kw) =>
      allTokens.some((t) => t.includes(kw) || kw.includes(t)),
    );

    const centrality = importCentrality.get(file.filePath) ?? 0;

    // Score: each keyword match worth 10 points, centrality worth up to 5
    const score = matchedKeywords.length * 10 + Math.min(centrality * 2, 5);

    if (score > 0) {
      results.push({
        filePath: file.filePath,
        score,
        matchedKeywords,
        importCentrality: centrality,
      });
    }
  }

  return results.sort((a, b) => b.score - a.score);
}

export { extractKeywords };
