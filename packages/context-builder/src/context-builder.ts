import path from "path";
import {
  indexRepositoryWithProject,
  buildDependencyGraph,
  buildSymbolGraph,
  buildCallGraph,
  getDependencies,
  getCallers,
  scoreFilesByImportCentrality,
  searchSymbols,
  semanticSearch,
} from "@gridiron/repo-intelligence";
import type { RepoIndex, CallGraph } from "@gridiron/repo-intelligence";
import { getPool } from "@gridiron/shared-db";
import type { DevTask } from "@gridiron/shared-types";
import { extractKeywords, scoreFiles, type ScoredFile } from "./scorer";

export interface ContextResult {
  relevantFiles: ScoredFile[];
  dependencyChain: string[];
  relatedSymbols: string[];
  callGraphEdges: string[];
  semanticMatches: string[];
  summary: string;
  indexStats: { totalFiles: number; totalSymbols: number; indexedAt: Date };
}

interface CacheEntry {
  index: RepoIndex;
  callGraph: CallGraph;
  expiresAt: number;
}

const indexCache = new Map<string, CacheEntry>();
const CACHE_TTL_MS = 5 * 60 * 1000; // 5 minutes

async function getCached(repoPath: string): Promise<{ index: RepoIndex; callGraph: CallGraph }> {
  const cached = indexCache.get(repoPath);
  if (cached && Date.now() < cached.expiresAt) {
    return { index: cached.index, callGraph: cached.callGraph };
  }
  const { index, project } = await indexRepositoryWithProject(repoPath);
  const callGraph = buildCallGraph(index, project);
  indexCache.set(repoPath, { index, callGraph, expiresAt: Date.now() + CACHE_TTL_MS });
  return { index, callGraph };
}

export async function buildContext(task: DevTask, repoPath: string): Promise<ContextResult> {
  const absRepo = path.resolve(repoPath);
  const { index, callGraph } = await getCached(absRepo);

  const depGraph = buildDependencyGraph(index);
  const symGraph = buildSymbolGraph(index);
  const centrality = scoreFilesByImportCentrality(depGraph);

  const keywords = extractKeywords(`${task.title} ${task.description ?? ""}`);
  const keywordFiles = scoreFiles(index.files, keywords, centrality).slice(0, 15);

  // Semantic search augmentation (when Voyage AI key is present)
  let semanticMatches: string[] = [];
  try {
    const db = getPool();
    const queryText = `${task.title} ${task.description ?? ""}`;
    const semResults = await semanticSearch(queryText, absRepo, db, 10);
    semanticMatches = semResults
      .filter((r) => r.similarity > 0.6)
      .map((r) => `${r.filePath} (similarity: ${r.similarity.toFixed(3)})`);

    // Merge semantic results into keyword results (deduplicate by filePath)
    const seenPaths = new Set(keywordFiles.map((f) => f.filePath));
    for (const sr of semResults.filter((r) => r.similarity > 0.6)) {
      if (!seenPaths.has(sr.filePath)) {
        keywordFiles.push({
          filePath: sr.filePath,
          score: Math.round(sr.similarity * 10),
          matchedKeywords: ["semantic"],
          importCentrality: 0,
        });
        seenPaths.add(sr.filePath);
      }
    }
    keywordFiles.sort((a, b) => b.score - a.score);
  } catch {
    // Semantic search is optional — keyword scoring is always the baseline
  }

  const topFiles = keywordFiles.slice(0, 15);

  // Expand with dependencies of top files (depth 1)
  const depChain = new Set<string>();
  for (const f of topFiles.slice(0, 5)) {
    getDependencies(depGraph, f.filePath).forEach((d) => depChain.add(d));
  }

  // Call graph: who calls functions in the top files?
  const callGraphEdges: string[] = [];
  for (const f of topFiles.slice(0, 5)) {
    const callers = getCallers(callGraph, f.filePath);
    callGraphEdges.push(...callers.map((c) => `${c} → ${f.filePath}`));
  }

  // Related symbols matching keywords
  const relatedSymbols = keywords
    .flatMap((kw) => searchSymbols(symGraph, kw).slice(0, 5))
    .map((s) => `${s.name} (${s.kind}) — ${s.filePath}:${s.line}`)
    .slice(0, 20);

  const topFileNames = topFiles.slice(0, 5).map((f) => f.filePath);
  const hasSemanticBoost = semanticMatches.length > 0;
  const summary =
    topFiles.length === 0
      ? `No files matched keywords: ${keywords.slice(0, 5).join(", ")}`
      : `Top ${topFileNames.length} relevant file(s): ${topFileNames.join(", ")}. ` +
        `${relatedSymbols.length} related symbol(s), ${callGraphEdges.length} call-graph edge(s)` +
        (hasSemanticBoost ? `, ${semanticMatches.length} semantic match(es)` : "") +
        ".";

  return {
    relevantFiles: topFiles,
    dependencyChain: [...depChain].slice(0, 10),
    relatedSymbols,
    callGraphEdges: [...new Set(callGraphEdges)].slice(0, 10),
    semanticMatches: semanticMatches.slice(0, 10),
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
