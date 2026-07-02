/**
 * Graph correctness tests — verify that repo-intelligence correctly
 * extracts the call graph from the demo-repo fixture.
 *
 * Uses the fixture at tests/fixtures/demo-repo/ (no DB, no Anthropic API).
 */
import { describe, it, expect } from "vitest";
import path from "path";
import { fileURLToPath } from "url";

const DEMO_REPO = path.resolve(
  fileURLToPath(import.meta.url),
  "../../fixtures/demo-repo",
);

describe("Repo intelligence — graph correctness (demo-repo fixture)", () => {
  it("indexes demo-repo and finds expected files", async () => {
    const { indexRepository } = await import("@gridiron/repo-intelligence");
    const index = await indexRepository(DEMO_REPO);

    const filePaths = index.files.map((f) => f.filePath);
    expect(filePaths.some((f) => f.includes("math.ts"))).toBe(true);
    expect(filePaths.some((f) => f.includes("calculator.ts"))).toBe(true);
  });

  it("extracts symbols from math.ts", async () => {
    const { indexRepository } = await import("@gridiron/repo-intelligence");
    const index = await indexRepository(DEMO_REPO);

    const mathFile = index.files.find((f) => f.filePath.endsWith("math.ts"));
    expect(mathFile).toBeDefined();
    const symbolNames = mathFile!.symbols.map((s) => s.name);
    expect(symbolNames).toContain("add");
    expect(symbolNames).toContain("multiply");
    expect(symbolNames).toContain("divide");
  });

  it("extracts Calculator class from calculator.ts", async () => {
    const { indexRepository } = await import("@gridiron/repo-intelligence");
    const index = await indexRepository(DEMO_REPO);

    const calcFile = index.files.find((f) => f.filePath.endsWith("calculator.ts"));
    expect(calcFile).toBeDefined();
    const symbolNames = calcFile!.symbols.map((s) => s.name);
    expect(symbolNames).toContain("Calculator");
  });

  it("builds call graph with edges from calculator to math", async () => {
    const { indexRepository, indexRepositoryWithProject, buildCallGraph } = await import(
      "@gridiron/repo-intelligence"
    );
    const { project } = await indexRepositoryWithProject(DEMO_REPO);
    const index = await indexRepository(DEMO_REPO);
    const graph = buildCallGraph(index, project);

    expect(graph.edges.length).toBeGreaterThan(0);
    const callsToMath = graph.edges.filter((e) => e.calleeFile?.includes("math"));
    expect(callsToMath.length).toBeGreaterThan(0);
  });

  it("content hash changes when file content changes", async () => {
    const crypto = await import("crypto");
    const content1 = "export function add(a: number, b: number): number { return a + b; }";
    const content2 = "export function add(a: number, b: number): number { return a + b + 1; }";

    const hash1 = crypto.default.createHash("sha256").update(content1).digest("hex").slice(0, 16);
    const hash2 = crypto.default.createHash("sha256").update(content2).digest("hex").slice(0, 16);

    expect(hash1).not.toBe(hash2);
  });
});
