import path from "path";
import { Project, SyntaxKind } from "ts-morph";
import type { RepoIndex, CallGraph } from "./types";

function buildImportMap(
  sourceFile: ReturnType<Project["addSourceFileAtPath"]>,
  absFilePath: string,
  repoPath: string,
): Map<string, string> {
  const importMap = new Map<string, string>();
  for (const decl of sourceFile.getImportDeclarations()) {
    const specifier = decl.getModuleSpecifierValue();
    if (!specifier.startsWith(".")) continue;
    const resolved = path.resolve(path.dirname(absFilePath), specifier);
    const candidates = [".ts", ".tsx", "/index.ts", "/index.tsx"].map((ext) => resolved + ext);
    const relPath = candidates
      .map((c) => path.relative(repoPath, c))
      .find((r) => !r.startsWith(".."));
    if (!relPath) continue;
    decl.getNamedImports().forEach((n) => importMap.set(n.getName(), relPath));
    const def = decl.getDefaultImport();
    if (def) importMap.set(def.getText(), relPath);
  }
  return importMap;
}

export function buildCallGraph(index: RepoIndex, project: Project): CallGraph {
  const absRepo = path.resolve(index.repoPath);
  const edges: CallGraph["edges"] = [];

  for (const sourceFile of project.getSourceFiles()) {
    const absPath = sourceFile.getFilePath();
    const relPath = path.relative(absRepo, absPath);
    const importMap = buildImportMap(sourceFile, absPath, absRepo);
    if (importMap.size === 0) continue;

    const allFns = [
      ...sourceFile.getFunctions().map((f) => ({ name: f.getName() ?? "<anon>", node: f })),
      ...sourceFile.getClasses().flatMap((cls) =>
        cls.getMethods().map((m) => ({ name: `${cls.getName() ?? "?"}.${m.getName()}`, node: m })),
      ),
    ];

    for (const { name: callerFn, node: fnNode } of allFns) {
      const callExprs = fnNode.getDescendantsOfKind(SyntaxKind.CallExpression);
      for (const call of callExprs) {
        const expr = call.getExpression();
        const calleeName = expr.getKind() === SyntaxKind.PropertyAccessExpression
          ? expr.asKindOrThrow(SyntaxKind.PropertyAccessExpression).getName()
          : expr.getText().split(".")[0] ?? "";
        const calleeFile = importMap.get(calleeName);
        if (!calleeFile) continue;
        edges.push({ callerFile: relPath, callerFn, calleeFile, calleeFn: calleeName });
      }
    }
  }

  const callerMap = new Map<string, string[]>();
  const calleeMap = new Map<string, string[]>();
  for (const edge of edges) {
    const callerKey = `${edge.callerFile}::${edge.callerFn}`;
    const calleeKey = `${edge.calleeFile}::${edge.calleeFn}`;
    callerMap.set(callerKey, [...(callerMap.get(callerKey) ?? []), calleeKey]);
    calleeMap.set(calleeKey, [...(calleeMap.get(calleeKey) ?? []), callerKey]);
  }

  return { edges, callerMap, calleeMap };
}

export function getCallees(graph: CallGraph, filePath: string, fnName?: string): string[] {
  const prefix = fnName ? `${filePath}::${fnName}` : filePath;
  const results: string[] = [];
  for (const [caller, callees] of graph.callerMap) {
    if (caller.startsWith(prefix)) results.push(...callees);
  }
  return [...new Set(results)];
}

export function getCallers(graph: CallGraph, filePath: string, fnName?: string): string[] {
  const prefix = fnName ? `${filePath}::${fnName}` : filePath;
  const results: string[] = [];
  for (const [callee, callers] of graph.calleeMap) {
    if (callee.startsWith(prefix)) results.push(...callers);
  }
  return [...new Set(results)];
}
