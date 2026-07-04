import { NextRequest } from "next/server";
import { getPolitician, slugify } from "@/lib/db";
import { profileCoverage } from "@/lib/coverage";

export const maxDuration = 30;

// GET /api/check-research/:id - checks if politician needs research
export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const profile = await getPolitician(id);
  
  if (!profile) {
    return Response.json({ needs_research: true, reason: "not_found" });
  }
  
  const cov = profileCoverage(profile);
  
  // Needs research if:
  // 1. Less than 8 stances (our "well-researched" threshold)
  // 2. Missing qualitative dimensions
  // 3. Tier is "minimal" (not full coverage)
  const needsResearch = 
    profile.stances.length < 8 ||
    !profile.qualitative ||
    profile.qualitative.length < 3 ||
    cov.tier === "minimal";
  
  return Response.json({
    needs_research: needsResearch,
    current_stances: profile.stances.length,
    current_qualitative: profile.qualitative?.length || 0,
    coverage_tier: cov.tier,
    researched_at: profile.researched_at,
  });
}
