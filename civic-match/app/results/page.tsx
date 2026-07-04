"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { loadPrefs } from "@/lib/prefs";
import type { MatchResult, VoterProfile } from "@/lib/types";
import type { BallotResponse } from "@/lib/dataBackend";
import BallotSection from "@/components/ballot/BallotSection";
import InsightsPanel from "@/components/ballot/InsightsPanel";

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

interface Explanation {
  headline: string;
  agreements: string[];
  conflicts: string[];
  caveat: string;
  evidence_note: string;
}

// "Your ballot" section — separate from the match-score UI above, sourced
// from our FastAPI data backend via the same-origin /api/ballot proxy.
type BallotState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "done"; data: BallotResponse };

export default function ResultsPage() {
  const [results, setResults] = useState<MatchResult[] | null>(null);
  const [noPrefs, setNoPrefs] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [explanations, setExplanations] = useState<Record<string, Explanation | "loading">>({});
  const [voterName, setVoterName] = useState<string | undefined>();
  const [voterProfile, setVoterProfile] = useState<VoterProfile | undefined>();
  const [address, setAddress] = useState<string | undefined>();
  const [ballotState, setBallotState] = useState<BallotState>({ status: "idle" });
  const [activeRaceId, setActiveRaceId] = useState<string | null>(null);

  const toggleExpand = (id: string) => {
    const next = expanded === id ? null : id;
    setExpanded(next);
    if (next && !explanations[next]) {
      const prefs = loadPrefs();
      if (!prefs) return;
      setExplanations((e) => ({ ...e, [next]: "loading" }));
      fetch("/api/explain", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ politician_id: next, prefs }),
      })
        .then((r) => r.json())
        .then((res) =>
          setExplanations((e) => ({ ...e, [next]: res.explanation ?? undefined }))
        )
        .catch(() =>
          setExplanations((e) => {
            const copy = { ...e };
            delete copy[next];
            return copy;
          })
        );
    }
  };

  useEffect(() => {
    const prefs = loadPrefs();
    if (!prefs) {
      setNoPrefs(true);
      return;
    }
    setVoterName(prefs.profile?.name);
    setVoterProfile(prefs.profile);
    setAddress(prefs.address);
    if (prefs.address) {
      setBallotState({ status: "loading" });
      fetch(`/api/ballot?address=${encodeURIComponent(prefs.address)}`)
        .then(async (r) => {
          const body = await r.json();
          if (!r.ok) throw new Error(body?.error ?? `Request failed (${r.status})`);
          return body as BallotResponse;
        })
        .then((data) => setBallotState({ status: "done", data }))
        .catch((err: unknown) =>
          setBallotState({
            status: "error",
            message: err instanceof Error ? err.message : "Could not load your ballot",
          })
        );
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
        <h1 className="text-2xl font-bold">
          {voterName ? `${voterName}, here's your alignment` : "Your candidate alignment"}
        </h1>
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
              onClick={() => toggleExpand(r.politician_id)}
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
                {explanations[r.politician_id] === "loading" ? (
                  <div className="rounded-lg bg-zinc-950 p-4 text-zinc-500 animate-pulse text-sm">
                    Writing your evidence-grounded explanation…
                  </div>
                ) : explanations[r.politician_id] ? (
                  (() => {
                    const ex = explanations[r.politician_id] as Explanation;
                    return (
                      <div className="rounded-lg bg-zinc-950 p-4 space-y-3">
                        <p className="font-medium text-zinc-200">{ex.headline}</p>
                        {ex.agreements.length > 0 && (
                          <ul className="space-y-1 text-zinc-400">
                            {ex.agreements.map((a, i) => (
                              <li key={i} className="flex gap-2">
                                <span className="text-emerald-400 shrink-0">+</span>
                                {a}
                              </li>
                            ))}
                          </ul>
                        )}
                        {ex.conflicts.length > 0 && (
                          <ul className="space-y-1 text-zinc-400">
                            {ex.conflicts.map((c, i) => (
                              <li key={i} className="flex gap-2">
                                <span className="text-red-400 shrink-0">−</span>
                                {c}
                              </li>
                            ))}
                          </ul>
                        )}
                        <p className="text-xs text-zinc-500">
                          <span className="text-yellow-500/90">Caveat:</span> {ex.caveat}
                        </p>
                        <p className="text-xs text-zinc-600">{ex.evidence_note}</p>
                      </div>
                    );
                  })()
                ) : null}

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

      {address && (
        <section className="mt-14 border-t border-zinc-800 pt-8">
          <h2 className="text-xl font-bold mb-1">Your ballot</h2>
          <p className="text-sm text-zinc-500 mb-6">
            Races and candidates for{" "}
            {ballotState.status === "done" ? ballotState.data.matched_address : address}, sourced
            from FEC filings, House Clerk roll-call votes, and official candidate lists.
          </p>

          {ballotState.status === "loading" && (
            <div className="text-sm text-zinc-500 animate-pulse">Loading your ballot…</div>
          )}
          {ballotState.status === "error" && (
            <div className="rounded-lg border border-red-900/50 bg-red-950/20 p-4 text-sm text-red-400">
              {ballotState.message}
            </div>
          )}
          {ballotState.status === "done" && (
            <>
              {ballotState.data.warning && (
                <p className="mb-4 text-xs text-yellow-500/90">{ballotState.data.warning}</p>
              )}
              <BallotSection
                races={ballotState.data.races}
                activeRaceId={activeRaceId}
                onExplain={setActiveRaceId}
              />
              <div className="mt-6">
                <InsightsPanel
                  raceId={activeRaceId}
                  races={ballotState.data.races}
                  profile={voterProfile}
                />
              </div>
            </>
          )}
        </section>
      )}
    </div>
  );
}
