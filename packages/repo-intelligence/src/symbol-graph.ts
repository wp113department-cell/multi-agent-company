import type { RepoIndex, SymbolEntry, SymbolGraph } from "./types";

export function buildSymbolGraph(index: RepoIndex): SymbolGraph {
  const symbols: Record<string, SymbolEntry> = {};
  const usages: Record<string, string[]> = {};

  for (const sym of index.symbols) {
    symbols[sym.name] = sym;
    if (!usages[sym.name]) usages[sym.name] = [];
  }

  return { symbols, usages };
}

export function findSymbol(graph: SymbolGraph, name: string): SymbolEntry | undefined {
  return graph.symbols[name] ?? graph.symbols[Object.keys(graph.symbols).find((k) => k.endsWith(`.${name}`)) ?? ""];
}

export function getSymbolsInFile(graph: SymbolGraph, filePath: string): SymbolEntry[] {
  return Object.values(graph.symbols).filter((s) => s.filePath === filePath);
}

export function searchSymbols(graph: SymbolGraph, query: string): SymbolEntry[] {
  const q = query.toLowerCase();
  return Object.values(graph.symbols).filter(
    (s) => s.name.toLowerCase().includes(q) || s.filePath.toLowerCase().includes(q),
  );
}
