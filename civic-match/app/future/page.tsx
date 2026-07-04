"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { hierarchy, tree, type HierarchyPointNode } from "d3-hierarchy";
import { loadPrefs } from "@/lib/prefs";
import type { ScenarioNode, ScenarioTree, UserPreferences } from "@/lib/types";

const NODE_W = 240;
const NODE_H = 84;
const GAP_X = 90; // horizontal gap between depths
const GAP_Y = 26; // vertical gap between siblings

function nodeColor(n: ScenarioNode): string {
  if (n.kind === "fact") return "#34d399"; // emerald
  if (n.likelihood === "high") return "#38bdf8"; // sky
  if (n.likelihood === "low") return "#71717a"; // zinc
  return "#facc15"; // yellow = medium
}

const LIKELIHOOD_RANK: Record<string, number> = { high: 3, medium: 2, low: 1 };
function nodeRank(n: ScenarioNode): number {
  return n.kind === "fact" ? 4 : LIKELIHOOD_RANK[n.likelihood ?? "medium"] ?? 2;
}

function affectsUser(n: ScenarioNode, prefs: UserPreferences | null): string[] {
  if (!prefs) return [];
  const hits: string[] = [];
  for (const id of n.issue_ids ?? []) {
    if ((prefs.priority_weights[id] ?? 0) > 0) hits.push(id.replace(/_/g, " "));
  }
  const flags = prefs.profile?.flags ?? {};
  for (const g of n.affected_groups ?? []) {
    if (g === flags.healthcare || flags[g as keyof typeof flags] === true)
      hits.push(g.replace(/_/g, " "));
  }
  return [...new Set(hits)];
}

export default function FuturePage() {
  const [available, setAvailable] = useState<{ race: string; slug: string }[]>([]);
  const [treeData, setTreeData] = useState<ScenarioTree | null>(null);
  const [loading, setLoading] = useState(true);
  const [prefs, setPrefs] = useState<UserPreferences | null>(null);
  const [selected, setSelected] = useState<ScenarioNode | null>(null);
  const treePaneRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    setPrefs(loadPrefs());
  }, []);

  const loadTree = useCallback((slug: string) => {
    setLoading(true);
    setSelected(null);
    fetch(`/api/scenario?race=${slug}`)
      .then((r) => r.json())
      .then((t) => {
        setTreeData(t.error ? null : t);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, []);

  useEffect(() => {
    let cancelled = false;

    fetch("/api/scenario")
      .then((r) => r.json())
      .then((d) => {
        if (cancelled) return;
        const nextAvailable = d.available ?? [];
        setAvailable(nextAvailable);
        if (nextAvailable.length) loadTree(nextAvailable[0].slug);
        else setLoading(false);
      })
      .catch(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [loadTree]);

  // d3-hierarchy layout: depth → x (left→right), siblings → y
  const layout = useMemo(() => {
    if (!treeData) return null;
    const root = hierarchy<ScenarioNode>(treeData.root, (d) => d.children);
    const t = tree<ScenarioNode>().nodeSize([NODE_H + GAP_Y, NODE_W + GAP_X]);
    const laid = t(root);
    const nodes = laid.descendants();
    const links = laid.links();
    let minX = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (const n of nodes) {
      minX = Math.min(minX, n.x);
      maxX = Math.max(maxX, n.x);
      maxY = Math.max(maxY, n.y);
    }
    const offsetX = -minX + 20;
    const width = maxY + NODE_W + 60;
    const height = maxX - minX + NODE_H + 40;
    return { nodes, links, offsetX, width, height };
  }, [treeData]);

  // Most likely down-the-line chain: from the root, follow the
  // highest-likelihood child at every branch (fact > high > medium > low).
  const mostLikely = useMemo(() => {
    if (!treeData) return { ids: new Set<string>(), path: [] as ScenarioNode[] };
    const path: ScenarioNode[] = [];
    let cur: ScenarioNode | undefined = treeData.root;
    while (cur) {
      path.push(cur);
      cur = [...cur.children].sort((a, b) => nodeRank(b) - nodeRank(a))[0];
    }
    return { ids: new Set(path.map((p) => p.id)), path };
  }, [treeData]);

  useEffect(() => {
    const pane = treePaneRef.current;
    if (!pane || !layout) return;

    const pathTops = layout.nodes
      .filter((n) => mostLikely.ids.has(n.data.id))
      .map((n) => n.x + layout.offsetX);
    const firstUsefulTop = pathTops.length ? Math.min(...pathTops) : 0;
    pane.scrollTop = Math.max(0, firstUsefulTop - 24);
    pane.scrollLeft = 0;
  }, [layout, mostLikely.ids, treeData?.race_slug]);

  const pos = (n: HierarchyPointNode<ScenarioNode>) => ({
    left: n.y + 10,
    top: n.x + (layout?.offsetX ?? 0),
  });

  return (
    <div className="mx-auto max-w-7xl px-4 py-10">
      <h1 className="text-2xl font-bold mb-1">Down the line</h1>
      <p className="text-sm text-zinc-500 mb-2 max-w-2xl">
        A branching node tree of what each outcome sets in motion — follow any path
        from the election to its leaf-node futures. Facts carry sources; projections
        are labeled with likelihood. Click a node for details and ground truth.
      </p>
      {prefs && (
        <p className="text-xs text-emerald-400/80 mb-4">
          Nodes ringed in green touch your stated priorities or situation.
        </p>
      )}

      <div className="flex flex-wrap items-center gap-2 mb-4">
        {available.map((a) => (
          <button
            key={a.slug}
            onClick={() => loadTree(a.slug)}
            aria-pressed={treeData?.race_slug === a.slug}
            className={`rounded-full border px-4 py-1.5 text-sm ${
              treeData?.race_slug === a.slug
                ? "border-emerald-400 bg-emerald-500/15 text-emerald-300"
                : "border-zinc-700 text-zinc-300 hover:border-zinc-500"
            }`}
          >
            {a.race}
          </button>
        ))}
        <div className="ml-auto flex gap-3 text-[11px] text-zinc-500">
          <span><span className="inline-block h-2 w-2 rounded-full mr-1" style={{ background: "#34d399" }} />fact</span>
          <span><span className="inline-block h-2 w-2 rounded-full mr-1" style={{ background: "#38bdf8" }} />high</span>
          <span><span className="inline-block h-2 w-2 rounded-full mr-1" style={{ background: "#facc15" }} />medium</span>
          <span><span className="inline-block h-2 w-2 rounded-full mr-1" style={{ background: "#71717a" }} />low</span>
        </div>
      </div>

      {loading ? (
        <div role="status" aria-live="polite" className="text-zinc-500 animate-pulse">Loading scenario tree…</div>
      ) : !treeData || !layout ? (
        <p className="text-sm text-zinc-500 border border-dashed border-zinc-800 rounded-lg p-6">
          No scenario trees built yet — run <code className="text-zinc-300">npm run seed:graph</code>.
        </p>
      ) : (
        <>
        {mostLikely.path.length > 1 && (
          <div className="mb-4 rounded-xl border border-sky-500/30 bg-sky-500/5 p-3">
            <div className="text-[10px] uppercase tracking-wider text-sky-400 mb-1.5">
              Most likely down the line (per current polling & likelihood labels — not a forecast)
            </div>
            <div className="flex flex-wrap items-center gap-1.5 text-xs">
              {mostLikely.path.slice(1).map((n, i) => (
                <span key={n.id} className="flex items-center gap-1.5">
                  {i > 0 && <span className="text-zinc-600">→</span>}
	                  <button
	                    onClick={() => setSelected(n)}
	                    aria-pressed={selected === n}
	                    className="rounded-full border px-2.5 py-1 hover:bg-zinc-800"
                    style={{ borderColor: nodeColor(n), color: nodeColor(n) }}
                  >
                    {n.label.length > 44 ? n.label.slice(0, 43) + "…" : n.label}
                    <span className="ml-1 text-[9px] text-zinc-500">{n.timeframe}</span>
                  </button>
                </span>
              ))}
            </div>
          </div>
        )}
        <div className="grid gap-4 lg:grid-cols-[1fr_340px]">
          <div ref={treePaneRef} className="rounded-xl border border-zinc-800 bg-zinc-950 overflow-auto max-h-[75vh]">
            <div className="relative" style={{ width: layout.width, height: layout.height }}>
              <svg className="absolute inset-0" width={layout.width} height={layout.height}>
                {layout.links.map((l, i) => {
                  const s = pos(l.source);
                  const t = pos(l.target);
                  const x1 = s.left + NODE_W;
                  const y1 = s.top + NODE_H / 2;
                  const x2 = t.left;
                  const y2 = t.top + NODE_H / 2;
                  const mx = (x1 + x2) / 2;
                  return (
                    <path
                      key={i}
                      d={`M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`}
                      fill="none"
                      stroke={nodeColor(l.target.data)}
                      strokeOpacity={mostLikely.ids.has(l.target.data.id) && mostLikely.ids.has(l.source.data.id) ? 0.9 : 0.35}
                      strokeWidth={mostLikely.ids.has(l.target.data.id) && mostLikely.ids.has(l.source.data.id) ? 2.5 : 1.2}
                      strokeDasharray={l.target.data.kind === "inference" ? "5 4" : undefined}
                    />
                  );
                })}
              </svg>
              {layout.nodes.map((n) => {
                const p = pos(n);
                const hits = affectsUser(n.data, prefs);
                const color = nodeColor(n.data);
                const isSel = selected === n.data;
                const onPath = mostLikely.ids.has(n.data.id);
                return (
	                  <button
	                    key={`${n.depth}-${n.data.id}`}
	                    onClick={() => setSelected(n.data)}
	                    aria-pressed={isSel}
	                    className={`absolute rounded-lg border p-2.5 text-left transition hover:bg-zinc-800 ${
                      isSel ? "ring-2 ring-white/70" : ""
                    } ${hits.length > 0 ? "shadow-[0_0_0_2px_rgba(52,211,153,0.5)]" : ""} ${
                      onPath ? "bg-zinc-800/90 border-2" : "bg-zinc-900 opacity-80"
                    }`}
                    style={{
                      left: p.left,
                      top: p.top,
                      width: NODE_W,
                      height: NODE_H,
                      borderColor: color,
                    }}
                  >
                    <div className="flex items-center gap-1.5 mb-1">
                      <span className="h-1.5 w-1.5 rounded-full shrink-0" style={{ background: color }} />
                      <span className="text-[10px] text-zinc-500">{n.data.timeframe}</span>
                      <span className="text-[9px] uppercase tracking-wide" style={{ color }}>
                        {n.data.kind === "fact" ? "fact" : n.data.likelihood}
                      </span>
                      {hits.length > 0 && (
                        <span className="ml-auto text-[9px] text-emerald-300">● you</span>
                      )}
                    </div>
                    <div className="text-xs font-medium text-zinc-200 leading-snug line-clamp-3">
                      {n.data.label}
                    </div>
                  </button>
                );
              })}
            </div>
          </div>

          <div className="rounded-xl border border-zinc-800 bg-zinc-900/50 p-4 text-sm max-h-[75vh] overflow-y-auto">
            {!selected ? (
              <p className="text-zinc-500">
                {layout.nodes.length} nodes across {Math.max(...layout.nodes.map((n) => n.depth)) + 1} levels.
                Click any node to inspect it.
              </p>
            ) : (
              <>
                <div className="flex items-center gap-2 mb-1">
                  <span className="h-2.5 w-2.5 rounded-full" style={{ background: nodeColor(selected) }} />
                  <span className="font-semibold">{selected.label}</span>
                </div>
                <p className="text-xs text-zinc-500 mb-2">
                  {selected.timeframe} ·{" "}
                  {selected.kind === "fact" ? "documented fact" : `projection — ${selected.likelihood} likelihood`}
                </p>
                <p className="text-zinc-300 mb-3">{selected.description}</p>
                {affectsUser(selected, prefs).length > 0 && (
                  <div className="mb-3 flex flex-wrap gap-1.5">
                    {affectsUser(selected, prefs).map((h) => (
                      <span key={h} className="rounded-full bg-emerald-500/15 border border-emerald-400/40 px-2 py-0.5 text-[10px] text-emerald-300">
                        affects {h}
                      </span>
                    ))}
                  </div>
                )}
                {selected.sources.length > 0 ? (
                  <div className="space-y-1.5">
                    <h3 className="text-xs uppercase tracking-wider text-zinc-500">Ground truth</h3>
                    {selected.sources.map((s, i) => (
                      <a key={i} href={s.url} target="_blank" className="block text-xs text-emerald-400 hover:underline">
                        {s.title}{s.publisher ? ` — ${s.publisher}` : ""} ↗
                      </a>
                    ))}
                  </div>
                ) : (
                  <p className="text-xs text-zinc-600">
                    Projection — no direct source; derived from the parent chain&apos;s evidence.
                  </p>
                )}
                {selected.children.length > 0 && (
                  <p className="mt-3 text-xs text-zinc-500">
                    {selected.children.length} downstream branch{selected.children.length > 1 ? "es" : ""} →
                  </p>
                )}
              </>
            )}
          </div>
        </div>
        </>
      )}
    </div>
  );
}
