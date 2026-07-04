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
import { CivitasPage, CivitasPanel, SourceLink, StatusPill } from "@/components/civitas-ui";
import type { GraphEdge, GraphNode, KnowledgeGraph } from "@/lib/types";

interface SimNode extends SimulationNodeDatum, GraphNode {}
type SimLink = SimulationLinkDatum<SimNode> & GraphEdge;

const TYPE_COLORS: Record<string, string> = {
  politician: "#b68d5d",
  office: "#eae3d5",
  race: "#9c2a2a",
  issue: "#8fb7c6",
  organization: "#d8a15b",
  event: "#c96b5b",
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
      <CivitasPage wide eyebrow="Knowledge graph" title="Loading connection graph">
      <div role="status" aria-live="polite" className="animate-pulse text-sm text-white/45">
        Loading knowledge graph…
      </div>
      </CivitasPage>
    );
  }
  if (graph.nodes.length === 0) {
    return (
      <CivitasPage wide eyebrow="Knowledge graph" title="Graph not built yet">
        <p className="text-sm text-white/52">
          Run <code className="text-gold">npm run seed:graph</code>.
        </p>
      </CivitasPage>
    );
  }

  const selectedEdges = selected
    ? graph.edges.filter((e) => e.source === selected.id || e.target === selected.id)
    : [];
  const nodeById = new Map(graph.nodes.map((n) => [n.id, n]));

  return (
    <CivitasPage
      wide
      eyebrow="Knowledge graph"
      title="The connection graph"
      description={
        <>
        Municipal ↔ state ↔ federal: how offices, races, people, issues, and future
        events connect. Click a node to inspect its edges and ground-truth sources.
        </>
      }
    >
      <div className="mb-4 flex flex-wrap gap-3 text-xs">
        {Object.entries(TYPE_COLORS).map(([t, c]) => (
          <span key={t} className="flex items-center gap-1.5 text-white/55">
            <span className="h-2.5 w-2.5 rounded-full" style={{ background: c }} />
            {t}
          </span>
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
        <CivitasPanel className="overflow-hidden bg-navy-dark/80">
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
                  stroke={active ? "#b68d5d" : e.kind === "inference" ? "#344457" : "#6f7f91"}
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
                  <circle r={n.type === "politician" ? 10 : 7} fill={TYPE_COLORS[n.type] ?? "#6f7f91"}
                          stroke={selected?.id === n.id ? "#fff" : "transparent"} strokeWidth={1.5} />
                  <text y={-12} textAnchor="middle" fontSize={9} fill="#cfc7b7">
                    {n.label.length > 24 ? n.label.slice(0, 23) + "…" : n.label}
                  </text>
                </g>
              );
            })}
          </svg>
        </CivitasPanel>

        <CivitasPanel className="max-h-[720px] overflow-y-auto p-4 text-sm">
          {!selected ? (
            <p className="text-white/45">
              {graph.nodes.length} nodes · {graph.edges.length} edges. Click any node.
            </p>
          ) : (
            <>
              <div className="mb-1 flex items-center gap-2">
                <span className="h-2.5 w-2.5 rounded-full" style={{ background: TYPE_COLORS[selected.type] }} />
                <span className="font-serif text-xl text-white">{selected.label}</span>
              </div>
              <p className="mb-3 text-xs text-white/45">
                {selected.type}
                {selected.meta?.level ? ` · ${selected.meta.level} level` : ""}
                {selected.meta?.timeframe ? ` · ${selected.meta.timeframe}` : ""}
              </p>
              <div className="space-y-2">
                {selectedEdges.map((e, i) => {
                  const other = e.source === selected.id ? e.target : e.source;
                  return (
                    <div key={i} className="rounded-[8px] border border-white/10 bg-navy-dark/60 p-2.5 text-xs">
                      <div className="text-white/70">
                        <span className="text-white/42">{e.source === selected.id ? "From" : "To"} {e.rel.replace(/_/g, " ")}:</span>{" "}
                        {nodeById.get(other)?.label ?? other}
                      </div>
                      {e.description && <p className="mt-1 text-white/45">{e.description}</p>}
                      <div className="mt-1 flex flex-wrap gap-2">
                        <StatusPill tone={e.kind === "fact" ? "gold" : "neutral"}>{e.kind}</StatusPill>
                        {e.sources.map((s, j) => (
                          <SourceLink key={j} href={s.url} className="text-[11px]">
                            {s.title.slice(0, 40)}
                          </SourceLink>
                        ))}
                      </div>
                    </div>
                  );
                })}
              </div>
            </>
          )}
        </CivitasPanel>
      </div>
    </CivitasPage>
  );
}
