"use client";

// Renders the voter's ballot: races grouped Federal -> Statewide, each with
// an equal-weight candidate comparison (name, party, incumbent tag, money
// raised w/ source link, up to 3 key votes w/ source links) and a button to
// request a personalized read via <InsightsPanel/> (owned by the parent).
import type { Candidate, Race } from "@/lib/dataBackend";

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

function CandidateColumn({ candidate }: { candidate: Candidate }) {
  if (candidate.data_missing) {
    return (
      <div className="min-w-[220px] flex-1 rounded-lg border border-dashed border-zinc-800 bg-zinc-950/50 p-4 text-xs text-zinc-600">
        No candidate data available in our set yet.
      </div>
    );
  }

  const votes = (candidate.record?.key_votes ?? []).slice(0, 3);
  const receipts = formatMoney(candidate.finance?.receipts);

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
      {candidate.party && (
        <span className="mb-3 inline-block rounded-full border border-zinc-700 px-2 py-0.5 text-xs text-zinc-400">
          {candidate.party}
        </span>
      )}

      <div className="mb-3 text-xs">
        <div className="mb-0.5 text-zinc-500">Money raised</div>
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
                rel="noreferrer"
                className="ml-1.5 text-emerald-400 hover:underline"
              >
                source ↗
              </a>
            )}
          </div>
        ) : (
          <div className="text-zinc-600">No finance data in our set</div>
        )}
      </div>

      <div className="text-xs">
        <div className="mb-1 text-zinc-500">Key votes</div>
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
                    rel="noreferrer"
                    className="text-emerald-400 hover:underline"
                  >
                    source ↗
                  </a>
                )}
              </li>
            ))}
          </ul>
        ) : (
          <div className="text-zinc-600">No recorded votes in our set</div>
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
    <div className="rounded-xl border border-zinc-800 bg-zinc-900/50 p-5">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="font-semibold">{race.office}</div>
          {race.district && <div className="text-xs text-zinc-500">{race.district}</div>}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {pill && (
            <span className="rounded-full border border-zinc-700 px-2.5 py-1 text-[11px] text-zinc-400">
              {pill}
            </span>
          )}
          <button
            onClick={() => onExplain(race.race_id)}
            className={`rounded-lg border px-3 py-1.5 text-xs font-medium transition ${
              active
                ? "border-emerald-400 bg-emerald-500/15 text-emerald-300"
                : "border-zinc-700 text-zinc-300 hover:border-emerald-400/60"
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
    </div>
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
      <p className="text-sm text-zinc-500">
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
          <h3 className="mb-3 text-xs uppercase tracking-wider text-zinc-500">
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
