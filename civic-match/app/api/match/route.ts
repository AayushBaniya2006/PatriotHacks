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
  const results = [];
  for (const id of politician_ids) {
    const profile = await getPolitician(id);
    if (profile) results.push(scoreMatch(prefs, profile));
  }
  results.sort((a, b) => b.overall - a.overall);
  return Response.json({ results });
}
