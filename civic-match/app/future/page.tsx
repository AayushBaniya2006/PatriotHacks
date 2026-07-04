"use client";

import { useEffect, useState } from "react";
import { loadPrefs } from "@/lib/prefs";
import type { ScenarioNode, ScenarioTree, UserPreferences } from "@/lib/types";

function likelihoodStyle(n: ScenarioNode) {
  if (n.kind === "fact") return "border-emerald-500/50 text-emerald-300";
  if (n.likelihood === "high") return "border-sky-500/50 text-sky-300";
  if (n.likelihood === "low") return "border-zinc-600 text-zinc-500";
  return "border-yellow-500/40 text-yellow-300";
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
      hits.push(`you: ${g.replace(/_/g, " ")}`);
  }
  return [...new Set(hits)];
}

function TreeNode({
  node,
  prefs,
  depth,
}: {
  node: ScenarioNode;
  prefs: UserPreferences | null;
  depth: number;
}) {
  const [open, setOpen] = useState(depth < 2);
  const hits = affectsUser(node, prefs);
  return (
    <div className={depth > 0 ? "ml-5 border-l border-zinc-800 pl-4" : ""}>
      <div className="py-2">
        <div className="flex flex-wrap items-center gap-2">
          {node.children.length > 0 && (
            <button
              onClick={() => setOpen(!open)}
              className="h-5 w-5 rounded border border-zinc-700 text-xs text-zinc-400 hover:border-zinc-500"
            >
              {open ? "−" : "+"}
            </button>
          )}
          <span className="font-medium text-zinc-200">{node.label}</span>
          <span className="text-[10px] text-zinc-500">{node.timeframe}</span>
          <span className={`rounded-full border px-2 py-0.5 text-[10px] uppercase tracking-wide ${likelihoodStyle(node)}`}>
            {node.kind === "fact" ? "fact" : `${node.likelihood} likelihood`}
          </span>
          {hits.map((h) => (
            <span key={h} className="rounded-full bg-emerald-500/15 border border-emerald-400/40 px-2 py-0.5 text-[10px] text-emerald-300">
              affects {h}
            </span>
          ))}
        </div>
        {node.description && (
          <p className="mt-1 text-sm text-zinc-400 max-w-2xl">{node.description}</p>
        )}
        {node.sources.length > 0 && (
          <div className="mt-1 flex flex-wrap gap-3">
            {node.sources.map((s, i) => (
              <a key={i} href={s.url} target="_blank" className="text-[11px] text-emerald-400 hover:underline">
                {s.title}{s.publisher ? ` — ${s.publisher}` : ""} ↗
              </a>
            ))}
          </div>
        )}
      </div>
      {open &&
        node.children.map((c) => (
          <TreeNode key={c.id} node={c} prefs={prefs} depth={depth + 1} />
        ))}
    </div>
  );
}

export default function FuturePage() {
  const [available, setAvailable] = useState<{ race: string; slug: string }[]>([]);
  const [tree, setTree] = useState<ScenarioTree | null>(null);
  const [loading, setLoading] = useState(true);
  const [prefs, setPrefs] = useState<UserPreferences | null>(null);

  useEffect(() => {
    setPrefs(loadPrefs());
    fetch("/api/scenario")
      .then((r) => r.json())
      .then((d) => {
        setAvailable(d.available ?? []);
        if (d.available?.length) loadTree(d.available[0].slug);
        else setLoading(false);
      });
  }, []);

  const loadTree = (slug: string) => {
    setLoading(true);
    fetch(`/api/scenario?race=${slug}`)
      .then((r) => r.json())
      .then((t) => {
        setTree(t.error ? null : t);
        setLoading(false);
      });
  };

  return (
    <div className="mx-auto max-w-4xl px-4 py-10">
      <h1 className="text-2xl font-bold mb-1">Down the line</h1>
      <p className="text-sm text-zinc-500 mb-2 max-w-2xl">
        A branching map of what each outcome could set in motion — offices vacated,
        successors appointed, policies compounding, and the elections that open up
        later. Facts carry sources; projections are labeled with likelihood.
        This is scenario analysis grounded in ground truth, not a forecast.
      </p>
      {prefs && (
        <p className="text-xs text-emerald-400/80 mb-6">
          Branches touching your stated priorities and situation are tagged “affects you”.
        </p>
      )}

      <div className="flex flex-wrap gap-2 mb-6">
        {available.map((a) => (
          <button
            key={a.slug}
            onClick={() => loadTree(a.slug)}
            className={`rounded-full border px-4 py-1.5 text-sm ${
              tree?.race_slug === a.slug
                ? "border-emerald-400 bg-emerald-500/15 text-emerald-300"
                : "border-zinc-700 text-zinc-300 hover:border-zinc-500"
            }`}
          >
            {a.race}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="text-zinc-500 animate-pulse">Loading scenario tree…</div>
      ) : !tree ? (
        <p className="text-sm text-zinc-500 border border-dashed border-zinc-800 rounded-lg p-6">
          No scenario trees built yet — run <code className="text-zinc-300">npm run seed:graph</code>.
        </p>
      ) : (
        <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-5">
          <TreeNode node={tree.root} prefs={prefs} depth={0} />
        </div>
      )}
    </div>
  );
}
