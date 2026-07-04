"use client";

// Fetches and renders the "what this means for you" read for whichever race
// id BallotSection's button last set. Grounded entirely in what
// /api/voter-insights returns — every bullet keeps its source link, and
// empty/unavailable data is shown honestly rather than papered over.
//
// AESTHETIC QA PASS: text-zinc-500/600 -> text-zinc-400 and border-zinc-700
// -> border-zinc-500 for the same measured reason as BallotSection.tsx (old
// shades fell under the WCAG AA 4.5:1 / 3:1 floors against this module's
// actual zinc-900/50-on-navy and zinc-950 surfaces; zinc-400/zinc-500 clear
// both with margin on every surface here). Loading state rebuilt as a
// skeleton shaped like the real InsightsBody (caption bar + 2-col candidate
// tiles) instead of one line of text, so the panel doesn't jump height when
// data lands. Error state gained the same red-card container
// (border-red-900/50 bg-red-950/20 rounded-lg p-4) results/page.tsx already
// uses for its ballot-fetch error, so the two error states in this flow
// read as one consistent "something failed" idiom instead of two.
import { useEffect, useState } from "react";
import type {
  Districts,
  HorizonBullet,
  InsightsResponse,
  LongTermHorizonBullet,
  Race,
} from "@/lib/dataBackend";
import type { VoterProfile } from "@/lib/types";
import { markReviewed, readinessKey } from "@/lib/readiness";

type FetchState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "done"; result: InsightsResponse };

// Loading skeleton shaped like InsightsBody's real output (caption line +
// a 2-col grid of candidate tiles, each with a name bar and 2 text lines)
// so the panel's height doesn't jump once data arrives. aria-hidden because
// the sr-only status text below it is the actual accessible announcement.
function InsightsSkeleton() {
  return (
    <div className="animate-pulse space-y-4" aria-hidden="true">
      <div className="h-3 w-2/3 rounded bg-zinc-800" />
      <div className="grid gap-3 sm:grid-cols-2">
        {[0, 1].map((i) => (
          <div key={i} className="space-y-2 rounded-lg bg-zinc-950 p-3">
            <div className="h-3 w-1/2 rounded bg-zinc-800" />
            <div className="h-2.5 w-full rounded bg-zinc-800" />
            <div className="h-2.5 w-5/6 rounded bg-zinc-800" />
          </div>
        ))}
      </div>
    </div>
  );
}

// Plain-English reason this read is personalized the way it is, keyed to
// app/main.py's _profile_archetype() exact return values (CLAUDE.md
// "Insight archetypes"). Purely a copy lookup against the archetype the
// backend already picked -- no new fetch, no re-derivation of the profile.
const ARCHETYPE_REASONS: Record<string, string> = {
  veteran: "Personalized because you selected veteran",
  small_business_owner: "Personalized because you marked small business owner",
  student: "Personalized because you selected student",
  healthcare_aca_or_uninsured: "Personalized because healthcare coverage was marked",
  medicare_retiree: "Personalized because you selected Medicare/retiree",
  homeowner_parent: "Personalized because you marked kids in public school",
  renter_young_worker: "Personalized because you selected renter",
  rural_agriculture: "Personalized because you selected an agriculture background",
  base: "General view — add profile details for a personalized take",
};

// Rendered under the panel title once a result is in. Reads only
// result.archetype_used -- never triggers or waits on a fetch itself.
function PersonalizationNote({ archetypeUsed }: { archetypeUsed?: string }) {
  if (!archetypeUsed) return null;
  const reason = ARCHETYPE_REASONS[archetypeUsed];
  if (!reason) return null;
  return <p className="mb-3 text-xs text-zinc-400">{reason}</p>;
}

export function InsightsPanel({
  raceId,
  races,
  profile,
  districts,
  prefetched,
}: {
  raceId: string | null;
  races: Race[];
  profile?: VoterProfile;
  // OPTIONAL: pass `ballot.districts` from the /api/ballot response so
  // opening this panel marks the race "reviewed" under the same
  // district-keyed readiness bucket BallotSection reads (lib/readiness.ts).
  districts?: Districts | null;
  // OPTIONAL: race_id -> already-resolved InsightsResponse, warmed by
  // app/results/page.tsx's post-ballot-load prefetch (design spec §4) for
  // the single highest-signal demo race. Purely additive to the existing
  // click-to-fetch flow below -- entries are folded into this panel's own
  // `cache` (never overwriting a race already fetched live), so a click on
  // an already-warmed race resolves from cache instantly instead of
  // showing the loading state. Absent/empty behaves exactly as before this
  // prop existed.
  prefetched?: Record<string, InsightsResponse>;
}) {
  const [state, setState] = useState<FetchState>({ status: "idle" });
  const [cache, setCache] = useState<Record<string, InsightsResponse>>({});

  // Fold newly-arrived prefetched entries into our own cache as they land
  // (the prefetch resolves asynchronously, typically well after this panel
  // has already mounted). Never overwrites an entry already present -- a
  // race the user opened live keeps its own (identical) result. Returning
  // the same `c` reference when nothing changed lets React bail out of the
  // re-render instead of looping.
  useEffect(() => {
    if (!prefetched) return;
    setCache((c) => {
      let changed = false;
      const next = { ...c };
      for (const [id, result] of Object.entries(prefetched)) {
        if (!(id in next)) {
          next[id] = result;
          changed = true;
        }
      }
      return changed ? next : c;
    });
  }, [prefetched]);

  useEffect(() => {
    if (!raceId) {
      setState({ status: "idle" });
      return;
    }

    // "Opening" this race's insights — cached or freshly fetched — is what
    // ballot-readiness means (improvements.md #2): mark it reviewed as soon
    // as it's requested, not only once the fetch succeeds.
    markReviewed(readinessKey(districts), raceId);

    const cached = cache[raceId];
    if (cached) {
      setState({ status: "done", result: cached });
      return;
    }

    let cancelled = false;
    setState({ status: "loading" });

    fetch("/api/voter-insights", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ profile, race_id: raceId }),
    })
      .then(async (r) => {
        const body = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(body?.error ?? `Request failed (${r.status})`);
        return body as InsightsResponse;
      })
      .then((result) => {
        if (cancelled) return;
        setCache((c) => ({ ...c, [raceId]: result }));
        setState({ status: "done", result });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setState({
          status: "error",
          message: err instanceof Error ? err.message : "Could not load insights",
        });
      });

    return () => {
      cancelled = true;
    };
    // profile/districts are captured at click time; refetch only when the
    // target race changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [raceId]);

  if (state.status === "idle") {
    return (
      <div className="rounded-xl border border-dashed border-zinc-500 p-5 text-sm text-zinc-400">
        Click “What this means for you” on any race above for a plain-English, source-linked read
        on what each candidate would likely mean for someone in your stated situation.
      </div>
    );
  }

  const race = races.find((r) => r.race_id === raceId);

  return (
    <div className="rounded-xl border border-zinc-500 bg-zinc-900/50 p-5">
      <h3 className="mb-3 font-semibold">
        What this means for you{race ? ` — ${race.office}` : ""}
      </h3>
      {state.status === "done" && <PersonalizationNote archetypeUsed={state.result.archetype_used} />}

      {state.status === "loading" && (
        <>
          <InsightsSkeleton />
          <p role="status" className="sr-only">
            Writing your evidence-grounded explanation…
          </p>
        </>
      )}
      {state.status === "error" && (
        <div className="rounded-lg border border-red-900/50 bg-red-950/20 p-4 text-sm text-red-400">
          {state.message}
        </div>
      )}
      {state.status === "done" && (
        <InsightsBody result={state.result} race={race} profile={profile} />
      )}
    </div>
  );
}

// One "now" or "long_term" bullet from `horizons` (CLAUDE.md § Consequence
// horizons). Long-term ones are explicitly conditional projections, never
// presented as fact — the "projection" badge and the "Assumes:" footnote
// (only rendered when the field is actually present) are what keep that
// visually unmistakable next to the plain "now" bullets.
function HorizonBulletItem({
  bullet,
  projection,
}: {
  bullet: HorizonBullet | LongTermHorizonBullet;
  projection?: boolean;
}) {
  const assumption = projection ? (bullet as LongTermHorizonBullet).assumption : undefined;
  return (
    <li className="text-xs text-zinc-400">
      {bullet.text}
      {projection && (
        <span className="ml-1.5 inline-block rounded-full border border-zinc-500 px-1.5 py-0 align-middle text-[9px] uppercase tracking-wide text-zinc-400">
          Projection
        </span>
      )}
      {bullet.source && (
        <a
          href={bullet.source}
          target="_blank"
          rel="noopener noreferrer"
          className="ml-1 text-gold hover:underline"
        >
          source ↗
        </a>
      )}
      {assumption && <span className="mt-0.5 block text-[11px] italic text-zinc-400">Assumes: {assumption}</span>}
    </li>
  );
}

const MONTH_NAMES = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];

// Formats a "YYYY-MM-DD" date string as "Month D, YYYY" using the string's
// own Y/M/D parts directly -- deliberately never `new Date(dateStr)`, which
// parses a bare date string as UTC midnight and then renders a day early via
// .toLocaleDateString() in any timezone behind UTC (i.e. everywhere in the
// US) once the browser applies the viewer's local zone.
function formatGeneratedAt(dateStr: string): string {
  const [y, m, d] = dateStr.split("-");
  const monthName = MONTH_NAMES[parseInt(m, 10) - 1];
  if (!y || !d || !monthName) return dateStr;
  return `${monthName} ${parseInt(d, 10)}, ${y}`;
}

function InsightsBody({
  result,
  race,
  profile,
}: {
  result: InsightsResponse;
  race?: Race;
  profile?: VoterProfile;
}) {
  if (result.mode === "unavailable") {
    return (
      <p className="text-sm text-zinc-400">
        {result.detail ?? "No personalized insights are available for this race yet."}
      </p>
    );
  }

  const hasProfile = !!(
    profile &&
    (profile.occupation ||
      profile.age_bracket ||
      profile.income_bracket ||
      Object.values(profile.flags ?? {}).some(Boolean))
  );
  const candidateIds = Object.keys(result.candidates ?? {});

  return (
    <div className="space-y-4">
      <p className="text-xs text-zinc-400">
        {hasProfile
          ? "Personalized for your stated situation."
          : "No profile details were provided, so this is the general read for this race."}{" "}
        {result.mode === "live"
          ? "Generated live from indexed sources."
          : "From our precomputed, source-checked set."}
      </p>

      {result.summary && <p className="text-sm text-zinc-300">{result.summary}</p>}

      {candidateIds.length === 0 ? (
        <p className="text-sm text-zinc-400">No candidate-level insights available for this race yet.</p>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2">
          {candidateIds.map((cid) => {
            const bullets = result.candidates[cid] ?? [];
            const name = race?.candidates.find((c) => c.candidate_id === cid)?.name ?? cid;
            // Additive, optional structure (absent on responses that predate
            // it) — when missing, this candidate renders exactly as before.
            const horizons = result.horizons?.[cid];
            const nowBullets = horizons?.now ?? [];
            const longTermBullets = horizons?.long_term ?? [];
            const hasHorizons = nowBullets.length > 0 || longTermBullets.length > 0;
            return (
              <div key={cid} className="rounded-lg bg-zinc-950 p-3">
                <div className="mb-1.5 text-sm font-medium text-zinc-200">{name}</div>
                {bullets.length > 0 ? (
                  <ul className="space-y-1.5">
                    {bullets.map((b, i) => (
                      <li key={i} className="text-xs text-zinc-400">
                        {b.text}
                        {b.source && (
                          <a
                            href={b.source}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="ml-1 text-gold hover:underline"
                          >
                            source ↗
                          </a>
                        )}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-xs text-zinc-400">
                    No public data in our set for this candidate here.
                  </p>
                )}

                {hasHorizons && (
                  <div className="mt-3 space-y-3 border-t border-zinc-500 pt-2.5">
                    {nowBullets.length > 0 && (
                      <div>
                        <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-zinc-400">
                          Right now
                        </div>
                        <ul className="space-y-1.5">
                          {nowBullets.map((b, i) => (
                            <HorizonBulletItem key={i} bullet={b} />
                          ))}
                        </ul>
                      </div>
                    )}
                    {longTermBullets.length > 0 && (
                      <div>
                        <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-zinc-400">
                          Down the road (projection)
                        </div>
                        <ul className="space-y-1.5">
                          {longTermBullets.map((b, i) => (
                            <HorizonBulletItem key={i} bullet={b} projection />
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {result.caveats && (
        <p className="text-xs text-zinc-400">
          <span className="text-gold/90">Caveat:</span> {result.caveats}
        </p>
      )}

      {/* Same "How we know" idiom as BallotSection's per-race disclosure
          (improvements.md "Add a concise How we know section on race cards
          or the insight panel... last checked/generated value if
          available") -- scoped to this insight's own provenance (when it
          was generated), not the candidate data provenance the race card's
          version already covers. Only present on mode "cached", since that's
          the only mode carrying a precomputed doc's generated_at. */}
      {result.generated_at && (
        <details className="rounded-lg border border-zinc-500 bg-zinc-950/40 p-3 text-xs text-zinc-400">
          <summary className="cursor-pointer select-none font-medium text-zinc-300">How we know</summary>
          <div className="mt-2 max-w-prose space-y-1.5">
            <p>Insights generated: {formatGeneratedAt(result.generated_at)}</p>
          </div>
        </details>
      )}
    </div>
  );
}

export default InsightsPanel;
