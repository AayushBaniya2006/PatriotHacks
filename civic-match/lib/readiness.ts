// Client-side ballot "readiness" tracking (P0 #2, local-only/competitive-
// analysis/improvements.md). Tracks which races a voter has opened
// "What this means for you" for, so BallotSection can show
// "Reviewed X of N races" and a "You're ballot-ready" completion state.
//
// Keyed by the voter's district triple (cd|sd|hd) ONLY — never the street
// address, never any VoterProfile field. That's an explicit, approved
// product decision (docs/superpowers/specs/2026-07-03-demo-improvements-
// design.md: "readiness keyed by district triple, never the address"), so
// this key is safe to keep in localStorage indefinitely: it identifies a
// ballot shape, not a person or a place they live.
//
// Every localStorage read/write here is SSR-safe (typeof window guard) and
// tolerant of corrupt/foreign JSON (try/catch, shape-checked) so a blocked
// or broken localStorage can never break the page — it just behaves as if
// nothing has been reviewed yet.

const KEY_PREFIX = "cm_reviewed_v1:";

export interface DistrictTriple {
  cd?: string | null;
  sd?: string | null;
  hd?: string | null;
}

// 'cm_reviewed_v1:' + [cd, sd, hd].join('|') — Array.prototype.join renders
// null/undefined entries as "", so a partially-resolved ballot (e.g. no HD
// match) still gets a stable, valid key instead of the literal word "null".
export function readinessKey(districts?: DistrictTriple | null): string {
  const cd = districts?.cd ?? null;
  const sd = districts?.sd ?? null;
  const hd = districts?.hd ?? null;
  return KEY_PREFIX + [cd, sd, hd].join("|");
}

function readRawString(key: string): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(key);
  } catch {
    // Storage disabled, or a security/quota error — treat exactly like
    // "nothing reviewed yet" rather than throwing.
    return null;
  }
}

function parseReviewed(raw: string | null): Set<string> {
  if (!raw) return new Set();
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return new Set();
    return new Set(parsed.filter((v): v is string => typeof v === "string"));
  } catch {
    // Corrupt JSON — treat exactly like "nothing reviewed yet".
    return new Set();
  }
}

// key -> the last raw string we read and the Set we parsed it into. Lets
// getReviewed() return the SAME Set reference across calls when nothing
// actually changed on disk, which is required for useSyncExternalStore
// (BallotSection's readiness bar) to avoid re-rendering on every render.
const snapshotCache = new Map<string, { raw: string | null; set: Set<string> }>();

// The set of race_id strings reviewed under this district key. Never
// throws; always resolves to a (possibly empty) Set. Referentially stable
// between calls unless the underlying localStorage value actually changed.
export function getReviewed(key: string): Set<string> {
  const raw = readRawString(key);
  const cached = snapshotCache.get(key);
  if (cached && cached.raw === raw) return cached.set;
  const set = parseReviewed(raw);
  snapshotCache.set(key, { raw, set });
  return set;
}

// Marks a single race reviewed. Idempotent: calling it again for a race
// already in the set is a silent no-op (no write, no notify). Only ever
// persists race_id strings — no address, no profile, no free text.
export function markReviewed(key: string, raceId: string): void {
  if (typeof window === "undefined" || !raceId) return;
  const current = getReviewed(key);
  if (current.has(raceId)) return;
  const next = new Set(current);
  next.add(raceId);
  const raw = JSON.stringify(Array.from(next));
  try {
    window.localStorage.setItem(key, raw);
  } catch {
    // Storage full/disabled — nothing actually persisted, so don't update
    // the cache or notify subscribers of a change that didn't happen.
    return;
  }
  snapshotCache.set(key, { raw, set: next });
  notifyReviewed();
}

// ---------------------------------------------------------------------------
// Tiny same-tab pub/sub. InsightsPanel and BallotSection are sibling client
// components mounted by app/results/page.tsx; this lets InsightsPanel mark a
// race reviewed and have BallotSection's readiness bar update immediately,
// without threading new state/props through the page.
// ---------------------------------------------------------------------------

type ReviewedListener = () => void;
const listeners = new Set<ReviewedListener>();

export function subscribeReviewed(listener: ReviewedListener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function notifyReviewed(): void {
  listeners.forEach((listener) => listener());
}
