import { NextRequest } from "next/server";
import { mapVoterProfileToBackend, postInsights } from "@/lib/dataBackend";
import type { VoterProfile } from "@/lib/types";

// POST /api/voter-insights { profile?: VoterProfile, race_id: string }
// Adapts the teammate's intake VoterProfile shape (lib/types.ts) to our data
// backend's contract profile fields, then thinly proxies POST /api/insights.
// Same-origin only — the browser never talks to the data backend directly.
export async function POST(req: NextRequest) {
  let body: { profile?: VoterProfile; race_id?: string };
  try {
    body = await req.json();
  } catch {
    return Response.json({ error: "Invalid JSON body" }, { status: 400 });
  }

  const raceId = body.race_id;
  if (!raceId) {
    return Response.json({ error: "race_id is required" }, { status: 400 });
  }

  const backendProfile = mapVoterProfileToBackend(body.profile);
  const result = await postInsights(backendProfile, raceId);
  if (!result.ok) {
    return Response.json({ error: result.reason }, { status: result.status ?? 502 });
  }
  return Response.json(result.data);
}
