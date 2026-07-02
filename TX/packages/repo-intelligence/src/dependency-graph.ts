import type { DependencyGraph, RepoIndex } from "./types";

export function buildDependencyGraph(index: RepoIndex): DependencyGraph {
  const nodeSet = new Set<string>(index.files.map((f) => f.filePath));
  const edges = index.imports.map((imp) => ({
    from: imp.fromFile,
    to: imp.toFile,
    importedNames: imp.importedNames,
  }));

  return {
    nodes: [...nodeSet],
    edges,
  };
}

export function getDependents(graph: DependencyGraph, filePath: string): string[] {
  return graph.edges.filter((e) => e.to === filePath).map((e) => e.from);
}

export function getDependencies(graph: DependencyGraph, filePath: string): string[] {
  return graph.edges.filter((e) => e.from === filePath).map((e) => e.to);
}

export function getTransitiveDependents(
  graph: DependencyGraph,
  filePath: string,
  visited = new Set<string>(),
): string[] {
  if (visited.has(filePath)) return [];
  visited.add(filePath);
  const direct = getDependents(graph, filePath);
  const transitive = direct.flatMap((d) => getTransitiveDependents(graph, d, visited));
  return [...new Set([...direct, ...transitive])];
}

export function scoreFilesByImportCentrality(graph: DependencyGraph): Map<string, number> {
  const scores = new Map<string, number>();
  for (const node of graph.nodes) {
    scores.set(node, 0);
  }
  for (const edge of graph.edges) {
    scores.set(edge.to, (scores.get(edge.to) ?? 0) + 1);
  }
  return scores;
}
