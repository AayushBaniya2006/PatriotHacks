# PatriotHacks — Civic Match

**Ground truth for your ballot.** A neutral candidate alignment engine powered by a
**Kimi agent swarm** — every claim on the site traces to a verifiable source
(roll-call votes, official filings, primary documents). **No source, no claim.**

The product lives in [`civic-match/`](civic-match/) — full architecture diagrams in
[`civic-match/README.md`](civic-match/README.md), data contracts in
[`civic-match/docs/SCHEMAS.md`](civic-match/docs/SCHEMAS.md).

```
Landing → Ballot lookup (address → your actual races)
        → Voter profile + 30-issue trade-off intake
        → Kimi swarm per candidate (8 parallel agents):
            4 issue clusters · profile · qualitative record ·
            promise-vs-record · follow-the-money
        → validator (no source, no claim) → verifier double-check
        → db of politicians (cached ground truth)
        → scoring: quant issue alignment × qual record quality → OVR (60–99)
        → surfaces: matches · explanations · Q&A · scenario trees ·
          knowledge graph · debate arena · stakes + motivation
```

What a voter gets:

- **Your matches** (`/results`) — 2K-style overall rating that decomposes to ground
  truth: issue-by-issue points, record quality (integrity, transparency,
  experience), sourced warnings, and a personalized "why your vote matters" card.
- **Ground-truth profiles** (`/p/[id]`) — every position with sources and quotes,
  a promise-vs-record scorecard with receipts, follow-the-money donor↔position
  correlations (correlation, never "proof"), and grounded Q&A that refuses to
  answer beyond the indexed evidence.
- **Down the line** (`/future`) — branching scenario trees per race: succession
  chains, policy consequences, later elections — facts sourced, projections
  labeled with likelihood, branches tagged "affects you".
- **The connection graph** (`/graph`) — 157-node knowledge graph linking
  municipal ↔ state ↔ federal offices, races, people, issues, and future events.
- **Debate arena** (`/debate`) — candidate-agents hard-grounded in their real
  records, judged on fidelity with unsourced claims penalized.

Quick start:

```bash
cd civic-match
npm install
npm run seed          # auto-query Nov Texas election + swarm-research candidates
npm run seed:graph    # scenario trees + cross-level knowledge graph
npm run dev           # http://localhost:3000
```

---

## Data backend (FastAPI + TX gold dataset)

Sibling service that feeds Civic Match hard, authoritative data — built
**precompute-first** from official APIs (Census geocoder, OpenFEC,
Congress.gov, House Clerk roll-call XML, MediaWiki):

- `GET /api/ballot?address=...` — any Texas address → districts (US House,
  TX Senate/House, county) → the voter's full ballot: statewide races **plus
  their US House district race**, with candidates, campaign finance, and
  actual roll-call voting records. Every fact carries a source URL.
- `data/tx/` — gold dataset (races, candidates, precomputed per-race insight
  content for 8 voter archetypes) shipped in-repo; SQLite serving layer.
- `pipeline/export_civic_match.py` — merges our authoritative evidence
  (votes, finance) into `civic-match/data/politicians/*.json` profiles.

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload   # http://localhost:8000 — /healthz for status
```

Env vars (all optional): `OPENROUTER_API_KEY` (live insight fallback only —
precomputed insights make the app functional without it), `FEC_API_KEY` /
`CONGRESS_GOV_API_KEY` (offline pipeline only; `DEMO_KEY` fallback works).

**Railway**: two services from this monorepo — Civic Match (root
`civic-match/`, Next.js autodetect) and the data backend (repo root:
`railway.json` + `Procfile`, healthcheck `/healthz`, binds `$PORT`). Data
ships in the repo; no post-deploy loading step.
