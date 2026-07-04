// Data-coverage helper: how much verifiable research a profile actually has.
// Used by scoring, LLM routes, and UI so sparse profiles degrade honestly
// ("insufficient data") instead of rendering as confident zeros.
import type { PoliticianProfile } from "./types";

export interface ProfileCoverage {
  stances: number; // sourced issue stances
  qual: number; // qualitative dimensions researched
  promises: number; // promise/record pairs
  finance: boolean; // any sourced finance data (donors, totals, correlations)
  researched: boolean; // did the research swarm find ANY verifiable evidence
  tier: "full" | "partial" | "minimal";
}

// Thresholds (issue taxonomy is 30 issues):
// full    = broad stance coverage + character record researched
// partial = some sourced stances to reason from
// minimal = essentially nothing verifiable — treat as "research pending"
export const FULL_STANCES = 12;
export const PARTIAL_STANCES = 4;

export function profileCoverage(profile: PoliticianProfile): ProfileCoverage {
  const stances = profile.stances.length;
  const qual = (profile.qualitative ?? []).length;
  const promises = (profile.promise_record ?? []).length;
  const f = profile.finance;
  const finance = !!(
    f &&
    (f.top_donors.length > 0 || f.correlations.length > 0 || f.total_raised)
  );
  const researched = stances > 0 || qual > 0 || promises > 0 || finance;
  const tier: ProfileCoverage["tier"] =
    stances >= FULL_STANCES && qual > 0
      ? "full"
      : stances >= PARTIAL_STANCES
      ? "partial"
      : "minimal";
  return { stances, qual, promises, finance, researched, tier };
}

/** Human-readable list of what's missing — for LLM prompts and UI captions. */
export function missingDataNote(cov: ProfileCoverage): string[] {
  const missing: string[] = [];
  if (cov.stances === 0) missing.push("issue positions");
  if (cov.qual === 0) missing.push("record quality (integrity/transparency/experience)");
  if (cov.promises === 0) missing.push("promise-vs-record scorecard");
  if (!cov.finance) missing.push("campaign finance");
  return missing;
}
