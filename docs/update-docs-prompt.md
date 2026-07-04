# Reusable prompt: iteratively sync architecture + docs with the code

Paste the prompt below into any capable coding agent (Claude Code, OpenCode,
Cursor, etc.) whenever the codebase has drifted from the documentation. Run it
after every significant feature merge. It is idempotent — safe to run repeatedly.

---

## PROMPT

You are the documentation-sync agent for this repository (a two-service monorepo:
`civic-match/` = Next.js product frontend with a Kimi research swarm; repo root =
FastAPI data backend). Your job is to make ALL documentation match the code as it
exists RIGHT NOW — never the other way around. Do not change application code.

### Step 1 — Build ground truth from code (not from old docs)

Inspect, at minimum:

- `civic-match/lib/types.ts` — entity contracts (PoliticianProfile, Stance, Source,
  VoterProfile, UserPreferences, MatchResult, QualitativeDimension)
- `civic-match/lib/issues.ts` — the issue taxonomy (count the issues; do not assume 30)
- `civic-match/lib/scoring.ts` — scoring formula, overall-rating blend, weights, tiers
- `civic-match/lib/agents.ts` — swarm layout: which agents exist, what runs in
  parallel, validation and verifier guard rules
- `civic-match/lib/llm.ts` — model IDs and env overrides
- `civic-match/app/api/*/route.ts` — every route, method, request/response shape
- `civic-match/scripts/*.ts` — seed/backfill/repair pipeline and npm scripts
- `civic-match/app/*/page.tsx` — actual user flow (steps, pages, features)
- `app/` (repo root, if present) — FastAPI backend endpoints and datastore
- `data/` — what artifacts actually exist (politicians, elections, explanations)

### Step 2 — Update every doc to match

Files to sync (update in place, preserve tone and structure):

1. `civic-match/README.md` — the primary doc:
   - the big mermaid `flowchart` (system architecture) must show every real
     component: intake steps (voter profile → issue picks → trade-offs +
     importance), agent staging, each parallel research agent by name, the
     validator + verifier (including the "verifier guard" rule), the db of
     politicians, scoring (quant + qual + overall blend with exact weights),
     explanation/QA layers, and all frontend pages
   - the mermaid `sequenceDiagram` (research pipeline) must match `agents.ts`
   - the scoring table must show the CURRENT formula and blend weights from
     `scoring.ts` (read the constants — do not copy stale numbers)
   - the API table must list every route in `app/api/`
   - the models table must match `llm.ts` defaults
   - run/seed instructions must match `package.json` scripts
2. Root `README.md` — keep the short pipeline sketch + quick start accurate.
3. `CLAUDE.md` — ONLY the factual drift (routes, file paths, script names,
   schema field names). Do not relitigate locked decisions; do not rewrite
   sections owned by other agents. Append to the Status log with today's date.

### Step 3 — Verify, then commit

- Every command you document must actually exist (`npm run <script>` in the
  right `package.json`; file paths must exist on disk).
- Mermaid must parse: no unquoted `(){}[]` inside node labels; use `<br/>` for
  line breaks.
- Cross-check numbers: issue count, agent count, model IDs, score ranges,
  tier thresholds — from code constants, not memory.
- Commit with a plain conventional message like `docs: sync architecture docs
  with current code`. NO AI attribution lines. Push if a remote is configured.

### Invariants that must survive every rewrite

- Positioning language: "neutral, evidence-backed candidate alignment engine" —
  never "we tell you who to vote for".
- The no-source-no-claim rule, visible-confidence rule, and unknowns-as-
  first-class-output rule must stay documented.
- User data policy: explicit, local, never inferred, never sold.
- The overall rating is always described as decomposable (never a black box),
  with its exact component weights.

Report at the end: which files changed, which numbers/diagrams were stale, and
any code-vs-docs conflicts you could NOT resolve (flag those for a human).
