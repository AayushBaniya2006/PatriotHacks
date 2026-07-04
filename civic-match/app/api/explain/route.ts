import { NextRequest } from "next/server";
import crypto from "crypto";
import { getPolitician } from "@/lib/db";
import { scoreMatch } from "@/lib/scoring";
import { chat, extractJSON, FAST_MODEL } from "@/lib/llm";
import { getIssueMap } from "@/lib/config";
import { kvGet, kvSet, NS } from "@/lib/store";
import type { UserPreferences } from "@/lib/types";

export const maxDuration = 120;

export interface QualitativeExplanation {
  headline: string; // one neutral sentence characterizing the match
  agreements: string[]; // evidence-grounded reasons, cite issue + evidence type
  conflicts: string[]; // where the user and candidate disagree
  caveat: string; // main caveat (weak evidence, unknowns, contradictions)
  evidence_note: string; // what the evidence is mostly based on + confidence
}

// POST /api/explain { politician_id, prefs }
// Qualitative companion to the quantitative score (PRD section 15).
// Grounded ONLY in the scored breakdown + indexed stance evidence. Cached by
// (politician, prefs-hash) so repeat views are instant.
export async function POST(req: NextRequest) {
  const { politician_id, prefs } = (await req.json()) as {
    politician_id: string;
    prefs: UserPreferences;
  };
  const profile = await getPolitician(politician_id);
  if (!profile) return Response.json({ error: "unknown politician" }, { status: 404 });

  const match = scoreMatch(prefs, profile);

  const hash = crypto
    .createHash("sha1")
    .update(politician_id + JSON.stringify(prefs) + profile.researched_at)
    .digest("hex")
    .slice(0, 16);
  const cached = await kvGet<QualitativeExplanation>(NS.explanations, hash);
  if (cached) {
    return Response.json({ explanation: cached, match, cached: true });
  }

  // Compact, evidence-grounded context for the explainer (minimize context).
  const voter = prefs.profile;
  const voterContext = voter
    ? {
        name: voter.name,
        occupation: voter.occupation,
        age: voter.age_bracket,
        income: voter.income_bracket,
        situation: Object.entries(voter.flags ?? {})
          .filter(([, v]) => v)
          .map(([k, v]) => (k === "healthcare" ? `healthcare: ${v}` : k.replace(/_/g, " "))),
      }
    : null;
  const ctx = {
    politician: `${profile.name} (${profile.party ?? "?"})`,
    voter: voterContext,
    score: match.score,
    confidence: match.confidence,
    // All scored issues (by user weight), with status so the explainer can
    // describe full matches, partial overlaps, and conflicts accurately.
    issues: match.breakdown
      .filter((b) => b.status !== "unknown")
      .slice(0, 8)
      .map((b) => ({
        issue: b.issue_name,
        status: b.status, // match | partial | conflict
        alignment_pct: b.alignment !== null ? Math.round(b.alignment * 100) : null,
        user_wants: describePosition(b.issue_id, b.user_position),
        candidate: b.candidate_label,
        evidence: stanceEvidence(profile, b.issue_id),
      })),
    unknown_issues: match.unknown_issues.map((b) => b.issue_name),
    contradictions: profile.contradictions.map((c) => c.description),
  };

  const out = await chat(
    [
      {
        role: "system",
        content: `You write short, strictly neutral match explanations for a voter-information tool.

HARD GROUNDING RULES:
- Use ONLY the JSON provided. Every bullet must correspond to an entry in the "issues" array — never mention issues that are not listed there.
- Respect each entry's "status": put match/partial entries in "agreements" (say "partially aligns" for partial), conflict entries in "conflicts".
- Describe the user's view ONLY as stated in "user_wants". Never attribute any other preference to the user.
- Candidate claims must come from the "evidence" fields provided.
- If there are no entries with status match or partial, say there were no strong evidence-backed agreements.

STYLE RULES: no persuasion, no telling the user how to vote, no emotional language. Characterize matches as "based on your stated priorities". Mention evidence types (voting record vs campaign platform vs statement). Always include the main caveat honestly.

If voter context is provided (occupation, situation), you may note where a listed issue concretely intersects their stated situation (e.g. a renter and housing policy) — factual intersections only, never emotional appeals, never demographic generalizations, never "people like you should".`,
      },
      {
        role: "user",
        content: `Write the qualitative explanation for this match result. Return ONLY JSON:
{"headline": "one neutral sentence", "agreements": ["2-4 short evidence-grounded bullets"], "conflicts": ["1-3 bullets, empty array if none"], "caveat": "main caveat in one sentence", "evidence_note": "one sentence: what the evidence mostly is and how confident"}

${JSON.stringify(ctx)}`,
      },
    ],
    { model: FAST_MODEL, maxTokens: 900, timeoutMs: 60_000 }
  );

  let explanation: QualitativeExplanation;
  try {
    explanation = extractJSON<QualitativeExplanation>(out);
  } catch {
    // Deterministic fallback — still qualitative, still honest.
    explanation = {
      headline: `${profile.name} aligns with ${match.score}% of your weighted priorities (${match.confidence.toLowerCase()} confidence).`,
      agreements: match.top_agreements.map(
        (b) => `${b.issue_name}: candidate position — ${b.candidate_label}`
      ),
      conflicts: match.top_conflicts.map(
        (b) => `${b.issue_name}: candidate position — ${b.candidate_label}`
      ),
      caveat:
        match.unknown_issues.length > 0
          ? `No reliable evidence found on: ${match.unknown_issues
              .map((b) => b.issue_name)
              .join(", ")}.`
          : "Evidence coverage is good across your priorities.",
      evidence_note: `Based on ${profile.stances.length} sourced positions.`,
    };
  }

  await kvSet(NS.explanations, hash, explanation);
  return Response.json({ explanation, match, cached: false });
}

function describePosition(issueId: string, pos: number | null): string {
  const issue = getIssueMap()[issueId];
  if (!issue || pos === null) return "no stated preference";
  const opt = issue.options.reduce((best, o) =>
    Math.abs(o.scalar - pos) < Math.abs(best.scalar - pos) ? o : best
  );
  return opt.label;
}

function stanceEvidence(profile: NonNullable<Awaited<ReturnType<typeof getPolitician>>>, issueId: string) {
  const s = profile.stances.find((s) => s.issue_id === issueId);
  if (!s) return null;
  return {
    summary: s.summary,
    type: s.evidence_type,
    confidence: s.confidence,
    sources: s.sources.map((src) => `${src.title} (${src.publisher})`),
  };
}
