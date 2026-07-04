// Pre-warm script (latency-first): auto-discovers the Texas November election,
// then runs the research swarm for every candidate and caches profiles.
// Usage: npx tsx scripts/seed.ts [state]
import { config } from "dotenv";
config({ path: ".env.local" });

import { discoverElection } from "../lib/discovery";
import { researchPolitician } from "../lib/agents";
import { getPolitician, slugify } from "../lib/db";

async function main() {
  const state = process.argv[2] || "texas";
  console.log(`Discovering November election races for ${state}...`);
  const races = await discoverElection(state);
  for (const r of races) {
    console.log(`  ${r.race} (${r.election_date}): ${r.candidates.map((c) => c.name).join(", ")}`);
  }

  const names = [...new Set(races.flatMap((r) => r.candidates.map((c) => c.name)))];
  console.log(`\nResearching ${names.length} candidates (parallel swarm per candidate)...`);

  // 2 candidates at a time; each candidate already fans out 5 parallel agents.
  const queue = [...names];
  const workers = Array.from({ length: 2 }, async () => {
    while (queue.length) {
      const name = queue.shift()!;
      if (await getPolitician(slugify(name))) {
        console.log(`[cache] ${name}`);
        continue;
      }
      console.log(`[start] ${name}`);
      try {
        const p = await researchPolitician(name, (e) => {
          if (e.type === "agent_done" || e.type === "complete")
            console.log(`  [${name}] ${e.message}`);
        });
        console.log(`[done]  ${name}: ${p.stances.length} stances, coverage ${(p.source_coverage_score * 100).toFixed(0)}%`);
      } catch (err) {
        console.error(`[fail]  ${name}:`, err instanceof Error ? err.message : err);
      }
    }
  });
  await Promise.all(workers);
  console.log("\nSeed complete. Profiles cached in data/politicians/.");
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
