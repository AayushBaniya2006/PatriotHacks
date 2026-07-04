import { NextRequest } from "next/server";
import { getPolitician } from "@/lib/db";
import { scoreMatch } from "@/lib/scoring";
import type { UserPreferences } from "@/lib/types";

// POST /api/match { prefs: UserPreferences, politician_ids: string[] }
// Pure computation over cached profiles — returns in milliseconds.
export async function POST(req: NextRequest) {
  const { prefs, politician_ids } = (await req.json()) as {
    prefs: UserPreferences;
    politician_ids: string[];
  };
  if (!prefs || !Array.isArray(politician_ids)) {
    return Response.json({ error: "prefs and politician_ids required" }, { status: 400 });
  }
  // Sanitize: weights/positions must be finite numbers in [0,1]-ish ranges
  prefs.priority_weights = Object.fromEntries(
    Object.entries(prefs.priority_weights ?? {})
      .filter(([, w]) => Number.isFinite(w) && (w as number) > 0)
      .map(([k, w]) => [k, Math.min(2, w as number)])
  );
  prefs.issue_positions = Object.fromEntries(
    Object.entries(prefs.issue_positions ?? {}).map(([k, v]) => [
      k,
      v === null || !Number.isFinite(v) ? null : Math.max(0, Math.min(1, v as number)),
    ])
  );
  const results = [];
  for (const id of politician_ids) {
    const profile = await getPolitician(id);
    if (profile) results.push(scoreMatch(prefs, profile));
  }
  // Scored candidates first (by overall); insufficient-data candidates sort
  // last so an unresearched profile never outranks a researched one — its
  // neutral qualitative midpoint would otherwise beat real-but-imperfect scores.
  results.sort((a, b) => {
    if (a.insufficient_data !== b.insufficient_data)
      return a.insufficient_data ? 1 : -1;
    if (a.insufficient_data)
      return b.coverage.scored_issues - a.coverage.scored_issues;
    return b.overall - a.overall;
  });
  return Response.json({ results });
}
