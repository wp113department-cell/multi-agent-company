import path from "path";
import {
  indexRepository,
  buildDependencyGraph,
  buildSymbolGraph,
  getDependencies,
  scoreFilesByImportCentrality,
  searchSymbols,
} from "@gridiron/repo-intelligence";
import type { RepoIndex } from "@gridiron/repo-intelligence";
import type { DevTask } from "@gridiron/shared-types";
import { extractKeywords, scoreFiles, type ScoredFile } from "./scorer";

export interface ContextResult {
  relevantFiles: ScoredFile[];
  dependencyChain: string[];
  relatedSymbols: string[];
  summary: string;
  indexStats: { totalFiles: number; totalSymbols: number; indexedAt: Date };
}

const indexCache = new Map<string, { index: RepoIndex; expiresAt: number }>();
const CACHE_TTL_MS = 5 * 60 * 1000; // 5 minutes

async function getCachedIndex(repoPath: string): Promise<RepoIndex> {
  const cached = indexCache.get(repoPath);
  if (cached && Date.now() < cached.expiresAt) {
    return cached.index;
  }
  const index = await indexRepository(repoPath);
  indexCache.set(repoPath, { index, expiresAt: Date.now() + CACHE_TTL_MS });
  return index;
}

export async function buildContext(task: DevTask, repoPath: string): Promise<ContextResult> {
  const absRepo = path.resolve(repoPath);
  const index = await getCachedIndex(absRepo);

  const depGraph = buildDependencyGraph(index);
  const symGraph = buildSymbolGraph(index);
  const centrality = scoreFilesByImportCentrality(depGraph);

  const keywords = extractKeywords(`${task.title} ${task.description ?? ""}`);
  const topFiles = scoreFiles(index.files, keywords, centrality).slice(0, 15);

  // Expand with dependencies of top files (up to depth 1)
  const depChain = new Set<string>();
  for (const f of topFiles.slice(0, 5)) {
    getDependencies(depGraph, f.filePath).forEach((d) => depChain.add(d));
  }

  // Related symbols matching keywords
  const relatedSymbols = keywords
    .flatMap((kw) => searchSymbols(symGraph, kw).slice(0, 5))
    .map((s) => `${s.name} (${s.kind}) — ${s.filePath}:${s.line}`)
    .slice(0, 20);

  const topFileNames = topFiles.slice(0, 5).map((f) => f.filePath);
  const summary =
    topFiles.length === 0
      ? `No files matched keywords: ${keywords.slice(0, 5).join(", ")}`
      : `Top ${topFileNames.length} relevant file(s): ${topFileNames.join(", ")}. ` +
        `${relatedSymbols.length} related symbol(s) found.`;

  return {
    relevantFiles: topFiles,
    dependencyChain: [...depChain].slice(0, 10),
    relatedSymbols,
    summary,
    indexStats: {
      totalFiles: index.files.length,
      totalSymbols: index.symbols.length,
      indexedAt: index.indexedAt,
    },
  };
}

export function invalidateContextCache(repoPath: string): void {
  indexCache.delete(path.resolve(repoPath));
}
