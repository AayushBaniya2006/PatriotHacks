// Election discovery agent: auto-query upcoming November elections for a state.
// Results cached to data/elections/<state>.json for latency.
import { promises as fs } from "fs";
import path from "path";
import { chat, extractJSON, RESEARCH_MODEL } from "./llm";

export interface DiscoveredRace {
  race: string; // e.g. "Texas Governor"
  office: string;
  election_date: string;
  candidates: { name: string; party: string }[];
}

const ELECTIONS_DIR = path.join(process.cwd(), "data", "elections");

export async function getCachedElection(state: string): Promise<DiscoveredRace[] | null> {
  try {
    const raw = await fs.readFile(
      path.join(ELECTIONS_DIR, `${state.toLowerCase()}.json`),
      "utf-8"
    );
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

export async function discoverElection(state: string): Promise<DiscoveredRace[]> {
  const cached = await getCachedElection(state);
  if (cached) return cached;

  const out = await chat(
    [
      {
        role: "user",
        content: `Use web search to find the major statewide and federal races on the ballot in ${state} for the upcoming November 2026 general election. Include U.S. Senate, Governor, and other statewide offices if on the ballot, plus their currently declared major-party candidates (post-primary nominees if primaries are done).

Return ONLY a JSON array:
[{"race": "...", "office": "...", "election_date": "YYYY-MM-DD", "candidates": [{"name": "...", "party": "..."}]}]

Only include candidates you can verify are actually running. Limit to the 4 most prominent races.`,
      },
    ],
    { model: RESEARCH_MODEL, maxTokens: 4096, timeoutMs: 150_000 }
  );
  const races = extractJSON<DiscoveredRace[]>(out);
  await fs.mkdir(ELECTIONS_DIR, { recursive: true });
  await fs.writeFile(
    path.join(ELECTIONS_DIR, `${state.toLowerCase()}.json`),
    JSON.stringify(races, null, 2)
  );
  return races;
}
