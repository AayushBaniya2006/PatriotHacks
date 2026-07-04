// Election discovery agent: auto-query upcoming November elections for a state.
// Results cached in Postgres (namespace "elections", key = state) for latency.
import { chat, extractJSON, RESEARCH_MODEL } from "./llm";
import { kvGet, kvSet, NS } from "./store";

export interface DiscoveredRace {
  race: string; // e.g. "Texas Governor"
  office: string;
  election_date: string;
  candidates: { name: string; party: string }[];
}

export async function getCachedElection(state: string): Promise<DiscoveredRace[] | null> {
  return kvGet<DiscoveredRace[]>(NS.elections, state.toLowerCase());
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
  await kvSet(NS.elections, state.toLowerCase(), races);
  return races;
}
