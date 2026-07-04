// Persistent cross-level knowledge graph (municipal ↔ state ↔ federal).
// Everything researched gets saved here and connected: politicians, offices,
// races, issues, orgs, and scenario events — with edges that cross government
// levels (preemption, funding flows, appointments, career pipelines, coattails).
import { chat, extractJSON, RESEARCH_MODEL } from "./llm";
import { listPoliticians, slugify } from "./db";
import { getCachedElection, type DiscoveredRace } from "./discovery";
import { kvGet, kvSet, NS } from "./store";
import type { GraphEdge, GraphNode, KnowledgeGraph, ScenarioTree } from "./types";

// The knowledge graph is a singleton document.
const GRAPH_KEY = "graph";

export async function loadGraph(): Promise<KnowledgeGraph> {
  const g = await kvGet<KnowledgeGraph>(NS.graph, GRAPH_KEY);
  return g ?? { nodes: [], edges: [], built_at: new Date().toISOString() };
}

export async function saveGraph(g: KnowledgeGraph): Promise<void> {
  g.built_at = new Date().toISOString();
  await kvSet(NS.graph, GRAPH_KEY, g);
}

const edgeKey = (e: GraphEdge) => `${e.source}→${e.rel}→${e.target}`;

export function mergeIntoGraph(
  g: KnowledgeGraph,
  nodes: GraphNode[],
  edges: GraphEdge[]
): KnowledgeGraph {
  const nodeMap = new Map(g.nodes.map((n) => [n.id, n]));
  for (const n of nodes) {
    const prev = nodeMap.get(n.id);
    nodeMap.set(n.id, prev ? { ...prev, ...n, meta: { ...prev.meta, ...n.meta } } : n);
  }
  const edgeMap = new Map(g.edges.map((e) => [edgeKey(e), e]));
  for (const e of edges) {
    if (!nodeMap.has(e.source) || !nodeMap.has(e.target)) continue;
    const prev = edgeMap.get(edgeKey(e));
    edgeMap.set(edgeKey(e), prev && prev.confidence >= e.confidence ? prev : e);
  }
  return { nodes: [...nodeMap.values()], edges: [...edgeMap.values()], built_at: g.built_at };
}

/** Deterministic layer: everything we already have cached becomes nodes+edges. */
export async function buildDeterministicLayer(state: string): Promise<{ nodes: GraphNode[]; edges: GraphEdge[] }> {
  const nodes: GraphNode[] = [];
  const edges: GraphEdge[] = [];
  const races = (await getCachedElection(state)) ?? [];

  for (const r of races) {
    const raceId = `race:${slugify(r.race)}`;
    const officeId = `office:${slugify(r.office)}`;
    const level = /u\.s\.|senate|congress|president/i.test(r.office) ? "federal" : "state";
    nodes.push(
      { id: raceId, type: "race", label: r.race, meta: { election_date: r.election_date, level } },
      { id: officeId, type: "office", label: r.office, meta: { level } }
    );
    edges.push({
      source: raceId, target: officeId, rel: "elects", kind: "fact", confidence: 1,
      sources: [], description: `${r.race} decides who holds ${r.office}`,
    });
    for (const c of r.candidates) {
      const pid = `pol:${slugify(c.name)}`;
      nodes.push({ id: pid, type: "politician", label: c.name, meta: { party: c.party, slug: slugify(c.name) } });
      edges.push({ source: pid, target: raceId, rel: "running_for", kind: "fact", confidence: 1, sources: [] });
    }
  }

  for (const p of await listPoliticians()) {
    const pid = `pol:${p.id}`;
    nodes.push({
      id: pid, type: "politician", label: p.name,
      meta: { party: p.party ?? null, slug: p.id, office: p.current_office ?? null },
    });
    if (p.current_office) {
      const officeId = `office:${slugify(p.current_office)}`;
      const level = /u\.s\.|senate|congress|president/i.test(p.current_office) ? "federal" : "state";
      nodes.push({ id: officeId, type: "office", label: p.current_office, meta: { level } });
      edges.push({ source: pid, target: officeId, rel: "holds", kind: "fact", confidence: 1, sources: [] });
    }
    for (const s of p.stances) {
      const issueId = `issue:${s.issue_id}`;
      nodes.push({ id: issueId, type: "issue", label: s.issue_id });
      edges.push({
        source: pid, target: issueId,
        rel: s.position_scalar === null ? "position_on" : s.position_scalar >= 0.5 ? "leans_1" : "leans_0",
        label: s.position_label, kind: "fact", confidence: s.confidence,
        sources: s.sources.slice(0, 2).map((src) => ({ title: src.title, url: src.url, publisher: src.publisher })),
      });
    }
  }
  return { nodes, edges };
}

/** Scenario trees become leads_to chains in the graph. */
export function scenarioLayer(tree: ScenarioTree): { nodes: GraphNode[]; edges: GraphEdge[] } {
  const nodes: GraphNode[] = [];
  const edges: GraphEdge[] = [];
  const raceId = `race:${tree.race_slug}`;
  const walk = (node: ScenarioTree["root"], parentId: string) => {
    const nid = `event:${tree.race_slug}:${node.id}`;
    nodes.push({
      id: nid, type: "event", label: node.label,
      meta: { timeframe: node.timeframe, kind: node.kind, likelihood: node.likelihood ?? null },
    });
    edges.push({
      source: parentId, target: nid, rel: "leads_to", kind: node.kind,
      confidence: node.kind === "fact" ? 0.95 : node.likelihood === "high" ? 0.7 : node.likelihood === "low" ? 0.3 : 0.5,
      description: node.description,
      sources: node.sources.map((s) => ({ title: s.title, url: s.url, publisher: s.publisher })),
    });
    for (const c of node.children) walk(c, nid);
  };
  nodes.push({ id: raceId, type: "race", label: tree.race });
  for (const c of tree.root.children) walk(c, raceId);
  return { nodes, edges };
}

/** Connection agent: researches CROSS-LEVEL links (municipal ↔ state ↔ federal). */
export async function runConnectionAgent(
  focus: string,
  context: string
): Promise<{ nodes: GraphNode[]; edges: GraphEdge[] }> {
  const out = await chat(
    [
      {
        role: "user",
        content: `You are a neutral government-structure researcher. Use web search to map how "${focus}" connects ACROSS LEVELS of U.S. government (municipal ↔ state ↔ federal). Context: ${context}

Find concrete, verifiable connections such as:
- preemption: state laws that override or could override municipal policies (and vice-versa pressure)
- funding flows: federal → state → municipal program dollars this office controls or administers
- appointment/succession powers crossing levels
- career pipeline: which lower offices feed this one, which higher offices its holders pursue (name real people where documented)
- coattails/party infrastructure effects between ballot levels

Return ONLY JSON:
{"nodes": [{"id": "type:slug (type ∈ pol|office|race|org|event|issue)", "type": "politician|office|race|organization|event|issue", "label": "...", "meta": {"level": "municipal|state|federal"}}],
 "edges": [{"source": "node id", "target": "node id", "rel": "preempts|funds|appoints|pipeline_to|influences|succession", "description": "one neutral sentence", "kind": "fact"|"inference", "confidence": 0.0-1.0, "sources": [{"title", "url", "publisher"}]}]}

Rules: fact edges REQUIRE a real source URL; max 10 nodes, 14 edges; neutral tone.`,
      },
    ],
    { model: RESEARCH_MODEL, maxTokens: 6144, timeoutMs: 180_000 }
  );
  try {
    const parsed = extractJSON<{ nodes: GraphNode[]; edges: GraphEdge[] }>(out);
    const nodes = (parsed.nodes ?? []).filter((n) => n?.id && n?.label);
    const ids = new Set(nodes.map((n) => n.id));
    const edges = (parsed.edges ?? []).filter(
      (e) =>
        e?.source && e?.target &&
        (e.kind !== "fact" || (e.sources ?? []).some((s) => s?.url?.startsWith("http")))
    );
    return { nodes, edges: edges.filter((e) => ids.has(e.source) || ids.has(e.target)) };
  } catch {
    return { nodes: [], edges: [] };
  }
}

/** Neighborhood query for the UI. */
export function neighborhood(g: KnowledgeGraph, focusId: string, depth: number): KnowledgeGraph {
  const keep = new Set<string>([focusId]);
  for (let d = 0; d < depth; d++) {
    for (const e of g.edges) {
      if (keep.has(e.source)) keep.add(e.target);
      if (keep.has(e.target)) keep.add(e.source);
    }
  }
  return {
    nodes: g.nodes.filter((n) => keep.has(n.id)),
    edges: g.edges.filter((e) => keep.has(e.source) && keep.has(e.target)),
    built_at: g.built_at,
  };
}

export type { DiscoveredRace };
