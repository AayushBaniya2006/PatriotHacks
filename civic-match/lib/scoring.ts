// Explainable match scoring (PRD 8.3).
// score = Σ(issue_weight × stance_alignment × evidence_confidence × recency_adjustment × source_quality)
// normalized against the maximum achievable given the user's weights.

import { ISSUE_MAP } from "./issues";
import type {
  IssueScoreBreakdown,
  MatchResult,
  PoliticianProfile,
  Stance,
  UserPreferences,
} from "./types";

const SOURCE_QUALITY: Record<string, number> = {
  voting_record: 1.0,
  sponsored_bill: 1.0,
  campaign_finance: 0.95,
  official_platform: 0.9,
  debate_transcript: 0.85,
  questionnaire: 0.85,
  public_statement: 0.8,
  interview: 0.8,
  news_report: 0.65,
  other: 0.5,
};

function recencyAdjustment(recency?: string): number {
  if (!recency) return 0.85;
  const ageYears =
    (Date.now() - new Date(recency).getTime()) / (365.25 * 24 * 3600 * 1000);
  if (Number.isNaN(ageYears)) return 0.85;
  if (ageYears <= 1) return 1.0;
  if (ageYears <= 3) return 0.92;
  if (ageYears <= 6) return 0.8;
  return 0.7;
}

function stanceFor(profile: PoliticianProfile, issueId: string): Stance | undefined {
  return profile.stances.find((s) => s.issue_id === issueId);
}

export function scoreMatch(
  prefs: UserPreferences,
  profile: PoliticianProfile
): MatchResult {
  const breakdown: IssueScoreBreakdown[] = [];

  const weightEntries = Object.entries(prefs.priority_weights).filter(
    ([, w]) => w > 0
  );
  const totalWeight = weightEntries.reduce((s, [, w]) => s + w, 0) || 1;

  for (const [issueId, rawWeight] of weightEntries) {
    const issue = ISSUE_MAP[issueId];
    if (!issue) continue;
    const weight = rawWeight / totalWeight;
    const userPos = prefs.issue_positions[issueId] ?? null;
    const stance = stanceFor(profile, issueId);

    if (userPos === null || !stance || stance.position_scalar === null) {
      breakdown.push({
        issue_id: issueId,
        issue_name: issue.name,
        user_position: userPos,
        candidate_position: stance?.position_scalar ?? null,
        candidate_label: stance?.position_label,
        alignment: null,
        weight,
        evidence_confidence: stance?.confidence ?? 0,
        source_quality: 0,
        recency_adjustment: 1,
        points: 0,
        max_points: weight,
        status: "unknown",
      });
      continue;
    }

    const alignment = 1 - Math.abs(userPos - stance.position_scalar); // 0..1
    const sourceQuality = Math.max(
      ...stance.sources.map((s) => SOURCE_QUALITY[s.type] ?? 0.5),
      SOURCE_QUALITY[stance.evidence_type] ?? 0.5
    );
    const recency = recencyAdjustment(stance.recency);
    const points = weight * alignment * stance.confidence * recency * sourceQuality;
    const maxPoints = weight * stance.confidence * recency * sourceQuality;

    breakdown.push({
      issue_id: issueId,
      issue_name: issue.name,
      user_position: userPos,
      candidate_position: stance.position_scalar,
      candidate_label: stance.position_label,
      alignment,
      weight,
      evidence_confidence: stance.confidence,
      source_quality: sourceQuality,
      recency_adjustment: recency,
      points,
      max_points: maxPoints,
      status: alignment >= 0.7 ? "match" : alignment >= 0.4 ? "partial" : "conflict",
    });
  }

  // Alignment score: earned points over max achievable points on issues with
  // evidence. Unknown issues do NOT inflate or deflate alignment — they lower
  // confidence instead (PRD sharp decision #3).
  const known = breakdown.filter((b) => b.alignment !== null);
  const earned = known.reduce((s, b) => s + b.points, 0);
  const possible = known.reduce((s, b) => s + b.max_points, 0);
  const score = possible > 0 ? Math.round((earned / possible) * 100) : 0;

  // Confidence: how much of the user's weighted priorities are covered by
  // evidence, scaled by that evidence's confidence and quality.
  const coverage = known.reduce(
    (s, b) => s + b.weight * b.evidence_confidence * b.source_quality,
    0
  );
  const confidenceValue = Math.min(1, coverage);
  const confidence =
    confidenceValue >= 0.65 ? "High" : confidenceValue >= 0.35 ? "Medium" : "Low";

  const sorted = [...known].sort((a, b) => (b.alignment ?? 0) - (a.alignment ?? 0));
  const byImpact = (arr: IssueScoreBreakdown[]) =>
    [...arr].sort((a, b) => b.weight - a.weight);

  const topConflicts = byImpact(sorted.filter((b) => b.status === "conflict")).slice(0, 5);

  // ---- 2K-style OVERALL (60 = worst, 99 = best) ----
  // Blends the quantitative alignment score with the qualitative evidence
  // confidence, minus a penalty for conflicts on the user's highest-weight
  // issues. Fully decomposed so it is never a black box.
  const quant = score / 100; // quantitative alignment 0..1
  const qual = confidenceValue; // qualitative evidence coverage/quality 0..1
  const conflictWeight = topConflicts.reduce((s, b) => s + b.weight, 0); // 0..1
  const alignmentComponent = 0.65 * quant;
  const evidenceComponent = 0.35 * qual;
  const conflictPenalty = Math.min(0.15, conflictWeight * 0.25);
  const blended = Math.max(0, alignmentComponent + evidenceComponent - conflictPenalty);
  const overall = Math.round(60 + 39 * blended); // 60..99
  const overallTier =
    overall >= 90 ? "Elite match"
    : overall >= 83 ? "Strong match"
    : overall >= 75 ? "Solid match"
    : overall >= 68 ? "Weak match"
    : "Poor match";

  return {
    politician_id: profile.id,
    politician_name: profile.name,
    party: profile.party,
    score,
    confidence,
    confidence_value: confidenceValue,
    overall,
    overall_tier: overallTier,
    overall_components: {
      alignment_component: Math.round(39 * alignmentComponent),
      evidence_component: Math.round(39 * evidenceComponent),
      conflict_penalty: Math.round(39 * conflictPenalty),
    },
    breakdown: byImpact(breakdown),
    top_agreements: byImpact(sorted.filter((b) => b.status === "match")).slice(0, 5),
    top_conflicts: topConflicts,
    unknown_issues: breakdown.filter((b) => b.status === "unknown"),
  };
}
