// One-shot fix for ground-truth violations (issue #7):
// 1. Scenario nodes with kind=fact but no sources → demoted to inference/medium.
// 2. Deterministic graph edges (structural: elects/running_for/holds/leans_*)
//    get `derived: true` — they're derived from already-sourced dataset records.
//    Researched fact edges without sources → demoted to inference.
// Usage: npx tsx scripts/fix-ground-truth.ts
import { config } from "dotenv";
config({ path: ".env.local" });

import { kvGet, kvList, kvSet, NS } from "../lib/store";
import type { GraphEdge, KnowledgeGraph, ScenarioNode, ScenarioTree } from "../lib/types";

const STRUCTURAL_RELS = new Set(["elects", "running_for", "holds", "leans_0", "leans_1", "position_on", "leads_to"]);

async function main() {
  // 1. scenarios
  const trees = await kvList<ScenarioTree>(NS.scenarios);
  for (const tree of trees) {
    let demoted = 0;
    const walk = (n: ScenarioNode) => {
      if (n.kind === "fact" && (!n.sources || n.sources.length === 0)) {
        n.kind = "inference";
        n.likelihood = n.likelihood ?? "medium";
        demoted++;
      }
      n.children.forEach(walk);
    };
    walk(tree.root);
    if (demoted > 0) {
      await kvSet(NS.scenarios, tree.race_slug, tree);
      console.log(`[scenario] ${tree.race_slug}: demoted ${demoted} unsourced facts → inference`);
    }
  }

  // 2. graph
  const g = await kvGet<KnowledgeGraph>(NS.graph, "graph");
  if (g) {
    let derived = 0, demoted = 0;
    for (const e of g.edges as (GraphEdge & { derived?: boolean })[]) {
      if (e.kind === "fact" && (!e.sources || e.sources.length === 0)) {
        if (STRUCTURAL_RELS.has(e.rel)) {
          e.derived = true; // provenance: the sourced election/profile records
          derived++;
        } else {
          e.kind = "inference";
          demoted++;
        }
      }
    }
    await kvSet(NS.graph, "graph", g);
    console.log(`[graph] marked ${derived} structural edges derived, demoted ${demoted} to inference`);
  }
  console.log("Ground-truth fix complete.");
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
