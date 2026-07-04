# Demo-Winning Improvements — Design (approved 2026-07-03)

Source requirements: `local-only/competitive-analysis/improvements.md` (P0/P1, UX rules,
do-not-build, acceptance criteria). User approvals: readiness keyed by **district triple
(cd|sd|hd), never the address**; **P0 + P1 scope** (share card skipped). This lane is
**uncommitted** until explicitly authorized.

## Components

1. `civic-match/lib/readiness.ts` (new) — `getReviewed(key)`, `markReviewed(key, raceId)`,
   `readinessKey(districts)` → `cm_reviewed_v1:{cd|sd|hd}` in localStorage (race_id set).
   No address, no profile data persisted.
2. `components/ballot/BallotSection.tsx` — readiness bar header ("Reviewed X of N races",
   progress, "You're ballot-ready ✓"); plain-English confidence labels
   (A Strong / B Good / C Partial / D Thin public record; letter + missing[] in tooltip);
   `<details>` "How we know" per race (finance source type, votes source, coverage counts,
   missing caveat — all from existing payload fields); plain labels (Money / Votes /
   What this means for you / Sources); advanced concepts behind details.
3. `components/ballot/InsightsPanel.tsx` — opening insights calls `markReviewed`.
4. `civic-match/app/results/page.tsx` — remove duplicated "Record quality (qual)" text
   (surgical); mount VotingPlan; prefetch top demo-ranked race's insights post-ballot-load.
5. `components/ballot/VotingPlan.tsx` (new) — Election Day (2026-11-03) vs early voting;
   time-window select; client-side `.ics` blob download; VoteTexas.gov link; no polling-place
   claims.
6. `pipeline/demo_readiness_gate.py` — golden-address assertions: expected race present,
   insights `mode:"cached"`, every bullet sourced.
7. Playwright smoke (optional, timeboxed): intake → results → Your ballot → source link →
   insights panel screenshot; skipped honestly if install is heavy.

## Error handling / constraints

localStorage guarded (SSR-safe, try/catch, quota). Prefetch failure = silent (button path
unchanged). `.ics` generation pure client-side. Do-not-build list enforced (no new live API
deps, no polling-place map, no persuasive language). `npm run build` gates every change.
Neutrality invariant: identical affordances for all candidates.

## Testing

Build gate; existing contract/hardening suites must stay green; gate script run post-change;
manual acceptance walk per the doc's criteria.
