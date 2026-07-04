// Backfill qualitative (character) dimensions for already-cached profiles.
// Usage: npx tsx scripts/backfill-qual.ts
import { config } from "dotenv";
config({ path: ".env.local" });

import { listPoliticians, savePolitician } from "../lib/db";
import { runQualitativeAgent } from "../lib/agents";

async function main() {
  const profiles = await listPoliticians();
  const todo = profiles.filter((p) => !p.qualitative || p.qualitative.length === 0);
  console.log(`${todo.length}/${profiles.length} profiles need qualitative backfill`);

  const queue = [...todo];
  const workers = Array.from({ length: 3 }, async () => {
    while (queue.length) {
      const p = queue.shift()!;
      console.log(`[start] ${p.name}`);
      try {
        const dims = await runQualitativeAgent(p.name, new Date().toISOString());
        p.qualitative = dims;
        await savePolitician(p);
        console.log(`[done]  ${p.name}: ${dims.map((d) => `${d.id}=${d.score.toFixed(2)}`).join(" ")}`);
      } catch (err) {
        console.error(`[fail]  ${p.name}:`, err instanceof Error ? err.message : err);
      }
    }
  });
  await Promise.all(workers);
  console.log("Backfill complete.");
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
