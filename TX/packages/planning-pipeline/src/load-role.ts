import fs from "fs/promises";
import path from "path";
import { fileURLToPath } from "url";

const ROLES_DIR = path.resolve(
  fileURLToPath(import.meta.url),
  "../../../agent-runtime/roles",
);

export async function loadRole(name: string): Promise<string> {
  const filePath = path.join(ROLES_DIR, `${name}.md`);
  try {
    return (await fs.readFile(filePath, "utf8")).trim();
  } catch {
    throw new Error(`Role file not found: ${filePath}`);
  }
}
