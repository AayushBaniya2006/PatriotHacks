import { NextRequest } from "next/server";
import crypto from "crypto";
import { promises as fs } from "fs";
import path from "path";
import { chat, extractJSON, FAST_MODEL } from "@/lib/llm";
import { getIssueMap, getUI } from "@/lib/config";
import { listPoliticians } from "@/lib/db";
import { getCachedElection } from "@/lib/discovery";
import { getScenario } from "@/lib/scenario";
import { slugify } from "@/lib/db";
import { kvGet, kvSet, NS } from "@/lib/store";
import type { ScenarioNode, UserPreferences } from "@/lib/types";

export const maxDuration = 120;

export interface Motivation {
  hook: string; // one sharp, personal line
  because: { text: string; source?: { title: string; url: string } }[]; // "you should vote because ..."
  if_you_vote: string; // what your vote concretely decides
  long_term: string; // the down-the-line consequence chain touching their priorities
  cta: string; // nonpartisan call to action
}

// POST /api/motivate { prefs } — personalized, nonpartisan "your vote matters"
// arc: hook → information → call to action. Motivates VOTING, never a candidate.
export async function POST(req: NextRequest) {
  const { prefs } = (await req.json()) as { prefs: UserPreferences };
  if (!prefs?.priority_weights) {
    return Response.json({ error: "prefs required" }, { status: 400 });
  }

  // Cache key includes a data version so re-researched profiles invalidate cards.
  const allProfiles = await listPoliticians();
  const dataVersion = allProfiles.map((p) => p.researched_at).sort().at(-1) ?? "0";
  const hash = crypto.createHash("sha1").update(JSON.stringify(prefs) + dataVersion).digest("hex").slice(0, 16);
  const cachedMotivation = await kvGet<Motivation>(NS.motivations, hash);
  if (cachedMotivation) {
    return Response.json({ motivation: cachedMotivation, cached: true });
  }

  const ISSUE_MAP = getIssueMap();
  const state = getUI().default_state;
  const topIssues = Object.entries(prefs.priority_weights)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 4)
    .map(([id]) => id);

  // Candidate divergence on the user's top issues (why the outcome differs)
  const politicians = allProfiles;
  const divergence = topIssues.map((issueId) => {
    const positions = politicians
      .map((p) => {
        const s = p.stances.find((s) => s.issue_id === issueId);
        return s && s.position_scalar !== null
          ? { name: p.name, label: s.position_label, scalar: s.position_scalar, source: s.sources[0] ? { title: s.sources[0].title, url: s.sources[0].url } : undefined }
          : null;
      })
      .filter(Boolean) as { name: string; label: string; scalar: number; source?: { title: string; url: string } }[];
    const spread = positions.length > 1
      ? Math.max(...positions.map((p) => p.scalar)) - Math.min(...positions.map((p) => p.scalar))
      : 0;
    return { issue: ISSUE_MAP[issueId]?.name ?? issueId, spread: Math.round(spread * 100), extremes: [positions[0], positions[positions.length - 1]].filter(Boolean) };
  });

  // Stakes (margins/turnout) + scenario branches touching their priorities
  let stakes: unknown = [];
  try {
    stakes = JSON.parse(await fs.readFile(path.join(process.cwd(), "data", "elections", `${state}-stakes.json`), "utf-8"));
  } catch { /* none */ }

  const races = (await getCachedElection(state)) ?? [];
  const flags = prefs.profile?.flags ?? {};
  const relevantBranches: { race: string; label: string; description: string; timeframe: string }[] = [];
  for (const r of races.slice(0, 4)) {
    const tree = await getScenario(slugify(r.race));
    if (!tree) continue;
    const walk = (n: ScenarioNode) => {
      const touches =
        (n.issue_ids ?? []).some((id) => topIssues.includes(id)) ||
        (n.affected_groups ?? []).some((f) => f === flags.healthcare || flags[f as keyof typeof flags] === true);
      if (touches) relevantBranches.push({ race: r.race, label: n.label, description: n.description, timeframe: n.timeframe });
      n.children.forEach(walk);
    };
    walk(tree.root);
  }

  const voter = prefs.profile;

  // Deterministic card (also the parse-failure fallback). Only sourced-data
  // claims; used directly — without an LLM call — when the data set has
  // nothing personal to ground on (no divergence, no stakes, no branches).
  const fallback: Motivation = {
    hook: "This ballot gets decided with or without you — the only variable is who decides.",
    because: divergence
      .filter((d) => d.spread > 30)
      .slice(0, 3)
      .map((d) => ({ text: `The candidates are ${d.spread} points apart on ${d.issue} — one of your top priorities.` })),
    if_you_vote: "Recent statewide races here have been decided by single-digit margins. Your vote weighs directly in every race on this ballot.",
    long_term: "Winners control appointments, budgets, and vetoes for years — and shape who runs for what next. See the down-the-line tree for the full chain.",
    cta: "Election day is November 3, 2026. Check your registration and make a plan to vote.",
  };

  const hasDivergence = divergence.some((d) => d.extremes.length > 0);
  const hasStakes = Array.isArray(stakes)
    ? stakes.length > 0
    : !!stakes && Object.keys(stakes as object).length > 0;
  if (!hasDivergence && !hasStakes && relevantBranches.length === 0) {
    return Response.json({ motivation: fallback, cached: false, grounding: "minimal" });
  }

  let motivation: Motivation;
  try {
    const out = await chat(
      [
        {
          role: "system",
          content: `You write personalized, NONPARTISAN voter-motivation cards for a ground-truth voter tool. You motivate the act of VOTING — never a candidate, party, or position. Use ONLY the provided JSON. Facts must carry their provided sources. Tone: direct, concrete, urgent but honest. Address the voter directly${voter?.name ? ` by name (${voter.name})` : ""}. Tie stakes to their stated priorities and situation.

FORBIDDEN: inventing adversaries or motives ("X is counting on you to stay home"), emotional manipulation, fear appeals beyond documented facts, any claim not present in the data. Urgency must come from real numbers: margins, turnout, candidate divergence, documented powers of the office.`,
        },
        {
          role: "user",
          content: `Build the motivation card. Return ONLY JSON:
{"hook": "one sharp personal line about why THIS ballot is theirs to decide",
 "because": [{"text": "you should vote because <concrete, sourced reason tied to their priorities>", "source": {"title","url"}}, ... 2-4 items],
 "if_you_vote": "2-3 sentences: what their single vote concretely weighs in (use real margins from stakes) and what gets decided on their top issues",
 "long_term": "2-3 sentences: the down-the-line chain from the scenario branches — how this election compounds into ${new Date().getFullYear() + 2}+ on their priorities",
 "cta": "one nonpartisan action line (make a plan, check registration, election date)"}

DATA:
voter: ${JSON.stringify({ name: voter?.name, occupation: voter?.occupation, situation: Object.entries(flags).filter(([, v]) => v).map(([k, v]) => (k === "healthcare" ? `healthcare:${v}` : k)) })}
top_priorities: ${JSON.stringify(topIssues.map((i) => ISSUE_MAP[i]?.name ?? i))}
candidate_divergence_on_their_issues: ${JSON.stringify(divergence)}
race_stakes_margins_turnout: ${JSON.stringify(stakes)}
scenario_branches_touching_them: ${JSON.stringify(relevantBranches.slice(0, 10))}
election_date: "2026-11-03"`,
        },
      ],
      { model: FAST_MODEL, maxTokens: 1200, timeoutMs: 90_000 }
    );
    motivation = extractJSON<Motivation>(out);
  } catch {
    motivation = fallback;
  }

  await kvSet(NS.motivations, hash, motivation);
  return Response.json({ motivation, cached: false });
}
