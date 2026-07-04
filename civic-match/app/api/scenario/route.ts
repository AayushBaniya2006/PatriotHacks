import { NextRequest } from "next/server";
import { getScenario } from "@/lib/scenario";
import { getCachedElection } from "@/lib/discovery";
import { slugify } from "@/lib/db";
import { getUI } from "@/lib/config";

// GET /api/scenario?race=<race-slug> | no param → list available trees
export async function GET(req: NextRequest) {
  const raceSlug = req.nextUrl.searchParams.get("race");
  if (!raceSlug) {
    const races = (await getCachedElection(getUI().default_state)) ?? [];
    const available = [];
    for (const r of races) {
      const slug = slugify(r.race);
      if (await getScenario(slug)) available.push({ race: r.race, slug });
    }
    return Response.json({ available });
  }
  const tree = await getScenario(raceSlug);
  if (!tree) return Response.json({ error: "no scenario tree for this race" }, { status: 404 });
  return Response.json(tree);
}
