"use client";

// Renders the voter's ballot: races grouped Federal -> Statewide, each with
// an equal-weight candidate comparison (name, party, incumbent tag, money
// raised w/ source link, up to 3 key votes w/ source links) and a button to
// request a personalized read via <InsightsPanel/> (owned by the parent).
import type { Candidate, DataQuality, Race } from "@/lib/dataBackend";
import { CivitasPanel, SourceLink, StatusPill } from "@/components/civitas-ui";

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

// Neutral "how much do we actually know here" signal — same label, same
// muted style, same spot for every tier A-D and every candidate/race, so it
// never reads as a knock on whoever happens to score low. The tooltip is the
// only place the underlying `missing[]` gaps (verbatim, e.g. "no campaign
// finance") show up; a D just means "we have little public data."
function QualityChip({ quality }: { quality?: DataQuality }) {
  if (!quality?.tier) return null;
  const missing = quality.missing ?? [];
  const title =
    missing.length > 0
      ? `Limited public data available: ${missing.join(", ")}`
      : "Data confidence score for what we could verify in our set";
  return (
    <StatusPill title={title}>
      Data confidence: {quality.tier}
    </StatusPill>
  );
}

function CandidateColumn({ candidate }: { candidate: Candidate }) {
  if (candidate.data_missing) {
    return (
      <div className="min-w-[220px] flex-1 rounded-[8px] border border-dashed border-white/14 bg-navy-dark/45 p-4 text-xs text-white/42">
        No candidate data available in our set yet.
      </div>
    );
  }

  const votes = (candidate.record?.key_votes ?? []).slice(0, 3);
  const receipts = formatMoney(candidate.finance?.receipts);

  return (
    <div className="min-w-[220px] flex-1 rounded-[8px] border border-white/10 bg-navy-dark/60 p-4">
      <div className="mb-1 flex items-start justify-between gap-2">
        <span className="font-serif text-lg leading-snug text-white">{candidate.name}</span>
        {candidate.incumbent && (
          <StatusPill tone="gold">Incumbent</StatusPill>
        )}
      </div>
      {(candidate.party || candidate.data_quality) && (
        <div className="mb-3 flex flex-wrap items-center gap-1.5">
          {candidate.party && (
            <span className="inline-block rounded-full border border-white/14 px-2 py-0.5 text-xs text-white/55">
              {candidate.party}
            </span>
          )}
          <QualityChip quality={candidate.data_quality} />
        </div>
      )}

      <div className="mb-3 text-xs">
        <div className="mb-0.5 font-semibold uppercase tracking-[0.16em] text-white/42">Money raised</div>
        {receipts ? (
          <div className="text-white/72">
            {receipts}
            {candidate.finance?.as_of && (
              <span className="text-white/38"> as of {candidate.finance.as_of}</span>
            )}
            {candidate.finance?.source && (
              <SourceLink href={candidate.finance.source} className="ml-1.5">source</SourceLink>
            )}
          </div>
        ) : (
          <div className="text-white/35">No finance data in our set</div>
        )}
      </div>

      <div className="text-xs">
        <div className="mb-1 font-semibold uppercase tracking-[0.16em] text-white/42">Key votes</div>
        {votes.length > 0 ? (
          <ul className="space-y-1.5">
            {votes.map((v, i) => (
              <li key={i} className="text-white/62">
                <span className="text-white/82">{v.bill ?? v.vote ?? "Vote"}</span>
                {v.position ? `: ${v.position}` : ""}
                {v.plain_english && (
                  <span className="block text-[11px] text-white/42">{v.plain_english}</span>
                )}
                {v.source && (
                  <SourceLink href={v.source}>source</SourceLink>
                )}
              </li>
            ))}
          </ul>
        ) : (
          <div className="text-white/35">No recorded votes in our set</div>
        )}
      </div>
    </div>
  );
}

function RaceCard({
  race,
  active,
  onExplain,
}: {
  race: Race;
  active: boolean;
  onExplain: (raceId: string) => void;
}) {
  const pill = marginPill(race);
  return (
    <CivitasPanel className="p-5">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="font-serif text-2xl leading-tight text-white">{race.office}</div>
          {race.district && <div className="text-xs uppercase tracking-[0.18em] text-white/45">{race.district}</div>}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <QualityChip quality={race.data_quality} />
          {pill && (
            <StatusPill>{pill}</StatusPill>
          )}
          <button
            onClick={() => onExplain(race.race_id)}
            className={`rounded-lg border px-3 py-1.5 text-xs font-medium transition ${
              active
                ? "border-gold bg-gold/12 text-gold"
                : "border-white/14 text-white/72 hover:border-gold/60 hover:text-gold"
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
        <p className="text-xs text-white/38">No candidate data available for this race yet.</p>
      )}
    </CivitasPanel>
  );
}

export function BallotSection({
  races,
  activeRaceId,
  onExplain,
}: {
  races: Race[];
  activeRaceId: string | null;
  onExplain: (raceId: string) => void;
}) {
  if (races.length === 0) {
    return (
      <p className="text-sm text-white/52">
        No races found for this address yet — the district may not be loaded in our data set.
      </p>
    );
  }

  const known = new Set(LEVEL_ORDER);
  const groups = LEVEL_ORDER.map((level) => ({
    level,
    races: races.filter((r) => r.level === level),
  })).filter((g) => g.races.length > 0);
  const other = races.filter((r) => !known.has(r.level));
  if (other.length > 0) groups.push({ level: "other", races: other });

  return (
    <div className="space-y-8">
      {groups.map((g) => (
        <div key={g.level}>
          <h3 className="mb-3 text-xs font-semibold uppercase tracking-[0.2em] text-gold/80">
            {LEVEL_LABELS[g.level] ?? g.level}
          </h3>
          <div className="space-y-5">
            {g.races.map((race) => (
              <RaceCard
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
