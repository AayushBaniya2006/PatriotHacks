# CLAUDE.md

## Project: Voter candidate-info tool (PatriotHacks, July 2026)

A tool for US voters who skip voting because good candidate information is hard to find. Core loop:

1. Voter enters their Texas address + optional profile (job title, income bracket, life-situation flags).
2. App resolves their ballot live via the Census geocoder (address → US House district + TX Senate/House districts).
3. App shows the candidates in their races with accurate, source-linked info (campaign finance, voting record, positions).
4. App generates plain-English personalized insights grounded in our data with citations — e.g. "Candidate X's healthcare position likely means Y for someone with your job/income in your area."

Accuracy is the product. Never show an insight that can't be tied to a cited source. Neutral, nonpartisan framing — inform, never endorse.

## LOCKED DECISIONS (2026-07-03 — do not relitigate, we have ~2-3 hours)

- **Scope**: Texas deep-dive, Nov 3 2026 general election. Statewide races (Governor, Lt. Gov, AG, US Senate) + all 38 US House districts — covers every Texas address. TX Legislature (150 HD + ~15 SD) = stretch goal only.
- **Stack — two-service monorepo (converged with teammate's work, 2026-07-03)**:
  - **`civic-match/` = the product frontend** (teammate-owned): Next.js 16 + React 19 + Tailwind 4. Kimi research swarm → validated `PoliticianProfile` JSONs (`civic-match/data/politicians/*.json`, contract in `civic-match/lib/types.ts`) → pure scoring engine → alignment UI. ⚠️ Before writing ANY civic-match code, read `civic-match/AGENTS.md`: this Next.js version postdates training — consult `node_modules/next/dist/docs/` first.
  - **Repo root = the data backend** (ours): FastAPI + precomputed TX gold dataset from official APIs. Supplies what civic-match lacks: address→district resolution, all 38 US House races, and authoritative evidence (FEC finance, House Clerk roll-call votes, Congress.gov records).
  - **Integration contract**: (1) `GET /api/ballot?address=` gives civic-match per-address ballots; (2) `pipeline/export_civic_match.py` merges our sourced evidence into their `PoliticianProfile` shape non-destructively (their slug convention is `firstname-lastname` via `lib/db.ts slugify` — ours is lastname-firstname internally; the exporter translates); (3) `civic-match/data/elections/texas-house.json` (new file) carries per-district House races — never rewrite their `texas.json`.
  - The fleet's `app/static/index.html` remains a standalone demo fallback only.
- **Storage (pivoted to Postgres 2026-07-03)**: bronze→gold pipeline. Raw fetches in `data/tx/raw/`, gold artifacts `data/tx/races.json` + `candidates.json` (source of truth, committed to git), served through **PostgreSQL** (JSONB columns, driven by `DATABASE_URL`; Railway Postgres in prod, `docker-compose.yml` locally where Docker exists) loaded idempotently by `pipeline/load_postgres.py`. **JSON fallback keeps the app fully functional with no DATABASE_URL** (this WSL box has no Docker/Postgres — demo runs on fallback until one is provisioned). SQLite is REMOVED per user decision — `data/tx/app.db` is deprecated/gitignored.
- **Query primitives**: ALL data access goes through `app/datastore.py` — `get_ballot(cd,sd,hd)`, `get_race(id)`, `get_candidate(id)`, `list_races(level)`, `search_candidates(q)`, `get_insights(race_id)`, `stats()` — backed by Postgres when `DATABASE_URL` is set, else gold JSON. Endpoints never touch storage directly. (MCP-shaped for a post-hackathon FastMCP wrap.)
- **Contract doc**: `schema.md` at repo root is the authoritative, detailed map — Postgres DDL, every API request/response shape with examples, frontend payloads, civic-match integration, env vars, failure modes. Keep it in sync with code changes.
- **Precompute-first**: everything precomputable IS precomputed at build time — the gold dataset, the Postgres load (or gold-JSON fallback), and per-race insight content (base + 8 voter archetypes) in `data/tx/insights/{race_id}.json`. Runtime = cache reads + Census geocoder (itself cached in `data/cache.db`) + optional live LLM only on cache miss. **The demo works with zero LLM key.**
- **Insight archetypes** (exact keys): renter_young_worker, homeowner_parent, small_business_owner, healthcare_aca_or_uninsured, medicare_retiree, veteran, student, rural_agriculture. Profile→archetype mapping is deterministic in the backend.
- **Hosting**: Railway — nixpacks autodetect, `railway.json` + `Procfile` (`uvicorn app.main:app --host 0.0.0.0 --port $PORT`), `/healthz` healthcheck, data ships in the repo, only env var is optional `OPENROUTER_API_KEY`.
- **LLM runtime (optional live path)**: OpenRouter (OpenAI SDK), model `anthropic/claude-sonnet-4.5`, used only when a race has no precomputed insights.
- **MCP**: SKIPPED for runtime — evidence-based (OpenRouter API has no native MCP; `@openrouter/agent` 0.7.2 contains zero MCP support; Anthropic's `mcp_servers` connector would require a provider switch + public HTTPS server). Full eval in `data/endpoint_inventory.json`.
- **Timeline**: ~2-3 hours total. Solo human + subagent fleet. Cut anything that threatens the end-to-end demo.

## Hackathon rules of engagement

- Thin end-to-end slice first (one address → ballot → candidates → one cited insight), then widen.
- No speculative abstractions, no gold-plating, nothing that won't appear in the demo.
- A flaky data source gets ~20 minutes, then we drop or mock it and move on.
- Demo fallback: pre-cache full responses for 3 addresses (San Marcos, Houston, Dallas) so the demo works even if an API dies live.

## Model orchestration policy

| Model | Use for |
|---|---|
| **Fable** (main session) | Architecture, schema design, integration, hard debugging, final review |
| **Opus** | Trivial/simple tasks: small edits, glue code, quick fixes |
| **Sonnet** | Bulk parallel work: scraping, endpoint probing, data fetching/normalization, tests, boilerplate, frontend/backend scaffolding |

Fan Sonnet subagents out in parallel; keep judgment, schema decisions, and synthesis in Fable.

## Data schema (agents write these exact shapes)

`data/tx/races.json`:
```json
{"state":"TX","election_date":"2026-11-03","races":[
  {"race_id":"tx-gov-2026","office":"Governor of Texas","level":"state","district":null,
   "candidate_ids":["..."],"context":{"last_result":"...","sources":["url"]}}
]}
```
`level`: `federal|state|state_leg`. `district`: `"TX-15"` / `"SD-26"` / `"HD-45"` / `null` (statewide).

`data/tx/candidates.json` (keyed by candidate_id, slug like `abbott-greg`):
```json
{"abbott-greg":{"name":"...","party":"...","office":"...","district":null,"incumbent":true,
  "fec_id":null,
  "finance":{"receipts":0,"disbursements":0,"cash_on_hand":0,"as_of":"date","source":"url"},
  "record":{"key_votes":[{"vote":"...","position":"...","date":"...","source":"url"}],
             "sponsored_highlights":["..."],"source":"url"},
  "positions":[{"issue":"healthcare","summary":"...","source":"url"}],
  "sources":["url"]}}
```

Every fact carries a `source` URL. Missing data = omit the field, never invent.

District resolution at runtime: Census geocoder returns CD + SLDU + SLDL GEOIDs → look up statewide races + that CD race (+ SD/HD races if stretch goal lands).

## API contract (backend ⇄ any JS frontend)

Stateless JSON over HTTP; nothing about the user is ever stored (address + profile live only in the request).

- `GET /api/ballot?address=<free text>` → 200 `{matched_address, districts:{cd:"TX-35", sd:"SD-21", hd:"HD-45", county}, races:[{race_id, office, level, district, context, candidates:[{candidate_id, name, party, incumbent, fec_id, finance{receipts,disbursements,cash_on_hand,as_of,source}, record{key_votes:[{bill,position,plain_english,date,source}], sponsored_highlights}, positions:[{issue,summary,source}], sources}]}], warning?}` · 422 address no-match · 400 non-Texas · 503 geocoder down.
- `POST /api/insights` body `{profile, race_id}` → 200 `{mode:"cached"|"live"|"unavailable", archetype_used, candidates:{<candidate_id>:[{text, source}]}, summary, caveats}`.
- `GET /healthz` → `{status, data_loaded, races, candidates, insights_cached}`.
- `profile` object (all fields optional): `{occupation:string, age_bracket:"18_24"|"25_34"|"35_49"|"50_64"|"65_plus", income_bracket:"under_35k"|"35_75k"|"75_150k"|"150k_plus", housing:"renter"|"homeowner", kids_public_school:bool, health_coverage:"employer"|"aca"|"medicare"|"uninsured", veteran:bool, small_business_owner:bool, student:bool}`.
- **CORS**: FastAPI must allow the civic-match origins (localhost:3000 + its Railway/Vercel domain) — add CORSMiddleware in the integration pass.

## Voter profile fields (frontend form)

Address (required). Optional: occupation (free text), age bracket, income bracket, and flags: homeowner/renter, kids in public school, health coverage (employer/ACA/medicare/uninsured), veteran, small-business owner, student.

## Insight engine rules

Precomputed-first: POST `/api/insights` {profile, race_id} maps the profile to an archetype (deterministic precedence: veteran → small_business_owner → student → healthcare_aca_or_uninsured → medicare_retiree → homeowner_parent → renter_young_worker → rural_agriculture → base) and serves `data/tx/insights/{race_id}.json`. Live OpenRouter generation only when no cache file exists AND `OPENROUTER_API_KEY` is set. Hard rules for ALL insight content, precomputed or live: only claims traceable to the race's candidate JSON; every bullet carries its source URL; neutral comparative tone, never endorse; explicit uncertainty ("no public data in our set on X") when data is missing; 2-3 bullets per candidate, ~8th-grade reading level.

## Sourcing + git policy

- Prefer existing public APIs over scraping, always. Every current source is an API (MediaWiki API for Wikipedia content). HTML scraping is a last resort and needs a logged justification.
- Commit at every milestone and at every agent completion. **Update the CLAUDE.md Status log with EVERY push** — one line: what shipped, where it lives. **Push ONLY to the `data-backend` branch — NEVER push to `main`.** `main` moves via PR merges only. Fetch origin and merge `origin/main` into `data-backend` regularly to stay conflict-free.
- **Commits carry NO AI attribution — no `Co-Authored-By: Claude`, no "Generated with Claude Code" lines.** Author is the repo's configured git user, plain conventional messages.
- Never commit `.env` or `data/cache.db`.

## Data sources (probed 2026-07-03 — see data/endpoint_inventory.json for live status)

Tier 1: Census Geocoder (no key), OpenFEC (`DEMO_KEY`/free key), Congress.gov API (free key), Wikipedia 2026 TX race pages (candidate lists post-primary), House Clerk roll-call XML (no key), Open States v3 (free key).
Tier 2 (stretch): Texas Ethics Commission (state campaign finance — not in original docx), OpenElections TX CSVs, Federal Register, USAspending, LegiScan.
Skip: courts stack, US Code bulk, EAC/NIST, SAM.gov, Google Civic representatives (deprecated 2025), all non-US sources.

### Keys — human action items

`.env` (copy from `.env.example`):
- `OPENROUTER_API_KEY` — **REQUIRED for insights** (missing as of 2026-07-03)
- `CONGRESS_GOV_API_KEY` — https://api.congress.gov/sign-up/ (instant)
- `FEC_API_KEY` — https://api.open.fec.gov/developers/ (instant; `DEMO_KEY` works meanwhile)
- `OPENSTATES_API_KEY` — https://openstates.org/accounts/signup/ (stretch goal only)

## Run

```
pip install -r requirements.txt
uvicorn app.main:app --reload          # data backend, http://localhost:8000 (/healthz)

cd civic-match && npm install
npm run seed                            # auto-discover TX races + research candidates
npm run dev                             # the product UI (Next.js)
```

## Status log

- 2026-07-03: Scope locked (TX, 2-3h). 16-agent probe fleet ran against all docx endpoints — 11/15 usable immediately, `DEMO_KEY` confirmed working on Congress.gov + OpenFEC + GovInfo; Open States/LegiScan/Google Civic key-gated (cut/stretch); LDA API sunsets 2026-07-31. Full inventory: `data/endpoint_inventory.json`.
- 2026-07-03: MCP evaluated → skipped for runtime; datastore primitives keep the door open.
- 2026-07-03: 9-agent build fleet launched: 4 fetchers → merge/validate (gold JSON + SQLite) → 3 insight-precompute agents, alongside backend (datastore + Railway) + frontend. Fable integration pass after.
- 2026-07-03: Pulled teammate's `civic-match/` (Next.js product: Kimi swarm, scoring engine, statewide TX races + 8 researched profiles). CONVERGED: we are the data backend; no second frontend gets built. Codex session writing contract tests + demo precache in parallel.
- 2026-07-03: Build fleet landed, validation PASS (46 races / 96 candidates / 290 vote records). Known gaps in `data/tx/unjoined_report.json`: 7 incumbents lost FEC joins to 2025 redistricting; positions[] empty pipeline-wide; sponsored_highlights empty (DEMO_KEY 429). Committed+pushed `ac341e6`.
- 2026-07-03: DB pivot SQLite→Postgres ordered; contract fixes queued (candidates dict→array, insights-shape selection, housing field). Wiring v2 running against teammate's latest intake/results (they shipped their own profile intake — do not duplicate). Reverse-bridge importing their researched stances into our positions[].
- 2026-07-03 (civic-match session, all pushed to main): shipped the full product loop — 30-issue trade-off intake + voter profile (`/intake`), 2K-style OVR scoring (quant issue alignment × qual record quality − conflict penalty, `lib/scoring.ts`), grounded explanations (`/api/explain`), markdown Q&A (`/api/qa`). All frontend content/config lives in the file DB (`data/config/`, `npm run export:config`) — nothing hardcoded.
- 2026-07-03 (civic-match agents): Kimi swarm per candidate now runs 8 agents — 4 issue clusters + profile + qualitative (integrity/public_interest/transparency/experience) + accountability (promise-vs-record scorecard w/ receipts) + follow-the-money (FEC/TEC donors ↔ position correlations, correlation-not-proof framing). Verifier guard ignores mass-nulling corrections. Backfill scripts: `backfill-qual|promises|finance.ts`, `repair.ts`.
- 2026-07-03 (civic-match surfaces): `/ballot` (address → races via our FastAPI `/api/ballot`, statewide fallback), `/future` (per-race scenario trees, fact-vs-inference + likelihood + "affects you" tags), `/graph` (157-node cross-level knowledge graph, d3-force), `/debate` (record-grounded candidate agents + fidelity judge penalizing unsourced claims), stakes banner + personalized nonpartisan motivation card (`/api/motivate`, hook→info→CTA). Schema reference: `civic-match/docs/SCHEMAS.md`. Docs-sync prompt: `docs/update-docs-prompt.md`.
- 2026-07-03: 9 TX candidates fully researched + cached in `civic-match/data/politicians/` (stances/qual/promises/finance all sourced); scenario trees + stakes + graph seeded for all 4 statewide races. Demo works with zero live LLM calls on the cached path.
- 2026-07-03: Root README rewritten around ground truth + full civic-match surface list; data-backend section untouched. Pushed with CLAUDE.md rule compliance.
- 2026-07-04: Full-site audit (profiles, scenarios, graph, stakes, code) → 6 GitHub issues filed and assigned: #6 data gaps (golkelj), #7 ground-truth violations (lolout1), #8 API hardening (lolout1), #9 UX polish (SulaymanB2024), #10 ballot e2e + Railway deploy (AayushBaniya2006), #11 neutrality eval (golkelj). Roles: Aayush+lolout1=backend, SulaymanB2024=UI, golkelj=data.
- 2026-07-04: Docs alignment pass — civic-match README swarm diagram now shows all 8 agents + /api/config + /api/voter-insights rows; SCHEMAS.md lists the voter-insights bridge; root README SQLite→Postgres reference fixed; CLAUDE.md precompute line de-SQLited; ballot route now honors DATA_BACKEND_URL (railway.md's canonical env) with BALLOT_BACKEND_URL as alias. Committed on postgres-migration (main is PR-only).
