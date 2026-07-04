# Deploying to Railway

Everything needed to take this monorepo live on Railway. Local demo works without any of
this (JSON fallback + localhost); Railway is the scale path. Total setup: ~15 minutes.

## What gets created

One Railway **project** containing three components:

| Component | Source | Purpose |
|---|---|---|
| `data-backend` service | this repo, root directory `/` | FastAPI — ballot resolution, candidate data, insights |
| `civic-match` service | this repo, root directory `civic-match/` | Next.js product UI (Kimi swarm, scoring, ballot view) |
| PostgreSQL database | Railway plugin | serving layer for the gold dataset |

## Step 1 — Project + Postgres

1. railway.app → **New Project** → **Deploy from GitHub repo** → pick this repo
   (grant the GitHub app access if asked). This creates the first service.
2. In the project canvas: **+ New → Database → Add PostgreSQL**. Railway provisions it
   and exposes `DATABASE_URL` as a reference variable other services can use.

## Step 2 — Backend service (repo root)

1. On the service created from the repo: **Settings → Root Directory** = `/` (default).
   Railway's Nixpacks auto-detects Python via `requirements.txt`; deploy behavior is
   already committed in `railway.json` + `Procfile`:
   - start: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
   - healthcheck: `/healthz`
2. **Variables** tab — add:

   | Var | Value | Required? |
   |---|---|---|
   | `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` (reference variable) | recommended — without it the app serves from the in-repo JSON fallback, which also works |
   | `CORS_ORIGINS` | `https://<civic-match domain>` (add after Step 3; comma-separated for multiple) | only if the browser ever calls the backend directly — the Next.js proxy path doesn't need it |
   | `OPENROUTER_API_KEY` | your key | optional — live insight fallback only; precomputed insights ship in-repo |

3. **Settings → Networking → Generate Domain** → note `https://<backend>.up.railway.app`.
4. **Load the data into Postgres** (one-time, rerunnable after any data rebuild):
   ```bash
   # from a local checkout, with the Railway CLI linked to the backend service:
   railway run python pipeline/load_postgres.py
   # OR: copy DATABASE_URL from the Railway Postgres "Connect" tab and run locally:
   DATABASE_URL='postgresql://...' python3 pipeline/load_postgres.py
   ```
   Skipping this is non-fatal: `/healthz` shows the fallback state and the app serves
   identical data from `data/tx/*.json` (it ships in the repo — no volume needed).
5. Verify: `curl https://<backend>.up.railway.app/healthz` → `data_loaded: true`, then
   `curl 'https://<backend>.up.railway.app/api/ballot?address=601 University Dr, San Marcos, TX 78666'`.

## Step 3 — civic-match service (Next.js)

1. **+ New → GitHub Repo** → same repo → on the new service set
   **Settings → Root Directory** = `civic-match`. Nixpacks auto-detects Next.js
   (`npm ci && npm run build`, start `next start` — it binds Railway's `$PORT` automatically).
2. **Variables** tab:

   | Var | Value |
   |---|---|
   | `DATA_BACKEND_URL` | `https://${{data-backend.RAILWAY_PUBLIC_DOMAIN}}` (or paste the backend URL from Step 2.3) |
   | LLM key(s) for the Kimi swarm | whatever `civic-match/lib/llm.ts` reads — check `.env`/teammate (seed + research features need it; the ballot view does not) |

   Private networking option (faster, no egress): `http://data-backend.railway.internal:8080`
   — if you use it, confirm the backend's internal port; the public domain is the
   zero-thought default for a hackathon.
3. **Generate Domain** → this is the URL you demo: `https://<civic-match>.up.railway.app`.
4. Back on the backend service, set `CORS_ORIGINS=https://<civic-match domain>` (only
   needed if any browser code bypasses the Next proxies).

## Step 4 — Verify end-to-end

1. Open the civic-match domain → landing loads (its own data is in-repo).
2. Enter a TX address on intake → results page shows the "Your ballot" section — that
   proves civic-match → `DATA_BACKEND_URL` → FastAPI → Postgres round-trip.
3. `GET /healthz` on the backend reports `races: 46, candidates: 96, insights_cached: 46+`.

## CLI alternative (no dashboard)

```bash
npm i -g @railway/cli && railway login
railway init                                   # create project (run at repo root)
railway add --database postgres
railway up                                     # deploys the backend (root)
# second service: create in dashboard with root dir civic-match, or `railway up` from
# a config where the service's root directory is set to civic-match.
railway run python pipeline/load_postgres.py   # seed Postgres
```

## Gotchas / troubleshooting

- **Deploys re-trigger on every push** to the tracked branch (default `main`). Point the
  services at the `data-backend` branch (Service → Settings → Source → Branch) if you
  want deploys to track our branch instead — or leave on `main` and deploy on merge.
- **Healthcheck failing** → the app must bind `0.0.0.0:$PORT`. Never hardcode a port
  (already enforced in `railway.json`/`Procfile`).
- **`data_loaded: false`** → Postgres is attached but empty (run Step 2.4) — or fine to
  ignore: JSON fallback is serving.
- **Next build fails** → wrong Root Directory (must be `civic-match`), or a type error —
  run `npm run build` locally first; it's the same build.
- **CORS errors in the browser console** → set `CORS_ORIGINS` on the backend to the exact
  civic-match origin (scheme + host, no trailing slash). The Next proxy routes
  (`/api/ballot`, `/api/voter-insights`) avoid CORS entirely — prefer them.
- **Postgres from local** → use the public `DATABASE_URL` from the database's Connect tab
  (the `railway.internal` one only resolves inside Railway).
- **Costs**: trial/hobby credits cover a hackathon demo comfortably; the only always-on
  cost drivers here are the two services + db staying awake.

## Scale levers (post-hackathon)

Bump service replicas (backend is stateless — safe to scale horizontally), keep Postgres
as the single source of truth, move geocode cache from file to the Postgres table (already
supported when `DATABASE_URL` is set), add states by rerunning the pipeline with a new
state config and loading the same schema.
