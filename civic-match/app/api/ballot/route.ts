import { NextRequest } from "next/server";
import { getCachedElection } from "@/lib/discovery";
import { getUI } from "@/lib/config";
import { slugify } from "@/lib/db";
import { getBallot } from "@/lib/dataBackend";

export const maxDuration = 60;

function fallbackRaceId(title: string) {
  const lower = title.toLowerCase();
  if (lower.includes("lieutenant governor")) return "tx-ltgov-2026";
  if (lower.includes("attorney general")) return "tx-ag-2026";
  if (lower.includes("u.s. senate") || lower.includes("us senate") || lower.includes("united states senate")) {
    return "tx-sen-2026";
  }
  if (lower.includes("governor")) return "tx-gov-2026";
  if (lower.includes("comptroller")) return "tx-comptroller-2026";
  if (lower.includes("land commissioner")) return "tx-landcomm-2026";
  if (lower.includes("agriculture commissioner")) return "tx-agcomm-2026";
  if (lower.includes("railroad commissioner")) return "tx-railroad-2026";
  return `fallback-${slugify(title)}`;
}

function fallbackLevel(title: string) {
  return /u\.?s\.?|united states|congress|house|senate/i.test(title) ? "federal" : "state";
}

// GET /api/ballot?address=... — resolves via the FastAPI data backend
// (Census geocoder → districts → races). Falls back to the cached statewide
// election if the backend is unreachable.
export async function GET(req: NextRequest) {
  const address = req.nextUrl.searchParams.get("address");
  if (!address) return Response.json({ error: "address required" }, { status: 400 });

  const result = await getBallot(address);
  if (result.ok) {
    return Response.json({ mode: "resolved", ...result.data });
  }

  if (result.status === 400 || result.status === 422) {
    return Response.json({ error: result.reason }, { status: result.status });
  }

  // Fallback: statewide races (ground truth still applies; we just can't
  // narrow to the district level without the resolver).
  const races = ((await getCachedElection(getUI().default_state)) ?? []).map((race) => {
    const title = race.office || race.race;
    return {
      race_id: fallbackRaceId(title),
      race: race.race,
      office: race.office,
      level: fallbackLevel(title),
      district: null,
      election_date: race.election_date,
      context: { sources: [] },
      candidates: (race.candidates ?? []).map((candidate) => ({
        candidate_id: slugify(candidate.name),
        name: candidate.name,
        party: candidate.party,
        incumbent: null,
      })),
    };
  });
  return Response.json({
    mode: "statewide_fallback",
    matched_address: address,
    districts: { cd: null, sd: null, hd: null, county: null },
    warning:
      "District resolver unavailable — showing statewide races for your state only.",
    races,
  });
}
