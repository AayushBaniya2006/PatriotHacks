// Backfill qualitative (character) dimensions for already-cached profiles.
// Usage: npx tsx scripts/backfill-qual.ts
import { config } from "dotenv";
config({ path: ".env.local" });

import { listPoliticians, savePolitician } from "../lib/db";
import { runQualitativeAgent } from "../lib/agents";

async function main() {
  const profiles = await listPoliticians();
  // Skip profiles already checked where the agent verifiably found nothing —
  // data_quality distinguishes "researched, found nothing" from "never ran".
  const todo = profiles.filter(
    (p) =>
      (!p.qualitative || p.qualitative.length === 0) &&
      !(p.data_quality?.qualitative?.researched && !p.data_quality.qualitative.found)
  );
  console.log(`${todo.length}/${profiles.length} profiles need qualitative backfill`);

  const queue = [...todo];
  const workers = Array.from({ length: 3 }, async () => {
    while (queue.length) {
      const p = queue.shift()!;
      console.log(`[start] ${p.name}`);
      try {
        const checkedAt = new Date().toISOString();
        const dims = await runQualitativeAgent(p.name, checkedAt);
        p.qualitative = dims;
        // Explicit marker: researched, and whether anything verifiable came back.
        p.data_quality = {
          ...p.data_quality,
          qualitative: { researched: true, found: dims.length > 0, checked_at: checkedAt },
        };
        await savePolitician(p);
        console.log(
          `[done]  ${p.name}: ${dims.length > 0 ? dims.map((d) => `${d.id}=${d.score.toFixed(2)}`).join(" ") : "nothing verifiable found (marked)"}`
        );
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
