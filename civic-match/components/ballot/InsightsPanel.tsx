"use client";

// Fetches and renders the "what this means for you" read for whichever race
// id BallotSection's button last set. Grounded entirely in what
// /api/voter-insights returns — every bullet keeps its source link, and
// empty/unavailable data is shown honestly rather than papered over.
import { useEffect, useState } from "react";
import type {
  HorizonBullet,
  InsightsResponse,
  LongTermHorizonBullet,
  Race,
} from "@/lib/dataBackend";
import type { VoterProfile } from "@/lib/types";
import { CivitasPanel, SourceLink, StatusPill } from "@/components/civitas-ui";

type FetchState =
  | { status: "idle" }
  | { status: "loading"; raceId: string }
  | { status: "error"; raceId: string; message: string }
  | { status: "done"; raceId: string; result: InsightsResponse };

export function InsightsPanel({
  raceId,
  races,
  profile,
}: {
  raceId: string | null;
  races: Race[];
  profile?: VoterProfile;
}) {
  const [state, setState] = useState<FetchState>({ status: "idle" });
  const [cache, setCache] = useState<Record<string, InsightsResponse>>({});
  const visibleState: FetchState = !raceId
    ? { status: "idle" }
    : cache[raceId]
      ? { status: "done", raceId, result: cache[raceId] }
      : state.status !== "idle" && state.raceId === raceId
        ? state
        : { status: "loading", raceId };

  useEffect(() => {
    if (!raceId || cache[raceId]) return;

    let cancelled = false;

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
        setState({ status: "done", raceId, result });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setState({
          status: "error",
          raceId,
          message: err instanceof Error ? err.message : "Could not load insights",
        });
      });

    return () => {
      cancelled = true;
    };
  }, [cache, profile, raceId]);

  if (visibleState.status === "idle") {
    return (
      <div className="rounded-[10px] border border-dashed border-white/14 p-5 text-sm leading-6 text-white/48">
        Click “What this means for you” on any race above for a plain-English, source-linked read
        on what each candidate would likely mean for someone in your stated situation.
      </div>
    );
  }

  const race = races.find((r) => r.race_id === raceId);

  return (
    <CivitasPanel className="p-5">
      <h3 className="mb-3 font-serif text-2xl font-normal text-white">
        What this means for you{race ? ` — ${race.office}` : ""}
      </h3>

      {visibleState.status === "loading" && (
        <div className="animate-pulse text-sm text-white/48">
          Writing your evidence-grounded explanation…
        </div>
      )}
      {visibleState.status === "error" && (
        <div className="text-sm text-red-200">{visibleState.message}</div>
      )}
      {visibleState.status === "done" && (
        <InsightsBody result={visibleState.result} race={race} profile={profile} />
      )}
    </CivitasPanel>
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
    <li className="text-xs leading-5 text-white/62">
      {bullet.text}
      {projection && (
        <StatusPill className="ml-1.5 align-middle" tone="gold">
          Projection
        </StatusPill>
      )}
      {bullet.source && (
        <SourceLink href={bullet.source} className="ml-1">source</SourceLink>
      )}
      {assumption && <span className="mt-0.5 block text-[11px] italic text-white/35">Assumes: {assumption}</span>}
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
      <p className="text-sm text-white/52">
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
      <p className="text-xs leading-5 text-white/45">
        {hasProfile
          ? `Personalized for your stated situation${
              result.archetype_used ? ` (${result.archetype_used.replace(/_/g, " ")} profile)` : ""
            }.`
          : "No profile details were provided, so this is the general read for this race."}{" "}
        {result.mode === "live"
          ? "Generated live from indexed sources."
          : "From our precomputed, source-checked set."}
      </p>

      {result.summary && <p className="text-sm leading-6 text-white/72">{result.summary}</p>}

      {candidateIds.length === 0 ? (
        <p className="text-sm text-white/35">No candidate-level insights available for this race yet.</p>
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
              <div key={cid} className="rounded-[8px] border border-white/10 bg-navy-dark/60 p-3">
                <div className="mb-1.5 font-serif text-lg text-white">{name}</div>
                {bullets.length > 0 ? (
                  <ul className="space-y-1.5">
                    {bullets.map((b, i) => (
                      <li key={i} className="text-xs leading-5 text-white/62">
                        {b.text}
                        {b.source && (
                          <SourceLink href={b.source} className="ml-1">source</SourceLink>
                        )}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-xs text-white/35">
                    No public data in our set for this candidate here.
                  </p>
                )}

                {hasHorizons && (
                  <div className="mt-3 space-y-3 border-t border-white/10 pt-2.5">
                    {nowBullets.length > 0 && (
                      <div>
                        <div className="mb-1 text-[10px] font-semibold uppercase tracking-[0.18em] text-gold/80">
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
                        <div className="mb-1 text-[10px] font-semibold uppercase tracking-[0.18em] text-gold/80">
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
        <p className="text-xs leading-5 text-white/45">
          <span className="text-gold">Caveat:</span> {result.caveats}
        </p>
      )}
    </div>
  );
}

export default InsightsPanel;
