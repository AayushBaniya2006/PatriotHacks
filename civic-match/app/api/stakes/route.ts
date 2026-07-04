import { NextRequest } from "next/server";
import { promises as fs } from "fs";
import path from "path";
import { getUI } from "@/lib/config";

export interface RaceStakes {
  race: string;
  last_margin?: { summary: string; source: { title: string; url: string; publisher?: string } };
  turnout?: { summary: string; source: { title: string; url: string; publisher?: string } };
  decided_anyway?: { text: string; source: { title: string; url: string; publisher?: string } }[];
}

// GET /api/stakes?state=texas — sourced "what happens with or without you" facts
export async function GET(req: NextRequest) {
  const state = req.nextUrl.searchParams.get("state") || getUI().default_state;
  try {
    const raw = await fs.readFile(
      path.join(process.cwd(), "data", "elections", `${state}-stakes.json`),
      "utf-8"
    );
    return Response.json({ state, stakes: JSON.parse(raw) as RaceStakes[] });
  } catch {
    return Response.json({ state, stakes: [] });
  }
}
