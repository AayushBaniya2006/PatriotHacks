// Targeted gap fixes for issue #6 — only the named statewide candidates.
// Usage: npx tsx scripts/fix-data-gaps.ts
import { config } from "dotenv";
config({ path: ".env.local" });

import { getPolitician, savePolitician } from "../lib/db";
import {
  researchPolitician,
  runAccountabilityAgent,
  runFinanceAgent,
  runQualitativeAgent,
} from "../lib/agents";

async function main() {
  const now = new Date().toISOString();

  await Promise.all([
    // Empty promise scorecards
    ...["clayton-tucker", "vikki-goodwin"].map(async (id) => {
      const p = await getPolitician(id);
      if (!p) return;
      p.promise_record = await runAccountabilityAgent(p.name, now);
      await savePolitician(p);
      console.log(`[promises] ${id}: ${p.promise_record.length} pairs`);
    }),
    // Missing finance
    (async () => {
      const p = await getPolitician("pat-dixon");
      if (!p) return;
      p.finance = await runFinanceAgent(p.name, now, p.stances.map((s) => ({ issue_id: s.issue_id, position: s.position_label })));
      await savePolitician(p);
      console.log(`[finance] pat-dixon: ${p.finance?.top_donors.length ?? 0} donors`);
    })(),
    // Missing qualitative dim
    (async () => {
      const p = await getPolitician("ken-paxton");
      if (!p) return;
      const dims = await runQualitativeAgent(p.name, now);
      if (dims.length >= (p.qualitative?.length ?? 0)) p.qualitative = dims;
      await savePolitician(p);
      console.log(`[qual] ken-paxton: ${p.qualitative?.length} dims`);
    })(),
    // Thin profile: full re-research
    researchPolitician("Nathan Sheets", (e) => {
      if (e.type === "complete") console.log(`[research] nathan-sheets: ${e.message}`);
    }),
  ]);
  console.log("Gap fixes complete.");
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
