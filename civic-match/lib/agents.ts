// Research agent swarm (per infra sketch):
//   user info → agent staging (minimize context) → parallel data-endpoint agents
//   → output report → verifier agent double-checks → db of politicians
import { getClusters, getIssueMap } from "./config";
const ISSUE_MAP = () => getIssueMap();
const CLUSTERS = () => getClusters();
import { chat, extractJSON, FAST_MODEL, RESEARCH_MODEL } from "./llm";
import { savePolitician, slugify } from "./db";
import type {
  CampaignFinance,
  PoliticianProfile,
  PromiseRecord,
  QualitativeDimension,
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
      const i = ISSUE_MAP()[id];
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

interface RawQualDim {
  id: string;
  score: number;
  summary: string;
  confidence: number;
  sources: RawStance["sources"];
}

const QUAL_DIM_IDS = new Set(["integrity", "public_interest", "transparency", "experience"]);

function toSource(
  s: { title?: string; publisher?: string; url: string; published_at?: string; type?: string; quote?: string; primary_source?: boolean },
  idPrefix: string,
  i: number,
  retrievedAt: string
): Source {
  return {
    source_id: `${idPrefix}_src_${i}`,
    type: (EVIDENCE_TYPES.has(s.type || "") ? s.type : "other") as Source["type"],
    title: s.title || "Untitled source",
    publisher: s.publisher || new URL(s.url).hostname,
    url: s.url,
    published_at: s.published_at,
    retrieved_at: retrievedAt,
    primary_source: !!s.primary_source,
    quote: s.quote,
    reliability_score: s.primary_source ? 0.95 : 0.7,
  };
}

const isRealUrl = (u?: string) => !!u && /^https?:\/\//.test(u);

/** Follow-the-money agent: funding overview + money↔votes cross-reference.
 * Correlations are framed as correlation in public records, never proof. */
export async function runFinanceAgent(
  name: string,
  retrievedAt: string,
  stanceContext: { issue_id: string; position: string }[]
): Promise<CampaignFinance | undefined> {
  const out = await chat(
    [
      {
        role: "user",
        content: `You are a neutral campaign-finance researcher. Use web search to document how U.S. politician "${name}" funds their campaigns. Prefer primary sources: FEC.gov (federal), Texas Ethics Commission (state), OpenSecrets/Transparency USA as secondary.

Find:
1. Totals: amount raised + cash on hand for the current cycle, with as-of date.
2. Top donors: biggest individual donors, PACs, organizations, and industry groups with reported amounts.
3. CROSS-REFERENCE: for each major donor/industry, check whether the politician has a documented position, vote, or floor action related to that donor's interests. Their documented positions: ${JSON.stringify(stanceContext.slice(0, 20))}

Return ONLY JSON:
{"total_raised": "...", "cash_on_hand": "...", "as_of": "YYYY-MM-DD",
 "overview_source": {"title","publisher","url","primary_source": true|false},
 "top_donors": [{"name": "...", "kind": "individual|pac|organization|industry|party", "amount": "...", "source": {"title","publisher","url","primary_source"}}],
 "correlations": [{"donor": "...", "issue_id": "one of the issue ids above", "position_or_vote": "the documented position/vote related to this donor's interests", "note": "one neutral sentence explicitly framing this as a correlation in public records, not proof of causation", "confidence": 0.0-1.0, "sources": [{"title","publisher","url","primary_source"}]}]}

Rules: every item needs a real source URL or omit it. Max 8 donors, 6 correlations. NEVER claim a donation caused a vote — correlation language only. Neutral tone.`,
      },
    ],
    { model: RESEARCH_MODEL, maxTokens: 6144, timeoutMs: 150_000 }
  );
  interface RawSrc { title?: string; publisher?: string; url: string; published_at?: string; primary_source?: boolean }
  let raw: {
    total_raised?: string; cash_on_hand?: string; as_of?: string;
    overview_source?: RawSrc;
    top_donors?: { name: string; kind: string; amount?: string; source: RawSrc }[];
    correlations?: { donor: string; issue_id: string; position_or_vote: string; note: string; confidence?: number; sources: RawSrc[] }[];
  };
  try {
    raw = extractJSON<typeof raw>(out);
  } catch {
    return undefined;
  }
  const kinds = new Set(["individual", "pac", "organization", "industry", "party"]);
  return {
    total_raised: raw.total_raised,
    cash_on_hand: raw.cash_on_hand,
    as_of: raw.as_of,
    overview_source: isRealUrl(raw.overview_source?.url)
      ? toSource({ ...raw.overview_source!, type: "campaign_finance" }, "fin_overview", 0, retrievedAt)
      : undefined,
    top_donors: (raw.top_donors ?? [])
      .filter((d) => d?.name && isRealUrl(d.source?.url))
      .map((d, i) => ({
        name: d.name,
        kind: (kinds.has(d.kind) ? d.kind : "organization") as "individual" | "pac" | "organization" | "industry" | "party",
        amount: d.amount,
        source: toSource({ ...d.source, type: "campaign_finance" }, `donor_${i}`, 0, retrievedAt),
      })),
    correlations: (raw.correlations ?? [])
      .filter((c) => c?.donor && (c.sources ?? []).some((s) => isRealUrl(s?.url)))
      .map((c, i) => ({
        donor: c.donor,
        issue_id: c.issue_id,
        position_or_vote: c.position_or_vote,
        note: c.note || "Correlation in public records; not proof of causation.",
        confidence: Math.max(0, Math.min(1, c.confidence ?? 0.5)),
        sources: c.sources.filter((s) => isRealUrl(s.url)).map((s, j) => toSource({ ...s, type: "campaign_finance" }, `corr_${i}`, j, retrievedAt)),
      })),
  };
}

/** Accountability agent: promise vs. record with receipts. */
export async function runAccountabilityAgent(
  name: string,
  retrievedAt: string
): Promise<PromiseRecord[]> {
  const out = await chat(
    [
      {
        role: "user",
        content: `You are a neutral accountability researcher. Use web search to find specific PUBLIC PROMISES U.S. politician "${name}" made (campaign pledges, platform commitments, public statements) and compare each against what they ACTUALLY DID (roll-call votes, signed/vetoed bills, executive actions, documented inaction). Only include pairs where both sides are verifiable. Never invent sources or quotes.

Return ONLY a JSON array (up to 8 strongest examples):
[{
  "promise": "what they promised, plain English",
  "promised_at": "YYYY-MM-DD if known",
  "promise_source": {"title": "...", "publisher": "...", "url": "real URL", "published_at": "...", "quote": "short exact quote if available", "primary_source": true|false},
  "action": "what they actually did",
  "action_at": "YYYY-MM-DD if known",
  "action_sources": [{"title": "...", "publisher": "...", "url": "real URL", "published_at": "...", "primary_source": true|false}],
  "verdict": "kept" | "broken" | "partial" | "untested",
  "explanation": "one neutral sentence reconciling promise and action",
  "confidence": 0.0-1.0
}]

Rules: verdict "untested" = no opportunity yet to act. Include kept promises too — this is a scorecard, not an attack file. Neutral language only.`,
      },
    ],
    { model: RESEARCH_MODEL, maxTokens: 6144, timeoutMs: 150_000 }
  );
  let raw: (Omit<PromiseRecord, "promise_source" | "action_sources"> & {
    promise_source: { title?: string; publisher?: string; url: string; published_at?: string; quote?: string; primary_source?: boolean };
    action_sources: { title?: string; publisher?: string; url: string; published_at?: string; primary_source?: boolean }[];
  })[] = [];
  try {
    raw = extractJSON<typeof raw>(out);
  } catch {
    return [];
  }
  const records: PromiseRecord[] = [];
  for (const [i, r] of raw.entries()) {
    if (!isRealUrl(r.promise_source?.url)) continue;
    const actionSources = (r.action_sources || []).filter((s) => isRealUrl(s.url));
    if (actionSources.length === 0 && r.verdict !== "untested") continue; // receipts required
    records.push({
      promise: r.promise,
      promised_at: r.promised_at,
      promise_source: toSource(r.promise_source, `promise_${i}`, 0, retrievedAt),
      action: r.action || "No action documented yet",
      action_at: r.action_at,
      action_sources: actionSources.map((s, j) => toSource(s, `action_${i}`, j, retrievedAt)),
      verdict: ["kept", "broken", "partial", "untested"].includes(r.verdict)
        ? r.verdict
        : "untested",
      explanation: r.explanation || "",
      confidence: Math.max(0, Math.min(1, r.confidence ?? 0.5)),
    });
  }
  return records;
}

/** Qualitative agent: character dimensions independent of issue positions. */
export async function runQualitativeAgent(
  name: string,
  retrievedAt: string
): Promise<QualitativeDimension[]> {
  const out = await chat(
    [
      {
        role: "user",
        content: `You are a neutral political researcher. Use web search to assess U.S. politician "${name}" on four QUALITATIVE dimensions (independent of policy positions). Base every claim on verifiable public evidence: court records, ethics filings, indictments, impeachment proceedings, approval polling, FOIA/press-access records, offices held, bills passed. Never invent sources.

Dimensions (score 0.0-1.0, higher = better):
- "integrity": corruption investigations, indictments, ethics violations, impeachments (clean record = high)
- "public_interest": approval ratings, constituent service reputation, responsiveness
- "transparency": financial disclosure, press access, records compliance
- "experience": offices held, tenure, legislative effectiveness (bills passed, leadership roles)

Return ONLY a JSON array:
[{"id": "integrity", "score": 0.0-1.0, "summary": "2 neutral sentences citing the specific evidence", "confidence": 0.0-1.0, "sources": [{"title": "...", "publisher": "...", "url": "real URL", "published_at": "YYYY-MM-DD if known", "primary_source": true|false}]}]

Rules: every dimension MUST have at least one real source URL or be omitted. Neutral language. Documented facts only — no speculation.`,
      },
    ],
    { model: RESEARCH_MODEL, maxTokens: 4096, timeoutMs: 150_000 }
  );
  let raw: RawQualDim[] = [];
  try {
    raw = extractJSON<RawQualDim[]>(out);
  } catch {
    return [];
  }
  const dims: QualitativeDimension[] = [];
  for (const d of raw) {
    if (!QUAL_DIM_IDS.has(d.id)) continue;
    const sources: Source[] = (d.sources || [])
      .filter((s) => s.url && /^https?:\/\//.test(s.url))
      .map((s, i) => ({
        source_id: `qual_${d.id}_src_${i}`,
        type: "other" as const,
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
    dims.push({
      id: d.id as QualitativeDimension["id"],
      score: Math.max(0, Math.min(1, d.score ?? 0.5)),
      summary: d.summary || "",
      confidence: Math.max(0, Math.min(1, d.confidence ?? 0.5)),
      sources,
    });
  }
  return dims;
}

/** Programmatic verification: no source, no claim (PRD R1). */
function validateStances(raw: RawStance[], retrievedAt: string): Stance[] {
  const stances: Stance[] = [];
  for (const r of raw) {
    if (!ISSUE_MAP()[r.issue_id]) continue;
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
    axis: `0=${ISSUE_MAP()[s.issue_id].axis0} | 1=${ISSUE_MAP()[s.issue_id].axis1}`,
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

  const clusters = CLUSTERS();
  const clusterNames = Object.keys(clusters);
  let done = 0;
  const total = clusterNames.length + 3;

  // Fan out: profile agent + qualitative agent + one agent per issue cluster,
  // all parallel (latency-first)
  const profilePromise = runProfileAgent(name).then((p) => {
    done++;
    onEvent({ type: "agent_done", agent: "profile", message: "Profile agent finished", progress: 0.1 + 0.6 * (done / total) });
    return p;
  });

  onEvent({ type: "agent_start", agent: "qualitative", message: "Agent researching character record (ethics, transparency, experience)" });
  const qualitativePromise = runQualitativeAgent(name, retrievedAt).then((q) => {
    done++;
    onEvent({ type: "agent_done", agent: "qualitative", message: `Qualitative agent scored ${q.length} dimensions`, progress: 0.1 + 0.6 * (done / total) });
    return q;
  });

  onEvent({ type: "agent_start", agent: "accountability", message: "Agent comparing promises vs record (receipts required)" });
  const promisesPromise = runAccountabilityAgent(name, retrievedAt).then((p) => {
    done++;
    onEvent({ type: "agent_done", agent: "accountability", message: `Accountability agent verified ${p.length} promise/record pairs`, progress: 0.1 + 0.6 * (done / total) });
    return p;
  });

  const clusterPromises = clusterNames.map((cluster) => {
    onEvent({ type: "agent_start", agent: cluster, message: `Agent researching ${cluster} issues` });
    return runClusterAgent(name, cluster, clusters[cluster]).then((r) => {
      done++;
      onEvent({ type: "agent_done", agent: cluster, message: `${cluster} agent found ${r.length} positions`, progress: 0.1 + 0.6 * (done / total) });
      return r;
    });
  });

  const [profilePart, qualitative, promiseRecord, ...clusterResults] = await Promise.all([
    profilePromise,
    qualitativePromise,
    promisesPromise,
    ...clusterPromises,
  ]);

  const rawStances = clusterResults.flat();
  onEvent({ type: "verify", message: `Validating ${rawStances.length} stances (no source, no claim)`, progress: 0.75 });
  let stances = validateStances(rawStances, retrievedAt);

  onEvent({ type: "verify", message: "Verifier agent double-checking placements", progress: 0.85 });
  const { corrections, contradictions } = await runVerifierAgent(name, stances);
  // Guard: a verifier that nulls out a large share of stances is misbehaving —
  // ignore its corrections rather than destroy researched placements.
  const nullingCorrections = corrections.filter((c) => c.position_scalar === null).length;
  if (nullingCorrections <= Math.max(2, stances.length * 0.3)) {
    for (const c of corrections) {
      const s = stances.find((s) => s.issue_id === c.issue_id);
      if (s) s.position_scalar = c.position_scalar === null ? null : Math.max(0, Math.min(1, c.position_scalar));
    }
  }

  const coveredIssues = new Set(stances.map((s) => s.issue_id));
  const unknowns = Object.keys(ISSUE_MAP()).filter((i) => !coveredIssues.has(i));

  onEvent({ type: "agent_start", agent: "finance", message: "Follow-the-money agent cross-referencing donors with votes" });
  const finance = await runFinanceAgent(
    name,
    retrievedAt,
    stances.map((s) => ({ issue_id: s.issue_id, position: s.position_label }))
  );
  onEvent({ type: "agent_done", agent: "finance", message: `Finance agent: ${finance?.top_donors.length ?? 0} donors, ${finance?.correlations.length ?? 0} correlations`, progress: 0.95 });

  const profile: PoliticianProfile = {
    id,
    name: profilePart.name || name,
    party: profilePart.party,
    current_office: profilePart.current_office,
    jurisdiction: profilePart.jurisdiction,
    bio: profilePart.bio,
    campaign_website: profilePart.campaign_website ?? undefined,
    stances,
    qualitative,
    promise_record: promiseRecord,
    finance,
    unknowns,
    contradictions,
    source_coverage_score: coveredIssues.size / Object.keys(ISSUE_MAP()).length,
    researched_at: retrievedAt,
    research_status: stances.length > 0 ? "complete" : "failed",
  };

  await savePolitician(profile);
  onEvent({ type: "complete", message: `Saved profile: ${stances.length} sourced stances, ${unknowns.length} unknowns`, progress: 1 });
  return profile;
}
