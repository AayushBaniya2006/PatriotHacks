// Scenario tree builder: per race, a research agent projects a branching
// future-possibilities tree grounded in cached candidate evidence + web search
// (succession rules, term lengths, filed bills, announced plans).
import { chat, extractJSON, RESEARCH_MODEL } from "./llm";
import { getIssues } from "./config";
import { slugify, getPolitician } from "./db";
import { kvGet, kvSet, NS } from "./store";
import type { DiscoveredRace } from "./discovery";
import type { ScenarioNode, ScenarioTree } from "./types";

export async function getScenario(raceSlug: string): Promise<ScenarioTree | null> {
  return kvGet<ScenarioTree>(NS.scenarios, raceSlug);
}

function sanitize(node: ScenarioNode, depth = 0): ScenarioNode | null {
  if (!node?.label || depth > 5) return null;
  return {
    id: node.id || `n_${Math.random().toString(36).slice(2, 8)}`,
    label: String(node.label),
    timeframe: node.timeframe || "",
    kind: node.kind === "fact" ? "fact" : "inference",
    likelihood:
      node.kind === "fact"
        ? undefined
        : ["high", "medium", "low"].includes(node.likelihood ?? "")
        ? node.likelihood
        : "medium",
    description: node.description || "",
    issue_ids: (node.issue_ids ?? []).filter(Boolean),
    affected_groups: (node.affected_groups ?? []).filter(Boolean),
    sources: (node.sources ?? []).filter((s) => s?.url?.startsWith("http")),
    children: (node.children ?? [])
      .map((c) => sanitize(c, depth + 1))
      .filter((c): c is ScenarioNode => c !== null),
  };
}

export async function buildScenarioTree(race: DiscoveredRace): Promise<ScenarioTree> {
  const issueIds = getIssues().map((i) => i.id);
  // Ground the agent in our cached, sourced candidate evidence (minimize context:
  // labels only, not full stances).
  const candidateContext = await Promise.all(
    race.candidates.map(async (c) => {
      const p = await getPolitician(slugify(c.name));
      return {
        name: c.name,
        party: c.party,
        current_office: p?.current_office,
        top_positions: p?.stances.slice(0, 12).map((s) => `${s.issue_id}: ${s.position_label}`),
        broken_promises: p?.promise_record?.filter((r) => r.verdict === "broken").map((r) => r.promise),
        integrity_flags: p?.qualitative?.find((q) => q.id === "integrity" && q.score < 0.45)?.summary,
      };
    })
  );

  const out = await chat(
    [
      {
        role: "user",
        content: `You are a neutral election-scenario analyst. Build a branching FUTURE-POSSIBILITIES TREE for this race: "${race.race}" (election ${race.election_date}).

Candidates and their evidenced positions:
${JSON.stringify(candidateContext)}

Use web search to verify: term lengths, succession/vacancy rules (who appoints replacements), announced future ambitions, filed/promised legislation, and downstream elections affected.

Tree shape (JSON, max depth 4 below root, 2-4 children per node):
- ROOT: the race being decided.
- LEVEL 1: one branch per candidate: "<Name> wins".
- LEVEL 2: consequences of that win — policy actions they are on record intending (cite the record), offices vacated and WHO fills them (succession rules = fact), power shifts.
- LEVEL 3+: longer-term possibilities down the line — who could run for or be appointed to what in 2027/2028+, what policies compound, what elections open up. Be hyper-specific with names and offices where public evidence exists.

Every node: {"id": "unique", "label": "short headline", "timeframe": "2026-11|2027|2028+", "kind": "fact"|"inference", "likelihood": "high"|"medium"|"low" (inference only), "description": "1-2 neutral sentences", "issue_ids": subset of ${JSON.stringify(issueIds)}, "affected_groups": subset of ["renter","homeowner","kids_in_public_school","veteran","small_business_owner","student","employer","aca","medicare","uninsured"], "sources": [{"title","url","publisher"}] (REQUIRED for kind=fact, best-effort for inference), "children": [...]}

Rules: label speculation honestly as inference with likelihood; facts need real source URLs; neutral tone — describe both favorable and unfavorable branches for every candidate equally; no persuasion.

Return ONLY the root node JSON object.`,
      },
    ],
    { model: RESEARCH_MODEL, maxTokens: 16384, timeoutMs: 240_000 }
  );

  const root = sanitize(extractJSON<ScenarioNode>(out));
  if (!root) throw new Error("scenario agent returned no usable tree");

  const tree: ScenarioTree = {
    race: race.race,
    race_slug: slugify(race.race),
    built_at: new Date().toISOString(),
    root,
  };
  await kvSet(NS.scenarios, tree.race_slug, tree);
  return tree;
}
