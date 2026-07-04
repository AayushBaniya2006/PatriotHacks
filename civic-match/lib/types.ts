// Core entity types for Civic Match — per PRD section 8.

export type EvidenceType =
  | "voting_record"
  | "sponsored_bill"
  | "official_platform"
  | "public_statement"
  | "debate_transcript"
  | "interview"
  | "campaign_finance"
  | "news_report"
  | "questionnaire"
  | "other";

export interface Source {
  source_id: string;
  type: EvidenceType;
  title: string;
  publisher: string;
  url: string;
  published_at?: string; // ISO date if known
  retrieved_at: string;
  primary_source: boolean;
  quote?: string; // extracted quote span supporting the claim
  reliability_score: number; // 0-1
}

export interface Stance {
  stance_id: string;
  issue_id: string; // matches IssueDef.id
  position_label: string; // short human-readable position
  // Scalar position on the issue's trade-off axis, 0..1.
  // 0 = option A pole, 1 = option C pole (see IssueDef.options mapping).
  position_scalar: number | null; // null = evidence exists but direction unclear
  summary: string; // 1-2 sentence neutral summary of the position
  evidence_type: EvidenceType;
  confidence: number; // 0-1 how clearly evidence supports this stance
  recency?: string; // ISO date of most recent supporting evidence
  sources: Source[];
}

// ---- Qualitative (character) assessment — independent of user's issue positions ----
// Researched with sources like everything else: corruption/ethics record,
// public interest & approval, transparency, experience/effectiveness.

export type QualitativeDimensionId =
  | "integrity" // corruption, indictments, ethics violations (higher = cleaner)
  | "public_interest" // approval, constituent service, responsiveness
  | "transparency" // disclosure, press access, records
  | "experience"; // offices held, legislative effectiveness

export interface QualitativeDimension {
  id: QualitativeDimensionId;
  score: number; // 0-1, higher is better
  summary: string; // neutral, evidence-grounded
  confidence: number; // 0-1
  sources: Source[];
}

// ---- Promise vs. record (accountability watchdog) ----

export interface PromiseRecord {
  promise: string; // what was promised, plain English
  promised_at?: string; // ISO date if known
  promise_source: Source;
  action: string; // what they actually did (vote, signed law, inaction)
  action_at?: string;
  action_sources: Source[];
  verdict: "kept" | "broken" | "partial" | "untested";
  explanation: string; // neutral one-sentence reconciliation
  confidence: number; // 0-1
}

// ---- Knowledge graph ----

export type GraphNodeType =
  | "politician"
  | "office"
  | "race"
  | "issue"
  | "organization"
  | "event"; // e.g. "AG vacancy if Paxton wins"

export interface GraphNode {
  id: string;
  type: GraphNodeType;
  label: string;
  meta?: Record<string, string | number | boolean | null>;
}

export interface GraphEdge {
  source: string; // node id
  target: string; // node id
  rel: string; // running_for | holds | supports | opposes | leads_to | endorsed_by | funded_by | succession | could_win
  label?: string;
  description?: string;
  kind: "fact" | "inference";
  confidence: number;
  sources: { title: string; url: string; publisher?: string }[];
}

export interface KnowledgeGraph {
  nodes: GraphNode[];
  edges: GraphEdge[];
  built_at: string;
}

// ---- Future-possibilities scenario tree ----
// Root = the race. First level = "candidate X wins". Deeper levels =
// consequences (policy, succession, vacancies, later elections). Leaves =
// long-term possibilities. Every node is labeled fact vs inference; inference
// carries likelihood. This is scenario analysis, NOT a forecast.

export interface ScenarioNode {
  id: string;
  label: string; // short headline, e.g. "Paxton wins → AG seat vacated"
  timeframe: string; // "2026-11", "2027", "2028+", ...
  kind: "fact" | "inference";
  likelihood?: "high" | "medium" | "low"; // required when kind = inference
  description: string; // 1-2 neutral sentences
  issue_ids?: string[]; // taxonomy ids, for user-priority highlighting
  affected_groups?: string[]; // VoterProfile flag keys: renter, veteran, ...
  sources: { title: string; url: string; publisher?: string }[];
  children: ScenarioNode[];
}

export interface ScenarioTree {
  race: string;
  race_slug: string;
  built_at: string;
  root: ScenarioNode;
}

// ---- Follow the money: funding + money↔votes cross-reference ----
// Correlations are labeled as correlation, NEVER causation/proof.

export interface DonorEntry {
  name: string; // donor, PAC, org, or industry group
  kind: "individual" | "pac" | "organization" | "industry" | "party";
  amount?: string; // as reported, e.g. "$1.2M (2022-2026 cycle)"
  source: Source;
}

export interface MoneyCorrelation {
  donor: string; // who/which industry
  issue_id: string;
  position_or_vote: string; // the related stance, vote, or floor action
  note: string; // neutral: "correlation in public records, not proof of causation"
  confidence: number;
  sources: Source[];
}

export interface CampaignFinance {
  total_raised?: string;
  cash_on_hand?: string;
  as_of?: string;
  overview_source?: Source;
  top_donors: DonorEntry[];
  correlations: MoneyCorrelation[];
}

export interface PoliticianProfile {
  id: string; // slug
  name: string;
  party?: string;
  current_office?: string;
  jurisdiction?: string;
  bio?: string;
  campaign_website?: string;
  stances: Stance[];
  qualitative?: QualitativeDimension[];
  promise_record?: PromiseRecord[];
  finance?: CampaignFinance;
  unknowns: string[]; // issue_ids with no reliable evidence found
  contradictions: {
    issue_id: string;
    description: string;
    sources: Source[];
  }[];
  source_coverage_score: number; // 0-1
  researched_at: string;
  research_status: "complete" | "partial" | "failed";
}

// ---- User preference model (PRD 8.2) ----
// Everything here is EXPLICITLY user-stated. Never inferred, never sold,
// stored locally in the browser. Used only to frame explanations
// ("what this means for someone in your situation") — never for
// sensitive-trait persuasion.

export interface VoterProfile {
  name?: string;
  occupation?: string;
  age_bracket?: "18-24" | "25-34" | "35-49" | "50-64" | "65+";
  income_bracket?: "<30k" | "30-60k" | "60-100k" | "100-200k" | "200k+";
  flags: {
    homeowner?: boolean;
    renter?: boolean;
    kids_in_public_school?: boolean;
    veteran?: boolean;
    small_business_owner?: boolean;
    student?: boolean;
    healthcare?: "employer" | "aca" | "medicare" | "uninsured";
  };
}

export interface UserPreferences {
  zip?: string;
  // Street address (optional). Powers the "Your ballot" section on the
  // results page via GET /api/ballot — kept separate from `zip` because the
  // Census geocoder needs a full address to resolve districts reliably.
  address?: string;
  profile?: VoterProfile;
  // issue_id -> weight 0..1 (normalized)
  priority_weights: Record<string, number>;
  // issue_id -> chosen scalar position 0..1, or null for "unsure / don't use"
  issue_positions: Record<string, number | null>;
}

// ---- Scoring output (PRD 8.3) ----

export interface IssueScoreBreakdown {
  issue_id: string;
  issue_name: string;
  user_position: number | null;
  candidate_position: number | null;
  candidate_label?: string;
  alignment: number | null; // 0-1, null if unknown
  weight: number;
  evidence_confidence: number;
  source_quality: number;
  recency_adjustment: number;
  points: number; // contribution to total, weighted
  max_points: number; // weight (what a perfect match would give)
  status: "match" | "partial" | "conflict" | "unknown";
}

export interface MatchResult {
  politician_id: string;
  politician_name: string;
  party?: string;
  score: number; // 0-100 alignment
  confidence: "High" | "Medium" | "Low";
  confidence_value: number; // 0-1
  // 2K-style overall rating: 60 = worst, 99 = best.
  // Blends quantitative issue alignment (taxes, economy, ...) with the
  // qualitative character assessment (corruption, public interest, ...).
  overall: number;
  overall_tier: string; // e.g. "Elite match", "Strong match", ...
  overall_components: {
    alignment_component: number; // from quantitative issue-alignment score
    qualitative_component: number; // from character dimensions (integrity etc.)
    conflict_penalty: number; // subtracted for high-weight conflicts
  };
  warnings: string[]; // ground-truth-backed cautions (broken promises, integrity flags, contradictions)
  qualitative_composite: number | null; // 0-1, null if not researched
  qualitative: {
    id: string;
    label: string;
    score: number;
    summary: string;
    confidence: number;
  }[];
  breakdown: IssueScoreBreakdown[];
  top_agreements: IssueScoreBreakdown[];
  top_conflicts: IssueScoreBreakdown[];
  unknown_issues: IssueScoreBreakdown[];
}

// ---- Research pipeline events ----

export interface ResearchEvent {
  type: "status" | "agent_start" | "agent_done" | "verify" | "complete" | "error";
  agent?: string;
  message: string;
  progress?: number; // 0-1
}
