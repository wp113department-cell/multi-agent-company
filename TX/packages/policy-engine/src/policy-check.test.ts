import { describe, expect, it } from "vitest";
import { checkCommand, checkPath, checkPathInWorktree } from "./policy-check";

describe("checkPath", () => {
  it("blocks .env variants", () => {
    expect(checkPath(".env").allowed).toBe(false);
    expect(checkPath(".env.local").allowed).toBe(false);
    expect(checkPath(".env.production").allowed).toBe(false);
    expect(checkPath("apps/web/.env").allowed).toBe(false);
  });

  it("blocks secrets/ directory", () => {
    expect(checkPath("secrets/api-key.txt").allowed).toBe(false);
    expect(checkPath("app/secrets/db.txt").allowed).toBe(false);
  });

  it("blocks .github/workflows", () => {
    expect(checkPath(".github/workflows/deploy.yml").allowed).toBe(false);
    expect(checkPath(".github/workflows/ci.yml").allowed).toBe(false);
  });

  it("allows normal source paths", () => {
    expect(checkPath("src/index.ts").allowed).toBe(true);
    expect(checkPath("packages/shared-types/src/types.ts").allowed).toBe(true);
    expect(checkPath("apps/web/app/page.tsx").allowed).toBe(true);
    expect(checkPath("README.md").allowed).toBe(true);
    expect(checkPath("package.json").allowed).toBe(true);
  });
});

describe("checkCommand", () => {
  it("blocks rm -rf", () => {
    expect(checkCommand("rm -rf /tmp/test").allowed).toBe(false);
    expect(checkCommand("sudo rm -rf /").allowed).toBe(false);
  });

  it("blocks kubectl apply", () => {
    expect(checkCommand("kubectl apply -f deployment.yaml").allowed).toBe(false);
  });

  it("blocks terraform apply", () => {
    expect(checkCommand("terraform apply").allowed).toBe(false);
  });

  it("blocks force push", () => {
    expect(checkCommand("git push --force origin main").allowed).toBe(false);
    expect(checkCommand("git push -f origin main").allowed).toBe(false);
    expect(checkCommand("git push main").allowed).toBe(false);
  });

  it("blocks publish and deploy commands", () => {
    expect(checkCommand("npm run deploy").allowed).toBe(false);
    expect(checkCommand("pnpm run deploy").allowed).toBe(false);
    expect(checkCommand("npm publish").allowed).toBe(false);
    expect(checkCommand("pnpm publish").allowed).toBe(false);
    expect(checkCommand("vercel deploy").allowed).toBe(false);
  });

  it("allows safe operations", () => {
    expect(checkCommand("pnpm typecheck").allowed).toBe(true);
    expect(checkCommand("pnpm test").allowed).toBe(true);
    expect(checkCommand("pnpm lint").allowed).toBe(true);
    expect(checkCommand("grep -r useState src/").allowed).toBe(true);
    expect(checkCommand("ls -la").allowed).toBe(true);
    expect(checkCommand("cat package.json").allowed).toBe(true);
    expect(checkCommand("find . -name '*.ts'").allowed).toBe(true);
  });

  it("blocks git push to main and master branches", () => {
    expect(checkCommand("git push origin main").allowed).toBe(false);
    expect(checkCommand("git push origin master").allowed).toBe(false);
  });

  it("blocks docker push", () => {
    expect(checkCommand("docker push myimage:latest").allowed).toBe(false);
  });

  it("blocks heroku", () => {
    expect(checkCommand("heroku deploy").allowed).toBe(false);
    expect(checkCommand("heroku releases").allowed).toBe(false);
  });
});

describe("checkPathInWorktree", () => {
  const WORKTREE = "/tmp/gridiron/worktrees/task-abc123";

  it("allows paths inside the worktree", () => {
    expect(checkPathInWorktree("src/index.ts", WORKTREE).allowed).toBe(true);
    expect(checkPathInWorktree(`${WORKTREE}/src/index.ts`, WORKTREE).allowed).toBe(true);
    expect(checkPathInWorktree("packages/shared-types/src/types.ts", WORKTREE).allowed).toBe(true);
  });

  it("blocks path traversal outside worktree", () => {
    const result = checkPathInWorktree(`${WORKTREE}/../../etc/passwd`, WORKTREE);
    expect(result.allowed).toBe(false);
    expect(result.reason).toContain("escapes worktree boundary");
  });

  it("blocks absolute paths outside worktree", () => {
    const result = checkPathInWorktree("/etc/passwd", WORKTREE);
    expect(result.allowed).toBe(false);
  });

  it("still applies .env protection inside worktree", () => {
    expect(checkPathInWorktree(".env", WORKTREE).allowed).toBe(false);
    expect(checkPathInWorktree(".env.production", WORKTREE).allowed).toBe(false);
    expect(checkPathInWorktree(".github/workflows/ci.yml", WORKTREE).allowed).toBe(false);
  });
});
