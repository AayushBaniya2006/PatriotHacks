import { NextRequest } from "next/server";
import { getCachedElection, discoverElection } from "@/lib/discovery";

export const maxDuration = 300;

// GET /api/election?state=texas — cached read (fast path)
export async function GET(req: NextRequest) {
  const state = req.nextUrl.searchParams.get("state") || "texas";
  const cached = await getCachedElection(state);
  return Response.json({ state, races: cached ?? [], cached: !!cached });
}

// POST /api/election { state } — force discovery (slow path, agent w/ web search)
export async function POST(req: NextRequest) {
  const { state = "texas" } = await req.json().catch(() => ({}));
  try {
    const races = await discoverElection(state);
    return Response.json({ state, races });
  } catch (err) {
    return Response.json(
      { error: err instanceof Error ? err.message : "discovery failed" },
      { status: 500 }
    );
  }
}
