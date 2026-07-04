import { NextRequest } from "next/server";
import { getCachedElection } from "@/lib/discovery";
import { getUI } from "@/lib/config";

export const maxDuration = 60;

// GET /api/ballot?address=... — resolves via the FastAPI data backend
// (Census geocoder → districts → races). Falls back to the cached statewide
// election if the backend is unreachable.
export async function GET(req: NextRequest) {
  const address = req.nextUrl.searchParams.get("address");
  if (!address) return Response.json({ error: "address required" }, { status: 400 });

  const backend =
    process.env.DATA_BACKEND_URL || process.env.BALLOT_BACKEND_URL || "http://localhost:8000";
  try {
    const res = await fetch(`${backend}/api/ballot?address=${encodeURIComponent(address)}`, {
      signal: AbortSignal.timeout(15_000),
    });
    if (res.ok) {
      const data = await res.json();
      return Response.json({ mode: "resolved", ...data });
    }
    if (res.status === 400 || res.status === 422) {
      return Response.json(await res.json(), { status: res.status });
    }
    throw new Error(`backend ${res.status}`);
  } catch {
    // Fallback: statewide races (ground truth still applies; we just can't
    // narrow to the district level without the resolver).
    const races = (await getCachedElection(getUI().default_state)) ?? [];
    return Response.json({
      mode: "statewide_fallback",
      warning:
        "District resolver unavailable — showing statewide races for your state only.",
      races,
    });
  }
}
