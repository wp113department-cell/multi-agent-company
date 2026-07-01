import path from "path";
import { Project, SyntaxKind, Node } from "ts-morph";
import { glob } from "glob";
import type { FileEntry, ImportEntry, RepoIndex, SymbolEntry, SymbolKind } from "./types";

const IGNORED_DIRS = ["node_modules", ".git", "dist", ".next", "build", "coverage", "repos"];
const TS_EXTENSIONS = [".ts", ".tsx", ".mts", ".cts"];
const JS_EXTENSIONS = [".js", ".jsx", ".mjs", ".cjs"];

function getLanguage(filePath: string): string {
  const ext = path.extname(filePath).toLowerCase();
  if (TS_EXTENSIONS.includes(ext)) return "typescript";
  if (JS_EXTENSIONS.includes(ext)) return "javascript";
  if (ext === ".py") return "python";
  if (ext === ".go") return "go";
  if (ext === ".rs") return "rust";
  if (ext === ".json") return "json";
  if (ext === ".md") return "markdown";
  if (ext === ".sql") return "sql";
  return "unknown";
}

function summarizeFile(content: string, filePath: string): string {
  const lines = content.split("\n");
  const firstComment = lines
    .slice(0, 10)
    .find((l) => l.trim().startsWith("//") || l.trim().startsWith("*") || l.trim().startsWith("#"));
  if (firstComment) return firstComment.replace(/^[\s/*#]+/, "").trim();
  const ext = path.extname(filePath).toLowerCase();
  return `${path.basename(filePath)} (${ext.slice(1) || "file"}, ${lines.length} lines)`;
}

function extractImportPaths(node: Node): string[] {
  const imports: string[] = [];
  node.forEachDescendant((child) => {
    if (
      child.getKind() === SyntaxKind.ImportDeclaration ||
      child.getKind() === SyntaxKind.ExportDeclaration
    ) {
      const moduleSpecifier = child.getChildrenOfKind(SyntaxKind.StringLiteral)[0];
      if (moduleSpecifier) {
        imports.push(moduleSpecifier.getLiteralValue());
      }
    }
  });
  return imports;
}

function extractSymbols(sourceFile: ReturnType<Project["addSourceFileAtPath"]>): SymbolEntry[] {
  const filePath = sourceFile.getFilePath();
  const symbols: SymbolEntry[] = [];

  // Functions
  sourceFile.getFunctions().forEach((fn) => {
    const name = fn.getName();
    if (name) {
      symbols.push({
        name,
        kind: "function" as SymbolKind,
        filePath,
        line: fn.getStartLineNumber(),
        isExported: fn.isExported(),
      });
    }
  });

  // Classes
  sourceFile.getClasses().forEach((cls) => {
    const name = cls.getName();
    if (name) {
      symbols.push({
        name,
        kind: "class" as SymbolKind,
        filePath,
        line: cls.getStartLineNumber(),
        isExported: cls.isExported(),
      });
      // Methods on the class
      cls.getMethods().forEach((method) => {
        symbols.push({
          name: `${name}.${method.getName()}`,
          kind: "function" as SymbolKind,
          filePath,
          line: method.getStartLineNumber(),
          isExported: false,
        });
      });
    }
  });

  // Interfaces
  sourceFile.getInterfaces().forEach((iface) => {
    symbols.push({
      name: iface.getName(),
      kind: "interface" as SymbolKind,
      filePath,
      line: iface.getStartLineNumber(),
      isExported: iface.isExported(),
    });
  });

  // Type aliases
  sourceFile.getTypeAliases().forEach((ta) => {
    symbols.push({
      name: ta.getName(),
      kind: "type" as SymbolKind,
      filePath,
      line: ta.getStartLineNumber(),
      isExported: ta.isExported(),
    });
  });

  // Enums
  sourceFile.getEnums().forEach((en) => {
    symbols.push({
      name: en.getName(),
      kind: "enum" as SymbolKind,
      filePath,
      line: en.getStartLineNumber(),
      isExported: en.isExported(),
    });
  });

  // Exported variable declarations (e.g. export const myFn = ...)
  sourceFile.getVariableDeclarations().forEach((vd) => {
    if (vd.isExported()) {
      symbols.push({
        name: vd.getName(),
        kind: "variable" as SymbolKind,
        filePath,
        line: vd.getStartLineNumber(),
        isExported: true,
      });
    }
  });

  return symbols;
}

function resolveImportPath(fromFile: string, importPath: string, repoPath: string): string | null {
  if (!importPath.startsWith(".")) return null;
  const resolved = path.resolve(path.dirname(fromFile), importPath);
  const withExt = [".ts", ".tsx", "/index.ts", "/index.tsx"].map((ext) => resolved + ext);
  const relative = withExt
    .map((p) => path.relative(repoPath, p))
    .find((rel) => !rel.startsWith(".."));
  return relative ?? null;
}

export async function indexRepository(repoPath: string): Promise<RepoIndex> {
  const absRepo = path.resolve(repoPath);

  const ignorePatterns = IGNORED_DIRS.map((d) => `${d}/**`);

  // Find all TypeScript/TSX files (primary — use ts-morph AST)
  const tsFiles = await glob("**/*.{ts,tsx}", {
    cwd: absRepo,
    ignore: ignorePatterns,
    absolute: true,
    nodir: true,
  });

  // All other files (JS, JSON, MD) — extract summary only
  const otherFiles = await glob("**/*.{js,jsx,mjs,cjs,json,md,sql,py,go,rs}", {
    cwd: absRepo,
    ignore: ignorePatterns,
    absolute: true,
    nodir: true,
  });

  // Find a usable tsconfig — prefer root, then any package-level one
  const { statSync } = await import("fs");
  const rootTsConfig = path.join(absRepo, "tsconfig.json");
  const baseTsConfig = path.join(absRepo, "tsconfig.base.json");
  const packagesTsConfig = (await glob("packages/*/tsconfig.json", { cwd: absRepo, absolute: true }))[0];
  const tsConfigPath = [rootTsConfig, baseTsConfig, packagesTsConfig].find((p) => {
    if (!p) return false;
    try { statSync(p); return true; } catch { return false; }
  });

  const project = new Project({
    ...(tsConfigPath ? { tsConfigFilePath: tsConfigPath } : { useInMemoryFileSystem: false }),
    skipFileDependencyResolution: true,
    skipLoadingLibFiles: true,
    skipAddingFilesFromTsConfig: true,
    compilerOptions: tsConfigPath ? undefined : {
      target: 99, // ESNext
      moduleResolution: 100, // Bundler
      strict: true,
    },
  });

  // Add TS files to project (batch for performance)
  for (const f of tsFiles) {
    try {
      project.addSourceFileAtPath(f);
    } catch {
      // skip unparseable files
    }
  }

  const fileEntries: FileEntry[] = [];
  const allSymbols: SymbolEntry[] = [];
  const allImports: ImportEntry[] = [];

  for (const sourceFile of project.getSourceFiles()) {
    const absPath = sourceFile.getFilePath();
    const relPath = path.relative(absRepo, absPath);
    const content = sourceFile.getFullText();
    const lines = content.split("\n").length;
    const language = getLanguage(absPath);

    const symbols = extractSymbols(sourceFile);
    allSymbols.push(...symbols.map((s) => ({ ...s, filePath: path.relative(absRepo, s.filePath) })));

    const rawImports = extractImportPaths(sourceFile);
    const resolvedImports: ImportEntry[] = rawImports
      .map((imp) => {
        const resolved = resolveImportPath(absPath, imp, absRepo);
        return resolved
          ? { fromFile: relPath, toFile: resolved, importedNames: [] as string[] }
          : null;
      })
      .filter((x): x is ImportEntry => x !== null);
    allImports.push(...resolvedImports);

    fileEntries.push({
      filePath: relPath,
      language,
      lines,
      symbols: symbols.map((s) => ({ ...s, filePath: path.relative(absRepo, s.filePath) })),
      imports: rawImports,
      summary: summarizeFile(content, absPath),
    });
  }

  // Process non-TS files (summary only, no AST)
  const { readFile } = await import("fs/promises");
  for (const f of otherFiles) {
    const relPath = path.relative(absRepo, f);
    if (fileEntries.find((e) => e.filePath === relPath)) continue;
    try {
      const content = await readFile(f, "utf-8");
      const lines = content.split("\n").length;
      fileEntries.push({
        filePath: relPath,
        language: getLanguage(f),
        lines,
        symbols: [],
        imports: [],
        summary: summarizeFile(content, f),
      });
    } catch {
      // skip unreadable files
    }
  }

  return {
    repoPath: absRepo,
    indexedAt: new Date(),
    files: fileEntries,
    symbols: allSymbols,
    imports: allImports,
  };
}
