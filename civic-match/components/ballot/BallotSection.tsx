"use client";

// Renders the voter's ballot: races grouped Federal -> Statewide, each with
// an equal-weight candidate comparison (name, party, incumbent tag, money
// raised w/ source link, up to 3 key votes w/ source links), a button to
// request a personalized read via <InsightsPanel/> (owned by the parent),
// and a per-race "How we know" disclosure. A readiness bar up top tracks
// how many races the voter has opened (lib/readiness.ts).
//
// AESTHETIC QA PASS (spacing / type hierarchy / alignment / contrast /
// states / density) applied on top of the existing structure:
//   - text-zinc-500/600 -> text-zinc-400 throughout: both former shades sit
//     below WCAG AA (4.5:1) against this module's actual card surfaces
//     (zinc-950 tiles, zinc-900/50-on-navy shells) -- verified in Python
//     (relative-luminance contrast, not eyeballed). zinc-400 clears 7:1+ on
//     every surface in this file, so one muted tier replaces two failing
//     ones rather than patching them to different values.
//   - border-zinc-700/800 -> border-zinc-500 throughout: at 1px, the old
//     borders measured 1.2-1.9:1 against every surface here (navy page,
//     zinc-900/50 shell, zinc-950 tile) -- far under the 3:1 AA floor for
//     UI-component boundaries. zinc-500 is the lightest *unmodified* zinc
//     step that clears 3:1 on all of them (3.3-4.1:1), so every card/chip/
//     button/divider border in this module now reads as an actual boundary
//     instead of nearly disappearing into the navy backdrop.
//   - Money/Votes field labels promoted to the same uppercase/tracked/
//     semibold micro-label treatment already used for the horizon eyebrows
//     ("Right now" / "Down the road" in InsightsPanel) and this file's own
//     level-group headers -- was plain sentence-case with an inconsistent
//     mb-0.5 vs mb-1 gap; now one consistent label idiom + one gap value.
//   - Candidate row switched from flex-wrap+flex-1 to a fixed 1/2-col grid:
//     flex-basis:0 with a min-w floor means a race with an odd candidate
//     count (this ballot's Governor race has 4) leaves an orphan candidate
//     alone on its row that then STRETCHES to the full card width while its
//     siblings stay ~220px -- a real, reproducible unequal-column bug, not
//     hypothetical. CSS Grid with explicit tracks keeps every column the
//     same width on every row regardless of how the last row fills, and
//     bonus: grid's default `align-items: stretch` equalizes row heights
//     for free (a 0-vote candidate's card no longer looks shorter next to a
//     3-vote one).
//   - RaceCard's office name promoted from a bare <div> to <h4> (nested one
//     level under "Your ballot" h2 -> level-group h3 -> race h4) so each
//     race card has exactly one real heading, matching SecondaryRaceRow.
//   - Featured race gets p-6 (vs secondary's p-5) so it visibly breathes in
//     its own right, on top of the existing expanded-vs-collapsed density
//     split; its accent border bumped emerald-500/40 -> emerald-400/60 to
//     actually clear 3:1 (was 2.15:1) -- now matches the "Featured race"
//     pill's own border token instead of a different, failing one.
//   - ReadinessBar's progress track gets a visible border (was indistinguishable
//     from its own card background at 1.2:1); HowWeKnow's disclosure body
//     gets max-w-prose so its source/coverage sentences don't run the full
//     card width on a wide featured race.
import { useSyncExternalStore } from "react";
import type { Candidate, DataQuality, Districts, Race, VotingInfo, VotingLocation } from "@/lib/dataBackend";
import { getReviewed, readinessKey, subscribeReviewed } from "@/lib/readiness";
import { ViewModeToggle, useViewMode } from "@/components/ballot/ViewModeToggle";

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

// Returns the pill's text plus its source URL (when the structured
// last_result_detail carries one, per schema.md) SEPARATELY rather than as
// one pre-joined string, so both render sites below can attach the same
// clickable "source ↗" affordance every other sourced number in this file
// gets -- this margin-pct figure is a citable fact like money/votes and must
// not be the one number in the module that renders with no citation at all.
// The unstructured `last_result` string fallback has no discrete `source`
// field in the schema, so it's surfaced with source left undefined rather
// than guessing/attaching one -- never invent a citation that isn't there.
function marginPill(race: Race): { text: string; source?: string } | null {
  const detail = race.context?.last_result_detail;
  if (detail && typeof detail.margin_pct === "number") {
    const who = detail.last_winner ?? "Last winner";
    const party = detail.party ? ` (${detail.party})` : "";
    return { text: `${who}${party} won by ${detail.margin_pct.toFixed(1)} pts`, source: detail.source };
  }
  if (race.context?.last_result) return { text: race.context.last_result };
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
      className="inline-flex shrink-0 items-center rounded-full border border-zinc-500 px-2 py-0.5 text-[10px] uppercase tracking-wide text-zinc-400"
    >
      {label}
    </span>
  );
}

// Shared micro-label recipe for in-card field labels ("Money", "Votes") —
// matches the horizon eyebrows in InsightsPanel.tsx ("Right now" / "Down
// the road") so the same visual language for "this is a field label, not a
// value" holds across both files in this module.
const FIELD_LABEL = "mb-1 text-[10px] font-semibold uppercase tracking-wide text-zinc-400";

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
    // and reading as a lesser candidate. `min-w-0` (not a fixed min-width)
    // because the grid parent now owns column sizing.
    return (
      <div className="min-w-0 rounded-lg border border-dashed border-zinc-500 bg-zinc-950/50 p-4">
        <div className="mb-1 flex items-start justify-between gap-2">
          <span className="min-w-0 break-words font-medium leading-snug text-zinc-400">{candidate.name}</span>
        </div>
        <div className="mb-3 flex min-h-[22px] flex-wrap items-center gap-1.5">
          <span className="text-xs text-zinc-400">No party data in our set</span>
        </div>
        <div className="mb-3 text-xs">
          <div className={FIELD_LABEL}>Money</div>
          <div className="text-zinc-400">No candidate data available in our set yet.</div>
        </div>
        <div className="text-xs">
          <div className={FIELD_LABEL}>Votes</div>
          <div className="text-zinc-400">No candidate data available in our set yet.</div>
        </div>
      </div>
    );
  }

  const votes = (candidate.record?.key_votes ?? []).slice(0, 3);
  const receipts = formatMoney(candidate.finance?.receipts);
  const financeMissingReason = candidateMissingReason(candidate, "finance");
  const votesMissingReason = candidateMissingReason(candidate, "voting record");

  return (
    <div className="min-w-0 rounded-lg border border-zinc-500 bg-zinc-950 p-4">
      <div className="mb-1 flex items-start justify-between gap-2">
        <span className="min-w-0 break-words font-medium leading-snug">{candidate.name}</span>
        {candidate.incumbent && (
          <span className="shrink-0 rounded-full border border-zinc-500 px-2 py-0.5 text-[10px] uppercase tracking-wide text-zinc-400">
            Incumbent
          </span>
        )}
      </div>
      {/* Always rendered (even when empty) so "Money" lands at the same
          vertical offset in every candidate column in the race, whether or
          not this candidate has a party/quality chip to show. */}
      <div className="mb-3 flex min-h-[22px] flex-wrap items-center gap-1.5">
        {candidate.party && (
          <span className="inline-block rounded-full border border-zinc-500 px-2 py-0.5 text-xs text-zinc-400">
            {candidate.party}
          </span>
        )}
        <QualityChip quality={candidate.data_quality} />
      </div>

      <div className="mb-3 text-xs">
        <div className={FIELD_LABEL}>Money</div>
        {receipts ? (
          <div className="text-zinc-300">
            {receipts}
            {candidate.finance?.as_of && (
              <span className="text-zinc-400"> as of {candidate.finance.as_of}</span>
            )}
            {candidate.finance?.source && (
              <a
                href={candidate.finance.source}
                target="_blank"
                rel="noopener noreferrer"
                className="ml-1.5 text-emerald-400 hover:underline"
              >
                source ↗
              </a>
            )}
          </div>
        ) : (
          <div className="text-zinc-400">
            {financeMissingReason ? refusingToGuessCaveat(financeMissingReason) : "No finance data in our set"}
          </div>
        )}
      </div>

      <div className="text-xs">
        <div className={FIELD_LABEL}>Votes</div>
        {votes.length > 0 ? (
          <ul className="space-y-1.5">
            {votes.map((v, i) => (
              <li key={i} className="text-zinc-400">
                <span className="text-zinc-300">{v.bill ?? v.vote ?? "Vote"}</span>
                {v.position ? `: ${v.position}` : ""}
                {v.plain_english && (
                  <span className="block text-[11px] text-zinc-400">{v.plain_english}</span>
                )}
                {v.source && (
                  <a
                    href={v.source}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-emerald-400 hover:underline"
                  >
                    source ↗
                  </a>
                )}
              </li>
            ))}
          </ul>
        ) : (
          <div className="text-zinc-400">
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
    <details className="mt-4 rounded-lg border border-zinc-500 bg-zinc-950/40 p-3 text-xs text-zinc-400">
      <summary className="cursor-pointer select-none py-3.5 sm:py-0 font-medium text-zinc-300">How we know</summary>
      {/* max-w-prose: this can run 2-3 sentences long, and the featured
          race's card is the widest in the module — cap the measure instead
          of letting a paragraph stretch the full card width. */}
      <div className="mt-2 max-w-prose space-y-1.5">
        <p>
          <span className="text-zinc-300">Sources — </span>
          Money: {financeSources.length > 0 ? financeSources.join(", ") : "no finance source on file for this race"}
          . Votes: {hasVotes ? "official U.S. House roll-call records" : "no recorded votes on file for this race"}.
        </p>
        <p>
          {counts.withFinance} of {counts.total} candidates have finance data, {counts.withVotes} of {counts.total}{" "}
          have recorded votes, {counts.withPositions} of {counts.total} have stated positions.
        </p>
        <p className="text-zinc-400">{caveat}</p>
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
  // The single demo_rank-1 race gets a subtle accent border AND a touch more
  // padding (p-6 vs p-5) so "visually primary" (improvements.md "Featured
  // race") holds as real breathing room, not just a label -- while every
  // candidate/vote/money row inside stays byte-for-byte the same component
  // as a secondary race's, so "featured" never means "more generous data,"
  // only "more space and default-open."
  featured?: boolean;
}) {
  const pill = marginPill(race);
  return (
    <div
      className={`rounded-xl border ${
        featured ? "border-emerald-400/60 bg-emerald-500/[0.03] p-6" : "border-zinc-500 bg-zinc-900/50 p-5"
      }`}
    >
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h4 className="font-semibold leading-snug">{race.office}</h4>
          {race.district && <div className="text-xs text-zinc-400">{race.district}</div>}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <QualityChip quality={race.data_quality} />
          {pill && (
            <span className="inline-flex items-center gap-1 rounded-full border border-zinc-500 px-2 py-0.5 text-[11px] text-zinc-400">
              {pill.text}
              {pill.source && (
                <a
                  href={pill.source}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-emerald-400 hover:underline"
                >
                  source ↗
                </a>
              )}
            </span>
          )}
          <button
            onClick={() => onExplain(race.race_id)}
            className={`rounded-lg border px-3 py-3.5 sm:py-1.5 text-xs font-medium transition ${
              active
                ? "border-emerald-400 bg-emerald-500/15 text-emerald-300"
                : "border-zinc-500 text-zinc-300 hover:border-emerald-400/60"
            }`}
          >
            What this means for you
          </button>
        </div>
      </div>

      {race.candidates.length > 0 ? (
        // Fixed 1/2-col grid (not flex-wrap+flex-1): every column is exactly
        // as wide as its row-mates regardless of candidate count, and an odd
        // last candidate (e.g. this ballot's 4-candidate Governor race, or a
        // 5-candidate race) sits alone in its own row instead of stretching
        // to the full card width. `items-stretch` (grid's default) also
        // equalizes each row's candidate-card heights for free.
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {race.candidates.map((c) => (
            <CandidateColumn key={c.candidate_id} candidate={c} />
          ))}
        </div>
      ) : (
        <p className="text-xs text-zinc-400">No candidate data available for this race yet.</p>
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
    <details className="rounded-xl border border-zinc-500 bg-zinc-900/50" open={active}>
      <summary className="flex cursor-pointer select-none flex-wrap items-center gap-2 p-4 text-sm">
        <h4 className="font-semibold">{race.office}</h4>
        {race.district && <span className="text-xs text-zinc-400">{race.district}</span>}
        <QualityChip quality={race.data_quality} />
        {pill && (
          <span className="inline-flex items-center gap-1 rounded-full border border-zinc-500 px-2 py-0.5 text-[11px] text-zinc-400">
            {pill.text}
            {pill.source && (
              <a
                href={pill.source}
                target="_blank"
                rel="noopener noreferrer"
                className="text-emerald-400 hover:underline"
              >
                source ↗
              </a>
            )}
          </span>
        )}
        {/* Explicit min-w-0 + max-w so this reliably truncates with an
            ellipsis at 375px instead of relying on flex-wrap shrink alone
            (which can just wrap the whole name list to its own full-width
            line instead of eliding it). */}
        <span title={names} className="min-w-0 max-w-[16rem] truncate text-xs text-zinc-400">{names}</span>
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
      <span>{label}: </span>
      <span className="text-zinc-300">{location.name ?? "Location"}</span>
      {location.address && <span>, {location.address}</span>}
      {location.hours && <span> ({location.hours})</span>}
      {extraCount > 0 && <span> and {extraCount} more</span>}
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
    <div className="mb-6 rounded-lg border border-zinc-500 bg-zinc-900/50 p-4">
      <div className="mb-2 text-xs font-semibold uppercase tracking-wider text-emerald-400">Your voting info</div>
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
          className="mt-2 inline-block text-xs text-emerald-400 hover:underline"
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
    <div className="rounded-xl border border-zinc-500 bg-zinc-900/50 p-4">
      <div className="mb-2 flex items-center justify-between gap-3 text-sm">
        <span className={complete ? "font-medium text-emerald-300" : "text-zinc-300"}>
          {complete ? "You're ballot-ready ✓" : `Reviewed ${reviewedCount} of ${total} races`}
        </span>
        <span className="text-xs text-zinc-400">{pct}%</span>
      </div>
      {/* Track needs its own visible border: at bg-zinc-800 inside a
          bg-zinc-900/50-on-navy card, the track was measured at 1.2:1
          against its own container -- effectively invisible until the fill
          renders. A 1px zinc-500 ring gives the meter a perceivable extent
          regardless of fill %. */}
      <div className="h-2 w-full rounded border border-zinc-500 bg-zinc-800">
        <div
          className={`h-full rounded-sm transition-all ${complete ? "bg-emerald-400" : "bg-emerald-500/70"}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      {!complete && (
        <p className="mt-2 text-xs text-zinc-400">
          Open “What this means for you” on a race below to mark it reviewed.
        </p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// SIMPLE MODE (plain-English, Gen-Z-friendly view) — additive alternative to
// RaceCard/SecondaryRaceRow/CandidateColumn above, switched via
// ViewModeToggle.tsx / lib/viewMode.ts ("cm_view_mode" in localStorage,
// default "simple"). Renders from the exact same Race/Candidate objects as
// the detailed view above (same /api/ballot payload, no new fetch, nothing
// invented) -- this section only picks a shorter, plainer way to say what's
// already there, and keeps the same two rules the detailed view enforces:
// never claim something without a source, and say so plainly ("No public
// record on this yet") when a candidate's public record is thin rather than
// guessing.
// ---------------------------------------------------------------------------

// Generic, factual "what does this job actually do" lines -- about the
// OFFICE itself, never about a specific candidate's record (candidate-level
// claims always come from the sourced fields below and carry their own
// link). Checked in order, most-specific pattern first (e.g. "lieutenant
// governor" before "governor", "county judge" before the generic judge/court
// catch-all) so a more specific title never falls through to a broader
// blurb that happens to also match. A level-based fallback covers any office
// this list doesn't recognize yet, so nothing ever renders with no blurb.
const OFFICE_BLURBS: [RegExp, string][] = [
  [/lieutenant governor/i, "Runs the state Senate and steps in if the governor can't serve."],
  [/governor/i, "Runs the state — schools, roads, emergencies, and signs or vetoes state laws."],
  [/attorney general/i, "The state's top lawyer — enforces state law and represents it in court."],
  [/secretary of state/i, "Runs state elections and keeps the state's official records."],
  [/comptroller/i, "Manages the state's money — collects taxes and writes the budget forecast."],
  [/treasurer/i, "Manages public money and debt."],
  [/land commissioner|general land office/i, "Manages state-owned land, plus some school and veterans' funding."],
  [/agriculture commissioner/i, "Oversees farming, food safety, and consumer-protection rules."],
  [/railroad commission/i, "Regulates oil, gas, and pipelines (not railroads, despite the name)."],
  [/u\.?s\.?\s*senat/i, "Represents the whole state in Washington — votes on federal laws, budgets, treaties."],
  [/u\.?s\.?\s*(house|rep)|congress/i, "Represents your district in Washington — votes on federal laws and the federal budget."],
  [/state senat/i, "Represents your district at the state capitol — votes on state laws and the state budget."],
  [/state (house|rep)|assembly/i, "Represents your district at the state capitol — votes on state laws and the state budget."],
  [/county judge/i, "Runs county government and its budget (the executive, not a courtroom judge, in Texas)."],
  [/district attorney|county attorney|prosecutor/i, "Decides which criminal cases to prosecute in the county."],
  [/sheriff/i, "Runs county law enforcement and the county jail."],
  [/county commissioner/i, "Votes on the county budget and services like roads."],
  [/mayor/i, "Runs city government day-to-day."],
  [/city council/i, "Votes on city laws, budget, and local services."],
  [/school board|trustee/i, "Sets policy and budget for public schools in the district."],
  [
    /district judge|supreme court|court of appeals|court of criminal appeals|justice of the peace|\bjudge\b/i,
    "Decides court cases and interprets the law — doesn't write new laws.",
  ],
];

function officeBlurb(office: string, level?: string): string {
  for (const [pattern, blurb] of OFFICE_BLURBS) {
    if (pattern.test(office)) return blurb;
  }
  if (level === "federal") return "A federal office — votes on national laws and the federal budget.";
  if (level === "state") return "A statewide office in Texas government.";
  if (level === "state_leg") return "A state lawmaker for your district.";
  return "A local elected office for your area.";
}

// "$1.6M raised" instead of a formatted table cell -- same underlying number
// as formatMoney() above (candidate.finance.receipts), just abbreviated for
// a compact card instead of spelled out to the dollar.
function formatMoneyFriendly(n?: number | null): string | null {
  if (n === null || n === undefined || Number.isNaN(n)) return null;
  const abs = Math.abs(n);
  if (abs >= 1_000_000) {
    const millions = Math.round((n / 1_000_000) * 10) / 10;
    return `$${millions % 1 === 0 ? millions.toFixed(0) : millions.toFixed(1)}M`;
  }
  if (abs >= 1_000) {
    return `$${Math.round(n / 1000)}K`;
  }
  return n.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
}

// Standard, widely-recognized US party color convention, applied identically
// to every party (never a "better" color for one side) -- same neutrality
// rule QualityChip's tier treatment above already follows.
function partyDotClass(party?: string | null): string {
  if (!party) return "border border-zinc-500 bg-transparent";
  const p = party.trim().toLowerCase();
  if (p.startsWith("d")) return "bg-sky-400";
  if (p.startsWith("r")) return "bg-red-400";
  if (p.startsWith("g")) return "bg-green-500";
  if (p.startsWith("l")) return "bg-amber-400";
  if (p.startsWith("i")) return "bg-zinc-300";
  return "bg-violet-400";
}

function PartyDot({ party }: { party?: string | null }) {
  return (
    <span
      className={`inline-block h-2.5 w-2.5 shrink-0 rounded-full ${partyDotClass(party)}`}
      role="img"
      aria-label={party ? `${party} party` : "Party not on file"}
      title={party ?? "Party not on file"}
    />
  );
}

// ONE short, plain-language takeaway per candidate -- never invented: every
// branch reads a field that's already rendered (sourced) somewhere in
// CandidateColumn above (incumbent, record.key_votes, finance.receipts,
// positions). Priority favors the most concrete, most citable fact first;
// falls all the way through to the same honest "no public record" line
// CandidateColumn's own empty states use when a candidate genuinely has none
// of the above.
function candidateTakeaway(candidate: Candidate, raceCandidates: Candidate[]): string {
  const topVote = (candidate.record?.key_votes ?? [])[0];
  const voteLabel = topVote ? topVote.plain_english || topVote.bill || topVote.vote || null : null;
  const receipts = candidate.finance?.receipts;
  const hasReceipts = typeof receipts === "number" && receipts > 0;

  const others = raceCandidates.filter((c) => c.candidate_id !== candidate.candidate_id && !c.data_missing);
  const maxOtherReceipts = others.reduce((max, c) => {
    const r = c.finance?.receipts;
    return typeof r === "number" && r > max ? r : max;
  }, 0);
  const isTopFundraiser = hasReceipts && others.length > 0 && (receipts as number) > maxOtherReceipts;
  const isWayAhead = isTopFundraiser && maxOtherReceipts > 0 && (receipts as number) > maxOtherReceipts * 1.5;

  if (candidate.incumbent && voteLabel) {
    return `Sitting officeholder — voted on ${voteLabel}.`;
  }
  if (isWayAhead) {
    return "Raised way more money than the other candidates in this race 💰";
  }
  if (isTopFundraiser) {
    return "Raised the most money in this race so far 💰";
  }
  if (voteLabel) {
    return `Voted on ${voteLabel}.`;
  }
  if (candidate.incumbent) {
    return "Current officeholder in this race.";
  }
  if (hasReceipts) {
    return "Has reported campaign fundraising so far.";
  }
  const firstPosition = candidate.positions?.[0];
  if (firstPosition?.issue) {
    return `Has a stated position on ${firstPosition.issue}.`;
  }
  return "No public record on this yet.";
}

// Every distinct source URL already attached to this candidate somewhere in
// the detailed view (finance/votes/positions/record/top-level sources[]) --
// deduped, never a new or guessed URL. A candidate with zero URLs on file
// gets no affordance at all rather than a link to nothing.
function candidateSourceLinks(candidate: Candidate): string[] {
  const links = new Set<string>();
  if (candidate.finance?.source) links.add(candidate.finance.source);
  if (candidate.record?.source) links.add(candidate.record.source);
  (candidate.record?.key_votes ?? []).forEach((v) => v.source && links.add(v.source));
  (candidate.positions ?? []).forEach((p) => p.source && links.add(p.source));
  (candidate.sources ?? []).forEach((s) => s && links.add(s));
  return Array.from(links);
}

// The small "sources" affordance simple mode still owes every claim
// (product requirement: simple ≠ unsourced). Collapsed by default so a
// compact card stays compact; renders nothing when there's genuinely
// nothing to link.
function SimpleSourcesLink({ links }: { links: string[] }) {
  if (links.length === 0) return null;
  return (
    <details className="mt-2 text-[11px] text-zinc-400">
      <summary className="cursor-pointer select-none py-1 hover:text-zinc-200">sources</summary>
      <ul className="mt-1 space-y-1 pl-3">
        {links.map((href, i) => (
          <li key={href}>
            <a href={href} target="_blank" rel="noopener noreferrer" className="text-emerald-400 hover:underline">
              source{links.length > 1 ? ` ${i + 1}` : ""} ↗
            </a>
          </li>
        ))}
      </ul>
    </details>
  );
}

function SimpleCandidateCard({
  candidate,
  raceCandidates,
}: {
  candidate: Candidate;
  raceCandidates: Candidate[];
}) {
  if (candidate.data_missing) {
    return (
      <div className="min-w-0 rounded-lg border border-dashed border-zinc-500 bg-zinc-950/50 p-4">
        <div className="flex items-center gap-2">
          <PartyDot party={null} />
          <span className="min-w-0 break-words font-medium leading-snug text-zinc-300">{candidate.name}</span>
        </div>
        <p className="mt-2 text-xs text-zinc-400">No public record on this yet.</p>
      </div>
    );
  }

  const takeaway = candidateTakeaway(candidate, raceCandidates);
  const money = formatMoneyFriendly(candidate.finance?.receipts);
  const links = candidateSourceLinks(candidate);

  return (
    <div className="min-w-0 rounded-lg border border-zinc-500 bg-zinc-950 p-4">
      <div className="mb-1.5 flex flex-wrap items-center gap-2">
        <PartyDot party={candidate.party} />
        <span className="min-w-0 break-words font-medium leading-snug text-zinc-100">{candidate.name}</span>
        {candidate.incumbent && (
          <span className="shrink-0 rounded-full border border-zinc-500 px-2 py-0.5 text-[10px] uppercase tracking-wide text-zinc-400">
            Incumbent
          </span>
        )}
      </div>
      {candidate.party && <div className="mb-2 text-xs text-zinc-400">{candidate.party}</div>}

      <p className="text-sm leading-5 text-zinc-200">{takeaway}</p>

      {money && (
        <p className="mt-1.5 text-xs text-zinc-400">
          <span className="text-zinc-300">{money} raised</span>
          {candidate.finance?.as_of && <span> as of {candidate.finance.as_of}</span>}
        </p>
      )}

      <SimpleSourcesLink links={links} />
    </div>
  );
}

// Race-level "the short version" -- one sentence, drawn from the same
// signals RaceCard's margin pill and money rows already surface above
// (never a new computation over hidden data). Falls back to an honest
// "not enough data" line rather than forcing a call the numbers don't
// support.
function shortVersionLine(race: Race): { text: string; source?: string } {
  const pill = marginPill(race);
  if (pill) {
    return { text: `Last time: ${pill.text}.`, source: pill.source };
  }

  const funded = race.candidates.filter(
    (c) => typeof c.finance?.receipts === "number" && (c.finance!.receipts as number) > 0
  );
  if (funded.length >= 2) {
    const leader = funded.reduce((a, b) => ((b.finance?.receipts ?? 0) > (a.finance?.receipts ?? 0) ? b : a));
    return {
      text: `${leader.name} has raised the most money in this race so far.`,
      source: leader.finance?.source ?? undefined,
    };
  }

  const withVotes = race.candidates.filter((c) => (c.record?.key_votes?.length ?? 0) > 0);
  if (withVotes.length > 0 && withVotes.length < race.candidates.length) {
    const names = withVotes.map((c) => c.name).join(" and ");
    return {
      text: `${names} ${withVotes.length === 1 ? "has" : "have"} a public voting record here — the others don't yet.`,
    };
  }

  return { text: "Not enough public data yet to call this one — check each candidate below." };
}

function SimpleRaceCard({
  race,
  active,
  onExplain,
}: {
  race: Race;
  active: boolean;
  onExplain: (raceId: string) => void;
}) {
  const short = shortVersionLine(race);
  return (
    <div className="rounded-xl border border-zinc-500 bg-zinc-900/50 p-5">
      <div className="mb-1 flex flex-wrap items-baseline justify-between gap-2">
        <h4 className="font-semibold leading-snug">{race.office}</h4>
        {race.district && <span className="text-xs text-zinc-400">{race.district}</span>}
      </div>
      <p className="mb-4 text-sm leading-5 text-zinc-400">{officeBlurb(race.office, race.level)}</p>

      {race.candidates.length > 0 ? (
        <>
          <div className="mb-4 rounded-lg border border-zinc-500 bg-zinc-950/40 p-3">
            <p className="text-[10px] font-semibold uppercase tracking-wide text-zinc-400">The short version</p>
            <p className="mt-1 text-sm leading-5 text-zinc-300">
              {short.text}
              {short.source && (
                <a
                  href={short.source}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="ml-1.5 text-emerald-400 hover:underline"
                >
                  source ↗
                </a>
              )}
            </p>
          </div>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {race.candidates.map((c) => (
              <SimpleCandidateCard key={c.candidate_id} candidate={c} raceCandidates={race.candidates} />
            ))}
          </div>

          <button
            onClick={() => onExplain(race.race_id)}
            className={`mt-4 rounded-lg border px-3 py-3.5 sm:py-1.5 text-xs font-medium transition ${
              active
                ? "border-emerald-400 bg-emerald-500/15 text-emerald-300"
                : "border-zinc-500 text-zinc-300 hover:border-emerald-400/60"
            }`}
          >
            What this means for you
          </button>
        </>
      ) : (
        <p className="text-xs text-zinc-400">No candidate data available for this race yet.</p>
      )}
    </div>
  );
}

// Shared level-grouping helper: detailed mode groups only the non-featured
// remainder (secondaryRaces); simple mode has no separate "featured" tier
// and groups ALL races the same way. Pulled into one function so both modes
// use byte-for-byte the same filter/push logic instead of duplicating it.
function groupRacesByLevel(list: Race[]): { level: string; races: Race[] }[] {
  const known = new Set(LEVEL_ORDER);
  const groups = LEVEL_ORDER.map((level) => ({
    level,
    races: list.filter((r) => r.level === level),
  })).filter((g) => g.races.length > 0);
  const other = list.filter((r) => !known.has(r.level));
  if (other.length > 0) groups.push({ level: "other", races: other });
  return groups;
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
  // nothing when omitted.
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
  // uniform density, unchanged from before this prop existed.
  featuredRaceId?: string | null;
}) {
  const reviewKey = readinessKey(districts);
  const reviewed = useSyncExternalStore(
    subscribeReviewed,
    () => getReviewed(reviewKey),
    () => EMPTY_REVIEWED
  );
  const [viewMode] = useViewMode();

  if (races.length === 0) {
    return (
      <>
        <VotingInfoCard votingInfo={votingInfo} />
        <p className="text-sm text-zinc-400">
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
  const groups = groupRacesByLevel(secondaryRaces);

  const raceIds = new Set(races.map((r) => r.race_id));
  const reviewedCount = Array.from(reviewed).filter((id) => raceIds.has(id)).length;

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-xs text-zinc-400">
          {viewMode === "simple"
            ? "Simple mode — plain-English take on each race."
            : "Detailed mode — every figure, vote, and source."}
        </p>
        <ViewModeToggle tone="zinc" />
      </div>

      <VotingInfoCard votingInfo={votingInfo} />
      <ReadinessBar reviewedCount={reviewedCount} total={races.length} />

      {viewMode === "simple" ? (
        // Simple mode has no separate "featured" tier -- every race (the
        // demo-rank one included) renders the same plain-English card, just
        // grouped by level like the detailed view's secondary races are.
        groupRacesByLevel(races).map((g) => (
          <div key={g.level}>
            <h3 className="mb-3 text-xs uppercase tracking-wider text-zinc-400">
              {LEVEL_LABELS[g.level] ?? g.level}
            </h3>
            <div className="space-y-3">
              {g.races.map((race) => (
                <SimpleRaceCard
                  key={race.race_id}
                  race={race}
                  active={activeRaceId === race.race_id}
                  onExplain={onExplain}
                />
              ))}
            </div>
          </div>
        ))
      ) : (
        <>
          {featuredRace && (
            <div>
              <div className="mb-3 flex flex-wrap items-center gap-2">
                <span className="rounded-full border border-emerald-400/60 bg-emerald-500/10 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide text-emerald-300">
                  Featured race
                </span>
                <span className="text-xs text-zinc-400">The race we can show you the most about right now.</span>
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
              <h3 className="mb-3 text-xs uppercase tracking-wider text-zinc-400">
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
        </>
      )}
    </div>
  );
}

export default BallotSection;
