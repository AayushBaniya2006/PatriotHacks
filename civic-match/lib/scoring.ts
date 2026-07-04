// Explainable match scoring (PRD 8.3).
// score = Σ(issue_weight × stance_alignment × evidence_confidence × recency_adjustment × source_quality)
// normalized against the maximum achievable given the user's weights.

import { getIssueMap, getUI } from "./config";
import { profileCoverage } from "./coverage";
import type {
  IssueScoreBreakdown,
  MatchResult,
  PoliticianProfile,
  Stance,
  UserPreferences,
} from "./types";

type LegacyUserPreferences = UserPreferences & {
  issue_stances?: Record<string, number | null>;
};

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
  const ISSUE_MAP = getIssueMap();
  const breakdown: IssueScoreBreakdown[] = [];
  const issuePositions =
    prefs.issue_positions ?? (prefs as LegacyUserPreferences).issue_stances ?? {};

  const weightEntries = Object.entries(prefs.priority_weights ?? {}).filter(
    ([, w]) => w > 0
  );
  const totalWeight = weightEntries.reduce((s, [, w]) => s + w, 0) || 1;

  for (const [issueId, rawWeight] of weightEntries) {
    const issue = ISSUE_MAP[issueId];
    if (!issue) continue;
    const weight = rawWeight / totalWeight;
    const userPos = issuePositions[issueId] ?? null;
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

  // ---- Honest coverage: don't let a thin profile masquerade as a scored one.
  // A candidate scored on fewer than MIN_SCORED of the user's issues (or fewer
  // than the user picked, whichever is smaller) gets an explicit
  // insufficient-data state instead of a confident-looking number.
  const cov = profileCoverage(profile);
  const MIN_SCORED = 3;
  const insufficientData =
    known.length === 0 || known.length < Math.min(MIN_SCORED, breakdown.length);

  const topConflicts = byImpact(sorted.filter((b) => b.status === "conflict")).slice(0, 5);

  // ---- Qualitative composite (character): corruption/ethics, public interest,
  // transparency, experience — independent of the user's issue positions. ----
  const QUAL_LABELS = getUI().qualitative_labels;
  const qualDims = (profile.qualitative ?? []).filter(
    (d) => typeof d.score === "number"
  );
  const qualWeightSum = qualDims.reduce((s, d) => s + d.confidence, 0);
  const qualComposite =
    qualDims.length > 0 && qualWeightSum > 0
      ? qualDims.reduce((s, d) => s + d.score * d.confidence, 0) / qualWeightSum
      : null;

  // ---- 2K-style OVERALL (60 = worst, 99 = best) ----
  // Quantitative issue alignment (taxes, economy, ...) + qualitative character
  // (corruption, public interest, ...) − penalty for conflicts on the user's
  // highest-weight issues. Fully decomposed — never a black box.
  const quant = score / 100;
  const qual = qualComposite ?? 0.5; // neutral midpoint when not yet researched
  const alignmentComponent = 0.6 * quant;
  const qualitativeComponent = 0.4 * qual;
  const conflictWeight = topConflicts.reduce((s, b) => s + b.weight, 0);
  const conflictPenalty = Math.min(0.15, conflictWeight * 0.25);
  const blended = Math.max(0, alignmentComponent + qualitativeComponent - conflictPenalty);
  const overall = Math.round(60 + 39 * blended); // 60..99
  const overallTier = insufficientData
    ? "Insufficient data"
    : getUI().results.tiers.find((t) => overall >= t.min)?.label ?? "Match";

  // Ground-truth-backed warnings
  const warnings: string[] = [];
  const broken = (profile.promise_record ?? []).filter((r) => r.verdict === "broken").length;
  if (broken > 0) warnings.push(`${broken} documented broken promise${broken > 1 ? "s" : ""} (see scorecard)`);
  const integrity = (profile.qualitative ?? []).find((d) => d.id === "integrity");
  if (integrity && integrity.score < 0.45)
    warnings.push("Documented integrity concerns (sourced in record quality)");
  if (profile.contradictions.length > 0)
    warnings.push(`${profile.contradictions.length} contradiction${profile.contradictions.length > 1 ? "s" : ""} between statements and actions`);

  return {
    politician_id: profile.id,
    politician_name: profile.name,
    party: profile.party,
    score,
    confidence,
    confidence_value: confidenceValue,
    insufficient_data: insufficientData,
    coverage: {
      scored_issues: known.length,
      user_issues: breakdown.length,
      profile_stances: cov.stances,
      tier: cov.tier,
    },
    warnings,
    overall,
    overall_tier: overallTier,
    overall_components: {
      alignment_component: Math.round(39 * alignmentComponent),
      qualitative_component: Math.round(39 * qualitativeComponent),
      conflict_penalty: Math.round(39 * conflictPenalty),
    },
    qualitative_composite: qualComposite,
    qualitative: qualDims.map((d) => ({
      id: d.id,
      label: QUAL_LABELS[d.id] ?? d.id,
      score: d.score,
      summary: d.summary,
      confidence: d.confidence,
    })),
    breakdown: byImpact(breakdown),
    top_agreements: byImpact(sorted.filter((b) => b.status === "match")).slice(0, 5),
    top_conflicts: topConflicts,
    unknown_issues: breakdown.filter((b) => b.status === "unknown"),
  };
}
