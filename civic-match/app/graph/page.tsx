"use client";

import { useEffect, useRef, useState } from "react";
import {
  forceCenter,
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  type SimulationLinkDatum,
  type SimulationNodeDatum,
} from "d3-force";
import type { GraphEdge, GraphNode, KnowledgeGraph } from "@/lib/types";

interface SimNode extends SimulationNodeDatum, GraphNode {}
type SimLink = SimulationLinkDatum<SimNode> & GraphEdge;

const TYPE_COLORS: Record<string, string> = {
  politician: "#34d399",
  office: "#60a5fa",
  race: "#f472b6",
  issue: "#a78bfa",
  organization: "#fbbf24",
  event: "#f87171",
};

export default function GraphPage() {
  const [graph, setGraph] = useState<KnowledgeGraph | null>(null);
  const [selected, setSelected] = useState<GraphNode | null>(null);
  const [positions, setPositions] = useState<Map<string, { x: number; y: number }>>(new Map());
  const simRef = useRef<ReturnType<typeof forceSimulation<SimNode>> | null>(null);
  const W = 1100;
  const H = 720;

  useEffect(() => {
    fetch("/api/graph")
      .then((r) => r.json())
      .then((g: KnowledgeGraph) => {
        setGraph(g);
        const nodes: SimNode[] = g.nodes.map((n) => ({ ...n }));
        const links: SimLink[] = g.edges.map((e) => ({ ...e, source: e.source, target: e.target }));
        const sim = forceSimulation<SimNode>(nodes)
          .force("link", forceLink<SimNode, SimLink>(links).id((d) => d.id).distance(70).strength(0.4))
          .force("charge", forceManyBody().strength(-160))
          .force("center", forceCenter(W / 2, H / 2))
          .force("collide", forceCollide(18));
        if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
          sim.stop();
          sim.tick(80);
          setPositions(new Map(nodes.map((n) => [n.id, { x: n.x ?? 0, y: n.y ?? 0 }])));
          simRef.current = sim;
          return;
        }
        sim.on("tick", () => {
          setPositions(new Map(nodes.map((n) => [n.id, { x: n.x ?? 0, y: n.y ?? 0 }])));
        });
        simRef.current = sim;
      });
    return () => {
      simRef.current?.stop();
    };
  }, []);

  if (!graph) {
    return (
      <div role="status" aria-live="polite" className="mx-auto max-w-5xl px-4 py-16 text-zinc-500 animate-pulse">
        Loading knowledge graph…
      </div>
    );
  }
  if (graph.nodes.length === 0) {
    return (
      <div className="mx-auto max-w-5xl px-4 py-16 text-sm text-zinc-500">
        Graph not built yet — run <code className="text-zinc-300">npm run seed:graph</code>.
      </div>
    );
  }

  const selectedEdges = selected
    ? graph.edges.filter((e) => e.source === selected.id || e.target === selected.id)
    : [];
  const nodeById = new Map(graph.nodes.map((n) => [n.id, n]));

  return (
    <div className="mx-auto max-w-6xl px-4 py-8">
      <h1 className="text-2xl font-bold mb-1">The connection graph</h1>
      <p className="text-sm text-zinc-500 mb-4 max-w-3xl">
        Municipal ↔ state ↔ federal: how offices, races, people, issues, and future
        events connect. Click a node to inspect its edges and ground-truth sources.
      </p>
      <div className="flex flex-wrap gap-3 mb-3 text-xs">
        {Object.entries(TYPE_COLORS).map(([t, c]) => (
          <span key={t} className="flex items-center gap-1.5 text-zinc-400">
            <span className="h-2.5 w-2.5 rounded-full" style={{ background: c }} />
            {t}
          </span>
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
        <div className="rounded-xl border border-zinc-800 bg-zinc-950 overflow-hidden">
          <svg viewBox={`0 0 ${W} ${H}`} className="w-full">
            {graph.edges.map((e, i) => {
              const s = positions.get(e.source);
              const t = positions.get(e.target);
              if (!s || !t) return null;
              const active = selected && (e.source === selected.id || e.target === selected.id);
              return (
                <line
                  key={i}
                  x1={s.x} y1={s.y} x2={t.x} y2={t.y}
                  stroke={active ? "#34d399" : e.kind === "inference" ? "#3f3f46" : "#52525b"}
                  strokeWidth={active ? 1.8 : 0.8}
                  strokeDasharray={e.kind === "inference" ? "4 3" : undefined}
                  opacity={selected && !active ? 0.25 : 0.8}
                />
              );
            })}
            {graph.nodes.map((n) => {
              const p = positions.get(n.id);
              if (!p) return null;
              const dim = selected && selected.id !== n.id &&
                !selectedEdges.some((e) => e.source === n.id || e.target === n.id);
              return (
                <g
                  key={n.id}
                  transform={`translate(${p.x},${p.y})`}
                  opacity={dim ? 0.3 : 1}
                  className="cursor-pointer outline-none"
                  role="button"
                  tabIndex={0}
                  aria-label={`Inspect ${n.label}, ${n.type}`}
                  aria-pressed={selected?.id === n.id}
                  onClick={() => setSelected(n)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      setSelected(n);
                    }
                  }}
                >
                  <circle r={n.type === "politician" ? 10 : 7} fill={TYPE_COLORS[n.type] ?? "#71717a"}
                          stroke={selected?.id === n.id ? "#fff" : "transparent"} strokeWidth={1.5} />
                  <text y={-12} textAnchor="middle" fontSize={9} fill="#a1a1aa">
                    {n.label.length > 24 ? n.label.slice(0, 23) + "…" : n.label}
                  </text>
                </g>
              );
            })}
          </svg>
        </div>

        <div className="rounded-xl border border-zinc-800 bg-zinc-900/50 p-4 text-sm max-h-[720px] overflow-y-auto">
          {!selected ? (
            <p className="text-zinc-500">
              {graph.nodes.length} nodes · {graph.edges.length} edges. Click any node.
            </p>
          ) : (
            <>
              <div className="mb-1 flex items-center gap-2">
                <span className="h-2.5 w-2.5 rounded-full" style={{ background: TYPE_COLORS[selected.type] }} />
                <span className="font-semibold">{selected.label}</span>
              </div>
              <p className="text-xs text-zinc-500 mb-3">
                {selected.type}
                {selected.meta?.level ? ` · ${selected.meta.level} level` : ""}
                {selected.meta?.timeframe ? ` · ${selected.meta.timeframe}` : ""}
              </p>
              <div className="space-y-2">
                {selectedEdges.map((e, i) => {
                  const other = e.source === selected.id ? e.target : e.source;
                  return (
                    <div key={i} className="rounded-lg bg-zinc-950 p-2.5 text-xs">
                      <div className="text-zinc-300">
                        <span className="text-zinc-500">{e.source === selected.id ? "→" : "←"} {e.rel.replace(/_/g, " ")}:</span>{" "}
                        {nodeById.get(other)?.label ?? other}
                      </div>
                      {e.description && <p className="mt-1 text-zinc-500">{e.description}</p>}
                      <div className="mt-1 flex flex-wrap gap-2">
                        <span className={`rounded-full border px-1.5 py-0.5 text-[9px] uppercase ${e.kind === "fact" ? "border-emerald-500/40 text-emerald-400" : "border-yellow-500/40 text-yellow-400"}`}>
                          {e.kind}
                        </span>
                        {e.sources.map((s, j) => (
                          <a key={j} href={s.url} target="_blank" className="text-emerald-400 hover:underline">
                            {s.title.slice(0, 40)} ↗
                          </a>
                        ))}
                      </div>
                    </div>
                  );
                })}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
