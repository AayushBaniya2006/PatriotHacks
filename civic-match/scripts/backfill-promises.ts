// Backfill promise-vs-record scorecards for cached profiles.
// Usage: npx tsx scripts/backfill-promises.ts
import { config } from "dotenv";
config({ path: ".env.local" });

import { listPoliticians, savePolitician } from "../lib/db";
import { runAccountabilityAgent } from "../lib/agents";

async function main() {
  const profiles = await listPoliticians();
  // data_quality distinguishes "researched, found nothing" from "never ran".
  const todo = profiles.filter(
    (p) =>
      (!p.promise_record || p.promise_record.length === 0) &&
      !(p.data_quality?.accountability?.researched && !p.data_quality.accountability.found)
  );
  console.log(`${todo.length}/${profiles.length} profiles need promise backfill`);
  const queue = [...todo];
  const workers = Array.from({ length: 3 }, async () => {
    while (queue.length) {
      const p = queue.shift()!;
      console.log(`[start] ${p.name}`);
      try {
        const checkedAt = new Date().toISOString();
        p.promise_record = await runAccountabilityAgent(p.name, checkedAt);
        p.data_quality = {
          ...p.data_quality,
          accountability: {
            researched: true,
            found: p.promise_record.length > 0,
            checked_at: checkedAt,
          },
        };
        await savePolitician(p);
        const counts = p.promise_record.reduce(
          (a, r) => ((a[r.verdict] = (a[r.verdict] ?? 0) + 1), a),
          {} as Record<string, number>
        );
        console.log(
          `[done]  ${p.name}:`,
          p.promise_record.length > 0 ? counts : "nothing verifiable found (marked)"
        );
      } catch (e) {
        console.error(`[fail]  ${p.name}:`, e instanceof Error ? e.message : e);
      }
    }
  });
  await Promise.all(workers);
  console.log("Promise backfill complete.");
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
