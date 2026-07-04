// Server-side client for our FastAPI data backend (repo root CLAUDE.md
// "API contract"). Only ever import/call this from Route Handlers or Server
// Components — never from a Client Component — so the backend never needs
// CORS and its URL stays out of client bundles (no NEXT_PUBLIC_ prefix).
//
// The backend candidates payload is a moving target while it's being fixed
// to match the contract (id-keyed object today, array per contract soon) —
// normalizeCandidates() below accepts both so this client keeps working
// across that change without a redeploy.
import type { VoterProfile } from "./types";

const DATA_BACKEND_URL = (process.env.DATA_BACKEND_URL ?? "http://localhost:8000").replace(/\/+$/, "");

const BALLOT_TIMEOUT_MS = 10_000;
const INSIGHTS_TIMEOUT_MS = 20_000;

// ---------------------------------------------------------------------------
// Contract types — mirrors CLAUDE.md "API contract" plus the extra fields
// actually present in data/tx/{races,candidates}.json (kept optional so we
// never lie about what's guaranteed).
// ---------------------------------------------------------------------------

export interface Districts {
  cd: string | null;
  sd: string | null;
  hd: string | null;
  county: string | null;
}

export interface FinanceInfo {
  receipts?: number | null;
  disbursements?: number | null;
  cash_on_hand?: number | null;
  as_of?: string | null;
  source?: string | null;
}

export interface KeyVote {
  bill?: string;
  vote?: string; // some pipeline output uses `vote` instead of `bill` — accept both
  question?: string;
  position?: string;
  plain_english?: string;
  date?: string;
  result?: string;
  source?: string;
}

export interface CandidateRecord {
  key_votes?: KeyVote[];
  sponsored_highlights?: string[];
  source?: string;
}

export interface CandidatePosition {
  issue?: string;
  summary?: string;
  source?: string;
}

// Coverage/completeness signal from pipeline/score_quality.py
// (data/tx/quality_report.json) — optional because older cached payloads and
// the live LLM path may not carry it yet. `missing` entries are pre-written,
// neutral, human-readable strings (e.g. "no campaign finance") meant to be
// shown verbatim, never paraphrased into something that reads as a knock on
// the candidate.
export interface DataQuality {
  score?: number;
  tier?: "A" | "B" | "C" | "D";
  missing?: string[];
  // Race-only (pipeline/score_quality.py writes race.data_quality =
  // {score, tier, demo_rank} vs candidate.data_quality = {score, tier,
  // missing} -- the two payloads share this one interface but not every
  // field). 1-indexed ascending across the WHOLE dataset: demo_rank 1 is
  // the single best/most-demoable race, not the highest score. Used by
  // app/results/page.tsx to prefetch insights for the top demo race
  // (design spec §4). Absent on candidate-level DataQuality and on any
  // cached payload predating this field.
  demo_rank?: number;
}

export interface Candidate {
  candidate_id: string;
  name: string;
  party?: string | null;
  office?: string;
  district?: string | null;
  incumbent?: boolean | null;
  fec_id?: string | null;
  finance?: FinanceInfo;
  record?: CandidateRecord;
  positions?: CandidatePosition[];
  sources?: string[];
  background?: string;
  // set by the backend when a race references a candidate_id it has no
  // record for — render an honest "no data" state, never guess a name.
  data_missing?: boolean;
  data_quality?: DataQuality;
}

export interface RaceContext {
  last_result?: string;
  last_result_detail?: {
    last_winner?: string;
    party?: string;
    margin_pct?: number;
    total_votes?: number;
    election_date?: string;
    source?: string;
  } | null;
  sources?: string[];
  [key: string]: unknown;
}

export interface Race {
  race_id: string;
  office: string;
  level: "federal" | "state" | "state_leg" | string;
  district: string | null;
  context?: RaceContext;
  candidates: Candidate[];
  data_quality?: DataQuality;
}

// Raw wire shape: candidates may be an id-keyed object (current backend) or
// an array (contract / post-fix backend).
interface RawRace extends Omit<Race, "candidates"> {
  candidates?: Candidate[] | Record<string, Candidate> | null;
}

// ---------------------------------------------------------------------------
// Optional Google Civic enrichment (backend: app/google_civic.py). Present
// on BallotResponse only when the backend's GOOGLE_CIVIC_API_KEY is set AND
// Google has data for this address -- absent otherwise, never a hollow
// object. Field shapes mirror schema.md's "voting_info / division_check —
// OPTIONAL Google Civic enrichment" section exactly.
// ---------------------------------------------------------------------------

export interface VotingLocation {
  name?: string | null;
  address?: string | null;
  hours?: string | null;
}

export interface VotingInfo {
  election: { name?: string | null; date?: string | null };
  polling_locations: VotingLocation[];
  early_vote_sites: VotingLocation[];
  dropoff_locations: VotingLocation[];
  contests_present: boolean;
  source: string;
}

// A live cross-validation of our Census-derived `districts.cd` against
// Google's OCD division data for the same address -- present only when
// Google returned at least one division with a comparable congressional-
// district number to compare against.
export interface DivisionCheck {
  consistent: boolean;
  ocd_ids: string[];
}

export interface BallotResponse {
  matched_address: string;
  districts: Districts;
  races: Race[];
  warning?: string;
  voting_info?: VotingInfo;
  division_check?: DivisionCheck;
}

export type BackendResult<T> =
  | { ok: true; data: T }
  | { ok: false; reason: string; status?: number };

// ---- POST /api/insights body — profile field names exactly per CLAUDE.md ----

export interface BackendVoterProfile {
  occupation?: string;
  age_bracket?: "18_24" | "25_34" | "35_49" | "50_64" | "65_plus";
  income_bracket?: "under_35k" | "35_75k" | "75_150k" | "150k_plus";
  housing?: "renter" | "homeowner";
  kids_public_school?: boolean;
  health_coverage?: "employer" | "aca" | "medicare" | "uninsured";
  veteran?: boolean;
  small_business_owner?: boolean;
  student?: boolean;
}

export interface InsightBullet {
  text: string;
  source?: string;
}

// "Consequence horizons" (CLAUDE.md § Consequence horizons) — profile-
// personalized short-term vs. long-term read, additive to `candidates`
// above. `now` restates current-term effect of a recorded vote/position;
// `long_term` is an explicitly conditional projection and always names the
// assumption it hangs on. Optional throughout: older cache entries and the
// live-LLM path may not carry it yet.
export interface HorizonBullet {
  text: string;
  source?: string;
  basis?: string;
}

export interface LongTermHorizonBullet extends HorizonBullet {
  assumption?: string;
}

export interface CandidateHorizons {
  now?: HorizonBullet[];
  long_term?: LongTermHorizonBullet[];
}

export interface InsightsResponse {
  mode: "cached" | "live" | "unavailable";
  archetype_used?: string;
  // Present on mode "cached" — the precomputed insight doc's own top-level
  // `generated_at` (YYYY-MM-DD), passed through by app/main.py's cached
  // branch. Absent on "live"/"unavailable" (no precomputed doc behind it).
  generated_at?: string;
  candidates: Record<string, InsightBullet[]>;
  horizons?: Record<string, CandidateHorizons>;
  summary?: string;
  caveats?: string;
  detail?: string; // present on mode "unavailable"
}

// ---------------------------------------------------------------------------
// Normalization
// ---------------------------------------------------------------------------

function normalizeCandidates(
  raw: Candidate[] | Record<string, Candidate> | null | undefined
): Candidate[] {
  if (!raw) return [];
  if (Array.isArray(raw)) return raw;
  return Object.entries(raw).map(([id, c]) => ({
    ...c,
    candidate_id: c?.candidate_id ?? id,
  }));
}

function normalizeRace(raw: RawRace): Race {
  return { ...raw, candidates: normalizeCandidates(raw.candidates) };
}

// ---------------------------------------------------------------------------
// fetch helpers — typed {ok:false, reason} errors, never throws
// ---------------------------------------------------------------------------

async function fetchJSON<T>(
  url: string,
  init: RequestInit,
  timeoutMs: number
): Promise<BackendResult<T>> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(url, { ...init, signal: controller.signal, cache: "no-store" });
    let body: unknown = null;
    try {
      body = await res.json();
    } catch {
      body = null;
    }
    if (!res.ok) {
      const b = (body ?? {}) as { detail?: string; error?: string; reason?: string };
      const reason = b.detail || b.error || b.reason || `Data backend responded ${res.status}`;
      return { ok: false, reason: String(reason), status: res.status };
    }
    return { ok: true, data: body as T };
  } catch (err) {
    if (err instanceof Error && err.name === "AbortError") {
      return { ok: false, reason: "Data backend timed out, please try again" };
    }
    return {
      ok: false,
      reason:
        err instanceof Error
          ? `Data backend unreachable (${err.message})`
          : "Data backend unreachable",
    };
  } finally {
    clearTimeout(timer);
  }
}

// ---------------------------------------------------------------------------
// GET /api/ballot?address=
// ---------------------------------------------------------------------------

export async function getBallot(address: string): Promise<BackendResult<BallotResponse>> {
  const url = `${DATA_BACKEND_URL}/api/ballot?address=${encodeURIComponent(address)}`;
  const result = await fetchJSON<{
    matched_address: string;
    districts: Districts;
    races: RawRace[];
    warning?: string;
    voting_info?: VotingInfo;
    division_check?: DivisionCheck;
  }>(url, { method: "GET" }, BALLOT_TIMEOUT_MS);
  if (!result.ok) return result;
  const { data } = result;
  return {
    ok: true,
    data: {
      matched_address: data.matched_address,
      districts: data.districts,
      races: (data.races ?? []).map(normalizeRace),
      warning: data.warning,
      voting_info: data.voting_info,
      division_check: data.division_check,
    },
  };
}

// ---------------------------------------------------------------------------
// POST /api/insights {profile, race_id}
// ---------------------------------------------------------------------------

export async function postInsights(
  profile: BackendVoterProfile,
  raceId: string
): Promise<BackendResult<InsightsResponse>> {
  const url = `${DATA_BACKEND_URL}/api/insights`;
  return fetchJSON<InsightsResponse>(
    url,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ profile, race_id: raceId }),
    },
    INSIGHTS_TIMEOUT_MS
  );
}

// ---------------------------------------------------------------------------
// Adapter: teammate's VoterProfile (lib/types.ts, intake page) -> our
// backend's contract profile fields. Everything is optional both sides —
// only translate what's actually present, never invent a value.
// ---------------------------------------------------------------------------

function mapAgeBracket(a?: VoterProfile["age_bracket"]): BackendVoterProfile["age_bracket"] {
  switch (a) {
    case "18-24":
      return "18_24";
    case "25-34":
      return "25_34";
    case "35-49":
      return "35_49";
    case "50-64":
      return "50_64";
    case "65+":
      return "65_plus";
    default:
      return undefined;
  }
}

function mapIncomeBracket(i?: VoterProfile["income_bracket"]): BackendVoterProfile["income_bracket"] {
  // The two sides' brackets don't share boundaries (frontend: <30k / 30-60k /
  // 60-100k / 100-200k / 200k+; backend: under_35k / 35_75k / 75_150k /
  // 150k_plus) — map each frontend bucket to the backend bucket containing
  // most of its range (by upper bound).
  switch (i) {
    case "<30k":
      return "under_35k";
    case "30-60k":
      return "35_75k";
    case "60-100k":
      return "75_150k";
    case "100-200k":
      return "150k_plus";
    case "200k+":
      return "150k_plus";
    default:
      return undefined;
  }
}

export function mapVoterProfileToBackend(profile?: VoterProfile | null): BackendVoterProfile {
  if (!profile) return {};
  const flags = profile.flags ?? {};
  const housing: BackendVoterProfile["housing"] = flags.homeowner
    ? "homeowner"
    : flags.renter
      ? "renter"
      : undefined;

  return {
    occupation: profile.occupation || undefined,
    age_bracket: mapAgeBracket(profile.age_bracket),
    income_bracket: mapIncomeBracket(profile.income_bracket),
    housing,
    kids_public_school: flags.kids_in_public_school || undefined,
    health_coverage: flags.healthcare,
    veteran: flags.veteran || undefined,
    small_business_owner: flags.small_business_owner || undefined,
    student: flags.student || undefined,
  };
}
