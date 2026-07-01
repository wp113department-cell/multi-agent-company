import { z } from "zod";

export const SymbolKindSchema = z.enum(["function", "class", "interface", "type", "variable", "enum"]);
export type SymbolKind = z.infer<typeof SymbolKindSchema>;

export const SymbolEntrySchema = z.object({
  name: z.string(),
  kind: SymbolKindSchema,
  filePath: z.string(),
  line: z.number(),
  isExported: z.boolean(),
});
export type SymbolEntry = z.infer<typeof SymbolEntrySchema>;

export const ImportEntrySchema = z.object({
  fromFile: z.string(),
  toFile: z.string(),
  importedNames: z.array(z.string()),
});
export type ImportEntry = z.infer<typeof ImportEntrySchema>;

export const FileEntrySchema = z.object({
  filePath: z.string(),
  language: z.string(),
  lines: z.number(),
  symbols: z.array(SymbolEntrySchema),
  imports: z.array(z.string()),
  summary: z.string(),
});
export type FileEntry = z.infer<typeof FileEntrySchema>;

export const RepoIndexSchema = z.object({
  repoPath: z.string(),
  indexedAt: z.date(),
  files: z.array(FileEntrySchema),
  symbols: z.array(SymbolEntrySchema),
  imports: z.array(ImportEntrySchema),
});
export type RepoIndex = z.infer<typeof RepoIndexSchema>;

export const DependencyGraphSchema = z.object({
  nodes: z.array(z.string()),
  edges: z.array(z.object({
    from: z.string(),
    to: z.string(),
    importedNames: z.array(z.string()),
  })),
});
export type DependencyGraph = z.infer<typeof DependencyGraphSchema>;

export const SymbolGraphSchema = z.object({
  symbols: z.record(z.string(), SymbolEntrySchema),
  usages: z.record(z.string(), z.array(z.string())),
});
export type SymbolGraph = z.infer<typeof SymbolGraphSchema>;

export const CallEdgeSchema = z.object({
  callerFile: z.string(),
  callerFn: z.string(),
  calleeFile: z.string(),
  calleeFn: z.string(),
});
export type CallEdge = z.infer<typeof CallEdgeSchema>;

export const CallGraphSchema = z.object({
  edges: z.array(CallEdgeSchema),
  callerMap: z.map(z.string(), z.array(z.string())),
  calleeMap: z.map(z.string(), z.array(z.string())),
});
export type CallGraph = z.infer<typeof CallGraphSchema>;

export const SemanticSearchResultSchema = z.object({
  filePath: z.string(),
  similarity: z.number(),
  content: z.string(),
});
export type SemanticSearchResult = z.infer<typeof SemanticSearchResultSchema>;
