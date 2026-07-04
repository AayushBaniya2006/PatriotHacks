// Materialize seed config into the file DB (data/config/*.json).
// After this runs, the DB is the source of truth — edit the JSON, not code.
// Usage: npm run export:config
import { promises as fs } from "fs";
import path from "path";
import { ISSUES } from "../lib/issues";
import { DEFAULT_UI } from "../lib/config";

async function main() {
  const dir = path.join(process.cwd(), "data", "config");
  await fs.mkdir(dir, { recursive: true });
  await fs.writeFile(path.join(dir, "issues.json"), JSON.stringify(ISSUES, null, 2));
  await fs.writeFile(path.join(dir, "ui.json"), JSON.stringify(DEFAULT_UI, null, 2));
  console.log(`Wrote ${ISSUES.length} issues + UI config to data/config/`);
}

main();
