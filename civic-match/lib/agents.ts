// Research agent swarm (per infra sketch):
//   user info → agent staging (minimize context) → parallel data-endpoint agents
//   → output report → verifier agent double-checks → db of politicians
import { CLUSTERS, ISSUE_MAP } from "./issues";
import { chat, extractJSON, FAST_MODEL, RESEARCH_MODEL } from "./llm";
import { savePolitician, slugify } from "./db";
import type {
  PoliticianProfile,
  ResearchEvent,
  Source,
  Stance,
} from "./types";

interface RawStance {
  issue_id: string;
  position_label: string;
  position_scalar: number | null;
  summary: string;
  evidence_type: string;
  confidence: number;
  recency?: string;
  sources: {
    title: string;
    publisher: string;
    url: string;
    published_at?: string;
    type?: string;
    quote?: string;
    primary_source?: boolean;
  }[];
}

const EVIDENCE_TYPES = new Set([
  "voting_record", "sponsored_bill", "official_platform", "public_statement",
  "debate_transcript", "interview", "campaign_finance", "news_report",
  "questionnaire", "other",
]);

function clusterPrompt(name: string, clusterIssues: string[]): string {
  const issueSpecs = clusterIssues
    .map((id) => {
      const i = ISSUE_MAP[id];
      return `- issue_id: "${i.id}" (${i.name}) — axis: 0.0 = "${i.axis0}" ... 1.0 = "${i.axis1}"`;
    })
    .join("\n");

  return `You are a neutral political researcher. Research the public, verifiable positions of the U.S. politician "${name}" on the issues below. Use web search. Prefer primary sources: roll-call votes, sponsored bills, official campaign/office websites, official transcripts. Never invent sources or quotes.

Issues and scoring axes:
${issueSpecs}

For EACH issue where you find real evidence, output a stance. If no reliable evidence exists for an issue, OMIT it (do not guess).

Return ONLY a JSON array:
[{
  "issue_id": "...",
  "position_label": "short neutral label of their position",
  "position_scalar": 0.0-1.0 placing them on the axis above (null if evidence exists but direction is unclear),
  "summary": "1-2 neutral sentences describing the position and the evidence",
  "evidence_type": one of ["voting_record","sponsored_bill","official_platform","public_statement","debate_transcript","interview","campaign_finance","news_report","questionnaire","other"],
  "confidence": 0.0-1.0 (how clearly the evidence supports the stance; vague statements = low),
  "recency": "YYYY-MM-DD of most recent supporting evidence, if known",
  "sources": [{"title": "...", "publisher": "...", "url": "real URL", "published_at": "YYYY-MM-DD if known", "type": same enum, "quote": "short exact quote if available", "primary_source": true|false}]
}]

Rules: every stance MUST have at least one source with a real URL. Neutral language only. No persuasion.`;
}

async function runClusterAgent(
  name: string,
  cluster: string,
  issueIds: string[]
): Promise<RawStance[]> {
  const out = await chat(
    [{ role: "user", content: clusterPrompt(name, issueIds) }],
    { model: RESEARCH_MODEL, maxTokens: 8192, timeoutMs: 150_000 }
  );
  try {
    return extractJSON<RawStance[]>(out);
  } catch {
    return [];
  }
}

async function runProfileAgent(name: string): Promise<Partial<PoliticianProfile>> {
  const out = await chat(
    [
      {
        role: "user",
        content: `Use web search to find basic verified facts about U.S. politician "${name}". Return ONLY JSON:
{"name": "full name", "party": "...", "current_office": "...", "jurisdiction": "...", "campaign_website": "url or null", "bio": "2 neutral sentences"}`,
      },
    ],
    { model: RESEARCH_MODEL, maxTokens: 1024, timeoutMs: 90_000 }
  );
  try {
    return extractJSON<Partial<PoliticianProfile>>(out);
  } catch {
    return { name };
  }
}

/** Programmatic verification: no source, no claim (PRD R1). */
function validateStances(raw: RawStance[], retrievedAt: string): Stance[] {
  const stances: Stance[] = [];
  for (const r of raw) {
    if (!ISSUE_MAP[r.issue_id]) continue;
    const sources: Source[] = (r.sources || [])
      .filter((s) => s.url && /^https?:\/\//.test(s.url))
      .map((s, i) => ({
        source_id: `${r.issue_id}_src_${i}`,
        type: (EVIDENCE_TYPES.has(s.type || "") ? s.type : "other") as Source["type"],
        title: s.title || "Untitled source",
        publisher: s.publisher || new URL(s.url).hostname,
        url: s.url,
        published_at: s.published_at,
        retrieved_at: retrievedAt,
        primary_source: !!s.primary_source,
        quote: s.quote,
        reliability_score: s.primary_source ? 0.95 : 0.7,
      }));
    if (sources.length === 0) continue; // no source, no claim
    const scalar =
      typeof r.position_scalar === "number"
        ? Math.max(0, Math.min(1, r.position_scalar))
        : null;
    stances.push({
      stance_id: `${r.issue_id}_${Date.now()}`,
      issue_id: r.issue_id,
      position_label: r.position_label || "Position found",
      position_scalar: scalar,
      summary: r.summary || "",
      evidence_type: (EVIDENCE_TYPES.has(r.evidence_type) ? r.evidence_type : "other") as Stance["evidence_type"],
      confidence: Math.max(0, Math.min(1, r.confidence ?? 0.5)),
      recency: r.recency,
      sources,
    });
  }
  // Dedupe by issue: keep highest confidence
  const byIssue = new Map<string, Stance>();
  for (const s of stances) {
    const prev = byIssue.get(s.issue_id);
    if (!prev || s.confidence > prev.confidence) byIssue.set(s.issue_id, s);
  }
  return [...byIssue.values()];
}

/** Verifier agent: double-checks scalar placement consistency + finds contradictions. */
async function runVerifierAgent(
  name: string,
  stances: Stance[]
): Promise<{ corrections: { issue_id: string; position_scalar: number | null }[]; contradictions: PoliticianProfile["contradictions"] }> {
  const compact = stances.map((s) => ({
    issue_id: s.issue_id,
    axis: `0=${ISSUE_MAP[s.issue_id].axis0} | 1=${ISSUE_MAP[s.issue_id].axis1}`,
    label: s.position_label,
    scalar: s.position_scalar,
    summary: s.summary,
  }));
  try {
    const out = await chat(
      [
        {
          role: "user",
          content: `You are a verification agent for a neutral voter-info tool. For politician "${name}", check each stance below: does the numeric scalar match the described position on the given axis? Also flag any pair of stances that contradict each other.

${JSON.stringify(compact)}

Return ONLY JSON:
{"corrections": [{"issue_id": "...", "position_scalar": corrected number or null}], "contradictions": [{"issue_id": "...", "description": "neutral one-sentence description of the contradiction"}]}
Only include corrections where the scalar is clearly wrong (off by more than 0.3).`,
        },
      ],
      { model: FAST_MODEL, maxTokens: 2048, timeoutMs: 60_000 }
    );
    const parsed = extractJSON<{
      corrections?: { issue_id: string; position_scalar: number | null }[];
      contradictions?: { issue_id: string; description: string }[];
    }>(out);
    return {
      corrections: parsed.corrections ?? [],
      contradictions: (parsed.contradictions ?? []).map((c) => ({
        ...c,
        sources: [],
      })),
    };
  } catch {
    return { corrections: [], contradictions: [] };
  }
}

export async function researchPolitician(
  name: string,
  onEvent: (e: ResearchEvent) => void
): Promise<PoliticianProfile> {
  const id = slugify(name);
  const retrievedAt = new Date().toISOString();
  onEvent({ type: "status", message: `Staging research for ${name}`, progress: 0.05 });

  const clusterNames = Object.keys(CLUSTERS);
  let done = 0;
  const total = clusterNames.length + 1;

  // Fan out: profile agent + one agent per issue cluster, all parallel (latency-first)
  const profilePromise = runProfileAgent(name).then((p) => {
    done++;
    onEvent({ type: "agent_done", agent: "profile", message: "Profile agent finished", progress: 0.1 + 0.6 * (done / total) });
    return p;
  });

  const clusterPromises = clusterNames.map((cluster) => {
    onEvent({ type: "agent_start", agent: cluster, message: `Agent researching ${cluster} issues` });
    return runClusterAgent(name, cluster, CLUSTERS[cluster]).then((r) => {
      done++;
      onEvent({ type: "agent_done", agent: cluster, message: `${cluster} agent found ${r.length} positions`, progress: 0.1 + 0.6 * (done / total) });
      return r;
    });
  });

  const [profilePart, ...clusterResults] = await Promise.all([
    profilePromise,
    ...clusterPromises,
  ]);

  const rawStances = clusterResults.flat();
  onEvent({ type: "verify", message: `Validating ${rawStances.length} stances (no source, no claim)`, progress: 0.75 });
  let stances = validateStances(rawStances, retrievedAt);

  onEvent({ type: "verify", message: "Verifier agent double-checking placements", progress: 0.85 });
  const { corrections, contradictions } = await runVerifierAgent(name, stances);
  for (const c of corrections) {
    const s = stances.find((s) => s.issue_id === c.issue_id);
    if (s) s.position_scalar = c.position_scalar === null ? null : Math.max(0, Math.min(1, c.position_scalar));
  }

  const coveredIssues = new Set(stances.map((s) => s.issue_id));
  const unknowns = Object.keys(ISSUE_MAP).filter((i) => !coveredIssues.has(i));

  const profile: PoliticianProfile = {
    id,
    name: profilePart.name || name,
    party: profilePart.party,
    current_office: profilePart.current_office,
    jurisdiction: profilePart.jurisdiction,
    bio: profilePart.bio,
    campaign_website: profilePart.campaign_website ?? undefined,
    stances,
    unknowns,
    contradictions,
    source_coverage_score: coveredIssues.size / Object.keys(ISSUE_MAP).length,
    researched_at: retrievedAt,
    research_status: stances.length > 0 ? "complete" : "failed",
  };

  await savePolitician(profile);
  onEvent({ type: "complete", message: `Saved profile: ${stances.length} sourced stances, ${unknowns.length} unknowns`, progress: 1 });
  return profile;
}
