import { slugify } from "./db-client";
import type { Candidate, DataQuality, Districts, Race } from "./dataBackend";
import type { MatchResult } from "./types";

export type CivitasConfidence = "High" | "Medium" | "Low";
export type CivitasStatus = "Reviewed" | "Limited data" | "Needs source data";

export interface CivitasCandidateView {
  id: string;
  name: string;
  initials: string;
  party?: string | null;
  office?: string;
  district?: string | null;
  incumbent?: boolean | null;
  profileHref?: string;
  alignmentScore?: number;
  overall?: number;
  alignmentLabel: string;
  confidence: CivitasConfidence;
  status: CivitasStatus;
  summary: string;
  topIssues: string[];
  sourceCount: number;
  financeLabel: string;
  financeSource?: string;
  keyVotesCount: number;
  dataQuality?: DataQuality;
  raw: Candidate;
  match?: MatchResult;
}

export interface CivitasRaceView {
  id: string;
  office: string;
  level: string;
  location: string;
  candidatesCount: number;
  alignmentRange: string;
  confidence: CivitasConfidence;
  status: CivitasStatus;
  contextSummary?: string;
  sourceCount: number;
  candidates: CivitasCandidateView[];
  raw: Race;
}

export interface CivitasDashboardView {
  location: string;
  districtSummary: string;
  mode?: string;
  warning?: string;
  stats: {
    races: number;
    candidates: number;
    scoreableCandidates: number;
    limitedRaces: number;
  };
  races: CivitasRaceView[];
  topCandidates: CivitasCandidateView[];
}

export interface CivitasBallotLike {
  matched_address?: string;
  districts?: Partial<Districts>;
  races: Race[];
  mode?: string;
  warning?: string;
}

const LEVEL_LABELS: Record<string, string> = {
  federal: "Federal",
  state: "Texas statewide",
  state_leg: "Texas Legislature",
};

function normalizeName(name: string): string {
  return slugify(name).replace(/\b(jr|sr|ii|iii|iv)\b/g, "").replace(/-+/g, "-");
}

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  return (parts[0]?.[0] ?? "?") + (parts.length > 1 ? parts[parts.length - 1][0] : "");
}

function formatMoney(value?: number | null): string {
  if (value === null || value === undefined) return "No finance data in our set";
  return value.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  });
}

function confidenceFromQuality(quality?: DataQuality): CivitasConfidence {
  if (quality?.tier === "A" || quality?.tier === "B") return "High";
  if (quality?.tier === "C") return "Medium";
  return "Low";
}

function confidenceForCandidate(candidate: Candidate, match?: MatchResult): CivitasConfidence {
  if (match?.confidence) return match.confidence;
  return confidenceFromQuality(candidate.data_quality);
}

function alignmentLabel(score?: number): string {
  if (score === undefined) return "Evidence available, no alignment score";
  if (score >= 80) return "Strongest match from your stated priorities";
  if (score >= 65) return "Strong alignment";
  if (score >= 45) return "Partial alignment";
  return "Lower alignment";
}

function statusForCandidate(candidate: Candidate): CivitasStatus {
  if (candidate.data_missing) return "Needs source data";
  const tier = candidate.data_quality?.tier;
  if (tier === "C" || tier === "D") return "Limited data";
  return "Reviewed";
}

function sourceUrls(candidate: Candidate): Set<string> {
  const urls = new Set<string>();
  for (const url of candidate.sources ?? []) urls.add(url);
  if (candidate.finance?.source) urls.add(candidate.finance.source);
  if (candidate.record?.source) urls.add(candidate.record.source);
  for (const vote of candidate.record?.key_votes ?? []) {
    if (vote.source) urls.add(vote.source);
  }
  for (const position of candidate.positions ?? []) {
    if (position.source) urls.add(position.source);
  }
  return urls;
}

function topIssues(candidate: Candidate, match?: MatchResult): string[] {
  const fromPositions = (candidate.positions ?? [])
    .map((position) => position.issue)
    .filter((issue): issue is string => Boolean(issue))
    .slice(0, 3);
  if (fromPositions.length) return fromPositions;

  const fromMatch = match?.top_agreements.map((item) => item.issue_name).slice(0, 3) ?? [];
  if (fromMatch.length) return fromMatch;

  const votes = candidate.record?.key_votes ?? [];
  if (votes.length) return ["Voting record"];

  return ["Public record"];
}

function candidateSummary(candidate: Candidate, match?: MatchResult): string {
  if (match) {
    const agreements = match.top_agreements.slice(0, 2).map((item) => item.issue_name);
    const conflicts = match.top_conflicts.slice(0, 1).map((item) => item.issue_name);
    if (agreements.length && conflicts.length) {
      return `Aligns on ${agreements.join(", ")}; differs on ${conflicts.join(", ")}.`;
    }
    if (agreements.length) return `Strongest overlap: ${agreements.join(", ")}.`;
    if (conflicts.length) return `Main tension: ${conflicts.join(", ")}.`;
    return match.overall_tier;
  }

  const firstPosition = candidate.positions?.[0]?.summary;
  if (firstPosition) return firstPosition;

  const firstVote = candidate.record?.key_votes?.[0];
  if (firstVote?.plain_english) return firstVote.plain_english;

  if (candidate.data_missing) return "No candidate data available in our set yet.";
  return "Source-linked candidate record is available for review.";
}

function buildMatchMap(matches: MatchResult[]): Map<string, MatchResult> {
  const map = new Map<string, MatchResult>();
  for (const match of matches) {
    map.set(normalizeName(match.politician_name), match);
  }
  return map;
}

function buildCandidateView(candidate: Candidate, match?: MatchResult): CivitasCandidateView {
  const urls = sourceUrls(candidate);
  return {
    id: candidate.candidate_id,
    name: candidate.name,
    initials: initials(candidate.name).toUpperCase(),
    party: candidate.party,
    office: candidate.office,
    district: candidate.district,
    incumbent: candidate.incumbent,
    profileHref: match ? `/p/${match.politician_id}` : undefined,
    alignmentScore: match?.score,
    overall: match?.overall,
    alignmentLabel: alignmentLabel(match?.score),
    confidence: confidenceForCandidate(candidate, match),
    status: statusForCandidate(candidate),
    summary: candidateSummary(candidate, match),
    topIssues: topIssues(candidate, match),
    sourceCount: urls.size,
    financeLabel: formatMoney(candidate.finance?.receipts),
    financeSource: candidate.finance?.source ?? undefined,
    keyVotesCount: candidate.record?.key_votes?.length ?? 0,
    dataQuality: candidate.data_quality,
    raw: candidate,
    match,
  };
}

function raceLocation(race: Race): string {
  if (race.district) return race.district;
  return LEVEL_LABELS[race.level] ?? race.level;
}

function raceStatus(candidates: CivitasCandidateView[]): CivitasStatus {
  if (candidates.some((candidate) => candidate.status === "Needs source data")) {
    return "Needs source data";
  }
  if (candidates.some((candidate) => candidate.status === "Limited data")) {
    return "Limited data";
  }
  return "Reviewed";
}

function raceConfidence(candidates: CivitasCandidateView[]): CivitasConfidence {
  if (!candidates.length) return "Low";
  if (candidates.every((candidate) => candidate.confidence === "High")) return "High";
  if (candidates.some((candidate) => candidate.confidence === "Low")) return "Low";
  return "Medium";
}

function alignmentRange(candidates: CivitasCandidateView[]): string {
  const scores = candidates
    .map((candidate) => candidate.alignmentScore)
    .filter((score): score is number => typeof score === "number")
    .sort((a, b) => a - b);
  if (!scores.length) return "Not scored";
  if (scores.length === 1) return `${scores[0]}%`;
  return `${scores[0]}-${scores[scores.length - 1]}%`;
}

function raceSourceCount(race: Race, candidates: CivitasCandidateView[]): number {
  const urls = new Set<string>();
  for (const url of race.context?.sources ?? []) urls.add(url);
  for (const candidate of candidates) {
    for (const url of sourceUrls(candidate.raw)) urls.add(url);
  }
  return urls.size;
}

function districtSummary(districts?: Partial<Districts>): string {
  const parts = [districts?.cd, districts?.sd, districts?.hd, districts?.county].filter(Boolean);
  return parts.length ? parts.join(" / ") : "Texas ballot";
}

export function buildCivitasDashboard(
  ballot: CivitasBallotLike,
  matches: MatchResult[]
): CivitasDashboardView {
  const matchMap = buildMatchMap(matches);
  const races = ballot.races.map((race) => {
    const candidates = race.candidates.map((candidate) =>
      buildCandidateView(candidate, matchMap.get(normalizeName(candidate.name)))
    );
    return {
      id: race.race_id,
      office: race.office,
      level: race.level,
      location: raceLocation(race),
      candidatesCount: race.candidates.length,
      alignmentRange: alignmentRange(candidates),
      confidence: raceConfidence(candidates),
      status: raceStatus(candidates),
      contextSummary: race.context?.last_result,
      sourceCount: raceSourceCount(race, candidates),
      candidates,
      raw: race,
    };
  });

  const allCandidates = races.flatMap((race) => race.candidates);
  const topCandidates = [...allCandidates]
    .filter((candidate) => typeof candidate.alignmentScore === "number")
    .sort((a, b) => (b.overall ?? b.alignmentScore ?? 0) - (a.overall ?? a.alignmentScore ?? 0))
    .slice(0, 6);

  return {
    location: ballot.matched_address || districtSummary(ballot.districts),
    districtSummary: districtSummary(ballot.districts),
    mode: ballot.mode,
    warning: ballot.warning,
    stats: {
      races: races.length,
      candidates: allCandidates.length,
      scoreableCandidates: allCandidates.filter((candidate) => candidate.match).length,
      limitedRaces: races.filter((race) => race.status !== "Reviewed").length,
    },
    races,
    topCandidates,
  };
}
