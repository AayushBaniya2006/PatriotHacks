"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { loadPrefs } from "@/lib/prefs";
import type { MatchResult, VoterProfile } from "@/lib/types";
import type { BallotResponse, InsightsResponse, Race } from "@/lib/dataBackend";
import BallotSection from "@/components/ballot/BallotSection";
import InsightsPanel from "@/components/ballot/InsightsPanel";
import VotingPlan from "@/components/ballot/VotingPlan";
import StakesBanner from "@/components/stakes-banner";
import MotivationCard from "@/components/motivation-card";

// Auto-research handler — triggers the research agent swarm for a
// candidate whose profile has insufficient sourced data to score, and
// streams its SSE progress into the inline status line rendered next to
// the "Auto-Research" button below. Reloads the page on completion so the
// freshly-researched profile flows back through the normal scoring path.
async function handleResearchNow(slug: string) {
  const statusEl = document.getElementById(`research-status-${slug}`);
  const messageEl = document.getElementById(`research-message-${slug}`);

  if (statusEl && messageEl) {
    statusEl.classList.remove("hidden");
    messageEl.textContent = "Starting research swarm...";
  }

  try {
    const response = await fetch("/api/research", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: slug, force: false }),
    });

    if (!response.ok) throw new Error("Research failed");

    const reader = response.body?.getReader();
    const decoder = new TextDecoder();

    if (reader) {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value);
        const lines = chunk.split("\n\n");

        for (const line of lines) {
          if (line.startsWith("data: ")) {
            const event = JSON.parse(line.slice(6));

            if (event.type === "progress" && messageEl) {
              messageEl.textContent = event.message || "Researching...";
            } else if (event.type === "complete") {
              if (messageEl) {
                messageEl.textContent = "✓ Research complete! Reloading...";
              }
              // Reload the page to show updated data
              setTimeout(() => window.location.reload(), 1500);
              return;
            } else if (event.type === "error") {
              if (messageEl) {
                messageEl.textContent = `✗ Error: ${event.message}`;
              }
              return;
            }
          }
        }
      }
    }
  } catch (error) {
    if (messageEl) {
      messageEl.textContent = `✗ Error: ${error instanceof Error ? error.message : "Research failed"}`;
    }
  }
}

interface PoliticianSummary {
  id: string;
  name: string;
  party?: string;
  current_office?: string;
}

function ovrColor(overall: number) {
  if (overall >= 88) return "text-gold border-gold/55";
  if (overall >= 78) return "text-cream-light border-cream/30";
  if (overall >= 70) return "text-white/75 border-white/25";
  if (overall >= 62) return "text-white/55 border-white/18";
  return "text-red-300 border-red-400/35";
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

// P1 prefetch (design spec §4) -- once the ballot is in, warm
// /api/voter-insights for the single highest-signal demo race in the
// background so a judge's first click on "What this means for you"
// resolves from InsightsPanel's own cache instantly instead of showing the
// loading state.
//
// "Highest-ranked" = the numerically LOWEST race.data_quality.demo_rank.
// pipeline/score_quality.py assigns demo_rank 1-indexed ascending across
// the whole dataset, where 1 is the single best/most-demoable race -- see
// also pipeline/demo_readiness_gate.py's resolve_top_demo_rank_race_id(),
// which resolves "the top demo_rank race" the same way (min(), not max()).
function pickTopDemoRankRace(races: Race[]): Race | null {
  let best: Race | null = null;
  let bestRank = Infinity;
  for (const race of races) {
    const rank = race.data_quality?.demo_rank;
    if (typeof rank === "number" && rank < bestRank) {
      best = race;
      bestRank = rank;
    }
  }
  return best;
}

// Staged status for the "Your ballot" load sequence (improvements.md "Demo
// UX Requirements" > Staged Progress). Each label maps to a real async
// boundary already in this component: the ballot fetch itself (Finding your
// ballot), races having rendered while the top-demo-rank race's prefetch
// above is still in flight (Loading public records / Checking sources), and
// that prefetch settling (Ready). No setTimeout/fake delay anywhere -- every
// transition is a real fetch state change, and a ballot with no
// demo_rank-carrying race (pickTopDemoRankRace returns null) has nothing to
// prefetch, so this goes straight from "Finding" to "Ready" rather than
// flashing a "Checking sources" stage with no real request behind it.
type Stage =
  | { key: "finding"; label: string }
  | { key: "finding_failed"; label: string; detail: string }
  | { key: "records"; label: string }
  | { key: "sources"; label: string }
  | { key: "sources_failed"; label: string; detail: string }
  | { key: "ready"; label: string };

function lowerFirst(s: string): string {
  return s.length > 0 ? s.charAt(0).toLowerCase() + s.slice(1) : s;
}

function deriveStage(
  ballot: BallotState,
  hasTopRace: boolean,
  prefetchPhase: "idle" | "loading" | "done" | "error",
  prefetchDetail: string | null
): Stage {
  if (ballot.status === "idle" || ballot.status === "loading") {
    return { key: "finding", label: "Finding your ballot" };
  }
  if (ballot.status === "error") {
    return {
      key: "finding_failed",
      label: "Finding your ballot",
      detail: `District lookup unavailable — ${ballot.message}`,
    };
  }
  // ballot.status === "done" below.
  if (!hasTopRace) return { key: "ready", label: "Ready" };
  if (prefetchPhase === "idle") return { key: "records", label: "Loading public records" };
  if (prefetchPhase === "loading") return { key: "sources", label: "Checking sources" };
  if (prefetchPhase === "error") {
    return {
      key: "sources_failed",
      label: "Checking sources",
      detail: `Ballot loaded, but ${lowerFirst(prefetchDetail ?? "insights are not cached for this race yet")}.`,
    };
  }
  return { key: "ready", label: "Ready" };
}

// Small, non-blocking status line -- deliberately never a scary/blocking
// error for the "sources" sub-stage (the P1 prefetch is silent-by-design:
// InsightsPanel's own click-to-fetch path works regardless of this line).
// "Finding your ballot" failing is the one case that reuses the existing red
// ballot-error styling, since that IS a real blocker -- there's no ballot to
// show at all.
function BallotStageStatus({ stage }: { stage: Stage }) {
  if (stage.key === "ready") {
    return <p className="mb-4 text-xs text-gold/80">✓ Ready</p>;
  }
  if (stage.key === "finding_failed") {
    return (
      <div className="mb-4 rounded-lg border border-red-900/50 bg-red-950/20 p-4 text-sm text-red-400">
        {stage.detail}
      </div>
    );
  }
  const failed = stage.key === "sources_failed";
  return (
    <div className="mb-4">
      <p className={failed ? "text-sm text-zinc-400" : "text-sm text-zinc-500 animate-pulse"}>{stage.label}…</p>
      {failed && <p className="mt-1 text-xs text-zinc-600">{stage.detail}</p>}
    </div>
  );
}

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
  // race_id -> InsightsResponse warmed by the post-ballot-load prefetch
  // below (design spec §4). Handed to InsightsPanel as `prefetched`.
  const [prefetchedInsights, setPrefetchedInsights] = useState<Record<string, InsightsResponse>>({});
  // Lifecycle of that same prefetch request (idle -> loading -> done/error),
  // tracked purely to drive the "Checking sources" / "Ready" staged-progress
  // line below (improvements.md "Demo UX Requirements" > Staged Progress).
  // Never affects the prefetch's own silent-on-failure behavior above --
  // InsightsPanel's click-to-fetch path is unaffected either way.
  const [prefetchPhase, setPrefetchPhase] = useState<"idle" | "loading" | "done" | "error">("idle");
  // The prefetch's backend-provided detail text on a settled-but-unavailable
  // or failed response (e.g. "Insights not yet generated for this race"),
  // reused verbatim in the stage-failure message rather than inventing one.
  const [prefetchDetail, setPrefetchDetail] = useState<string | null>(null);

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
        .then((data) => {
          setBallotState({ status: "done", data });
        })
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

  // P1 prefetch (design spec §4) -- once the ballot is in, warm
  // /api/voter-insights for the single highest-signal demo race in the
  // background so a judge's first click on "What this means for you"
  // resolves from InsightsPanel's own cache instantly instead of showing
  // the loading state. Fire-and-forget for InsightsPanel's own purposes
  // (silent on failure -- its click-to-fetch path is completely untouched
  // either way), but prefetchPhase/prefetchDetail additionally track this
  // request's own lifecycle to drive the "Loading public records" /
  // "Checking sources" / "Ready" staged-progress line below (improvements.md
  // "Demo UX Requirements" > Staged Progress). Split into its own effect
  // (rather than chained inside the ballot fetch's .then()) specifically so
  // "Loading public records" -- ballotState done, this effect not yet run --
  // is a real, separately-rendered moment instead of always collapsing into
  // the same React commit as "done".
  useEffect(() => {
    if (ballotState.status !== "done") return;
    if (prefetchPhase !== "idle") return; // fire once per resolved ballot
    const topRace = pickTopDemoRankRace(ballotState.data.races);
    if (!topRace) return;

    let cancelled = false;
    setPrefetchPhase("loading");
    fetch("/api/voter-insights", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ profile: voterProfile, race_id: topRace.race_id }),
    })
      .then(async (r) => {
        const result = (await r.json().catch(() => null)) as (InsightsResponse & { error?: string }) | null;
        if (cancelled) return;
        if (!r.ok || !result) {
          setPrefetchPhase("error");
          setPrefetchDetail(result?.error ?? null);
          return;
        }
        setPrefetchedInsights((prev) => ({ ...prev, [topRace.race_id]: result }));
        if (result.mode === "unavailable") {
          // Settled, but nothing to warm the cache with -- still a real,
          // honest "sources" outcome, not a network failure.
          setPrefetchPhase("error");
          setPrefetchDetail(result.detail ?? null);
        } else {
          setPrefetchPhase("done");
        }
      })
      .catch(() => {
        // Silent by design -- see comment above; still recorded for the
        // staged-progress line (network-level failure, no backend detail
        // text available).
        if (cancelled) return;
        setPrefetchPhase("error");
        setPrefetchDetail(null);
      });

    return () => {
      cancelled = true;
    };
    // voterProfile/prefetchPhase are read, not depended on: re-running when
    // voterProfile's reference changes isn't wanted (it's set once at mount)
    // and prefetchPhase is only read here to guard the fire-once behavior.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ballotState]);

  if (noPrefs) {
    return (
      <div className="mx-auto max-w-2xl px-4 py-16 text-center">
        <p className="text-zinc-400 mb-4">You haven&apos;t set your priorities yet.</p>
        <Link href="/intake" className="rounded-lg bg-gold px-5 py-2.5 font-medium text-navy-dark">
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

  // The single "featured" race (data_quality.demo_rank 1, same lookup the
  // prefetch above already uses) -- BallotSection renders this one full and
  // labeled "Featured race", every other race at compact/secondary density.
  const featuredRace = ballotState.status === "done" ? pickTopDemoRankRace(ballotState.data.races) : null;
  const stage = deriveStage(ballotState, featuredRace !== null, prefetchPhase, prefetchDetail);

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
        number decomposes to ground truth — click a card and follow the sources.
      </p>

      <MotivationCard />
      <StakesBanner />

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
              {r.insufficient_data ? (
                <div className="flex h-16 w-16 shrink-0 flex-col items-center justify-center rounded-xl border-2 border-dashed border-zinc-700 bg-zinc-950 text-zinc-500">
                  <span className="text-2xl font-black leading-none">–</span>
                  <span className="text-[9px] uppercase tracking-widest opacity-80">no data</span>
                </div>
              ) : (
                <div
                  className={`flex h-16 w-16 shrink-0 flex-col items-center justify-center rounded-xl border-2 bg-zinc-950 ${ovrColor(r.overall)}`}
                >
                  <span className="text-2xl font-black leading-none">{r.overall}</span>
                  <span className="text-[9px] uppercase tracking-widest opacity-80">OVR</span>
                </div>
              )}
              <div className="min-w-0 flex-1">
                <div className="flex items-baseline gap-2">
                  <span className="font-semibold truncate">{r.politician_name}</span>
                  {r.party && <span className="text-xs text-zinc-500">({r.party})</span>}
                </div>
                <div className="text-sm text-zinc-400">
                  {r.insufficient_data ? "Limited data — research pending" : r.overall_tier}
                </div>
                {r.warnings.length > 0 && (
                  <div className="mt-1 flex flex-wrap gap-1.5">
                    {r.warnings.map((w) => (
                      <span key={w} className="rounded-full border border-red-500/40 bg-red-500/10 px-2 py-0.5 text-[10px] text-red-300">
                        ⚠ {w}
                      </span>
                    ))}
                  </div>
                )}
                <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs text-zinc-500">
                  {r.insufficient_data ? (
                    <span>
                      Not scored — sourced evidence on{" "}
                      <b className="text-zinc-300">
                        {r.coverage.scored_issues} of your {r.coverage.user_issues}
                      </b>{" "}
                      issues ({r.coverage.profile_stances} researched position
                      {r.coverage.profile_stances === 1 ? "" : "s"} total)
                    </span>
                  ) : (
                    <>
                      <span>Issue alignment: <b className="text-zinc-300">{r.score}%</b></span>
                      <span>
                        Scored on{" "}
                        <b className="text-zinc-300">
                          {r.coverage.scored_issues} of your {r.coverage.user_issues}
                        </b>{" "}
                        issues
                      </span>
                      <span>
                        Record quality:{" "}
                        <b className="text-zinc-300">
                          {r.qualitative_composite !== null
                            ? `${Math.round(r.qualitative_composite * 100)}%`
                            : "n/a"}
                        </b>
                      </span>
                      <span>Evidence: <b className="text-zinc-300">{r.confidence}</b></span>
                    </>
                  )}
                </div>
              </div>
              <Link
                href={`/p/${r.politician_id}`}
                onClick={(e) => e.stopPropagation()}
                className="text-xs text-gold hover:underline shrink-0"
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
                                <span className="text-gold shrink-0">+</span>
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
                          <span className="text-gold/90">Caveat:</span> {ex.caveat}
                        </p>
                        <p className="text-xs text-zinc-600">{ex.evidence_note}</p>
                      </div>
                    );
                  })()
                ) : null}

                {r.insufficient_data ? (
                  <div className="space-y-2">
                    <div className="rounded-lg border border-dashed border-zinc-700 bg-zinc-950 p-3 text-xs text-zinc-400">
                      <span className="text-zinc-300 font-medium">Limited data — research pending.</span>{" "}
                      Our research set doesn&apos;t have enough sourced positions for this
                      candidate to compute an honest score, so no rating is shown. This
                      reflects our coverage, not the candidate&apos;s record.
                    </div>
                    <button
                      onClick={() => handleResearchNow(r.politician_id)}
                      className="w-full rounded-md bg-gold/15 border border-gold/40 px-3 py-2 text-xs font-medium text-gold hover:bg-gold/25 transition-colors"
                    >
                      🔬 Auto-Research via Agent Swarm (Uses Government Data)
                    </button>
                    <div id={`research-status-${r.politician_id}`} className="hidden rounded-lg bg-zinc-950 p-3 text-xs text-zinc-400">
                      <span id={`research-message-${r.politician_id}`} />
                    </div>
                  </div>
                ) : (
                  <div className="grid grid-cols-3 gap-3 text-center text-xs">
                    <div className="rounded-lg bg-zinc-950 p-3">
                      <div className="text-lg font-bold text-gold">
                        +{r.overall_components.alignment_component}
                      </div>
                      <div className="text-zinc-500">from issue alignment (quant)</div>
                    </div>
                    <div className="rounded-lg bg-zinc-950 p-3">
                      <div className="text-lg font-bold text-sky-400">
                        +{r.overall_components.qualitative_component}
                      </div>
                      <div className="text-zinc-500">from record quality</div>
                    </div>
                    <div className="rounded-lg bg-zinc-950 p-3">
                      <div className="text-lg font-bold text-red-400">
                        −{r.overall_components.conflict_penalty}
                      </div>
                      <div className="text-zinc-500">conflicts on your top issues</div>
                    </div>
                  </div>
                )}

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
                                  ? "bg-gold"
                                  : b.status === "partial"
                                  ? "bg-cream"
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

          <BallotStageStatus stage={stage} />

          {ballotState.status === "done" && (
            <>
              {ballotState.data.warning && (
                <p className="mb-4 text-xs text-gold/90">{ballotState.data.warning}</p>
              )}
              <BallotSection
                races={ballotState.data.races}
                activeRaceId={activeRaceId}
                onExplain={setActiveRaceId}
                districts={ballotState.data.districts}
                featuredRaceId={featuredRace?.race_id ?? null}
              />
              <div className="mt-6">
                <InsightsPanel
                  raceId={activeRaceId}
                  races={ballotState.data.races}
                  profile={voterProfile}
                  districts={ballotState.data.districts}
                  prefetched={prefetchedInsights}
                />
              </div>
              <div className="mt-8">
                <VotingPlan races={ballotState.data.races} districts={ballotState.data.districts} />
              </div>
            </>
          )}
        </section>
      )}
    </div>
  );
}
