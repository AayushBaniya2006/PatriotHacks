"use client";

// Fetches and renders the "what this means for you" read for whichever race
// id BallotSection's button last set. Grounded entirely in what
// /api/voter-insights returns — every bullet keeps its source link, and
// empty/unavailable data is shown honestly rather than papered over.
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
      <div className="rounded-xl border border-dashed border-zinc-800 p-5 text-sm text-zinc-500">
        Click “What this means for you” on any race above for a plain-English, source-linked read
        on what each candidate would likely mean for someone in your stated situation.
      </div>
    );
  }

  const race = races.find((r) => r.race_id === raceId);

  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900/50 p-5">
      <h3 className="mb-3 font-semibold">
        What this means for you{race ? ` — ${race.office}` : ""}
      </h3>

      {state.status === "loading" && (
        <div className="animate-pulse text-sm text-zinc-500">
          Writing your evidence-grounded explanation…
        </div>
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
        <span className="ml-1.5 inline-block rounded-full border border-zinc-700 px-1.5 py-0 align-middle text-[9px] uppercase tracking-wide text-zinc-400">
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
      {assumption && <span className="mt-0.5 block text-[11px] italic text-zinc-600">Assumes: {assumption}</span>}
    </li>
  );
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
      <p className="text-sm text-zinc-500">
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
      <p className="text-xs text-zinc-500">
        {hasProfile
          ? `Personalized for your stated situation${
              result.archetype_used ? ` (${result.archetype_used.replace(/_/g, " ")} profile)` : ""
            }.`
          : "No profile details were provided, so this is the general read for this race."}{" "}
        {result.mode === "live"
          ? "Generated live from indexed sources."
          : "From our precomputed, source-checked set."}
      </p>

      {result.summary && <p className="text-sm text-zinc-300">{result.summary}</p>}

      {candidateIds.length === 0 ? (
        <p className="text-sm text-zinc-600">No candidate-level insights available for this race yet.</p>
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
                  <p className="text-xs text-zinc-600">
                    No public data in our set for this candidate here.
                  </p>
                )}

                {hasHorizons && (
                  <div className="mt-3 space-y-3 border-t border-zinc-800 pt-2.5">
                    {nowBullets.length > 0 && (
                      <div>
                        <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-zinc-500">
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
                        <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-zinc-500">
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
        <p className="text-xs text-zinc-500">
          <span className="text-gold/90">Caveat:</span> {result.caveats}
        </p>
      )}
    </div>
  );
}

export default InsightsPanel;
