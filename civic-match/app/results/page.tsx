"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { loadPrefs } from "@/lib/prefs";
import type { MatchResult, UserPreferences, VoterProfile } from "@/lib/types";
import type { BallotResponse } from "@/lib/dataBackend";
import BallotSection from "@/components/ballot/BallotSection";
import InsightsPanel from "@/components/ballot/InsightsPanel";
import StakesBanner from "@/components/stakes-banner";
import MotivationCard from "@/components/motivation-card";
import { CivitasLinkButton, CivitasPage, CivitasPanel, MetricSeal, StatusPill } from "@/components/civitas-ui";

interface PoliticianSummary {
  id: string;
  name: string;
  party?: string;
  current_office?: string;
}

function ovrColor(overall: number) {
  if (overall >= 90) return "border-gold/80 text-white";
  if (overall >= 83) return "border-gold/60 text-white";
  if (overall >= 75) return "border-cream/35 text-cream-light";
  if (overall >= 68) return "border-red/45 text-red-100";
  return "border-red/60 text-red-100";
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
  const [prefs, setPrefs] = useState<UserPreferences | null>(null);
  const [prefsLoaded, setPrefsLoaded] = useState(false);
  const [results, setResults] = useState<MatchResult[] | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [explanations, setExplanations] = useState<Record<string, Explanation | "loading">>({});
  const [ballotState, setBallotState] = useState<BallotState>({ status: "idle" });
  const [activeRaceId, setActiveRaceId] = useState<string | null>(null);
  const voterName = prefs?.profile?.name;
  const voterProfile = prefs?.profile as VoterProfile | undefined;
  const address = prefs?.address;

  useEffect(() => {
    const loaded = loadPrefs();
    setPrefs(loaded);
    setBallotState(loaded?.address ? { status: "loading" } : { status: "idle" });
    setPrefsLoaded(true);
  }, []);

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
    if (!prefs) return;

    let cancelled = false;

    if (prefs.address) {
      fetch(`/api/ballot?address=${encodeURIComponent(prefs.address)}`)
        .then(async (r) => {
          const body = await r.json();
          if (!r.ok) throw new Error(body?.error ?? `Request failed (${r.status})`);
          return body as BallotResponse;
        })
        .then((data) => {
          if (!cancelled) setBallotState({ status: "done", data });
        })
        .catch((err: unknown) => {
          if (cancelled) return;
          setBallotState({
            status: "error",
            message: err instanceof Error ? err.message : "Could not load your ballot",
          });
        });
    }

    (async () => {
      const list: PoliticianSummary[] = await fetch("/api/politicians").then((r) => r.json());
      const res = await fetch("/api/match", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prefs, politician_ids: list.map((p) => p.id) }),
      }).then((r) => r.json());
      if (!cancelled) setResults(res.results);
    })();

    return () => {
      cancelled = true;
    };
  }, [prefs]);

  if (!prefsLoaded) {
    return (
      <CivitasPage eyebrow="Matches" title="Loading your saved priorities">
      <div className="animate-pulse text-sm text-white/45">
        Loading your saved priorities...
      </div>
      </CivitasPage>
    );
  }

  if (!prefs) {
    return (
      <CivitasPage eyebrow="Matches" title="Set your priorities first">
        <p className="mb-5 text-white/62">You haven&apos;t set your priorities yet.</p>
        <CivitasLinkButton href="/intake">
          Pick your priorities
        </CivitasLinkButton>
      </CivitasPage>
    );
  }

  if (!results) {
    return (
      <CivitasPage eyebrow="Matches" title="Scoring candidate records">
      <div className="animate-pulse text-sm text-white/45">
        Scoring cached candidate profiles…
      </div>
      </CivitasPage>
    );
  }

  return (
    <CivitasPage
      eyebrow="Evidence dossier"
      title={voterName ? `${voterName}, here's your alignment` : "Your candidate alignment"}
      description={
        <>
        Overall = 60–99, 2K style: quantitative issue alignment + qualitative record
        (integrity, transparency, experience) − conflicts on your top issues. Every
        number decomposes to ground truth — click a card and follow the sources.
        </>
      }
    >
      <div className="mb-8">
        <Link href="/intake" className="text-xs font-semibold uppercase tracking-[0.18em] text-gold hover:text-white">
          Edit priorities
        </Link>
      </div>

      <MotivationCard />
      <StakesBanner />

      <div className="space-y-4">
        {results.map((r) => (
          <CivitasPanel
            key={r.politician_id}
            className="overflow-hidden"
          >
            <button
              className="flex w-full items-center gap-5 p-5 text-left hover:bg-white/[0.035]"
              onClick={() => toggleExpand(r.politician_id)}
            >
              <MetricSeal value={r.overall} label="OVR" className={ovrColor(r.overall)} />
              <div className="min-w-0 flex-1">
                <div className="flex items-baseline gap-2">
                  <span className="truncate font-serif text-xl text-white">{r.politician_name}</span>
                  {r.party && <span className="text-xs text-white/42">({r.party})</span>}
                </div>
                <div className="text-sm text-white/58">{r.overall_tier}</div>
                {r.warnings.length > 0 && (
                  <div className="mt-1 flex flex-wrap gap-1.5">
                    {r.warnings.map((w) => (
                      <StatusPill key={w} tone="red">{w}</StatusPill>
                    ))}
                  </div>
                )}
                <div className="mt-2 flex flex-wrap gap-4 text-xs text-white/45">
                  <span>Issue alignment: <b className="text-white/75">{r.score}%</b></span>
                  <span>
                    Record quality:{" "}
                    <b className="text-white/75">
                      {r.qualitative_composite !== null
                        ? `${Math.round(r.qualitative_composite * 100)}%`
                        : "n/a"}
                    </b>
                  </span>
                  <span>Evidence: <b className="text-white/75">{r.confidence}</b></span>
                </div>
              </div>
              <Link
                href={`/p/${r.politician_id}`}
                onClick={(e) => e.stopPropagation()}
                className="shrink-0 text-xs font-semibold uppercase tracking-[0.16em] text-gold hover:text-white"
              >
                Full profile
              </Link>
            </button>

            {expanded === r.politician_id && (
              <div className="space-y-4 border-t border-white/10 p-5 text-sm">
                {explanations[r.politician_id] === "loading" ? (
                  <div className="animate-pulse rounded-[8px] border border-white/10 bg-navy-dark/60 p-4 text-sm text-white/45">
                    Writing your evidence-grounded explanation…
                  </div>
                ) : explanations[r.politician_id] ? (
                  (() => {
                    const ex = explanations[r.politician_id] as Explanation;
                    return (
                      <div className="space-y-3 rounded-[8px] border border-white/10 bg-navy-dark/60 p-4">
                        <p className="font-medium text-white/82">{ex.headline}</p>
                        {ex.agreements.length > 0 && (
                          <ul className="space-y-1 text-white/62">
                            {ex.agreements.map((a, i) => (
                              <li key={i} className="flex gap-2">
                                <span className="shrink-0 text-gold">+</span>
                                {a}
                              </li>
                            ))}
                          </ul>
                        )}
                        {ex.conflicts.length > 0 && (
                          <ul className="space-y-1 text-white/62">
                            {ex.conflicts.map((c, i) => (
                              <li key={i} className="flex gap-2">
                                <span className="shrink-0 text-red-200">-</span>
                                {c}
                              </li>
                            ))}
                          </ul>
                        )}
                        <p className="text-xs text-white/45">
                          <span className="text-gold">Caveat:</span> {ex.caveat}
                        </p>
                        <p className="text-xs text-white/35">{ex.evidence_note}</p>
                      </div>
                    );
                  })()
                ) : null}

                <div className="grid grid-cols-3 gap-3 text-center text-xs">
                  <div className="rounded-[8px] border border-white/10 bg-navy-dark/60 p-3">
                    <div className="font-serif text-xl text-gold">
                      +{r.overall_components.alignment_component}
                    </div>
                    <div className="text-white/42">from issue alignment (quant)</div>
                  </div>
                  <div className="rounded-[8px] border border-white/10 bg-navy-dark/60 p-3">
                    <div className="font-serif text-xl text-gold">
                      +{r.overall_components.qualitative_component}
                    </div>
                    <div className="text-white/42">from record quality (qual)</div>
                  </div>
                  <div className="rounded-[8px] border border-white/10 bg-navy-dark/60 p-3">
                    <div className="font-serif text-xl text-red-100">
                      −{r.overall_components.conflict_penalty}
                    </div>
                    <div className="text-white/42">conflicts on your top issues</div>
                  </div>
                </div>

                {r.qualitative.length > 0 && (
                  <div>
                    <h3 className="mb-2 font-serif text-xl text-white">Record quality (sourced)</h3>
                    <div className="grid gap-2 sm:grid-cols-2">
                      {r.qualitative.map((q) => (
                        <div key={q.id} className="rounded-[8px] border border-white/10 bg-navy-dark/60 p-3">
                          <div className="flex justify-between mb-1">
                            <span className="text-white/72">{q.label}</span>
                            <span className="font-mono text-gold">
                              {Math.round(q.score * 100)}
                            </span>
                          </div>
                          <p className="text-xs text-white/42">{q.summary}</p>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                <div>
                  <h3 className="mb-2 font-serif text-xl text-white">Issue-by-issue points</h3>
                  <div className="space-y-1.5">
                    {r.breakdown.map((b) => (
                      <div key={b.issue_id} className="flex items-center gap-3">
                        <span className="w-44 shrink-0 truncate text-white/58">{b.issue_name}</span>
                        <div className="h-2 flex-1 rounded bg-white/10">
                          {b.alignment !== null && (
                            <div
                              className={`h-2 rounded ${
                                b.status === "match"
                                  ? "bg-gold"
                                  : b.status === "partial"
                                  ? "bg-cream"
                                  : "bg-red"
                              }`}
                              style={{ width: `${(b.alignment ?? 0) * 100}%` }}
                            />
                          )}
                        </div>
                        <span className="w-20 shrink-0 text-right text-xs text-white/42">
                          {b.status === "unknown" ? "no evidence" : `${Math.round((b.alignment ?? 0) * 100)}%`}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>

                {r.top_conflicts.length > 0 && (
                  <p className="text-xs text-white/45">
                    <span className="font-medium text-red-100">Disagreements shown, not hidden: </span>
                    conflicts with you on {r.top_conflicts.map((c) => c.issue_name).join(", ")}.
                  </p>
                )}
                {r.unknown_issues.length > 0 && (
                  <p className="text-xs text-white/45">
                    <span className="font-medium text-white/65">Unknown: </span>
                    no reliable evidence on {r.unknown_issues.map((u) => u.issue_name).join(", ")}.
                  </p>
                )}
              </div>
            )}
          </CivitasPanel>
        ))}
      </div>

      {address && (
        <section className="mt-14 border-t border-white/10 pt-8">
          <h2 className="mb-1 font-serif text-3xl font-normal text-white">Your ballot</h2>
          <p className="mb-6 text-sm leading-6 text-white/52">
            Races and candidates for{" "}
            {ballotState.status === "done" ? ballotState.data.matched_address : address}, sourced
            from FEC filings, House Clerk roll-call votes, and official candidate lists.
          </p>

          {ballotState.status === "loading" && (
            <div className="animate-pulse text-sm text-white/45">Loading your ballot…</div>
          )}
          {ballotState.status === "error" && (
            <div className="rounded-[8px] border border-red/45 bg-red/10 p-4 text-sm text-red-100">
              {ballotState.message}
            </div>
          )}
          {ballotState.status === "done" && (
            <>
              {ballotState.data.warning && (
                <p className="mb-4 text-xs text-gold">{ballotState.data.warning}</p>
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
    </CivitasPage>
  );
}
