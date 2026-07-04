// Load the committed data/ ground truth into Postgres (kv table).
// Run once after attaching a Railway Postgres: DATABASE_URL=... npm run import:pg
import { config } from "dotenv";
config({ path: ".env.local" });

import { promises as fs } from "fs";
import path from "path";
import { kvSet, NS } from "../lib/store";

const DATA_DIR = path.join(process.cwd(), "data");

async function importDir(namespace: string): Promise<number> {
  const dir = path.join(DATA_DIR, namespace);
  let files: string[];
  try {
    files = (await fs.readdir(dir)).filter((f) => f.endsWith(".json"));
  } catch {
    return 0;
  }
  let n = 0;
  for (const f of files) {
    const key = f.replace(/\.json$/, "");
    try {
      const value = JSON.parse(await fs.readFile(path.join(dir, f), "utf-8"));
      await kvSet(namespace, key, value);
      n++;
    } catch (e) {
      console.error(`  [skip] ${namespace}/${f}:`, e instanceof Error ? e.message : e);
    }
  }
  return n;
}

async function main() {
  if (!process.env.DATABASE_URL) {
    console.error("DATABASE_URL not set — nothing to import into. (Without it, the app reads data/ directly.)");
    process.exit(1);
  }
  for (const ns of Object.values(NS)) {
    const n = await importDir(ns);
    console.log(`${ns}: imported ${n} records`);
  }
  console.log("Import complete.");
  process.exit(0);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
