// Stakes agent: per race, ground-truth facts that make non-voting concrete —
// last margin, turnout, and what gets decided with or without you.
// Usage: npx tsx scripts/seed-stakes.ts [state]
import { config } from "dotenv";
config({ path: ".env.local" });

import { promises as fs } from "fs";
import path from "path";
import { getCachedElection } from "../lib/discovery";
import { chat, extractJSON, RESEARCH_MODEL } from "../lib/llm";

async function main() {
  const state = process.argv[2] || "texas";
  const races = (await getCachedElection(state)) ?? [];
  const results = await Promise.all(
    races.map(async (r) => {
      try {
        const out = await chat(
          [
            {
              role: "user",
              content: `Use web search to find turnout stakes for this race: "${r.race}" (${state}, next election ${r.election_date}).

Find with real sources:
1. The margin (votes and %) in the most recent comparable election for this office.
2. Turnout % in that election (and among registered under-30 voters if available).
3. 2-3 concrete powers this office controls that get decided regardless of turnout (appointments, vetoes, budgets, law enforcement priorities).

Return ONLY JSON:
{"race": "${r.race}", "last_margin": {"summary": "decided by X votes (Y%) in ZZZZ", "source": {"title","url","publisher"}}, "turnout": {"summary": "only X% of registered voters voted in ZZZZ", "source": {"title","url","publisher"}}, "decided_anyway": [{"text": "this office will still appoint/veto/control ...", "source": {"title","url","publisher"}}]}

Rules: every item needs a real source URL or omit it. Neutral tone: motivate participation, never a candidate.`,
            },
          ],
          { model: RESEARCH_MODEL, maxTokens: 3072, timeoutMs: 150_000 }
        );
        const parsed = extractJSON<Record<string, unknown>>(out);
        console.log(`[done] ${r.race}`);
        return parsed;
      } catch (e) {
        console.error(`[fail] ${r.race}:`, e instanceof Error ? e.message : e);
        return null;
      }
    })
  );
  const stakes = results.filter(Boolean);
  const file = path.join(process.cwd(), "data", "elections", `${state}-stakes.json`);
  await fs.writeFile(file, JSON.stringify(stakes, null, 2));
  console.log(`Saved ${stakes.length} race stakes → ${file}`);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
