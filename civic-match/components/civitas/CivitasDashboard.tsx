"use client";

import Link from "next/link";
import { useMemo, useState, type ReactNode } from "react";
import {
  AlertCircle,
  ArrowLeft,
  BarChart3,
  CheckCircle2,
  ChevronRight,
  FileText,
  MessageSquare,
  Scale,
  Search,
  ShieldCheck,
  Sparkles,
  Users,
  Vote,
} from "lucide-react";
import InsightsPanel from "@/components/ballot/InsightsPanel";
import {
  CivitasPanel,
  CivitasSectionHeading,
  MetricSeal,
  SourceLink,
  StatusPill,
  cn,
} from "@/components/civitas-ui";
import type {
  CivitasCandidateView,
  CivitasConfidence,
  CivitasDashboardView,
  CivitasRaceView,
  CivitasStatus,
} from "@/lib/civitasView";
import type { VoterProfile } from "@/lib/types";

type DashboardTab = "overview" | "races" | "compare" | "ask";

const tabs: { id: DashboardTab; label: string; icon: typeof BarChart3 }[] = [
  { id: "overview", label: "Overview", icon: BarChart3 },
  { id: "races", label: "All races", icon: Vote },
  { id: "compare", label: "Compare", icon: Scale },
  { id: "ask", label: "Ask", icon: MessageSquare },
];

function statusTone(status: CivitasStatus): "neutral" | "gold" | "red" {
  if (status === "Reviewed") return "gold";
  if (status === "Needs source data") return "red";
  return "neutral";
}

function statusIcon(status: CivitasStatus) {
  if (status === "Reviewed") return <CheckCircle2 className="h-4 w-4 text-gold" />;
  return <AlertCircle className="h-4 w-4 text-red-200" />;
}

function scoreTone(score?: number) {
  if (score === undefined) return "text-white/42";
  if (score >= 70) return "text-gold";
  if (score >= 45) return "text-cream";
  return "text-red-200";
}

function confidenceTone(confidence: CivitasConfidence) {
  if (confidence === "High") return "bg-gold";
  if (confidence === "Medium") return "bg-cream";
  return "bg-red-200";
}

function SignalBars({ level }: { level: CivitasConfidence }) {
  const active = confidenceTone(level);
  return (
    <div className="flex h-3.5 items-end gap-[2px]" aria-hidden="true">
      <div className={cn("h-1.5 w-1 rounded-sm", active)} />
      <div className={cn("h-2.5 w-1 rounded-sm", level === "Low" ? "bg-white/16" : active)} />
      <div className={cn("h-3.5 w-1 rounded-sm", level === "High" ? active : "bg-white/16")} />
    </div>
  );
}

function CandidateAvatar({ candidate }: { candidate: CivitasCandidateView }) {
  return (
    <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-[8px] border border-gold/30 bg-navy-dark font-serif text-base text-gold">
      {candidate.initials}
    </span>
  );
}

function CandidateName({ candidate }: { candidate: CivitasCandidateView }) {
  if (candidate.profileHref) {
    return (
      <Link href={candidate.profileHref} className="block min-w-0 truncate font-medium text-white hover:text-gold">
        {candidate.name}
      </Link>
    );
  }
  return <span className="block min-w-0 truncate font-medium text-white">{candidate.name}</span>;
}

function StatCard({
  icon,
  value,
  label,
  sublabel,
}: {
  icon: ReactNode;
  value: ReactNode;
  label: string;
  sublabel?: string;
}) {
  return (
    <CivitasPanel className="flex min-h-[118px] flex-col justify-between p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="text-gold">{icon}</div>
        <div className="font-serif text-3xl leading-none text-white">{value}</div>
      </div>
      <div>
        <div className="text-sm font-medium text-white/65">{label}</div>
        {sublabel && <div className="mt-1 text-xs text-white/38">{sublabel}</div>}
      </div>
    </CivitasPanel>
  );
}

function TopCandidate({ candidate }: { candidate: CivitasCandidateView }) {
  return (
    <div className="flex gap-4">
      <CandidateAvatar candidate={candidate} />
      <div className="min-w-0 flex-1">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <CandidateName candidate={candidate} />
            <p className="mt-0.5 truncate text-xs text-white/42">{candidate.office}</p>
          </div>
          <div className="shrink-0 text-right">
            <div className={cn("text-lg font-semibold leading-none", scoreTone(candidate.alignmentScore))}>
              {candidate.alignmentScore !== undefined ? `${candidate.alignmentScore}%` : "n/a"}
            </div>
            <div className="mt-1 text-[10px] uppercase tracking-[0.16em] text-white/38">
              alignment
            </div>
          </div>
        </div>
        <p className="mt-2 line-clamp-2 text-xs leading-5 text-white/55">{candidate.summary}</p>
      </div>
    </div>
  );
}

function RaceSnapshot({
  races,
  onSelectRace,
}: {
  races: CivitasRaceView[];
  onSelectRace: (raceId: string, tab?: DashboardTab) => void;
}) {
  return (
    <CivitasPanel className="overflow-hidden">
      <div className="border-b border-white/10 p-5">
        <CivitasSectionHeading
          className="mb-0"
          title="Race snapshot"
          description="Real races from the address resolver, with neutral data-confidence signals."
        />
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[720px] text-sm">
          <thead>
            <tr className="border-b border-white/10 text-left text-[10px] font-semibold uppercase tracking-[0.18em] text-white/38">
              <th className="px-5 py-3 font-semibold">Race</th>
              <th className="px-5 py-3 font-semibold">Candidates</th>
              <th className="px-5 py-3 font-semibold">Alignment range</th>
              <th className="px-5 py-3 font-semibold">Confidence</th>
              <th className="px-5 py-3 font-semibold">Status</th>
              <th className="px-5 py-3 text-right font-semibold">Open</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/8">
            {races.map((race) => (
              <tr
                key={race.id}
                tabIndex={0}
                aria-label={`Compare candidates in ${race.office}`}
                onClick={() => onSelectRace(race.id, "compare")}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    onSelectRace(race.id, "compare");
                  }
                }}
                className="cursor-pointer transition hover:bg-white/[0.025] focus-visible:bg-white/[0.035] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-gold/70"
              >
                <td className="px-5 py-4">
                  <div className="font-medium text-white">{race.office}</div>
                  <div className="mt-1 text-xs text-white/42">{race.location}</div>
                </td>
                <td className="px-5 py-4">
                  <div className="flex items-center gap-1.5">
                    {race.candidates.slice(0, 3).map((candidate) => (
                      <span
                        key={candidate.id}
                        className="flex h-7 w-7 items-center justify-center rounded-full border border-navy bg-gold/15 text-[10px] font-semibold text-gold"
                        title={candidate.name}
                      >
                        {candidate.initials}
                      </span>
                    ))}
                    {race.candidatesCount > 3 && (
                      <span className="flex h-7 w-7 items-center justify-center rounded-full border border-white/10 bg-white/8 text-[10px] text-white/62">
                        +{race.candidatesCount - 3}
                      </span>
                    )}
                  </div>
                </td>
                <td className="px-5 py-4 font-mono text-gold">{race.alignmentRange}</td>
                <td className="px-5 py-4">
                  <div className="flex items-center gap-2">
                    <SignalBars level={race.confidence} />
                    <span className="text-white/62">{race.confidence}</span>
                  </div>
                </td>
                <td className="px-5 py-4">
                  <div className="flex items-center gap-2">
                    {statusIcon(race.status)}
                    <span className="text-white/62">{race.status}</span>
                  </div>
                </td>
                <td className="px-5 py-4 text-right">
                  <button
                    type="button"
                    onClick={(event) => {
                      event.stopPropagation();
                      onSelectRace(race.id, "compare");
                    }}
                    className="inline-flex items-center gap-1 text-xs font-semibold uppercase tracking-[0.14em] text-gold hover:text-white"
                  >
                    Compare <ChevronRight className="h-4 w-4" />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </CivitasPanel>
  );
}

function OverviewTab({
  view,
  onSelectRace,
}: {
  view: CivitasDashboardView;
  onSelectRace: (raceId: string, tab?: DashboardTab) => void;
}) {
  return (
    <div className="grid gap-7 lg:grid-cols-[minmax(0,1fr)_320px]">
      <div className="space-y-7">
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <StatCard icon={<Vote className="h-6 w-6" />} value={view.stats.races} label="Races on ballot" />
          <StatCard icon={<Users className="h-6 w-6" />} value={view.stats.candidates} label="Candidates loaded" />
          <StatCard
            icon={<Sparkles className="h-6 w-6" />}
            value={view.stats.scoreableCandidates}
            label="Scoreable profiles"
            sublabel="from researched records"
          />
          <StatCard
            icon={<AlertCircle className="h-6 w-6" />}
            value={view.stats.limitedRaces}
            label="Need review"
            sublabel="limited public data"
          />
        </div>
        <RaceSnapshot races={view.races} onSelectRace={onSelectRace} />
      </div>

      <div className="space-y-5">
        <CivitasPanel className="p-5">
          <div className="mb-5 flex items-start gap-3">
            <ShieldCheck className="h-5 w-5 shrink-0 text-gold" />
            <div>
              <h3 className="font-medium text-white">Resolved ballot</h3>
              <p className="mt-1 text-xs leading-5 text-white/50">{view.districtSummary}</p>
            </div>
          </div>
          <div className="space-y-3 text-sm">
            <div className="flex justify-between gap-4 border-b border-white/8 pb-3">
              <span className="text-white/45">Address match</span>
              <span className="max-w-[12rem] text-right text-white/72">{view.location}</span>
            </div>
            <div className="flex justify-between gap-4 border-b border-white/8 pb-3">
              <span className="text-white/45">Source policy</span>
              <span className="text-right text-white/72">No source, no claim</span>
            </div>
            <div className="flex justify-between gap-4">
              <span className="text-white/45">Mode</span>
              <span className="text-right text-white/72">{view.mode ?? "resolved"}</span>
            </div>
          </div>
        </CivitasPanel>

        <CivitasPanel className="p-5">
          <div className="mb-5 flex items-start gap-3">
            <Sparkles className="h-5 w-5 shrink-0 fill-gold text-gold" />
            <div>
              <h3 className="font-medium text-white">Top alignments</h3>
              <p className="mt-1 text-xs leading-5 text-white/50">
                Based on your stated priorities, not an endorsement.
              </p>
            </div>
          </div>
          {view.topCandidates.length ? (
            <div className="space-y-5">
              {view.topCandidates.slice(0, 3).map((candidate) => (
                <TopCandidate key={candidate.id} candidate={candidate} />
              ))}
            </div>
          ) : (
            <p className="text-sm leading-6 text-white/50">
              No scoreable profile matched this selected race yet. The ballot data still renders from the
              backend.
            </p>
          )}
        </CivitasPanel>
      </div>
    </div>
  );
}

function AllRacesTab({
  races,
  onSelectRace,
}: {
  races: CivitasRaceView[];
  onSelectRace: (raceId: string, tab?: DashboardTab) => void;
}) {
  return <RaceSnapshot races={races} onSelectRace={onSelectRace} />;
}

function CandidateCompareCard({ candidate }: { candidate: CivitasCandidateView }) {
  const votes = candidate.raw.record?.key_votes?.slice(0, 3) ?? [];
  const positions = candidate.raw.positions?.slice(0, 4) ?? [];

  return (
    <CivitasPanel className="flex min-w-[240px] flex-1 flex-col p-5">
      <div className="mb-5 grid grid-cols-[auto_minmax(0,1fr)_auto] items-start gap-4">
        <CandidateAvatar candidate={candidate} />
        <div className="min-w-0 flex-1">
          <CandidateName candidate={candidate} />
          <div className="mt-1 flex flex-wrap items-center gap-2">
            {candidate.party && <StatusPill>{candidate.party}</StatusPill>}
            {candidate.incumbent && <StatusPill tone="gold">Incumbent</StatusPill>}
          </div>
        </div>
        <div className="shrink-0 text-right">
          <div className={cn("text-xl font-semibold leading-none", scoreTone(candidate.alignmentScore))}>
            {candidate.alignmentScore !== undefined ? `${candidate.alignmentScore}%` : "n/a"}
          </div>
          <div className="mt-1 text-[10px] uppercase tracking-[0.16em] text-white/38">alignment</div>
        </div>
      </div>

      <p className="mb-5 min-h-[3rem] text-sm leading-6 text-white/62">{candidate.summary}</p>

      <div className="mb-5 flex flex-wrap gap-2">
        {candidate.topIssues.map((issue) => (
          <StatusPill key={issue}>{issue}</StatusPill>
        ))}
      </div>

      <div className="mb-5 grid grid-cols-2 gap-3 text-xs">
        <div className="border-l border-gold/35 bg-navy-dark/55 p-3">
          <div className="text-white/38">Confidence</div>
          <div className="mt-1 flex items-center gap-2 text-white/72">
            <SignalBars level={candidate.confidence} />
            {candidate.confidence}
          </div>
        </div>
        <div className="border-l border-white/18 bg-navy-dark/55 p-3">
          <div className="text-white/38">Sources</div>
          <div className="mt-1 text-white/72">{candidate.sourceCount || "No"} linked</div>
        </div>
      </div>

      <div className="space-y-5 text-sm">
        <div>
          <div className="mb-1 text-xs uppercase tracking-[0.18em] text-white/38">Campaign finance</div>
          <p className="text-white/68">
            {candidate.financeLabel}
            {candidate.financeSource && (
              <>
                {" "}
                <SourceLink href={candidate.financeSource} className="text-xs">
                  FEC source
                </SourceLink>
              </>
            )}
          </p>
        </div>

        <div>
          <div className="mb-1 text-xs uppercase tracking-[0.18em] text-white/38">Positions</div>
          {positions.length ? (
            <ul className="space-y-2">
              {positions.map((position) => (
                <li key={`${candidate.id}-${position.issue}`} className="text-white/62">
                  <span className="text-white/82">{position.issue}:</span> {position.summary}
                  {position.source && (
                    <>
                      {" "}
                      <SourceLink href={position.source} className="text-xs">
                        source
                      </SourceLink>
                    </>
                  )}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-white/42">No sourced issue positions in this dataset.</p>
          )}
        </div>

        <div>
          <div className="mb-1 text-xs uppercase tracking-[0.18em] text-white/38">Record</div>
          {votes.length ? (
            <ul className="space-y-2">
              {votes.map((vote, index) => (
                <li key={`${candidate.id}-vote-${index}`} className="text-white/62">
                  <span className="text-white/82">{vote.bill ?? vote.vote ?? "Vote"}:</span>{" "}
                  {vote.position ?? "recorded"}
                  {vote.source && (
                    <>
                      {" "}
                      <SourceLink href={vote.source} className="text-xs">
                        source
                      </SourceLink>
                    </>
                  )}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-white/42">No recorded votes in this dataset.</p>
          )}
        </div>
      </div>

      <div className="mt-auto pt-6">
        {candidate.profileHref ? (
          <Link
            href={candidate.profileHref}
            className="inline-flex w-full items-center justify-center gap-2 rounded-[8px] border border-gold/45 bg-gold/10 px-4 py-3 text-xs font-black uppercase tracking-[0.18em] text-gold transition hover:border-gold hover:bg-gold/15"
          >
            Full profile <ChevronRight className="h-4 w-4" />
          </Link>
        ) : (
          <div className="rounded-[8px] border border-white/10 px-4 py-3 text-center text-xs text-white/42">
            No researched profile matched yet.
          </div>
        )}
      </div>
    </CivitasPanel>
  );
}

function CompareTab({
  race,
  races,
  onSelectRace,
}: {
  race: CivitasRaceView | null;
  races: CivitasRaceView[];
  onSelectRace: (raceId: string, tab?: DashboardTab) => void;
}) {
  if (!race) {
    return (
      <CivitasPanel className="p-6 text-sm text-white/55">
        No race is selected. Return to the overview and choose a race.
      </CivitasPanel>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="mb-2 text-xs font-semibold uppercase tracking-[0.22em] text-gold">
            Compare candidates
          </p>
          <h2 className="font-serif text-4xl leading-tight text-white">{race.office}</h2>
          <p className="mt-2 text-sm text-white/55">
            {race.location} / {race.candidatesCount} candidates / {race.sourceCount} linked sources
          </p>
        </div>
        <select
          value={race.id}
          onChange={(event) => onSelectRace(event.target.value, "compare")}
          className="h-11 rounded-[8px] border border-white/14 bg-navy-dark px-3 text-sm text-white outline-none focus:border-gold"
        >
          {races.map((item) => (
            <option key={item.id} value={item.id}>
              {item.office}
            </option>
          ))}
        </select>
      </div>

      {race.contextSummary && (
        <CivitasPanel className="p-4 text-sm leading-6 text-white/62">
          <span className="font-medium text-white/82">Context:</span> {race.contextSummary}
        </CivitasPanel>
      )}

      <div className="flex flex-col gap-4 xl:flex-row">
        {race.candidates.length ? (
          race.candidates.map((candidate) => (
            <CandidateCompareCard key={candidate.id} candidate={candidate} />
          ))
        ) : (
          <CivitasPanel className="p-5 text-sm text-white/55">
            No candidate data available for this race yet.
          </CivitasPanel>
        )}
      </div>
    </div>
  );
}

function AskTab({
  race,
  races,
  profile,
  onSelectRace,
}: {
  race: CivitasRaceView | null;
  races: CivitasRaceView[];
  profile?: VoterProfile;
  onSelectRace: (raceId: string, tab?: DashboardTab) => void;
}) {
  const backendRaces = useMemo(() => races.map((item) => item.raw), [races]);

  return (
    <div className="mx-auto max-w-4xl">
      <div className="mb-8">
        <p className="mb-2 text-xs font-semibold uppercase tracking-[0.22em] text-gold">Ask Civitas</p>
        <h2 className="font-serif text-4xl leading-tight text-white">Ask about this election</h2>
        <p className="mt-3 text-sm leading-6 text-white/58">
          Answers come from the existing source-grounded insight path. Missing evidence stays visible.
        </p>
      </div>

      <div className="mb-6 flex flex-wrap gap-3">
        {races.slice(0, 6).map((item) => (
          <button
            key={item.id}
            type="button"
            onClick={() => onSelectRace(item.id, "ask")}
            className={cn(
              "rounded-[8px] border px-4 py-2 text-left text-xs transition",
              race?.id === item.id
                ? "border-gold bg-gold/10 text-gold"
                : "border-white/12 bg-white/[0.035] text-white/58 hover:border-white/26 hover:text-white"
            )}
          >
            {item.office}
          </button>
        ))}
      </div>

      <InsightsPanel raceId={race?.id ?? null} races={backendRaces} profile={profile} />

      {race?.candidates.some((candidate) => candidate.profileHref) && (
        <CivitasPanel className="mt-5 p-5">
          <div className="mb-3 flex items-center gap-2 text-sm font-medium text-white">
            <Search className="h-4 w-4 text-gold" />
            Candidate-specific source Q&A
          </div>
          <div className="flex flex-wrap gap-2">
            {race.candidates
              .filter((candidate) => candidate.profileHref)
              .map((candidate) => (
                <Link
                  key={candidate.id}
                  href={candidate.profileHref!}
                  className="rounded-full border border-white/12 px-3 py-1.5 text-xs text-white/58 hover:border-gold/50 hover:text-gold"
                >
                  Ask about {candidate.name}
                </Link>
              ))}
          </div>
        </CivitasPanel>
      )}
    </div>
  );
}

export default function CivitasDashboard({
  view,
  initialRaceId,
  profile,
  onEditSettings,
}: {
  view: CivitasDashboardView;
  initialRaceId?: string | null;
  profile?: VoterProfile;
  onEditSettings: () => void;
}) {
  const [tab, setTab] = useState<DashboardTab>("overview");
  const [activeRaceId, setActiveRaceId] = useState<string | null>(
    initialRaceId ?? view.races[0]?.id ?? null
  );

  const activeRace = useMemo(
    () => view.races.find((race) => race.id === activeRaceId) ?? view.races[0] ?? null,
    [activeRaceId, view.races]
  );

  const selectRace = (raceId: string, nextTab: DashboardTab = tab) => {
    setActiveRaceId(raceId);
    setTab(nextTab);
  };

  return (
    <section className="flex min-h-full flex-1 flex-col bg-navy text-cream-light">
      <header className="border-b border-white/10 px-5 py-4 lg:px-8">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex items-center gap-4">
            <button
              type="button"
              onClick={onEditSettings}
              className="inline-flex items-center gap-2 rounded-[8px] border border-white/12 px-3 py-2 text-xs font-semibold uppercase tracking-[0.14em] text-white/58 transition hover:border-white/26 hover:bg-white/[0.035] hover:text-white"
              aria-label="Edit ballot settings"
            >
              <ArrowLeft className="h-5 w-5" />
              <span>Edit settings</span>
            </button>
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-[0.22em] text-gold">
                Your ballot at a glance
              </p>
              <h1 className="font-serif text-3xl leading-tight text-white">{view.location}</h1>
              <p className="mt-1 text-xs text-white/45">{view.districtSummary}</p>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            {tabs.map((item) => {
              const Icon = item.icon;
              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => setTab(item.id)}
                  className={cn(
                    "inline-flex items-center gap-2 rounded-[8px] border px-3 py-2 text-xs font-semibold uppercase tracking-[0.14em] transition",
                    tab === item.id
                      ? "border-gold bg-gold/10 text-gold"
                      : "border-white/12 text-white/55 hover:border-white/26 hover:text-white"
                  )}
                >
                  <Icon className="h-4 w-4" />
                  {item.label}
                </button>
              );
            })}
          </div>
        </div>
        {view.warning && (
          <p className="mt-4 rounded-[8px] border border-gold/30 bg-gold/10 p-3 text-xs leading-5 text-gold">
            {view.warning}
          </p>
        )}
      </header>

      <div className="flex-1 overflow-y-auto px-5 py-6 lg:px-8 lg:py-8">
        {tab === "overview" && <OverviewTab view={view} onSelectRace={selectRace} />}
        {tab === "races" && <AllRacesTab races={view.races} onSelectRace={selectRace} />}
        {tab === "compare" && (
          <CompareTab race={activeRace} races={view.races} onSelectRace={selectRace} />
        )}
        {tab === "ask" && (
          <AskTab
            race={activeRace}
            races={view.races}
            profile={profile}
            onSelectRace={selectRace}
          />
        )}
      </div>

      <footer className="border-t border-white/10 px-5 py-3 lg:px-8">
        <div className="flex flex-col gap-3 text-xs text-white/42 lg:flex-row lg:items-center lg:justify-between">
          <span>Neutral alignment from stated priorities. Matches are not endorsements.</span>
          <div className="flex flex-wrap items-center gap-2">
            <StatusPill tone={statusTone(activeRace?.status ?? "Limited data")}>
              {activeRace?.status ?? "Limited data"}
            </StatusPill>
            <div className="flex items-center gap-2">
              <FileText className="h-4 w-4 text-gold" />
              <span>{activeRace?.sourceCount ?? 0} linked sources in selected race</span>
            </div>
            {activeRace && (
              <MetricSeal
                value={activeRace.alignmentRange === "Not scored" ? "n/a" : activeRace.alignmentRange}
                label="range"
                className="hidden h-12 w-12 sm:flex [&_span:first-child]:text-sm"
              />
            )}
          </div>
        </div>
      </footer>
    </section>
  );
}
