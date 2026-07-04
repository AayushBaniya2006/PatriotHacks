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
- **Storage**: bronze→gold pipeline. Raw fetches in `data/tx/raw/`, gold artifacts `data/tx/races.json` + `candidates.json` (source of truth, committed to git), served through **SQLite** (`data/tx/app.db`, indexed, read-only at runtime) with JSON fallback.
- **Query primitives**: ALL data access goes through `app/datastore.py` — `get_ballot(cd,sd,hd)`, `get_race(id)`, `get_candidate(id)`, `list_races(level)`, `search_candidates(q)`, `get_insights(race_id)`, `stats()`. Endpoints never touch files directly. (These primitives are MCP-shaped — a post-hackathon FastMCP wrap is trivial.)
- **Precompute-first**: everything precomputable IS precomputed at build time — the gold dataset, the SQLite index, and per-race insight content (base + 8 voter archetypes) in `data/tx/insights/{race_id}.json`. Runtime = cache reads + Census geocoder (itself cached in `data/cache.db`) + optional live LLM only on cache miss. **The demo works with zero LLM key.**
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

## Voter profile fields (frontend form)

Address (required). Optional: occupation (free text), age bracket, income bracket, and flags: homeowner/renter, kids in public school, health coverage (employer/ACA/medicare/uninsured), veteran, small-business owner, student.

## Insight engine rules

Precomputed-first: POST `/api/insights` {profile, race_id} maps the profile to an archetype (deterministic precedence: veteran → small_business_owner → student → healthcare_aca_or_uninsured → medicare_retiree → homeowner_parent → renter_young_worker → rural_agriculture → base) and serves `data/tx/insights/{race_id}.json`. Live OpenRouter generation only when no cache file exists AND `OPENROUTER_API_KEY` is set. Hard rules for ALL insight content, precomputed or live: only claims traceable to the race's candidate JSON; every bullet carries its source URL; neutral comparative tone, never endorse; explicit uncertainty ("no public data in our set on X") when data is missing; 2-3 bullets per candidate, ~8th-grade reading level.

## Sourcing + git policy

- Prefer existing public APIs over scraping, always. Every current source is an API (MediaWiki API for Wikipedia content). HTML scraping is a last resort and needs a logged justification.
- Commit at every milestone (docs locked, data landed, app landed, integration green) and push if a remote exists.
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
