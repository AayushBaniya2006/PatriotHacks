// Ground-truth validator (issue #7): fails (exit 1) if any rendered fact lacks
// a source. Run before every push: npx tsx scripts/validate-ground-truth.ts
import { config } from "dotenv";
config({ path: ".env.local" });

import { kvGet, kvList, NS } from "../lib/store";
import type {
  GraphEdge,
  KnowledgeGraph,
  PoliticianProfile,
  ScenarioNode,
  ScenarioTree,
} from "../lib/types";

let failures = 0;
const fail = (msg: string) => {
  failures++;
  console.error(`✗ ${msg}`);
};

const hasUrl = (sources?: { url: string }[]) =>
  (sources ?? []).some((s) => /^https?:\/\//.test(s.url));

async function main() {
  // profiles
  const profiles = await kvList<PoliticianProfile>(NS.politicians);
  for (const p of profiles) {
    for (const s of p.stances) {
      if (!hasUrl(s.sources)) fail(`${p.id}: stance ${s.issue_id} has no valid source`);
    }
    for (const q of p.qualitative ?? []) {
      if (!hasUrl(q.sources)) fail(`${p.id}: qualitative ${q.id} has no valid source`);
    }
    for (const [i, r] of (p.promise_record ?? []).entries()) {
      if (!/^https?:\/\//.test(r.promise_source?.url ?? ""))
        fail(`${p.id}: promise ${i} has no promise source`);
      if (r.verdict !== "untested" && !hasUrl(r.action_sources))
        fail(`${p.id}: promise ${i} verdict=${r.verdict} without action receipts`);
    }
    for (const [i, d] of (p.finance?.top_donors ?? []).entries()) {
      if (!/^https?:\/\//.test(d.source?.url ?? "")) fail(`${p.id}: donor ${i} has no source`);
    }
    for (const [i, c] of (p.finance?.correlations ?? []).entries()) {
      if (!hasUrl(c.sources)) fail(`${p.id}: money correlation ${i} has no source`);
    }
  }
  console.log(`profiles: ${profiles.length} checked`);

  // scenarios
  const trees = await kvList<ScenarioTree>(NS.scenarios);
  for (const t of trees) {
    const walk = (n: ScenarioNode) => {
      if (n.kind === "fact" && !hasUrl(n.sources))
        fail(`scenario ${t.race_slug}: fact node "${n.label}" has no source`);
      n.children.forEach(walk);
    };
    walk(t.root);
  }
  console.log(`scenarios: ${trees.length} trees checked`);

  // graph
  const g = await kvGet<KnowledgeGraph>(NS.graph, "graph");
  if (g) {
    for (const e of g.edges as (GraphEdge & { derived?: boolean })[]) {
      if (e.kind === "fact" && !e.derived && !hasUrl(e.sources))
        fail(`graph: fact edge ${e.source} →${e.rel}→ ${e.target} has no source (and not derived)`);
    }
    console.log(`graph: ${g.edges.length} edges checked`);
  }

  if (failures > 0) {
    console.error(`\nGROUND TRUTH VALIDATION FAILED: ${failures} violation(s). No source, no claim.`);
    process.exit(1);
  }
  console.log("\n✓ Ground truth validated: every fact carries a source.");
  process.exit(0);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
