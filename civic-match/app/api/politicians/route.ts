import { listPoliticians } from "@/lib/db";

export async function GET() {
  const profiles = await listPoliticians();
  return Response.json(
    profiles.map((p) => ({
      id: p.id,
      name: p.name,
      party: p.party,
      current_office: p.current_office,
      jurisdiction: p.jurisdiction,
      source_coverage_score: p.source_coverage_score,
      stance_count: p.stances.length,
      researched_at: p.researched_at,
    }))
  );
}
