# What we're building — Abheek's side of PatriotHacks

**Product (whole team):** Civic Match — "ground truth for your ballot." A voter enters
their Texas address + a short profile, and gets their actual Nov 3, 2026 ballot with
neutral, source-backed candidate comparisons, alignment scores, and personalized
insights. Every claim traces to a verifiable source. No source, no claim. Never an
endorsement.

**Team split:**

| Side | Owner | What it is |
|---|---|---|
| `civic-match/` | Aayush + team | Next.js product UI — Kimi research swarm, scoring engine (OVR 60-99), scenario trees (`/future`), knowledge graph, debate arena |
| repo root | **Abheek (this doc)** | **The data backend** — FastAPI + precomputed Texas gold dataset from official government APIs, feeding everything above |

## What the data backend does

```
address → Census geocoder → your districts (US House + TX Senate/House + county)
        → your races (8 statewide + your US House seat, from 46 total)
        → candidates with EVIDENCE: FEC + Texas Ethics Commission money,
          real House roll-call votes, researched positions — every fact sourced
        → personalized insights per voter archetype (8 archetypes), including
          "Right now" vs "Down the road" consequence projections with stated
          assumptions — precomputed, so the demo needs zero live LLM calls
```

## Built and verified (validation gate PASS)

- **46 races / 96 candidates / 290 roll-call vote records / 79 candidates with
  finance** — from Census, OpenFEC, Congress.gov, House Clerk XML, Wikipedia,
  OpenElections, and a surgical range-request extraction of TEC's 1GB archive
  (34MB fetched, 22/22 statewide candidates matched)
- **Insights precomputed** for all 46 races (base + 8 archetypes on marquee races),
  horizons projections, all source-validated; served cached in <ms
- **Data-quality layer**: every candidate/race carries a tier (A-D) + what's missing,
  demo ranking 1-46, golden demo addresses geocode-verified
- **Storage**: gold JSON in git (audit trail) → PostgreSQL serving layer
  (`DATABASE_URL`-driven, JSONB, insights keyed by race+archetype with
  inputs_hash change-detection + write-through) with a JSON fallback that keeps
  the app fully functional with no database at all
- **Integration**: civic-match calls our `/api/ballot` + `/api/insights` through
  same-origin proxies; our evidence exported into their politician profiles
  (280 voting-record stances, 87 new House profiles); their researched stances
  imported into our positions
- **Tests**: contract suite + API-hardening abuse battery + smoke test + a
  demo-readiness gate that fails on stale cache or unsourced claims

## My GitHub issues

- **#7 ground-truth violations** — audit agent swept every bullet/source/UI claim;
  found+fixed the FEC-vs-TEC attribution bug; live link-checking done
- **#8 API hardening** — input validation, rate limiting, security headers,
  privacy-safe logging (addresses never logged), abuse tests in
  `tests/test_hardening.py`

## Run / demo

```bash
python3 -m uvicorn app.main:app --port 8010        # backend (data ships in-repo)
cd civic-match && npm run dev                       # product UI
python3 pipeline/demo_readiness_gate.py             # last check before stage
```

**Prod**: `https://web-production-17c3f.up.railway.app` (Railway, tracking `main`) —
serving from Railway Postgres, loaded + write-through verified 2026-07-04.

Follow `DEMO_PLAYBOOK.md` — 3-minute script, golden addresses, failure fallbacks.

## Docs map

`CLAUDE.md` (decisions + contracts) · `schema.md` (API/DB shapes) · `data.md`
(quant-vs-qual architecture) · `database.md` (Postgres setup) · `railway.md`
(deploy) · `data/tx/QUALITY.md` (tiers + golden addresses) · `DEMO_PLAYBOOK.md`

## Flagged for the team

- `sheets-nate` vs `nathan-sheets` — possible duplicate person, needs a human call
- Teammate's `texas.json` AG roster (Sheets/Tucker) disagrees with post-runoff
  sources (Middleton/Johnson/Oxford) — affects their AG match scores
- `sponsored_highlights` empty pipeline-wide — needs a free `CONGRESS_GOV_API_KEY`
  in `.env` + one fetcher rerun
- Promise-vs-record feature exists in their tree but is dark — demo potential
