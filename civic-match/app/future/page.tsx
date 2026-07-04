"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { hierarchy, tree, type HierarchyPointNode } from "d3-hierarchy";
import { loadPrefs } from "@/lib/prefs";
import type { ScenarioNode, ScenarioTree, UserPreferences } from "@/lib/types";

const NODE_W = 248;
const NODE_H = 94;
const GAP_X = 88;
const GAP_Y = 28;

const LIKELIHOOD_RANK: Record<string, number> = { high: 3, medium: 2, low: 1 };

type Tone = {
  label: string;
  dot: string;
  border: string;
  text: string;
  line: string;
  surface: string;
};

function cn(...classes: Array<string | false | null | undefined>) {
  return classes.filter(Boolean).join(" ");
}

function nodeTone(n: ScenarioNode): Tone {
  if (n.kind === "fact") {
    return {
      label: "Fact",
      dot: "#b68d5d",
      border: "rgba(182,141,93,0.62)",
      text: "#d8bd8d",
      line: "rgba(182,141,93,0.74)",
      surface: "rgba(182,141,93,0.11)",
    };
  }
  if (n.likelihood === "high") {
    return {
      label: "High",
      dot: "#8fb7c6",
      border: "rgba(143,183,198,0.56)",
      text: "#bdd6df",
      line: "rgba(143,183,198,0.68)",
      surface: "rgba(143,183,198,0.10)",
    };
  }
  if (n.likelihood === "low") {
    return {
      label: "Low",
      dot: "#77828f",
      border: "rgba(119,130,143,0.46)",
      text: "#a9b0b8",
      line: "rgba(119,130,143,0.5)",
      surface: "rgba(119,130,143,0.09)",
    };
  }
  return {
    label: "Medium",
    dot: "#d8a15b",
    border: "rgba(216,161,91,0.54)",
    text: "#e6bf87",
    line: "rgba(216,161,91,0.62)",
    surface: "rgba(216,161,91,0.10)",
  };
}

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
  for (const group of n.affected_groups ?? []) {
    if (group === flags.healthcare || flags[group as keyof typeof flags] === true) {
      hits.push(group.replace(/_/g, " "));
    }
  }
  return [...new Set(hits)];
}

function countNodes(root?: ScenarioNode): number {
  if (!root) return 0;
  return 1 + root.children.reduce((sum, child) => sum + countNodes(child), 0);
}

function maxDepth(root?: ScenarioNode): number {
  if (!root) return 0;
  if (root.children.length === 0) return 1;
  return 1 + Math.max(...root.children.map((child) => maxDepth(child)));
}

function truncateLabel(label: string, limit = 58) {
  return label.length > limit ? `${label.slice(0, limit - 1)}...` : label;
}

function LegendItem({ node }: { node: ScenarioNode }) {
  const tone = nodeTone(node);
  return (
    <span className="inline-flex items-center gap-2 text-[11px] uppercase tracking-[0.16em] text-white/48">
      <span
        className="h-2 w-2 rounded-full"
        style={{ backgroundColor: tone.dot, boxShadow: `0 0 16px ${tone.dot}55` }}
      />
      {tone.label}
    </span>
  );
}

function SourceList({ sources }: { sources: ScenarioNode["sources"] }) {
  if (sources.length === 0) {
    return (
      <p className="rounded-[8px] border border-white/10 bg-white/[0.025] p-3 text-xs leading-5 text-white/42">
        Projection only: no direct source is attached to this node. Read it through the parent chain&apos;s evidence.
      </p>
    );
  }

  return (
    <div className="space-y-2">
      {sources.map((source, index) => (
        <a
          key={`${source.url}-${index}`}
          href={source.url}
          target="_blank"
          rel="noreferrer"
          className="block rounded-[8px] border border-white/10 bg-white/[0.025] p-3 text-xs leading-5 text-white/66 transition hover:border-gold/45 hover:bg-gold/10 hover:text-white"
        >
          <span className="block font-semibold text-gold">{source.title}</span>
          {source.publisher && <span className="mt-1 block text-white/42">{source.publisher}</span>}
        </a>
      ))}
    </div>
  );
}

export default function FuturePage() {
  const [available, setAvailable] = useState<{ race: string; slug: string }[]>([]);
  const [treeData, setTreeData] = useState<ScenarioTree | null>(null);
  const [loading, setLoading] = useState(true);
  const [prefs, setPrefs] = useState<UserPreferences | null>(null);
  const [selected, setSelected] = useState<ScenarioNode | null>(null);
  const treePaneRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    let cancelled = false;
    queueMicrotask(() => {
      if (!cancelled) setPrefs(loadPrefs());
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const loadTree = useCallback((slug: string) => {
    setLoading(true);
    fetch(`/api/scenario?race=${slug}`)
      .then((response) => response.json())
      .then((nextTree) => {
        if (nextTree.error) {
          setTreeData(null);
          setSelected(null);
        } else {
          setTreeData(nextTree);
          const firstOutcome =
            [...nextTree.root.children].sort((a, b) => nodeRank(b) - nodeRank(a))[0] ?? nextTree.root;
          setSelected(firstOutcome);
        }
        setLoading(false);
      })
      .catch(() => {
        setTreeData(null);
        setSelected(null);
        setLoading(false);
      });
  }, []);

  useEffect(() => {
    let cancelled = false;

    fetch("/api/scenario")
      .then((response) => response.json())
      .then((data) => {
        if (cancelled) return;
        const nextAvailable = data.available ?? [];
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

  const layout = useMemo(() => {
    if (!treeData) return null;
    const root = hierarchy<ScenarioNode>(treeData.root, (node) => node.children);
    const treeLayout = tree<ScenarioNode>().nodeSize([NODE_H + GAP_Y, NODE_W + GAP_X]);
    const laidOut = treeLayout(root);
    const nodes = laidOut.descendants();
    const links = laidOut.links();
    let minX = Infinity;
    let maxX = -Infinity;
    let maxY = -Infinity;

    for (const node of nodes) {
      minX = Math.min(minX, node.x);
      maxX = Math.max(maxX, node.x);
      maxY = Math.max(maxY, node.y);
    }

    const offsetX = -minX + 28;
    const width = maxY + NODE_W + 72;
    const height = maxX - minX + NODE_H + 56;
    return { nodes, links, offsetX, width, height };
  }, [treeData]);

  const mostLikely = useMemo(() => {
    if (!treeData) return { ids: new Set<string>(), path: [] as ScenarioNode[] };
    const path: ScenarioNode[] = [];
    let current: ScenarioNode | undefined = treeData.root;
    while (current) {
      path.push(current);
      current = [...current.children].sort((a, b) => nodeRank(b) - nodeRank(a))[0];
    }
    return { ids: new Set(path.map((node) => node.id)), path };
  }, [treeData]);

  const selectedNode = selected ?? treeData?.root ?? null;
  const selectedHits = selectedNode ? affectsUser(selectedNode, prefs) : [];
  const visibleNodeCount = treeData ? countNodes(treeData.root) : 0;
  const visibleDepth = treeData ? maxDepth(treeData.root) : 0;

  const pos = (node: HierarchyPointNode<ScenarioNode>) => ({
    left: node.y + 18,
    top: node.x + (layout?.offsetX ?? 0),
  });

  const focusNode = useCallback(
    (node: ScenarioNode) => {
      setSelected(node);
      const pane = treePaneRef.current;
      if (!pane || !layout) return;
      const match = layout.nodes.find((item) => item.data.id === node.id);
      if (!match) return;
      pane.scrollTo({
        left: Math.max(0, match.y - 36),
        top: Math.max(0, match.x + layout.offsetX - 32),
        behavior: "smooth",
      });
    },
    [layout]
  );

  useEffect(() => {
    const pane = treePaneRef.current;
    if (!pane || !layout) return;

    const pathTops = layout.nodes
      .filter((node) => mostLikely.ids.has(node.data.id))
      .map((node) => node.x + layout.offsetX);
    const firstUsefulTop = pathTops.length ? Math.min(...pathTops) : 0;
    pane.scrollTop = Math.max(0, firstUsefulTop - 28);
    pane.scrollLeft = 0;
  }, [layout, mostLikely.ids, treeData?.race_slug]);

  return (
    <div className="min-h-full bg-[radial-gradient(circle_at_78%_0%,rgba(182,141,93,0.13),transparent_32%),linear-gradient(180deg,#041629_0%,#020c17_100%)] text-cream-light">
      <section className="mx-auto flex min-h-[calc(100svh-123px)] max-w-7xl flex-col px-4 py-6 sm:px-6 lg:px-8">
        <header className="mb-4 grid gap-5 lg:grid-cols-[minmax(0,1fr)_360px] lg:items-end">
          <div>
            <h1 className="font-serif text-4xl font-normal leading-[1.05] text-white sm:text-5xl">
              Down the line
            </h1>
            <div className="mt-3 h-0.5 w-14 bg-red" />
            <p className="mt-3 max-w-3xl text-sm leading-6 text-white/68 sm:text-base sm:leading-7">
              Follow each election outcome into the policy moves, succession questions, and long-term
              possibilities it could set in motion. Facts carry sources; projections stay labeled.
            </p>
          </div>

          <div className="grid grid-cols-3 overflow-hidden rounded-[8px] border border-white/12 bg-white/[0.035] text-center">
            <div className="border-r border-white/10 px-4 py-3">
              <div className="font-serif text-2xl text-white">{visibleNodeCount || "--"}</div>
              <div className="mt-1 text-[10px] font-semibold uppercase tracking-[0.18em] text-white/42">
                Nodes
              </div>
            </div>
            <div className="border-r border-white/10 px-4 py-3">
              <div className="font-serif text-2xl text-white">{visibleDepth || "--"}</div>
              <div className="mt-1 text-[10px] font-semibold uppercase tracking-[0.18em] text-white/42">
                Levels
              </div>
            </div>
            <div className="px-4 py-3">
              <div className="font-serif text-2xl text-white">{mostLikely.path.length || "--"}</div>
              <div className="mt-1 text-[10px] font-semibold uppercase tracking-[0.18em] text-white/42">
                Path
              </div>
            </div>
          </div>
        </header>

        <div className="mb-4 flex flex-col gap-3 rounded-[8px] border border-white/12 bg-[#05182a]/92 p-3 shadow-[0_18px_54px_rgba(0,0,0,0.2)] lg:flex-row lg:items-center lg:justify-between">
          <div className="flex flex-wrap gap-2">
            {available.map((race) => {
              const active = treeData?.race_slug === race.slug;
              return (
                <button
                  key={race.slug}
                  type="button"
                  onClick={() => loadTree(race.slug)}
                  aria-pressed={active}
                  className={cn(
                    "rounded-[7px] border px-3.5 py-2 text-xs font-semibold uppercase tracking-[0.14em] transition",
                    active
                      ? "border-gold bg-gold/12 text-gold"
                      : "border-white/10 bg-white/[0.025] text-white/55 hover:border-white/24 hover:text-white"
                  )}
                >
                  {race.race}
                </button>
              );
            })}
          </div>

          <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-white/10 pt-3 lg:border-t-0 lg:pt-0">
            {[
              treeData?.root,
              { kind: "inference", likelihood: "high" } as ScenarioNode,
              { kind: "inference", likelihood: "medium" } as ScenarioNode,
              { kind: "inference", likelihood: "low" } as ScenarioNode,
            ]
              .filter(Boolean)
              .map((node, index) => (
                <LegendItem key={index} node={node as ScenarioNode} />
              ))}
          </div>
        </div>

        {loading ? (
          <div
            role="status"
            aria-live="polite"
            className="flex min-h-[32rem] items-center justify-center rounded-[8px] border border-white/12 bg-white/[0.025] text-sm text-white/45"
          >
            Loading scenario tree...
          </div>
        ) : !treeData || !layout ? (
          <div className="rounded-[8px] border border-dashed border-white/16 bg-white/[0.025] p-8 text-sm leading-6 text-white/50">
            No scenario trees are available yet. Run <code className="text-gold">npm run seed:graph</code>.
          </div>
        ) : (
          <div className="grid min-h-0 flex-1 gap-4 lg:grid-cols-[minmax(0,1fr)_360px]">
            <div className="min-w-0 space-y-4">
              {mostLikely.path.length > 1 && (
                <section className="rounded-[8px] border border-gold/24 bg-gold/[0.055] p-4">
                  <div className="mb-3 flex items-center justify-between gap-3">
                    <h2 className="text-xs font-semibold uppercase tracking-[0.2em] text-gold">
                      Most likely path
                    </h2>
                    <span className="text-[11px] uppercase tracking-[0.16em] text-white/38">
                      Likelihood labels, not a forecast
                    </span>
                  </div>
                  <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
                    {mostLikely.path.slice(1).map((node, index) => {
                      const tone = nodeTone(node);
                      const active = selectedNode?.id === node.id;
                      return (
                        <button
                          key={node.id}
                          type="button"
                          onClick={() => focusNode(node)}
                          aria-pressed={active}
                          className={cn(
                            "group min-w-0 rounded-[7px] border bg-[#06192d]/80 p-3 text-left transition",
                            active ? "border-gold shadow-[0_0_0_1px_rgba(182,141,93,0.35)]" : "border-white/12 hover:border-gold/45"
                          )}
                        >
                          <span className="flex items-center justify-between gap-2">
                            <span className="text-[10px] font-bold uppercase tracking-[0.18em] text-white/40">
                              Step {index + 1}
                            </span>
                            <span className="text-[10px] font-semibold uppercase tracking-[0.16em]" style={{ color: tone.text }}>
                              {node.timeframe}
                            </span>
                          </span>
                          <span className="mt-2 block text-sm font-semibold leading-5 text-white/82 group-hover:text-white">
                            {truncateLabel(node.label, 48)}
                          </span>
                        </button>
                      );
                    })}
                  </div>
                </section>
              )}

              <section className="overflow-hidden rounded-[8px] border border-white/12 bg-[#030b14] shadow-[0_20px_70px_rgba(0,0,0,0.28)]">
                <div className="flex flex-col gap-3 border-b border-white/10 bg-[#06192d]/92 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
                  <div>
                    <h2 className="font-serif text-2xl font-normal text-white">Scenario map</h2>
                    <p className="mt-1 text-xs leading-5 text-white/45">
                      Select any node to inspect the evidence boundary and downstream branches.
                    </p>
                  </div>
                  <div className="flex items-center gap-2 text-[10px] uppercase tracking-[0.16em] text-white/38">
                    <span className="h-2 w-2 rounded-full bg-gold" />
                    On path
                    <span className="ml-2 h-2 w-2 rounded-full border border-gold/70" />
                    Affects you
                  </div>
                </div>

                <div
                  ref={treePaneRef}
                  className="max-h-[58svh] min-h-[31rem] overflow-auto bg-[linear-gradient(rgba(255,255,255,0.035)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.035)_1px,transparent_1px)] bg-[size:36px_36px]"
                >
                  <div className="relative" style={{ width: layout.width, height: layout.height }}>
                    <svg className="absolute inset-0" width={layout.width} height={layout.height}>
                      {layout.links.map((link, index) => {
                        const source = pos(link.source);
                        const target = pos(link.target);
                        const x1 = source.left + NODE_W;
                        const y1 = source.top + NODE_H / 2;
                        const x2 = target.left;
                        const y2 = target.top + NODE_H / 2;
                        const midpoint = (x1 + x2) / 2;
                        const onPath =
                          mostLikely.ids.has(link.target.data.id) && mostLikely.ids.has(link.source.data.id);
                        const tone = nodeTone(link.target.data);
                        return (
                          <path
                            key={index}
                            d={`M${x1},${y1} C${midpoint},${y1} ${midpoint},${y2} ${x2},${y2}`}
                            fill="none"
                            stroke={tone.line}
                            strokeOpacity={onPath ? 0.9 : 0.34}
                            strokeWidth={onPath ? 2.2 : 1.2}
                            strokeDasharray={link.target.data.kind === "inference" ? "5 5" : undefined}
                          />
                        );
                      })}
                    </svg>

                    {layout.nodes.map((node) => {
                      const point = pos(node);
                      const data = node.data;
                      const tone = nodeTone(data);
                      const isSelected = selectedNode?.id === data.id;
                      const onPath = mostLikely.ids.has(data.id);
                      const hits = affectsUser(data, prefs);
                      return (
                        <button
                          key={`${node.depth}-${data.id}`}
                          type="button"
                          onClick={() => focusNode(data)}
                          aria-pressed={isSelected}
                          className={cn(
                            "absolute rounded-[8px] border p-3 text-left transition hover:-translate-y-0.5 hover:bg-[#0b2135]",
                            onPath ? "bg-[#0a2136]" : "bg-[#071522]/92",
                            isSelected && "shadow-[0_0_0_2px_rgba(182,141,93,0.6)]",
                            hits.length > 0 && "ring-1 ring-gold/55"
                          )}
                          style={{
                            left: point.left,
                            top: point.top,
                            width: NODE_W,
                            height: NODE_H,
                            borderColor: isSelected ? "#b68d5d" : tone.border,
                            backgroundImage: onPath ? `linear-gradient(180deg, ${tone.surface}, transparent)` : undefined,
                          }}
                        >
                          <span className="flex items-center gap-2">
                            <span
                              className="h-2 w-2 shrink-0 rounded-full"
                              style={{ backgroundColor: tone.dot, boxShadow: `0 0 14px ${tone.dot}55` }}
                            />
                            <span className="text-[10px] font-semibold uppercase tracking-[0.16em] text-white/42">
                              {data.timeframe}
                            </span>
                            <span className="text-[10px] font-semibold uppercase tracking-[0.16em]" style={{ color: tone.text }}>
                              {tone.label}
                            </span>
                            {hits.length > 0 && (
                              <span className="ml-auto text-[10px] font-semibold text-gold">You</span>
                            )}
                          </span>
                          <span className="mt-2 block text-sm font-semibold leading-5 text-white/86">
                            {truncateLabel(data.label, 64)}
                          </span>
                        </button>
                      );
                    })}
                  </div>
                </div>
              </section>
            </div>

            <aside className="rounded-[8px] border border-white/12 bg-[#06192d]/92 shadow-[0_20px_70px_rgba(0,0,0,0.24)] lg:max-h-[calc(100svh-13rem)] lg:overflow-y-auto">
              {selectedNode && (
                <div className="p-5">
                  <div className="mb-5 flex items-start justify-between gap-4">
                    <div>
                      <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-gold">
                        Evidence inspector
                      </p>
                      <h2 className="mt-3 font-serif text-2xl font-normal leading-tight text-white">
                        {selectedNode.label}
                      </h2>
                    </div>
                    <span
                      className="mt-1 rounded-[7px] border px-2.5 py-1 text-[10px] font-bold uppercase tracking-[0.16em]"
                      style={{
                        borderColor: nodeTone(selectedNode).border,
                        color: nodeTone(selectedNode).text,
                        backgroundColor: nodeTone(selectedNode).surface,
                      }}
                    >
                      {nodeTone(selectedNode).label}
                    </span>
                  </div>

                  <dl className="grid grid-cols-2 gap-2 border-y border-white/10 py-3 text-xs">
                    <div>
                      <dt className="uppercase tracking-[0.18em] text-white/35">Timeframe</dt>
                      <dd className="mt-1 font-semibold text-white/76">{selectedNode.timeframe}</dd>
                    </div>
                    <div>
                      <dt className="uppercase tracking-[0.18em] text-white/35">Boundary</dt>
                      <dd className="mt-1 font-semibold text-white/76">
                        {selectedNode.kind === "fact" ? "Documented" : "Projection"}
                      </dd>
                    </div>
                  </dl>

                  <p className="mt-5 text-sm leading-6 text-white/68">{selectedNode.description}</p>

                  {selectedHits.length > 0 && (
                    <div className="mt-5">
                      <h3 className="text-[11px] font-semibold uppercase tracking-[0.2em] text-white/38">
                        Matches your context
                      </h3>
                      <div className="mt-2 flex flex-wrap gap-2">
                        {selectedHits.map((hit) => (
                          <span
                            key={hit}
                            className="rounded-[7px] border border-gold/35 bg-gold/10 px-2.5 py-1 text-[11px] font-semibold text-gold"
                          >
                            {hit}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}

                  {selectedNode.children.length > 0 && (
                    <div className="mt-5">
                      <h3 className="text-[11px] font-semibold uppercase tracking-[0.2em] text-white/38">
                        Downstream branches
                      </h3>
                      <div className="mt-2 space-y-2">
                        {selectedNode.children.map((child) => (
                          <button
                            key={child.id}
                            type="button"
                            onClick={() => focusNode(child)}
                            className="block w-full rounded-[8px] border border-white/10 bg-white/[0.025] p-3 text-left text-xs leading-5 text-white/66 transition hover:border-gold/45 hover:text-white"
                          >
                            <span className="block font-semibold">{child.label}</span>
                            <span className="mt-1 block uppercase tracking-[0.16em] text-white/35">
                              {child.timeframe} / {nodeTone(child).label}
                            </span>
                          </button>
                        ))}
                      </div>
                    </div>
                  )}

                  <div className="mt-5">
                    <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-[0.2em] text-white/38">
                      Sources
                    </h3>
                    <SourceList sources={selectedNode.sources} />
                  </div>
                </div>
              )}
            </aside>
          </div>
        )}
      </section>
    </div>
  );
}
