// Backfill follow-the-money data for cached profiles.
import { config } from "dotenv";
config({ path: ".env.local" });
import { listPoliticians, savePolitician } from "../lib/db";
import { runFinanceAgent } from "../lib/agents";

async function main() {
  const profiles = await listPoliticians();
  // data_quality distinguishes "researched, found nothing" from "never ran".
  const todo = profiles.filter(
    (p) =>
      !p.finance &&
      !(p.data_quality?.finance?.researched && !p.data_quality.finance.found)
  );
  console.log(`${todo.length}/${profiles.length} profiles need finance backfill`);
  const queue = [...todo];
  const workers = Array.from({ length: 3 }, async () => {
    while (queue.length) {
      const p = queue.shift()!;
      console.log(`[start] ${p.name}`);
      try {
        const checkedAt = new Date().toISOString();
        p.finance = await runFinanceAgent(
          p.name,
          checkedAt,
          p.stances.map((s) => ({ issue_id: s.issue_id, position: s.position_label }))
        );
        const found = !!(
          p.finance &&
          (p.finance.top_donors.length > 0 || p.finance.correlations.length > 0 || p.finance.total_raised)
        );
        p.data_quality = {
          ...p.data_quality,
          finance: { researched: true, found, checked_at: checkedAt },
        };
        await savePolitician(p);
        console.log(
          `[done]  ${p.name}: ${found ? `${p.finance?.top_donors.length ?? 0} donors, ${p.finance?.correlations.length ?? 0} correlations` : "nothing verifiable found (marked)"}`
        );
      } catch (e) {
        console.error(`[fail]  ${p.name}:`, e instanceof Error ? e.message : e);
      }
    }
  });
  await Promise.all(workers);
  console.log("Finance backfill complete.");
}
main().catch((e) => { console.error(e); process.exit(1); });
