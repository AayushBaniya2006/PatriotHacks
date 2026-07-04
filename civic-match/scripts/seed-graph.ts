// Build scenario trees for every discovered race + fold everything into the
// cross-level knowledge graph. Usage: npx tsx scripts/seed-graph.ts [state]
import { config } from "dotenv";
config({ path: ".env.local" });

import { getCachedElection } from "../lib/discovery";
import { buildScenarioTree, getScenario } from "../lib/scenario";
import {
  buildDeterministicLayer,
  loadGraph,
  mergeIntoGraph,
  runConnectionAgent,
  saveGraph,
  scenarioLayer,
} from "../lib/graph";
import { slugify } from "../lib/db";

async function main() {
  const state = process.argv[2] || "texas";
  const races = (await getCachedElection(state)) ?? [];
  if (races.length === 0) {
    console.error("No cached election — run npm run seed first.");
    process.exit(1);
  }

  console.log("1/3 Scenario trees (parallel)...");
  const trees = await Promise.all(
    races.map(async (r) => {
      const existing = await getScenario(slugify(r.race));
      if (existing) {
        console.log(`  [cache] ${r.race}`);
        return existing;
      }
      try {
        const t = await buildScenarioTree(r);
        console.log(`  [done]  ${r.race}: ${JSON.stringify(t.root.children.map((c) => c.label))}`);
        return t;
      } catch (e) {
        console.error(`  [fail]  ${r.race}:`, e instanceof Error ? e.message : e);
        return null;
      }
    })
  );

  console.log("2/3 Cross-level connection agents (parallel)...");
  const connections = await Promise.all(
    races.map((r) =>
      runConnectionAgent(
        r.office,
        `Race: ${r.race}, ${state}, election ${r.election_date}. Candidates: ${r.candidates
          .map((c) => `${c.name} (${c.party})`)
          .join(", ")}. Map municipal↔state↔federal connections for this office.`
      ).then((res) => {
        console.log(`  [done]  ${r.office}: ${res.nodes.length} nodes, ${res.edges.length} edges`);
        return res;
      })
    )
  );

  console.log("3/3 Merging graph...");
  let g = await loadGraph();
  const det = await buildDeterministicLayer(state);
  g = mergeIntoGraph(g, det.nodes, det.edges);
  for (const t of trees) if (t) {
    const layer = scenarioLayer(t);
    g = mergeIntoGraph(g, layer.nodes, layer.edges);
  }
  for (const c of connections) g = mergeIntoGraph(g, c.nodes, c.edges);
  await saveGraph(g);
  console.log(`Graph saved: ${g.nodes.length} nodes, ${g.edges.length} edges.`);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
