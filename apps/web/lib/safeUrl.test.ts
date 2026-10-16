import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { safeExternalUrl } from "./safeUrl";

describe("safeExternalUrl (G13)", () => {
  it("keeps http(s) links", () => {
    expect(safeExternalUrl("https://github.com/o/r/pull/7")).toBe("https://github.com/o/r/pull/7");
    expect(safeExternalUrl("http://localhost:3000/x")).toBe("http://localhost:3000/x");
  });

  it.each(["javascript:alert(document.cookie)", "JavaScript:alert(1)", "data:text/html,<script>x</script>", "vbscript:x", "not a url", "", null])(
    "refuses %s",
    (value) => {
      expect(safeExternalUrl(value as string | null)).toBeNull();
    },
  );
});

describe("no raw-HTML sinks in the app (G13)", () => {
  const roots = ["app", "components", "lib"];
  const sink = /dangerouslySetInnerHTML|\.innerHTML\s*=|outerHTML\s*=|insertAdjacentHTML|document\.write|\beval\(|new Function\(/;

  function files(dir: string): string[] {
    return readdirSync(dir).flatMap((name) => {
      const path = join(dir, name);
      if (statSync(path).isDirectory()) return files(path);
      return /\.(tsx?|jsx?)$/.test(name) && !/\.test\./.test(name) ? [path] : [];
    });
  }

  it("React's escaping is never bypassed", () => {
    const offenders = roots
      .flatMap((r) => files(join(__dirname, "..", r)))
      .filter((f) => sink.test(readFileSync(f, "utf8")));
    expect(offenders).toEqual([]);
  });
});
