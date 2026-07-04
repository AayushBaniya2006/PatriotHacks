"use client";

// Renders the voter's ballot: races grouped Federal -> Statewide, each with
// an equal-weight candidate comparison (name, party, incumbent tag, money
// raised w/ source link, up to 3 key votes w/ source links), a button to
// request a personalized read via <InsightsPanel/> (owned by the parent),
// and a per-race "How we know" disclosure. A readiness bar up top tracks
// how many races the voter has opened (lib/readiness.ts).
import { useSyncExternalStore } from "react";
import type { Candidate, DataQuality, Districts, Race, VotingInfo, VotingLocation } from "@/lib/dataBackend";
import { getReviewed, readinessKey, subscribeReviewed } from "@/lib/readiness";

// Stable empty-set reference for useSyncExternalStore's server snapshot —
// BallotSection only ever mounts client-side (after the ballot fetch
// resolves) but the hook still requires a value for the SSR/hydration pass.
const EMPTY_REVIEWED: ReadonlySet<string> = new Set();

const LEVEL_LABELS: Record<string, string> = {
  federal: "Federal",
  state: "Statewide",
  state_leg: "State Legislature",
};
const LEVEL_ORDER = ["federal", "state", "state_leg"];

function formatMoney(n?: number | null): string | null {
  if (n === null || n === undefined) return null;
  return n.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  });
}

function marginPill(race: Race): string | null {
  const detail = race.context?.last_result_detail;
  if (detail && typeof detail.margin_pct === "number") {
    const who = detail.last_winner ?? "Last winner";
    const party = detail.party ? ` (${detail.party})` : "";
    return `${who}${party} won by ${detail.margin_pct.toFixed(1)} pts`;
  }
  if (race.context?.last_result) return race.context.last_result;
  return null;
}

// Plain-English data-confidence labels (improvements.md "Human-readable
// data confidence"). The underlying A-D tier is still there and still
// honest — it just lives in the tooltip now instead of the headline chip
// text, alongside the specific `missing[]` gaps.
const CONFIDENCE_LABELS: Record<string, string> = {
  A: "Strong public record",
  B: "Good public record",
  C: "Partial public record",
  D: "Thin public record",
};

// Neutral "how much do we actually know here" signal — same label, same
// muted style, same spot for every tier A-D and every candidate/race, so it
// never reads as a knock on whoever happens to score low. The tooltip is the
// only place the underlying tier letter and `missing[]` gaps (verbatim, e.g.
// "no campaign finance") show up; a "Thin public record" just means "we
// have little public data," not a knock on the candidate.
function QualityChip({ quality }: { quality?: DataQuality }) {
  if (!quality?.tier) return null;
  const missing = quality.missing ?? [];
  const label = CONFIDENCE_LABELS[quality.tier] ?? "Public record";
  const title =
    missing.length > 0
      ? `Tier ${quality.tier} — limited public data available: ${missing.join(", ")}`
      : `Tier ${quality.tier} — data confidence score for what we could verify in our set`;
  return (
    <span
      title={title}
      className="inline-flex shrink-0 items-center rounded-full border border-zinc-700 px-2 py-0.5 text-[10px] uppercase tracking-wide text-zinc-400"
    >
      {label}
    </span>
  );
}

// Visible-by-default, "refusing to guess" phrasing for a candidate's genuine
// data gaps (improvements.md "Intentional Caveats": show at least one
// caveat deliberately, framed as the product refusing to guess rather than
// papering over it). Only ever invoked when the pipeline's OWN `missing[]`
// analysis already flagged the gap for THIS candidate -- never inferred
// from an empty field alone, so a candidate whose data is simply short
// (rather than actually missing) is never mislabeled.
const MISSING_REASON_TEXT: Record<string, string> = {
  "no voting record": "No roll-call voting record found for this candidate",
  "no campaign finance": "No public finance record found for this candidate in our current dataset",
  "stale campaign finance": "This candidate's public finance record is out of date in our current dataset",
  "no issue positions": "No stated issue positions found for this candidate in our set",
  "no biography": "No biography found for this candidate in our set",
  "no sources": "No source citations found for this candidate in our set",
  "no fec/bioguide id": "No FEC or Bioguide identifier found for this candidate in our set",
};

function refusingToGuessCaveat(reason: string): string {
  const known = MISSING_REASON_TEXT[reason];
  const lead = known ?? `${reason.charAt(0).toUpperCase()}${reason.slice(1)} for this candidate in our set`;
  return `${lead} — we don't guess where records don't exist.`;
}

// Finds this candidate's own `missing[]` entry containing `keyword`, if the
// pipeline actually recorded one (e.g. keyword "finance" matches both "no
// campaign finance" and "stale campaign finance"). Returns null -- never a
// fabricated reason -- when nothing was flagged.
function candidateMissingReason(candidate: Candidate, keyword: string): string | null {
  return (candidate.data_quality?.missing ?? []).find((m) => m.includes(keyword)) ?? null;
}

function CandidateColumn({ candidate }: { candidate: Candidate }) {
  if (candidate.data_missing) {
    // Mirrors the populated card's row-for-row layout (name / party / money /
    // votes) instead of one short blob, so a "no data" column holds the same
    // visual weight as its siblings in the same race rather than shrinking
    // and reading as a lesser candidate.
    return (
      <div className="min-w-[220px] flex-1 rounded-lg border border-dashed border-zinc-800 bg-zinc-950/50 p-4">
        <div className="mb-1 flex items-start justify-between gap-2">
          <span className="font-medium leading-snug text-zinc-500">{candidate.name}</span>
        </div>
        <div className="mb-3 flex min-h-[22px] flex-wrap items-center gap-1.5">
          <span className="text-xs text-zinc-600">No party data in our set</span>
        </div>
        <div className="mb-3 text-xs">
          <div className="mb-0.5 text-zinc-500">Money</div>
          <div className="text-zinc-600">No candidate data available in our set yet.</div>
        </div>
        <div className="text-xs">
          <div className="mb-1 text-zinc-500">Votes</div>
          <div className="text-zinc-600">No candidate data available in our set yet.</div>
        </div>
      </div>
    );
  }

  const votes = (candidate.record?.key_votes ?? []).slice(0, 3);
  const receipts = formatMoney(candidate.finance?.receipts);
  const financeMissingReason = candidateMissingReason(candidate, "finance");
  const votesMissingReason = candidateMissingReason(candidate, "voting record");

  return (
    <div className="min-w-[220px] flex-1 rounded-lg border border-zinc-800 bg-zinc-950 p-4">
      <div className="mb-1 flex items-start justify-between gap-2">
        <span className="font-medium leading-snug">{candidate.name}</span>
        {candidate.incumbent && (
          <span className="shrink-0 rounded-full border border-zinc-700 px-2 py-0.5 text-[10px] uppercase tracking-wide text-zinc-400">
            Incumbent
          </span>
        )}
      </div>
      {/* Always rendered (even when empty) so "Money" lands at the same
          vertical offset in every candidate column in the race, whether or
          not this candidate has a party/quality chip to show. */}
      <div className="mb-3 flex min-h-[22px] flex-wrap items-center gap-1.5">
        {candidate.party && (
          <span className="inline-block rounded-full border border-zinc-700 px-2 py-0.5 text-xs text-zinc-400">
            {candidate.party}
          </span>
        )}
        <QualityChip quality={candidate.data_quality} />
      </div>

      <div className="mb-3 text-xs">
        <div className="mb-0.5 text-zinc-500">Money</div>
        {receipts ? (
          <div className="text-zinc-300">
            {receipts}
            {candidate.finance?.as_of && (
              <span className="text-zinc-600"> as of {candidate.finance.as_of}</span>
            )}
            {candidate.finance?.source && (
              <a
                href={candidate.finance.source}
                target="_blank"
                rel="noopener noreferrer"
                className="ml-1.5 text-gold hover:underline"
              >
                source ↗
              </a>
            )}
          </div>
        ) : (
          <div className="text-zinc-600">
            {financeMissingReason ? refusingToGuessCaveat(financeMissingReason) : "No finance data in our set"}
          </div>
        )}
      </div>

      <div className="text-xs">
        <div className="mb-1 text-zinc-500">Votes</div>
        {votes.length > 0 ? (
          <ul className="space-y-1.5">
            {votes.map((v, i) => (
              <li key={i} className="text-zinc-400">
                <span className="text-zinc-300">{v.bill ?? v.vote ?? "Vote"}</span>
                {v.position ? `: ${v.position}` : ""}
                {v.plain_english && (
                  <span className="block text-[11px] text-zinc-500">{v.plain_english}</span>
                )}
                {v.source && (
                  <a
                    href={v.source}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-gold hover:underline"
                  >
                    source ↗
                  </a>
                )}
              </li>
            ))}
          </ul>
        ) : (
          <div className="text-zinc-600">
            {votesMissingReason ? refusingToGuessCaveat(votesMissingReason) : "No recorded votes in our set"}
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// "How we know" (improvements.md #4) — a short, honest per-race provenance
// summary: what kind of source backs the money numbers, what kind backs the
// votes, how many candidates actually have each, and one caveat line. Never
// a raw source dump — just source *types*, derived from fields already on
// the payload (finance.source URL host, record.key_votes presence).
// ---------------------------------------------------------------------------

function financeSourceType(url?: string | null): string | null {
  if (!url) return null;
  if (/fec\.gov/i.test(url)) return "Federal Election Commission filings";
  if (/ethics\.state\.tx\.us/i.test(url)) return "Texas Ethics Commission filings";
  return null;
}

function raceFinanceSources(race: Race): string[] {
  const types = new Set<string>();
  for (const c of race.candidates) {
    const t = financeSourceType(c.finance?.source);
    if (t) types.add(t);
  }
  return Array.from(types);
}

function raceHasKeyVotes(race: Race): boolean {
  return race.candidates.some((c) => (c.record?.key_votes?.length ?? 0) > 0);
}

interface CoverageCounts {
  total: number;
  withFinance: number;
  withVotes: number;
  withPositions: number;
}

function coverageCounts(race: Race): CoverageCounts {
  const cands = race.candidates;
  return {
    total: cands.length,
    withFinance: cands.filter((c) => c.finance?.receipts !== null && c.finance?.receipts !== undefined).length,
    withVotes: cands.filter((c) => (c.record?.key_votes?.length ?? 0) > 0).length,
    withPositions: cands.filter((c) => (c.positions?.length ?? 0) > 0).length,
  };
}

// One honest missing-data caveat line — prefers the specific, pre-written
// `missing[]` gaps already on the race/candidate quality payloads, and only
// falls back to a generic "coverage is uneven" note when those aren't set
// but the counts still show a gap. Never invents a reason.
function missingCaveat(race: Race, counts: CoverageCounts): string {
  const gaps = new Set<string>();
  (race.data_quality?.missing ?? []).forEach((m) => gaps.add(m));
  race.candidates.forEach((c) => (c.data_quality?.missing ?? []).forEach((m) => gaps.add(m)));
  if (gaps.size > 0) {
    return `What we don't have yet: ${Array.from(gaps).join(", ")}.`;
  }
  const uneven =
    counts.total > 0 &&
    (counts.withFinance < counts.total || counts.withVotes < counts.total || counts.withPositions < counts.total);
  return uneven
    ? "Coverage is uneven across candidates in this race — see the counts above."
    : "No known coverage gaps for this race in our set.";
}

function HowWeKnow({ race }: { race: Race }) {
  const financeSources = raceFinanceSources(race);
  const hasVotes = raceHasKeyVotes(race);
  const counts = coverageCounts(race);
  const caveat = missingCaveat(race, counts);

  return (
    <details className="mt-4 rounded-lg border border-zinc-800 bg-zinc-950/40 p-3 text-xs text-zinc-400">
      <summary className="cursor-pointer select-none font-medium text-zinc-300">How we know</summary>
      <div className="mt-2 space-y-1.5">
        <p>
          <span className="text-zinc-300">Sources — </span>
          Money: {financeSources.length > 0 ? financeSources.join(", ") : "no finance source on file for this race"}
          . Votes: {hasVotes ? "official U.S. House roll-call records" : "no recorded votes on file for this race"}.
        </p>
        <p>
          {counts.withFinance} of {counts.total} candidates have finance data, {counts.withVotes} of {counts.total}{" "}
          have recorded votes, {counts.withPositions} of {counts.total} have stated positions.
        </p>
        <p className="text-zinc-500">{caveat}</p>
      </div>
    </details>
  );
}

function RaceCard({
  race,
  active,
  onExplain,
  featured,
}: {
  race: Race;
  active: boolean;
  onExplain: (raceId: string) => void;
  // The single demo_rank-1 race gets a subtle accent border so "visually
  // primary" (improvements.md "Featured race") holds even once a secondary
  // race is expanded to this exact same card -- the label above (in
  // BallotSection) is what actually says "Featured race"; this is just the
  // one purely-visual difference between the two densities.
  featured?: boolean;
}) {
  const pill = marginPill(race);
  return (
    <div
      className={`rounded-xl border p-5 ${
        featured ? "border-gold/40 bg-gold/[0.03]" : "border-zinc-800 bg-zinc-900/50"
      }`}
    >
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="font-semibold">{race.office}</div>
          {race.district && <div className="text-xs text-zinc-500">{race.district}</div>}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <QualityChip quality={race.data_quality} />
          {pill && (
            <span className="rounded-full border border-zinc-700 px-2.5 py-1 text-[11px] text-zinc-400">
              {pill}
            </span>
          )}
          <button
            onClick={() => onExplain(race.race_id)}
            className={`rounded-lg border px-3 py-1.5 text-xs font-medium transition ${
              active
                ? "border-gold bg-gold/15 text-gold"
                : "border-zinc-700 text-zinc-300 hover:border-gold/60"
            }`}
          >
            What this means for you
          </button>
        </div>
      </div>

      {race.candidates.length > 0 ? (
        <div className="flex flex-wrap gap-3">
          {race.candidates.map((c) => (
            <CandidateColumn key={c.candidate_id} candidate={c} />
          ))}
        </div>
      ) : (
        <p className="text-xs text-zinc-600">No candidate data available for this race yet.</p>
      )}

      {race.candidates.length > 0 && <HowWeKnow race={race} />}
    </div>
  );
}

// Compact/secondary density for every race except the one featured race
// (improvements.md "one featured race... remaining races listed compactly
// below"). Collapsed by default: office, district, tier chip, margin, and
// candidate names in the summary line only -- the exact same RaceCard (full
// candidate detail, equal treatment, "How we know") is one click away via
// native <details>, never a separate or lesser code path. Opens
// automatically when this race becomes the active "What this means for
// you" selection.
function SecondaryRaceRow({
  race,
  active,
  onExplain,
}: {
  race: Race;
  active: boolean;
  onExplain: (raceId: string) => void;
}) {
  const pill = marginPill(race);
  const names = race.candidates.map((c) => c.name).join(" vs. ") || "No candidates yet";
  return (
    <details className="rounded-xl border border-zinc-800 bg-zinc-900/50" open={active}>
      <summary className="flex cursor-pointer select-none flex-wrap items-center gap-2 p-4 text-sm">
        <span className="font-semibold">{race.office}</span>
        {race.district && <span className="text-xs text-zinc-500">{race.district}</span>}
        <QualityChip quality={race.data_quality} />
        {pill && (
          <span className="rounded-full border border-zinc-700 px-2 py-0.5 text-[11px] text-zinc-400">{pill}</span>
        )}
        <span className="truncate text-xs text-zinc-500">{names}</span>
      </summary>
      <div className="px-4 pb-4 pt-1">
        <RaceCard race={race} active={active} onExplain={onExplain} />
      </div>
    </details>
  );
}

// Optional Google Civic enrichment (backend: app/google_civic.py, only
// present when GOOGLE_CIVIC_API_KEY is set there). One compact line per
// location type — first location shown in full, any others summarized as
// "and N more" rather than listed out, to keep this card small relative to
// the races below it.
function VotingLocationLine({
  label,
  location,
  extraCount,
}: {
  label: string;
  location: VotingLocation;
  extraCount: number;
}) {
  return (
    <div className="text-xs text-zinc-400">
      <span className="text-zinc-500">{label}: </span>
      <span className="text-zinc-300">{location.name ?? "Location"}</span>
      {location.address && <span>, {location.address}</span>}
      {location.hours && <span className="text-zinc-500"> ({location.hours})</span>}
      {extraCount > 0 && <span className="text-zinc-500"> and {extraCount} more</span>}
    </div>
  );
}

// Renders nothing when `votingInfo` is absent (no GOOGLE_CIVIC_API_KEY on
// the backend, or Google has no coverage for this address yet) or present
// but empty of anything worth showing -- same "omit, don't show a hollow
// card" rule the backend already applies before ever setting this field.
function VotingInfoCard({ votingInfo }: { votingInfo?: VotingInfo }) {
  if (!votingInfo) return null;

  const polling = votingInfo.polling_locations ?? [];
  const early = votingInfo.early_vote_sites ?? [];
  const electionLabel = [votingInfo.election?.name, votingInfo.election?.date].filter(Boolean).join(" — ");
  if (!electionLabel && polling.length === 0 && early.length === 0) return null;

  return (
    <div className="mb-6 rounded-lg border border-zinc-800 bg-zinc-900/50 p-4">
      <div className="mb-2 text-xs font-semibold uppercase tracking-wider text-gold">Your voting info</div>
      {electionLabel && <div className="mb-2 text-sm text-zinc-200">{electionLabel}</div>}
      <div className="space-y-1">
        {polling.length > 0 && (
          <VotingLocationLine label="Polling location" location={polling[0]} extraCount={polling.length - 1} />
        )}
        {early.length > 0 && (
          <VotingLocationLine label="Early voting" location={early[0]} extraCount={early.length - 1} />
        )}
      </div>
      {votingInfo.source && (
        <a
          href={votingInfo.source}
          target="_blank"
          rel="noopener noreferrer"
          className="mt-2 inline-block text-xs text-gold hover:underline"
        >
          source ↗
        </a>
      )}
    </div>
  );
}

// Readiness bar (improvements.md #2 / design spec §2) — "Reviewed X of N
// races", a progress bar, and a celebratory-but-neutral completion state.
// Purely presentational; BallotSection owns the reviewed-count state so
// this stays a dumb function of two numbers.
function ReadinessBar({ reviewedCount, total }: { reviewedCount: number; total: number }) {
  const pct = total > 0 ? Math.round((Math.min(reviewedCount, total) / total) * 100) : 0;
  const complete = total > 0 && reviewedCount >= total;

  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900/50 p-4">
      <div className="mb-2 flex items-center justify-between gap-3 text-sm">
        <span className={complete ? "font-medium text-gold" : "text-zinc-300"}>
          {complete ? "You're ballot-ready ✓" : `Reviewed ${reviewedCount} of ${total} races`}
        </span>
        <span className="text-xs text-zinc-500">{pct}%</span>
      </div>
      <div className="h-2 w-full rounded bg-zinc-800">
        <div
          className={`h-2 rounded transition-all ${complete ? "bg-gold" : "bg-gold/70"}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      {!complete && (
        <p className="mt-2 text-xs text-zinc-500">
          Open “What this means for you” on a race below to mark it reviewed.
        </p>
      )}
    </div>
  );
}

export function BallotSection({
  races,
  activeRaceId,
  onExplain,
  votingInfo,
  districts,
  featuredRaceId,
}: {
  races: Race[];
  activeRaceId: string | null;
  onExplain: (raceId: string) => void;
  // OPTIONAL: pass `ballot.voting_info` from the /api/ballot response to
  // surface a compact "Your voting info" card above the races. Renders
  // nothing when omitted. NOT YET WIRED from app/results/page.tsx (out of
  // scope for this change) -- once its <BallotSection .../> call also
  // passes votingInfo={ballotState.data.voting_info}, this activates with no
  // further change needed here.
  votingInfo?: VotingInfo;
  // OPTIONAL: pass `ballot.districts` from the /api/ballot response so the
  // readiness bar keys its localStorage state by district triple (cd|sd|hd)
  // rather than address (lib/readiness.ts). Falls back to a shared
  // "unknown district" bucket when omitted.
  districts?: Districts | null;
  // OPTIONAL: race_id of the single data_quality.demo_rank-1 race
  // (app/results/page.tsx computes this the same way its insight-prefetch
  // does). Rendered full-density and labeled "Featured race" above every
  // other race, which render at compact/secondary density instead
  // (improvements.md "one featured race... remaining races listed
  // compactly"). Omitted/unmatched -> every race renders at the original
  // uniform density, unchanged from before this prop existed. Candidate
  // treatment WITHIN any single race never varies by this prop.
  featuredRaceId?: string | null;
}) {
  const reviewKey = readinessKey(districts);
  const reviewed = useSyncExternalStore(
    subscribeReviewed,
    () => getReviewed(reviewKey),
    () => EMPTY_REVIEWED
  );

  if (races.length === 0) {
    return (
      <>
        <VotingInfoCard votingInfo={votingInfo} />
        <p className="text-sm text-zinc-500">
          No races found for this address yet — the district may not be loaded in our data set.
        </p>
      </>
    );
  }

  // "One featured race" (improvements.md "What Better Means"): the single
  // demo_rank-1 race, pulled out of its level group and rendered first, full
  // density, labeled. Every other race -- including other races in what
  // would've been its own level group -- renders compactly below via
  // SecondaryRaceRow. Unmatched/omitted featuredRaceId -> featuredRace is
  // null and every race falls through to the original uniform grouping,
  // unchanged from before this prop existed.
  const featuredRace = featuredRaceId ? races.find((r) => r.race_id === featuredRaceId) ?? null : null;
  const secondaryRaces = featuredRace ? races.filter((r) => r.race_id !== featuredRace.race_id) : races;

  const known = new Set(LEVEL_ORDER);
  const groups = LEVEL_ORDER.map((level) => ({
    level,
    races: secondaryRaces.filter((r) => r.level === level),
  })).filter((g) => g.races.length > 0);
  const other = secondaryRaces.filter((r) => !known.has(r.level));
  if (other.length > 0) groups.push({ level: "other", races: other });

  const raceIds = new Set(races.map((r) => r.race_id));
  const reviewedCount = Array.from(reviewed).filter((id) => raceIds.has(id)).length;

  return (
    <div className="space-y-8">
      <VotingInfoCard votingInfo={votingInfo} />
      <ReadinessBar reviewedCount={reviewedCount} total={races.length} />

      {featuredRace && (
        <div>
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <span className="rounded-full border border-gold/60 bg-gold/10 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide text-gold">
              Featured race
            </span>
            <span className="text-xs text-zinc-500">The race we can show you the most about right now.</span>
          </div>
          <RaceCard
            race={featuredRace}
            active={activeRaceId === featuredRace.race_id}
            onExplain={onExplain}
            featured
          />
        </div>
      )}

      {groups.map((g) => (
        <div key={g.level}>
          <h3 className="mb-3 text-xs uppercase tracking-wider text-zinc-500">
            {LEVEL_LABELS[g.level] ?? g.level}
          </h3>
          <div className="space-y-3">
            {g.races.map((race) => (
              <SecondaryRaceRow
                key={race.race_id}
                race={race}
                active={activeRaceId === race.race_id}
                onExplain={onExplain}
              />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

export default BallotSection;
