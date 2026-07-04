# PatriotHacks — Civic Match

A neutral, source-grounded candidate alignment engine powered by a **Kimi agent swarm**.

The app lives in [`civic-match/`](civic-match/) — full architecture diagram, pipeline
docs, and run instructions are in [`civic-match/README.md`](civic-match/README.md).

```
Landing → User info → Agent staging (minimize context)
       → Kimi swarm (parallel data-endpoint agents)
       → Output report → Verifier agent (double checks)
       → db of Politicians → Scoring (quant + qual) → Presentation
```

Quick start:

```bash
cd civic-match
npm install
npm run seed    # auto-query Nov Texas election + research candidates
npm run dev
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
