"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { loadPrefs } from "@/lib/prefs";
import type { MatchResult } from "@/lib/types";

interface PoliticianSummary {
  id: string;
  name: string;
  party?: string;
  current_office?: string;
}

function ovrColor(overall: number) {
  if (overall >= 90) return "text-emerald-300 border-emerald-400/60";
  if (overall >= 83) return "text-emerald-400 border-emerald-500/40";
  if (overall >= 75) return "text-yellow-300 border-yellow-400/40";
  if (overall >= 68) return "text-orange-300 border-orange-400/40";
  return "text-red-400 border-red-500/40";
}

export default function ResultsPage() {
  const [results, setResults] = useState<MatchResult[] | null>(null);
  const [noPrefs, setNoPrefs] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);

  useEffect(() => {
    const prefs = loadPrefs();
    if (!prefs) {
      setNoPrefs(true);
      return;
    }
    (async () => {
      const list: PoliticianSummary[] = await fetch("/api/politicians").then((r) => r.json());
      const res = await fetch("/api/match", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prefs, politician_ids: list.map((p) => p.id) }),
      }).then((r) => r.json());
      setResults(res.results);
    })();
  }, []);

  if (noPrefs) {
    return (
      <div className="mx-auto max-w-2xl px-4 py-16 text-center">
        <p className="text-zinc-400 mb-4">You haven&apos;t set your priorities yet.</p>
        <Link href="/intake" className="rounded-lg bg-emerald-500 px-5 py-2.5 font-medium text-zinc-950">
          Pick your priorities
        </Link>
      </div>
    );
  }

  if (!results) {
    return (
      <div className="mx-auto max-w-3xl px-4 py-16 text-zinc-500 animate-pulse">
        Scoring cached candidate profiles…
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-3xl px-4 py-10">
      <div className="flex items-baseline justify-between mb-1">
        <h1 className="text-2xl font-bold">Your candidate alignment</h1>
        <Link href="/intake" className="text-xs text-zinc-400 hover:text-zinc-200">
          Edit priorities →
        </Link>
      </div>
      <p className="text-sm text-zinc-500 mb-8">
        Overall = 60–99, 2K style: quantitative issue alignment + qualitative record
        (integrity, transparency, experience) − conflicts on your top issues. Every
        number decomposes — click a card.
      </p>

      <div className="space-y-4">
        {results.map((r) => (
          <div
            key={r.politician_id}
            className="rounded-xl border border-zinc-800 bg-zinc-900/50 overflow-hidden"
          >
            <button
              className="w-full flex items-center gap-5 p-5 text-left hover:bg-zinc-900"
              onClick={() => setExpanded(expanded === r.politician_id ? null : r.politician_id)}
            >
              <div
                className={`flex h-16 w-16 shrink-0 flex-col items-center justify-center rounded-xl border-2 bg-zinc-950 ${ovrColor(r.overall)}`}
              >
                <span className="text-2xl font-black leading-none">{r.overall}</span>
                <span className="text-[9px] uppercase tracking-widest opacity-80">OVR</span>
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-baseline gap-2">
                  <span className="font-semibold truncate">{r.politician_name}</span>
                  {r.party && <span className="text-xs text-zinc-500">({r.party})</span>}
                </div>
                <div className="text-sm text-zinc-400">{r.overall_tier}</div>
                <div className="mt-1 flex gap-4 text-xs text-zinc-500">
                  <span>Issue alignment: <b className="text-zinc-300">{r.score}%</b></span>
                  <span>
                    Record quality:{" "}
                    <b className="text-zinc-300">
                      {r.qualitative_composite !== null
                        ? `${Math.round(r.qualitative_composite * 100)}%`
                        : "n/a"}
                    </b>
                  </span>
                  <span>Evidence: <b className="text-zinc-300">{r.confidence}</b></span>
                </div>
              </div>
              <Link
                href={`/p/${r.politician_id}`}
                onClick={(e) => e.stopPropagation()}
                className="text-xs text-emerald-400 hover:underline shrink-0"
              >
                Full profile →
              </Link>
            </button>

            {expanded === r.politician_id && (
              <div className="border-t border-zinc-800 p-5 text-sm space-y-4">
                <div className="grid grid-cols-3 gap-3 text-center text-xs">
                  <div className="rounded-lg bg-zinc-950 p-3">
                    <div className="text-lg font-bold text-emerald-400">
                      +{r.overall_components.alignment_component}
                    </div>
                    <div className="text-zinc-500">from issue alignment (quant)</div>
                  </div>
                  <div className="rounded-lg bg-zinc-950 p-3">
                    <div className="text-lg font-bold text-sky-400">
                      +{r.overall_components.qualitative_component}
                    </div>
                    <div className="text-zinc-500">from record quality (qual)</div>
                  </div>
                  <div className="rounded-lg bg-zinc-950 p-3">
                    <div className="text-lg font-bold text-red-400">
                      −{r.overall_components.conflict_penalty}
                    </div>
                    <div className="text-zinc-500">conflicts on your top issues</div>
                  </div>
                </div>

                {r.qualitative.length > 0 && (
                  <div>
                    <h3 className="font-medium text-zinc-300 mb-2">Record quality (sourced)</h3>
                    <div className="grid gap-2 sm:grid-cols-2">
                      {r.qualitative.map((q) => (
                        <div key={q.id} className="rounded-lg bg-zinc-950 p-3">
                          <div className="flex justify-between mb-1">
                            <span className="text-zinc-300">{q.label}</span>
                            <span className="font-mono text-zinc-400">
                              {Math.round(q.score * 100)}
                            </span>
                          </div>
                          <p className="text-xs text-zinc-500">{q.summary}</p>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                <div>
                  <h3 className="font-medium text-zinc-300 mb-2">Issue-by-issue points</h3>
                  <div className="space-y-1.5">
                    {r.breakdown.map((b) => (
                      <div key={b.issue_id} className="flex items-center gap-3">
                        <span className="w-44 shrink-0 truncate text-zinc-400">{b.issue_name}</span>
                        <div className="h-2 flex-1 rounded bg-zinc-800">
                          {b.alignment !== null && (
                            <div
                              className={`h-2 rounded ${
                                b.status === "match"
                                  ? "bg-emerald-400"
                                  : b.status === "partial"
                                  ? "bg-yellow-400"
                                  : "bg-red-400"
                              }`}
                              style={{ width: `${(b.alignment ?? 0) * 100}%` }}
                            />
                          )}
                        </div>
                        <span className="w-20 shrink-0 text-right text-xs text-zinc-500">
                          {b.status === "unknown" ? "no evidence" : `${Math.round((b.alignment ?? 0) * 100)}%`}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>

                {r.top_conflicts.length > 0 && (
                  <p className="text-xs text-zinc-500">
                    <span className="text-red-400 font-medium">Disagreements shown, not hidden: </span>
                    conflicts with you on {r.top_conflicts.map((c) => c.issue_name).join(", ")}.
                  </p>
                )}
                {r.unknown_issues.length > 0 && (
                  <p className="text-xs text-zinc-500">
                    <span className="text-zinc-400 font-medium">Unknown: </span>
                    no reliable evidence on {r.unknown_issues.map((u) => u.issue_name).join(", ")}.
                  </p>
                )}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
