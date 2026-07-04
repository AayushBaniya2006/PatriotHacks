# PatriotHacks / Civic Match — Technical Architecture Deep Dive

Generated from the uploaded repository `PatriotHacks-main (1)(3).zip` on July 3, 2026.

This file describes the code that is present in the repo, not the product the repo might become after another build pass. Where the docs describe a future or optional capability, I mark it as optional, fallback, or risk.

---

## 1. What this repo is

PatriotHacks is a voter-alignment product for Texas elections. The product intent is straightforward: a user enters a location, sees the elections that apply to them, answers a short set of preference questions, and receives sourced candidate comparisons, match scores, explanations, candidate Q&A, projections, and supporting civic context.

The repo is not a single app. It is a two-app system plus an offline data pipeline:

1. **FastAPI data backend at the repository root**  
   This serves ballot lookup and precomputed voter insight blocks. It is built around a precompute-first data model. The hot path is mostly JSON/Postgres reads, not live scraping or live LLM calls.

2. **Next.js product frontend under `civic-match/`**  
   This is the primary user-facing app. It owns the landing page, intake flow, ballot wizard, match results, candidate profile pages, scenario tree, graph view, debate UI, and most LLM-assisted product surfaces.

3. **Python data pipeline under `pipeline/`**  
   This builds the Texas race/candidate dataset, pulls or enriches official records, validates quality, exports data into the Next app, precomputes insights, and optionally loads Postgres.

4. **Data stores**  
   The system can run from checked-in JSON files. It can also use Postgres. There are two Postgres patterns: fixed civic tables used by the FastAPI backend, and a generic KV table used by the Next app.

The strongest architectural idea is **precompute first, generate only on fallback**. That fits the product. Voter tools need low latency, high auditability, and clear source boundaries. The implementation mostly honors that: ballot lookup uses cached district/race data, insight text is precomputed by race/archetype, and LLM calls are not in the default backend path unless insight files are missing.

---

## 2. Current repository shape

```text
PatriotHacks-main/
  README.md
  schema.md
  database.md
  railway.md
  data.md
  requirements.txt
  Procfile
  railway.json
  docker-compose.yml

  app/                         # FastAPI backend
    main.py                    # HTTP app, geocoder, ballot endpoint, insights endpoint
    datastore.py               # JSON/Postgres data access, geocode cache, ballot assembly
    insights.py                # OpenRouter fallback generation for backend insights
    google_civic.py            # Optional Google Civic enrichment
    middleware.py              # Body cap, rate limit, security headers
    static/index.html          # Legacy/static frontend served by FastAPI root

  pipeline/                    # Offline data build and quality pipeline
    build_dataset.py
    fetch_fec.py
    fetch_votes.py
    fetch_context.py
    fetch_statewide.py
    fetch_tec_finance.py
    import_civicmatch_positions.py
    precompute_horizons.py
    precompute_marquee_insights.py
    load_postgres.py
    validate_data.py
    score_quality.py
    smoke_backend.py
    ...

  data/tx/                     # Backend gold data
    races.json
    candidates.json
    geocode_seed.json
    quality_report.json
    insights/*.json

  civic-match/                 # Next.js product app
    app/                       # App Router pages and API routes
    components/                # UI components
    lib/                       # Core TS modules: scoring, store, agents, graph, etc.
    data/                      # File-backed app data
    scripts/                   # Seed, import/export, validate scripts
    package.json
    tsconfig.json
```

Rough code size, excluding `node_modules`:

| Language group | Files | Lines |
|---|---:|---:|
| Python | 35 | 13,240 |
| TypeScript | 41 | 4,015 |
| TSX / React | 15 | 4,180 |

Current data volumes in the uploaded repo:

| Dataset | Count / shape |
|---|---:|
| Backend races in `data/tx/races.json` | 46 |
| Backend candidates in `data/tx/candidates.json` | 96 |
| Race levels | {'state': 7, 'federal': 39} |
| Seeded geocode records | 8 |
| Backend insight files | 46 |
| Backend insight archetype coverage | `{'base': 46, 'renter_young_worker': 10, 'homeowner_parent': 10, 'small_business_owner': 10, 'healthcare_aca_or_uninsured': 10, 'medicare_retiree': 10, 'veteran': 10, 'student': 10, 'rural_agriculture': 10}` |
| Frontend issue taxonomy entries | 30 |
| Frontend politician profiles | 96 |
| Frontend profile statuses | `{'partial': 87, 'complete': 9}` |
| Frontend profile stance count | min 0, max 27, avg 4.5 |
| Frontend graph | 157 nodes / 287 edges |

Backend candidate source coverage from `data/tx/quality_report.json`:

| Source field | Count | Coverage |
|---|---:|---:|
| FEC finance | 79 | 82.3% |
| Clerk key votes | 37 | 38.5% |
| Civic Match positions | 8 | 8.3% |
| Background bio | 24 | 25.0% |
| FEC or Bioguide ID | 67 | 69.8% |

Important distinction: the backend candidate dataset has finance coverage on 79/96 candidates. The frontend politician profile files have richer profile objects, but only 9/96 include a `finance` block, 9/96 include qualitative dimensions, and 8/96 include promise/accountability records. Those are separate data layers.

---

## 3. Runtime architecture

The deployed product has two HTTP servers in normal development:

- **Next.js** on `localhost:3000` for the user interface and most product API routes.
- **FastAPI** on `localhost:8000` for ballot and insight data.

The browser should mostly talk to same-origin Next routes. The Next app then calls the FastAPI backend server-side through `DATA_BACKEND_URL`. That is a good boundary. It avoids exposing the backend URL as a public browser config and lets the frontend normalize backend failure states.

```mermaid
flowchart LR
  U[Browser user]
  N[Next.js app\ncivic-match]
  NA[Next API routes]
  F[FastAPI backend\nrepo root app/]
  DS[app/datastore.py]
  J1[(Backend JSON\ndata/tx/*.json)]
  J2[(Next file DB\ncivic-match/data/*)]
  PG[(Postgres optional)]
  C[Census Geocoder]
  G[Google Civic optional]
  L[OpenRouter optional]

  U --> N
  N --> NA
  NA --> J2
  NA --> F
  F --> DS
  DS --> PG
  DS --> J1
  F --> C
  F --> G
  F --> L
```

The default ballot flow:

```mermaid
sequenceDiagram
  participant B as Browser
  participant N as Next /api/ballot
  participant F as FastAPI /api/ballot
  participant D as datastore.py
  participant C as Census Geocoder
  participant P as Postgres or JSON cache

  B->>N: GET /api/ballot?address=...
  N->>F: GET DATA_BACKEND_URL/api/ballot?address=...
  F->>F: validate + clean address
  F->>D: geocode_cache_get(address)
  D->>P: runtime cache / seed cache lookup
  alt cache hit
    P-->>D: matched address + districts
    D-->>F: cached districts
  else cache miss
    F->>C: geographies/onelineaddress
    C-->>F: Census match + geographies
    F->>D: geocode_cache_put(address, districts)
  end
  F->>D: get_ballot(cd, sd, hd)
  D-->>F: matching federal/state races with candidates embedded
  F-->>N: ballot response
  N-->>B: normalized ballot response
```

The default match flow:

```mermaid
sequenceDiagram
  participant B as Browser
  participant N as Next app
  participant API as Next API
  participant FS as file/KV store

  B->>N: complete location + priority intake
  N->>API: GET /api/politicians
  API->>FS: list cached politician profiles
  FS-->>API: profiles
  API-->>N: profile summaries
  N->>API: POST /api/match { prefs, politician_ids }
  API->>FS: read candidate profiles
  API->>API: scoreMatch(prefs, profile)
  API-->>N: sorted match results
  N-->>B: result cards + evidence affordances
```

The fallback research flow:

```mermaid
sequenceDiagram
  participant B as Browser
  participant API as Next /api/research
  participant A as lib/agents.ts
  participant O as OpenRouter
  participant S as file/KV store

  B->>API: POST /api/research { name, force? }
  API->>S: check existing profile
  alt cached and not force
    S-->>API: profile
    API-->>B: SSE complete event
  else research needed
    API->>A: researchPolitician(name, onEvent)
    A->>O: cluster agents + profile + qualitative + accountability
    O-->>A: structured JSON fragments
    A->>A: validate, clamp, dedupe, verifier pass
    A->>O: finance agent after validated stances
    O-->>A: sourced finance JSON
    A->>S: save PoliticianProfile
    A-->>API: complete event
    API-->>B: SSE progress + complete
  end
```

The product is therefore split by responsibility:

| Layer | Responsibility | Should not own |
|---|---|---|
| Browser React pages | User flow, local preference state, progressive disclosure, visualizations | Secrets, live government calls, direct OpenRouter calls |
| Next API routes | Same-origin API, preference scoring, LLM product features, server-side backend proxy | District extraction, official backend race assembly |
| FastAPI backend | Address-to-district lookup, geocode caching, ballot assembly, cached insight selection | Full UI, candidate profile research UI |
| `app/datastore.py` | Backend data access; Postgres-first/JSON fallback | Request validation, HTTP-specific behavior |
| Pipeline scripts | Build, clean, validate, precompute, load | Runtime UI concerns |
| Postgres / JSON | Data persistence | Business logic |

---

## 4. Backend architecture: FastAPI service

The backend is centered on `app/main.py` and `app/datastore.py`.

### 4.1 Backend stack

`requirements.txt` declares:

```text
openai>=1.0.0
python-dotenv>=1.0.0
fastapi>=0.110.0
uvicorn[standard]>=0.29.0
httpx>=0.27.0
pytest
psycopg[binary,pool]>=3.1
```

Main dependencies:

- `fastapi` and `uvicorn[standard]` for the HTTP service.
- `httpx` for the Census and Google Civic HTTP calls.
- `psycopg[binary,pool]` for Postgres when `DATABASE_URL` is configured.
- `openai` because `app/insights.py` uses the OpenAI-compatible client against OpenRouter.
- `pytest` for the root Python test suite.

### 4.2 Backend endpoints

| Surface | Method | Path | Handler | Purpose |
|---|---:|---|---|---|
| FastAPI backend | GET | `/` | `app/main.py::read_index` | Serves the legacy static ballot UI from `app/static/index.html`. |
| FastAPI backend | GET | `/healthz` | `app/main.py::healthz` | Healthcheck and data-load status for Railway. |
| FastAPI backend | GET | `/api/ballot?address=` | `app/main.py::api_ballot` | Address validation, geocode cache lookup, Census geocode on miss, district extraction, ballot assembly, optional Google Civic enrichment. |
| FastAPI backend | POST | `/api/insights` | `app/main.py::api_insights` | Archetype selection, cached insight lookup, OpenRouter fallback only if cache is missing and key is present. |
| Next app | GET | `/api/config` | `civic-match/app/api/config/route.ts` | Returns issue taxonomy and UI copy/config from the file/KV config store. |
| Next app | GET/POST | `/api/election` | `civic-match/app/api/election/route.ts` | Gets cached state election metadata or runs live election discovery. |
| Next app | GET | `/api/politicians` | `civic-match/app/api/politicians/route.ts` | Lists cached politician profile summaries. |
| Next app | POST | `/api/research` | `civic-match/app/api/research/route.ts` | Server-sent research stream for a candidate profile. Uses cached profile unless forced. |
| Next app | POST | `/api/match` | `civic-match/app/api/match/route.ts` | Scores candidate profiles against user preferences. |
| Next app | POST | `/api/explain` | `civic-match/app/api/explain/route.ts` | Generates or retrieves cached explanation for one match result. |
| Next app | POST | `/api/qa` | `civic-match/app/api/qa/route.ts` | Evidence-only Q&A over one cached candidate profile. |
| Next app | GET | `/api/ballot?address=` | `civic-match/app/api/ballot/route.ts` | Server-side proxy to FastAPI `/api/ballot`; cached statewide fallback if backend is down. |
| Next app | POST | `/api/voter-insights` | `civic-match/app/api/voter-insights/route.ts` | Maps frontend voter profile shape to backend profile and proxies insight generation/lookup. |
| Next app | GET | `/api/scenario` | `civic-match/app/api/scenario/route.ts` | Lists or returns scenario trees. |
| Next app | GET | `/api/graph` | `civic-match/app/api/graph/route.ts` | Returns full graph or focus-node neighborhood. |
| Next app | GET | `/api/stakes` | `civic-match/app/api/stakes/route.ts` | Returns election stakes copy/data. |
| Next app | POST | `/api/motivate` | `civic-match/app/api/motivate/route.ts` | Generates cached civic motivation cards from preferences and cached profile version. |
| Next app | POST | `/api/debate` | `civic-match/app/api/debate/route.ts` | Streams candidate-agent debate using evidence packs. |


### 4.3 Request hardening

The backend installs three custom middleware classes before CORS:

1. **Body size cap**  
   `BodySizeLimitMiddleware` rejects oversized requests at 16 KB. It checks `Content-Length` when present and also wraps request body reads so chunked bodies cannot bypass the cap. Oversized requests return JSON 413.

2. **Rate limit**  
   `RateLimitMiddleware` applies an in-process sliding window to `/api/*` routes. The default is 60 requests per 60 seconds per ASGI client IP. It intentionally ignores `X-Forwarded-For`, which avoids trusting spoofed client headers but also means behavior behind a proxy depends on how Railway/Uvicorn expose client addresses. The response includes `Retry-After` on 429.

3. **Security headers**  
   `SecurityHeadersMiddleware` adds `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, and `Cache-Control: no-store` for `/api/*` responses.

CORS is added last, which means it becomes outermost in Starlette middleware ordering. That matters because CORS headers still need to attach to early 429/413 responses produced by the hardening middleware.

The global exception handler logs method and path only, not query string or body. That is the right default for a tool that receives home addresses and preference profiles.

### 4.4 Address validation and geocoding

The backend accepts an address through `GET /api/ballot?address=...`.

Before cache lookup or network calls, it applies a simple validation gate:

- Rejects ASCII control characters.
- Rejects addresses longer than 200 characters.
- Rejects trimmed strings shorter than 3 characters.
- Uses the same friendly 422 message for these rejections and for geocoder “no match” cases.

The live geocoder is the Census geocoder endpoint:

```text
https://geocoding.geo.census.gov/geocoder/geographies/onelineaddress
```

It uses:

- `benchmark=Public_AR_Current`
- `vintage=Current_Current`
- `format=json`

The backend extracts districts from Census geography layers:

| District field | Census layer | Output format |
|---|---|---|
| Congressional district | `119th Congressional Districts` | `TX-01`, `TX-20`, etc. |
| State Senate | `2024 State Legislative Districts - Upper` | `SD-14`, etc. |
| State House | `2024 State Legislative Districts - Lower` | `HD-49`, etc. |
| County | `Counties` | County name string |

The code strips the Texas FIPS prefix from Census `GEOID` values before formatting districts.

Failure behavior:

- Timeout: one retry after a short backoff; then 503.
- No match: 422 with friendly address retry message.
- Non-Texas match: 422 with the same friendly message.
- Explicit test escape hatch: `GEOCODER_DISABLED=1` forces the 503 path.

This means the live geocoder is a dependency only on cache misses. The code deliberately tries cache layers first.

### 4.5 Geocode cache layers

`app/datastore.py` resolves cached addresses in this order:

1. **In-process LRU cache**  
   An `OrderedDict` capped at 256 entries.

2. **Runtime cache**  
   - Postgres `geocode_cache` table when `DATABASE_URL` is configured and reachable.
   - JSON file `data/geocode_cache.json` when Postgres is not active.

3. **Committed seed cache**  
   `data/tx/geocode_seed.json`, which currently contains 8 seeded address records.

4. **Live Census geocoder**  
   Used only when every cache layer misses.

JSON writes are atomic: write temp file, then `os.replace`. That avoids partially written JSON cache files if a process crashes mid-write.

The Google Civic enrichment payload uses the same cache entry under `civic_json` when that optional feature is active.

### 4.6 Ballot assembly

The backend data model has two primary gold files:

- `data/tx/races.json`
- `data/tx/candidates.json`

`get_ballot(cd, sd, hd)` assembles races by district. It includes:

- statewide races where `district is None`
- congressional races matching `cd`
- state senate races matching `sd`
- state house races matching `hd`

In the current uploaded dataset, the race levels are `{'state': 7, 'federal': 39}`. The docs and DDL allow `state_leg`, but the current checked-in race data has federal and state races only.

Candidates are embedded into each race response. `datastore.py` injects `candidate_id` if a candidate is retrieved from a key-value JSON map and does not already carry its id internally.

The ballot response includes:

- `matched_address`
- `districts`
- `races`
- optional `warning` when data is pending
- optional `voting_info` and `division_check` if Google Civic is configured and returns useful data

### 4.7 Backend insight selection

The backend `POST /api/insights` route accepts a voter profile and a race id. It is designed to avoid live LLM generation when precomputed insights exist.

The route maps the profile to an archetype in a fixed precedence order:

1. `veteran`
2. `small_business_owner` / `small_business`
3. `student`
4. `healthcare_aca_or_uninsured` when health coverage is ACA or uninsured
5. `medicare_retiree` when Medicare or age is 65+
6. `homeowner_parent` when the user has children in public school
7. `renter_young_worker` when renter and the lower bound of age bracket is below 40
8. `rural_agriculture` when occupation contains farm/ranch/agriculture terms
9. `base`

Current insight file coverage:

| Archetype | Race files covered |
|---|---:|
| `base` | 46 |
| `healthcare_aca_or_uninsured` | 10 |
| `homeowner_parent` | 10 |
| `medicare_retiree` | 10 |
| `renter_young_worker` | 10 |
| `rural_agriculture` | 10 |
| `small_business_owner` | 10 |
| `student` | 10 |
| `veteran` | 10 |

Selection behavior:

- Prefer exact archetype block.
- Fall back to `base` if the archetype is missing.
- Support a legacy flat insight shape.
- Fall back to base horizons if a selected archetype lacks horizon bullets.
- Validate `race_id` with regex `^[a-z0-9-]{1,64}$`.
- Cap `occupation` at 120 chars and ignore extra profile fields.

When no cached insight exists, the route checks that the race exists. If `OPENROUTER_API_KEY` is set, it calls `app/insights.py` and then writes the generated block back through `datastore.put_insight_block`. If the key is absent, it returns `mode: "unavailable"` instead of pretending to have data.

### 4.8 OpenRouter backend insight fallback

`app/insights.py` uses the OpenAI-compatible SDK with:

```text
base_url = https://openrouter.ai/api/v1
model    = anthropic/claude-sonnet-4.5
```

The system prompt tells the model:

- Use only candidate JSON supplied in the request.
- Attach exact source URLs from candidate JSON to factual bullets.
- Stay neutral and nonpartisan.
- State data gaps explicitly.
- Return structured JSON with candidate bullets, summary, and caveats.

The parser strips Markdown fences and extracts the outermost JSON object if the model returns extra text. That is pragmatic, but it is still a structural parser, not a source-verification engine. It does not fetch every URL to prove the URL currently resolves or supports the exact sentence. The source discipline depends on the supplied candidate JSON and the model following the output contract.

### 4.9 Optional Google Civic enrichment

`app/google_civic.py` is explicitly optional. No API key means no network call and no response-shape change.

The module comments note that Google Civic’s representatives endpoint was shut down in 2025. The implementation therefore uses election/voter-info style endpoints rather than treating Google Civic as a full representatives lookup provider.

Capabilities:

- Select likely target election, biased toward `2026-11-03` and Texas/national coverage.
- Call `voterInfoQuery` for polling locations, early vote sites, drop-off sites, contests, and district IDs.
- Extract OCD division IDs from contests for cross-checking.
- Cache civic payloads under the geocode cache record.
- Fail softly on 403/quota/no coverage.

The product should treat this as enrichment, not as the core ballot authority.

---

## 5. Backend data access and storage

`app/datastore.py` is the backend’s data boundary. That is one of the better structural choices in the repo. HTTP handlers do not manually open files or write SQL. They call datastore primitives.

### 5.1 Datastore public surface

Key exported operations include:

| Function | Role |
|---|---|
| `get_ballot(cd, sd, hd)` | Assemble district-relevant races and embedded candidates. |
| `get_race(race_id)` | Fetch one race by id. |
| `get_candidate(candidate_id)` | Fetch one candidate by id. |
| `list_races()` | Return all races. |
| `search_candidates(query)` | Candidate search helper. |
| `get_insights(race_id)` | Load insight blocks for a race. |
| `put_insight_block(race_id, archetype, payload, inputs_hash)` | Write insight block to Postgres or JSON. |
| `compute_inputs_hash(race_id)` | Hash race candidate inputs for stale insight detection. |
| `stats()` | Healthcheck counts. |
| `geocode_cache_get(address)` | Resolve address cache. |
| `geocode_cache_put(address, entry)` | Persist district cache. |
| `geocode_cache_get_civic(address)` | Fetch optional civic cache. |
| `geocode_cache_put_civic(address, payload)` | Persist optional civic payload. |
| `data_is_pending()` | Surface incomplete data status. |

### 5.2 Postgres-first, JSON fallback

If `DATABASE_URL` is set and `psycopg` is available, the backend tries Postgres. If not, it logs and falls back to JSON.

Fallback is not an afterthought. The root docs state that JSON mode should behave the same as Postgres mode for the demo/product path. The tests in the repo appear to target this equivalence, although the sandbox could not run the full suite because of a missing Python dependency.

### 5.3 Locked backend schema

The backend Postgres schema described in `schema.md` / `database.md` contains:

```sql
CREATE TABLE races (
  race_id TEXT PRIMARY KEY,
  office TEXT NOT NULL,
  level TEXT NOT NULL CHECK (level IN ('federal', 'state', 'state_leg')),
  district TEXT,
  election_date DATE NOT NULL DEFAULT '2026-11-03',
  context JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX idx_races_district ON races(district);
CREATE INDEX idx_races_level ON races(level);

CREATE TABLE candidates (
  candidate_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  party TEXT,
  office TEXT,
  district TEXT,
  incumbent BOOLEAN DEFAULT false,
  fec_id TEXT,
  finance JSONB NOT NULL DEFAULT '{}'::jsonb,
  record JSONB NOT NULL DEFAULT '{}'::jsonb,
  positions JSONB NOT NULL DEFAULT '[]'::jsonb,
  sources JSONB NOT NULL DEFAULT '[]'::jsonb
);

CREATE INDEX idx_cand_district ON candidates(district);
CREATE INDEX idx_cand_name ON candidates(name);

CREATE TABLE race_candidates (
  race_id TEXT REFERENCES races(race_id) ON DELETE CASCADE,
  candidate_id TEXT REFERENCES candidates(candidate_id) ON DELETE CASCADE,
  PRIMARY KEY (race_id, candidate_id)
);

CREATE TABLE insights (
  race_id TEXT NOT NULL,
  archetype TEXT NOT NULL,
  payload JSONB NOT NULL,
  generated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  inputs_hash TEXT,
  PRIMARY KEY (race_id, archetype)
);

CREATE TABLE geocode_cache (
  address_norm TEXT PRIMARY KEY,
  matched_address TEXT,
  cd TEXT,
  sd TEXT,
  hd TEXT,
  county TEXT,
  civic_json JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

There is a real design choice here: candidate records keep official identifiers and most evidence fields in JSONB instead of normalizing every vote, donor, and source into separate tables. For an MVP, this is acceptable because reads are race/candidate-document oriented. For deeper analytics, such as “all candidates who took X money and voted Y,” the system would eventually need extracted tables or materialized views.

### 5.4 Candidate/race id conventions

There are two id conventions:

| Layer | Convention | Example style |
|---|---|---|
| Backend candidate ids | `lastname-firstname` style in docs | `allred-colin` style |
| Next politician profile slugs | `firstname-lastname` from `slugify` | `colin-allred` style |

This is a real join risk. The frontend often filters race candidates by normalized display name instead of shared canonical ids. That can work for the current dataset but will break on suffixes, middle names, duplicate names, name changes, or candidates with different official/common names. The architecture needs one canonical cross-layer candidate id with aliases attached, not two implied conventions.

### 5.5 Input hashing for insight freshness

`compute_inputs_hash(race_id)` builds a SHA-256 hash over canonical candidate JSON for the race. It strips `candidate_id` from candidate objects to keep Postgres and JSON shapes consistent.

That hash is a useful stale-cache primitive. If candidate finance/vote/position inputs change, the insight block can be marked stale or regenerated. The architecture already has the right hook for this. The next step is making stale detection visible in admin/CI instead of only storing `inputs_hash`.

---

## 6. Next.js app architecture

The `civic-match/` app is the main product layer.

### 6.1 Frontend stack

`civic-match/package.json` declares:

| Package | Version / role |
|---|---|
| `next` | 16.2.10 |
| `react` | 19.2.4 |
| `react-dom` | 19.2.4 |
| `typescript` | ^5 |
| `tailwindcss` | ^4 |
| `pg` | ^8.22.0 for optional KV Postgres backend |
| `d3-force` | ^3.0.0 for graph visualization |
| `d3-hierarchy` | ^3.1.2 for scenario tree visualization |
| `react-markdown` + `remark-gfm` | Markdown explanation rendering |
| `lucide-react` | Icons |

Scripts:

```json
{
  "dev": "next dev",
  "build": "next build",
  "start": "next start",
  "lint": "eslint",
  "seed": "tsx scripts/seed.ts texas",
  "seed:state": "tsx scripts/seed.ts",
  "export:config": "tsx scripts/export-config.ts",
  "seed:graph": "tsx scripts/seed-graph.ts",
  "import:pg": "tsx scripts/import-to-postgres.ts",
  "validate": "tsx scripts/validate-ground-truth.ts",
  "fix:groundtruth": "tsx scripts/fix-ground-truth.ts"
}
```

### 6.2 App Router surfaces

Pages present in the repo:

- `civic-match/app/ballot/page.tsx`
- `civic-match/app/debate/page.tsx`
- `civic-match/app/future/page.tsx`
- `civic-match/app/graph/page.tsx`
- `civic-match/app/intake/page.tsx`
- `civic-match/app/p/[id]/page.tsx`
- `civic-match/app/page.tsx`
- `civic-match/app/results/page.tsx`

API route files present in the repo:

- `civic-match/app/api/ballot/route.ts`
- `civic-match/app/api/config/route.ts`
- `civic-match/app/api/debate/route.ts`
- `civic-match/app/api/election/route.ts`
- `civic-match/app/api/explain/route.ts`
- `civic-match/app/api/graph/route.ts`
- `civic-match/app/api/match/route.ts`
- `civic-match/app/api/motivate/route.ts`
- `civic-match/app/api/politicians/route.ts`
- `civic-match/app/api/qa/route.ts`
- `civic-match/app/api/research/route.ts`
- `civic-match/app/api/scenario/route.ts`
- `civic-match/app/api/stakes/route.ts`
- `civic-match/app/api/voter-insights/route.ts`

### 6.3 Product flow implemented in `app/ballot/page.tsx`

The main wizard in `app/ballot/page.tsx` is the most developed voter flow. It has these conceptual states:

1. Welcome
2. Location
3. Elections found
4. Focus selection
5. Priorities
6. Stance questions
7. Tradeoff questions
8. Dealbreakers
9. Review
10. Matches

It loads `/api/config`, looks up `/api/ballot`, writes preferences to browser `localStorage`, fetches `/api/politicians`, scores through `/api/match`, then filters match results to selected race candidates.

The match filtering currently uses normalized candidate names from the selected race rather than stable profile ids. That is acceptable for a prototype, but brittle for production.

The page currently builds a limited voter profile for backend insights. The backend supports richer profile archetype selection, but the current wizard does not collect all fields that backend archetypes can use. For example, it does not fully populate veteran status, health coverage, renter/homeowner status, occupation, and children-in-school fields in the main flow. The code path exists; the UI capture is thinner.

### 6.4 Older intake and results path

`app/intake/page.tsx` and `app/results/page.tsx` represent an older or parallel product path:

- `intake` loads config-driven issues and tradeoffs.
- It saves user preferences through `lib/prefs.ts` into `localStorage` key `civicmatch_prefs`.
- `results` reads preferences, optionally fetches ballot by address, fetches cached profiles, posts to `/api/match`, and renders cards.
- Expanded cards call `/api/explain` lazily.
- Results include `MotivationCard`, `StakesBanner`, `BallotSection`, and `InsightsPanel`.

There are therefore two intake surfaces: the newer ballot wizard and the older issue intake page. Both are useful, but they should be reconciled before launch so users do not land in mismatched flows.

### 6.5 Candidate profile page and Q&A

`app/p/[id]/page.tsx` renders a candidate profile. It shows:

- stance records
- qualitative dimensions
- promise/accountability records
- finance records
- source coverage
- unknowns and contradictions
- an embedded Q&A box

`app/p/[id]/qa-box.tsx` posts to `/api/qa`. The route answers only from the cached profile evidence pack. That is the correct product direction: a user should be able to ask follow-up questions, but the answer should stay bounded to known evidence rather than free-form web claims.

### 6.6 Future/scenario tree

`app/future/page.tsx` renders scenario branches from `/api/scenario`. The underlying `lib/scenario.ts` asks the research model to produce a bounded tree with max depth and source/inference separation. The visual is D3 hierarchy-based.

The scenario system separates:

- **fact nodes** with URLs
- **inference nodes** with likelihood levels
- branch effects and affected issues

This matters because projections are not the same as records. The code’s data model has the right distinction, but the UI needs to preserve it clearly.

### 6.7 Graph view

`app/graph/page.tsx` renders the graph returned by `/api/graph`. `lib/graph.ts` can build deterministic layers from cached election/profile data and merge in connection-agent edges. It supports a focus neighborhood with capped depth.

Graph nodes include types like politician, race, office, issue, scenario event, and likely related civic entities. Edges include deterministic relationships and model-researched connections. The merge logic dedupes nodes by id and edges by source/relation/target, keeping higher-confidence edges.

The graph is powerful but needs strict visual and semantic labeling. A deterministic “candidate is in race” edge should not look the same as a lower-confidence inferred “policy influence” edge.

### 6.8 Debate view

`app/debate/page.tsx` streams candidate-agent debate events from `/api/debate`. The route caches debates by candidate ids, topic, and profile `researched_at` values. Each candidate agent receives an evidence pack and is supposed to argue only from that pack. A judge stage scores fidelity and unsourced claims.

This is a high-risk surface from a trust perspective. It can be useful, but the product should visually mark it as a simulated comparison over evidence records, not as actual candidate speech.

---

## 7. Next app storage: file DB and KV Postgres

The Next app uses `lib/store.ts` as its persistence layer.

Namespaces:

| Namespace | Stored data |
|---|---|
| `politicians` | Cached `PoliticianProfile` objects. |
| `scenarios` | Scenario trees by race slug. |
| `graph` | Singleton civic graph document. |
| `elections` | Cached discovered elections by state. |
| `explanations` | Cached match explanations by hash. |
| `motivations` | Cached motivation cards by hash. |
| `debates` | Cached debate streams/results by hash. |

When `DATABASE_URL` is set, the Next store uses a generic Postgres table:

```sql
CREATE TABLE IF NOT EXISTS kv (
  namespace TEXT NOT NULL,
  key TEXT NOT NULL,
  value JSONB NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (namespace, key)
);
```

When no database is set, it writes files under `civic-match/data/<namespace>/<key>.json`. Keys are sanitized to prevent path traversal, and writes are atomic.

This gives a good local developer experience. It also means the Next app can persist LLM-generated product objects without needing a full relational schema for every object type.

The trade-off: the KV layer makes it easier to ship, but harder to query. If this becomes a serious civic knowledge base, core entities should be relational or graph-native, while long-form generated artifacts can stay blobbed.

---

## 8. Core TypeScript data contracts

`civic-match/lib/types.ts` is the central product schema file. It defines the domain language that the scoring engine, profile pages, Q&A, explanations, and research agents share.

### 8.1 Source model

Evidence source types include:

- `voting_record`
- `sponsored_bill`
- `official_platform`
- `public_statement`
- `debate_transcript`
- `interview`
- `campaign_finance`
- `news_report`
- `questionnaire`
- `other`

A `Source` carries:

- `id`
- `type`
- `title`
- `url`
- optional publisher/date/accessed date
- reliability score
- excerpt

The URL is required by downstream validation for most stance records. That is important. A civic product without URL-level evidence becomes just another black-box score.

### 8.2 Stance model

A `Stance` includes:

- `issue_id`
- `position_label`
- `position_scalar` from 0 to 1, or `null`
- `summary`
- `evidence_type`
- `confidence`
- `recency`
- `sources`
- optional notes

The scalar axis is what makes matching possible. The label and summary make it explainable. The evidence type/confidence/source list make it auditable.

A production issue taxonomy needs each issue’s scalar axis to be tightly defined. “0 = less regulation, 1 = more regulation” may be fine for one issue and wrong for another. The verifier agent can catch some axis mismatches, but the taxonomy itself is the stronger control point.

### 8.3 Politician profile

A `PoliticianProfile` includes:

- identity fields: id, name, party, state, office, district
- stance array
- qualitative dimensions
- promise/accountability record
- campaign finance summary
- unknowns
- contradictions
- source coverage score
- researched timestamp
- research status: `complete`, `partial`, or `failed`

Current frontend profile state:

| Profile status | Count |
|---|---:|
| `complete` | 9 |
| `partial` | 87 |

### 8.4 User preferences

`UserPreferences` contains:

- optional zip/address/profile context
- `priority_weights`: issue id to numeric weight
- `issue_positions`: issue id to user scalar position
- tradeoffs
- dealbreakers
- optional qualitative preferences

Preferences are saved in browser localStorage by `lib/prefs.ts`. That keeps the current product simple and low-friction, but it means preferences are device-local unless the app later adds accounts or share links.

---

## 9. Match scoring engine

The scoring engine is implemented in `civic-match/lib/scoring.ts`.

The documented formula is:

```text
score = Σ(issue_weight × stance_alignment × evidence_confidence × recency_adjustment × source_quality)
```

Then the score is normalized against the maximum achievable points for issues where the candidate has evidence.

### 9.1 Weight normalization

The engine takes all positive user priority weights and normalizes them by total weight. If a user picks five issues, each raw weight is converted into a percentage of the user’s selected priority set.

Unknown or zero-weight issues do not influence the score.

### 9.2 Alignment

When both the user and candidate have scalar positions:

```text
alignment = 1 - abs(user_position - candidate_position)
```

So:

- exact scalar match = 1.0 alignment
- half-axis difference = 0.5 alignment
- opposite endpoints = 0.0 alignment

Status buckets:

| Alignment | Status |
|---:|---|
| `>= 0.7` | `match` |
| `>= 0.4` and `< 0.7` | `partial` |
| `< 0.4` | `conflict` |
| missing user/candidate stance | `unknown` |

### 9.3 Evidence quality and recency

Source quality weights:

| Evidence/source type | Weight |
|---|---:|
| `voting_record` | 1.00 |
| `sponsored_bill` | 1.00 |
| `campaign_finance` | 0.95 |
| `official_platform` | 0.90 |
| `debate_transcript` | 0.85 |
| `questionnaire` | 0.85 |
| `public_statement` | 0.80 |
| `interview` | 0.80 |
| `news_report` | 0.65 |
| `other` | 0.50 |

Recency adjustment:

| Evidence age | Adjustment |
|---|---:|
| missing/invalid date | 0.85 |
| <= 1 year | 1.00 |
| <= 3 years | 0.92 |
| <= 6 years | 0.80 |
| older than 6 years | 0.70 |

For a stance with multiple sources, source quality uses the max quality across sources and the stance’s declared evidence type. That means one high-quality record can raise the source-quality multiplier for a stance.

### 9.4 Unknowns are handled correctly

Unknown issues do not lower the alignment score directly. They lower confidence instead.

This is the right choice. If a candidate has no sourced position on the user’s top issue, the app should not pretend they disagree. It should say the evidence is missing. Penalizing unknowns as disagreement would distort results.

### 9.5 Confidence

Confidence is evidence-weighted coverage over the user’s priorities:

```text
coverage = Σ(issue_weight × evidence_confidence × source_quality)
confidence_value = min(1, coverage)
```

Buckets:

| Confidence value | Label |
|---:|---|
| `>= 0.65` | High |
| `>= 0.35` and `< 0.65` | Medium |
| `< 0.35` | Low |

### 9.6 60–99 overall score

The product also calculates a game-style “overall” score from 60 to 99:

```text
quant = issue_alignment_score / 100
qual = qualitative_composite or 0.5
alignment_component = 0.6 * quant
qualitative_component = 0.4 * qual
conflict_penalty = min(0.15, top_conflict_weight * 0.25)
blended = max(0, alignment_component + qualitative_component - conflict_penalty)
overall = round(60 + 39 * blended)
```

This makes the display more legible, but it is a product choice, not a mathematically necessary civic metric. The UI should always let users inspect the decomposed components. The code already returns `overall_components`, top agreements, top conflicts, unknown issues, and qualitative dimensions.

### 9.7 Warning flags

The score result can include warnings for:

- documented broken promises
- integrity score below 0.45
- contradictions between statements and actions

This is useful, but the warnings depend on the completeness of the candidate profile. A profile with no accountability research should not look “clean”; it should look under-researched.

---

## 10. Research and LLM agent layer

The TypeScript research layer is mostly under:

- `civic-match/lib/llm.ts`
- `civic-match/lib/agents.ts`
- `civic-match/lib/discovery.ts`
- `civic-match/lib/scenario.ts`
- `civic-match/lib/graph.ts`
- product routes like `/api/explain`, `/api/qa`, `/api/motivate`, `/api/debate`

### 10.1 Model access

`lib/llm.ts` talks to OpenRouter through raw `fetch`:

```text
https://openrouter.ai/api/v1/chat/completions
```

Defaults:

| Env var | Default | Use |
|---|---|---|
| `RESEARCH_MODEL` | `moonshotai/kimi-k2-0905:online` | Online research-style tasks. |
| `FAST_MODEL` | `moonshotai/kimi-k2-0905` | Lower-latency explanation/motivation tasks. |
| `OPENROUTER_API_KEY` | required for model calls | Secret for OpenRouter. |

`extractJSON` tries to parse fenced JSON, raw JSON, or the first object/array found in a text response.

### 10.2 Research agent fanout

`researchPolitician(name, onEvent)` orchestrates a profile build. It emits progress events through SSE.

The rough stages are:

1. Load issue taxonomy.
2. Split issues into clusters.
3. Run stance cluster agents in parallel.
4. Run profile, qualitative, and accountability agents.
5. Validate stances.
6. Run verifier/correction agent.
7. Run finance agent after stances validate.
8. Compose and save `PoliticianProfile`.
9. Emit complete or error event.

The pipeline uses multiple small prompts rather than one huge prompt. That is the right direction. The validator then drops unusable records instead of letting weak model output enter the product silently.

### 10.3 Validation rules

`validateStances` applies several hard filters and clamps:

- Drop invalid `issue_id` values.
- Drop stances without real `http(s)` URLs.
- Clamp scalar positions and confidence values.
- Assign reliability score based on source type and primary/secondary evidence.
- Deduplicate by issue id, keeping the highest-confidence stance.

The verifier agent checks axis consistency and contradictions. Its corrections are ignored if it tries to null out more than `max(2, 30% of stances)`. That is a good guard against a verifier overcorrecting the profile into emptiness.

### 10.4 Finance agent

The finance agent returns:

- totals
- top donors
- donor-position correlations
- source records

The prompt explicitly treats correlations as not proof of causation. The current data model supports this distinction through a `correlations` field rather than turning donor data into definitive motive claims.

### 10.5 Accountability and qualitative agents

The accountability agent extracts promise/action pairs:

- promise text
- action text
- verdict: kept, broken, partial, untested
- sources

The qualitative agent scores:

- integrity
- public interest
- transparency
- experience

These are higher-subjectivity outputs. They can be useful if well-sourced, but the UI should not display them as equal to a roll-call vote. They need confidence and source visibility.

### 10.6 Explanation route

`/api/explain` takes a politician id and user preferences, recomputes the match result, then uses a cache key based on:

- politician id
- preferences
- profile `researched_at`

That is a good cache invalidation primitive. If profile data changes, the cached explanation no longer matches the key.

The route falls back to deterministic explanation if model parsing fails. That prevents a broken LLM call from breaking the results page.

### 10.7 Q&A route

`/api/qa` answers questions about one politician from cached profile evidence.

Hardening details:

- The user question is length-limited/sliced.
- The prompt separates the question from the evidence pack.
- The model is instructed to use only profile evidence and include source labels.

This should still be treated as a generated answer, not a source of new facts. The product should render source links next to any factual answer.

### 10.8 Election discovery

`lib/discovery.ts` can use the online research model to find major statewide/federal races for a state and cache them. It limits the live-discovered set to a small number of prominent races.

This is useful for bootstrapping, but should not be the final authority for ballot data. The backend’s district/race dataset should remain authoritative for actual user ballot lookup.

### 10.9 Scenario, graph, motivation, debate

These features expand the product beyond simple matching:

| Feature | Files | Data boundary |
|---|---|---|
| Scenario tree | `lib/scenario.ts`, `/api/scenario`, `app/future/page.tsx` | Scenario facts need URLs; projections carry likelihood. |
| Civic graph | `lib/graph.ts`, `/api/graph`, `app/graph/page.tsx` | Deterministic edges should be separated from researched/inferred edges. |
| Motivation cards | `/api/motivate` | Should motivate voting/learning, not candidate persuasion. |
| Debate | `/api/debate`, `app/debate/page.tsx` | Simulated debate over evidence packs; must not look like real candidate quotes. |

The architecture can support these, but they are trust-sensitive. Each one needs visible boundaries between verified record, model interpretation, and projection.

---

## 11. Data pipeline architecture

The pipeline is the source of the backend gold dataset. It lives in `pipeline/` and follows a staged design.

### 11.1 Intended data flow

```mermaid
flowchart LR
  APIs[Official/public APIs\nFEC, clerk votes, TEC, context]
  Raw[Raw bronze data\ngitignored / working files]
  Build[pipeline/build_dataset.py]
  Gold[Gold JSON\ndata/tx/races.json\ndata/tx/candidates.json]
  Quality[pipeline/score_quality.py\nvalidate_data.py]
  Insights[pipeline/precompute_*\ndata/tx/insights]
  PG[pipeline/load_postgres.py\nPostgres tables]
  Export[pipeline/export_civic_match.py\nNext app data]
  App[FastAPI + Next app]

  APIs --> Raw
  Raw --> Build
  Build --> Gold
  Gold --> Quality
  Gold --> Insights
  Gold --> PG
  Gold --> Export
  Insights --> PG
  Insights --> App
  Gold --> App
  Export --> App
```

### 11.2 Pipeline script inventory

Key scripts and expected responsibilities:

| Script | Role |
|---|---|
| `fetch_fec.py` | Pull federal campaign finance / candidate identifiers. |
| `fetch_votes.py` | Pull or transform key vote records. |
| `fetch_context.py` | Add race/context background. |
| `fetch_statewide.py` | Statewide race data collection. |
| `fetch_tec_finance.py` | Texas Ethics Commission finance data. |
| `build_dataset.py` | Combine source inputs into gold race/candidate JSON. |
| `clean_gold.py` | Clean normalized gold data. |
| `import_civicmatch_positions.py` | Import frontend/product issue positions into backend candidate records. |
| `precompute_horizons.py` | Build “right now” and “down the road” insight horizon blocks. |
| `precompute_marquee_insights.py` | Precompute high-value race insights. |
| `build_insights_house.py` / `build_insights_tx20_38.py` | Race-specific insight build scripts. |
| `validate_insights_*` | Validate insight structure and coverage. |
| `validate_data.py` | Validate gold data contracts. |
| `score_quality.py` | Produce data quality report. |
| `build_geocode_seed.py` | Create seeded address-to-district cache entries. |
| `load_postgres.py` | Load backend gold data into locked Postgres tables. |
| `export_civic_match.py` | Export backend data into `civic-match/data`. |
| `smoke_backend.py` | Runtime smoke check against backend endpoints. |
| `demo_readiness_gate.py` | Demo gate / readiness validation. |

### 11.3 Gold data shape

`data/tx/races.json` is a document with:

- `state`
- `election_date`
- `races[]`

Each race carries:

- `race_id`
- `office`
- `level`
- `district`
- `context`
- candidate references

`data/tx/candidates.json` is keyed by candidate id. Candidate entries include:

- name/party/office/district/incumbent
- `fec_id`
- `finance`
- `record`
- `positions`
- `sources`

Current backend candidate field coverage:

| Field family | Count |
|---|---:|
| `finance` present | 79/96 |
| `record.key_votes` present | 37/96 |
| `positions` present | 10/96 |
| `sources` present | 96/96 |

### 11.4 Quality report

`data/tx/quality_report.json` tracks dataset source coverage, quality tiers, golden demo districts, and known name-collision issues. This is the right artifact to use as a release gate.

A civic product should not just have tests over code. It needs tests over evidence coverage and missingness. The quality report can become the central release artifact for that.

---

## 12. Frontend-to-backend contract

The Next app talks to the FastAPI backend through `civic-match/lib/dataBackend.ts`.

### 12.1 Backend URL handling

`DATA_BACKEND_URL` defaults to:

```text
http://localhost:8000
```

It is server-side only. The file deliberately does not use `NEXT_PUBLIC_`.

### 12.2 Fetch behavior

The helper returns result objects instead of throwing:

```ts
{ ok: true, data }
{ ok: false, reason, status? }
```

Timeouts:

| Operation | Timeout |
|---|---:|
| Ballot lookup | 10 seconds in `dataBackend.ts`; the Next API route uses a 15 second proxy timeout. |
| Voter insights | 20 seconds. |

Requests use `cache: "no-store"`.

### 12.3 Candidate normalization

`normalizeCandidates` accepts candidates as either:

- an array
- an id-keyed object

That is a good compatibility shim because backend JSON/Postgres shapes can differ.

### 12.4 Profile mapping

`mapVoterProfileToBackend` maps the frontend profile shape into the backend insight profile shape.

Some mappings are approximate, especially income and age bracket buckets. That is acceptable if the UI treats archetypes as coarse personalization, not exact demographic identity.

The more important issue is collection coverage: the current main ballot wizard does not yet capture every field the backend uses for archetype selection.

### 12.5 Backend failure fallback

`civic-match/app/api/ballot/route.ts` proxies to FastAPI. If the backend returns validation errors, the Next route forwards those. If the backend is down or returns a non-validation failure, the Next route can fall back to a cached statewide election response.

This gives the UI something to show during backend failure, but it creates a contract risk: a true ballot response has address, matched districts, and district-specific races; a statewide fallback does not prove the user’s exact ballot. The UI must label fallback mode clearly.

---

## 13. Configuration and issue taxonomy

`civic-match/lib/config.ts` loads config from file/KV storage, with defaults available if files are missing.

Current issue taxonomy count: 30.

The UI config includes:

- site name
- default state
- election title
- intake minimum picks
- importance levels
- qualitative labels
- suggested questions
- result tiers

The issue taxonomy is a central control surface for the product. It controls:

- what users can prioritize
- what axes candidate stances map onto
- how the match score interprets distance
- how scenario effects and graph issue nodes attach

A future hardening pass should treat taxonomy changes like schema migrations. If an issue id changes, cached profiles, explanations, graphs, and scenario effects may all become stale.

---

## 14. Deployment architecture

### 14.1 FastAPI deployment

Root files indicate Railway deployment for the FastAPI backend:

- `Procfile`
- `railway.json`
- `nixpacks.toml`
- `railway.md`

The process command is:

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

`railway.json` uses `/healthz` as healthcheck.

### 14.2 Local backend run

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

### 14.3 Local Next run

```bash
cd civic-match
npm install
npm run seed
npm run seed:graph
npm run dev
```

### 14.4 Postgres

The repo includes `docker-compose.yml` and docs for a local Postgres flow. The root docs refer to a local URL like:

```text
postgresql://postgres:postgres@localhost:5433/patriothacks
```

`pipeline/load_postgres.py --dry-run` is documented as a sanity check before loading. Based on the docs, expected parse counts are:

- races: 46
- candidates: 96
- race-candidate links: 96
- insight files: 46

### 14.5 Environment variables

Backend/root environment:

| Variable | Role |
|---|---|
| `OPENROUTER_API_KEY` | Enables fallback insight generation in FastAPI and model calls in Next if shared. |
| `DATABASE_URL` | Enables Postgres backend storage. |
| `CORS_ORIGINS` | Controls allowed browser origins for FastAPI. |
| `GOOGLE_CIVIC_API_KEY` | Enables optional Google Civic enrichment. |
| `GEOCODER_DISABLED` | Test/ops escape hatch to force geocoder unavailable path. |
| `FEC_API_KEY` | Pipeline source key for FEC. |
| `CONGRESS_GOV_API_KEY` | Pipeline source key for congressional data. |

Next environment:

| Variable | Role |
|---|---|
| `DATA_BACKEND_URL` | Server-side URL for FastAPI backend. Defaults to `http://localhost:8000`. |
| `DATABASE_URL` | Enables Next KV Postgres store. |
| `OPENROUTER_API_KEY` | Required for Next LLM routes. |
| `RESEARCH_MODEL` | Overrides default online research model. |
| `FAST_MODEL` | Overrides default faster model. |

The same `DATABASE_URL` can point both apps at one database, but the apps use different tables. FastAPI uses locked civic tables; Next uses `kv`.

---

## 15. Resilience and latency design

The repo already contains several latency and reliability decisions that fit the product:

### 15.1 Precompute-first backend

The backend avoids live LLM and government data calls during normal ballot and insight lookup:

- race/candidate data is prebuilt
- insight blocks are precomputed by race/archetype
- geocode results are cached
- Postgres and JSON modes both exist

This is the right architecture for the user’s first run. The product can show a ballot quickly instead of making a user wait for live research.

### 15.2 Graceful optional providers

Optional provider behavior:

| Provider | Used for | Failure behavior |
|---|---|---|
| Census geocoder | Address-to-district on cache miss | 503 on timeout/down; 422 on no match/non-TX. |
| Google Civic | Optional voting info and division cross-check | Omitted on no key/quota/no coverage. |
| OpenRouter in FastAPI | Missing insight fallback | `mode: unavailable` if no key. |
| OpenRouter in Next | Research/explanation/scenario/debate/motivation | Route-level fallbacks vary; some deterministic fallback exists. |

### 15.3 Caching layers

Caching exists at several levels:

| Cache | Layer | Key |
|---|---|---|
| Geocode LRU | FastAPI process | normalized address |
| Geocode runtime cache | Postgres or JSON | normalized address |
| Geocode seed | checked-in JSON | normalized address |
| Backend insights | Postgres or `data/tx/insights` | race id + archetype |
| Next profiles | KV or file DB | profile slug |
| Explanations | KV or file DB | hash of prefs/profile version |
| Debates | KV or file DB | candidates + topic + profile versions |
| Motivation cards | KV or file DB | prefs + data version |
| Graph | KV or file DB | singleton / focus expansion |
| Scenario trees | KV or file DB | race slug |

### 15.4 Known scaling limits

- The FastAPI rate limiter is in-process. Multiple backend instances would each have their own window. For real abuse protection, use Redis or platform-level rate limits.
- JSON fallback is fine for local/demo, but concurrent writes can still have race conditions across multiple processes even with atomic replace.
- Next research jobs run inside API route/SSE request lifetimes. Long jobs can hit platform timeouts. A queue would be safer for production.
- Large profile lists are read from file/KV and scored in-process. That is fine at Texas MVP size, but not for all US races without pagination and precomputed match indexes.

---

## 16. Security and privacy model

### 16.1 Current controls

The repo has several sane defaults:

- API body cap.
- API rate limiting.
- Security headers.
- CORS origin config.
- Generic 500 response without stack traces.
- Backend logs method/path only for unhandled errors, not query/body.
- Address validation before external calls.
- Server-side `DATA_BACKEND_URL`, not public browser env.
- Browser localStorage for preferences, avoiding a user account database for MVP.
- Q&A prompt isolates user question and evidence pack.

### 16.2 Sensitive data paths

Sensitive or semi-sensitive data includes:

- home address entered for ballot lookup
- inferred districts
- issue preferences
- dealbreakers/tradeoffs
- profile archetype fields such as veteran, renter, health coverage, Medicare, occupation, school children

Current behavior:

- Address goes to FastAPI, cache, and Census geocoder on miss.
- Preferences are stored in localStorage by frontend code.
- Archetype profile is sent to FastAPI for insights.
- If live LLM fallback is triggered for backend insights, candidate/race/profile context may go to OpenRouter. The backend only does this when cached insights are missing and `OPENROUTER_API_KEY` is set.
- Next LLM routes can send preference/profile/candidate evidence packs to OpenRouter.

Production hardening should add a simple privacy matrix in the UI and docs: what is stored locally, what is sent to the backend, what can reach model providers, and what is never stored.

### 16.3 Prompt injection posture

The repo has some protection:

- Q&A is evidence-bounded.
- Research validators require URLs.
- Backend insight generation tells the model to use candidate JSON only.
- Debate agents receive bounded evidence packs.

But prompt injection is not solved by instructions. For production, add:

- output schema validation everywhere a model returns data
- URL allowlists or source reputation scoring for official records
- post-generation source support checks for claims
- persistent audit logs for generated explanations and rejected outputs
- route tests with adversarial user questions

---

## 17. Testing and validation state

The repo includes root Python tests:

- `tests/test_contracts.py`
- `tests/test_e2e_demo.py`
- `tests/test_google_civic.py`
- `tests/test_hardening.py`

I attempted:

```bash
cd /mnt/data/patriot_review/PatriotHacks-main
python3 -m pytest -q
```

Collection failed because the sandbox Python environment does not have the `openai` package installed:

```text
ModuleNotFoundError: No module named 'openai'
```

The failure happens while importing `app/main.py`, which imports `app/insights.py`, which imports `OpenAI` from the `openai` package. This is an environment dependency issue in the review sandbox, not evidence that the app tests fail after installing `requirements.txt`.

There are also Next scripts:

- `npm run lint`
- `npm run validate`
- `npm run fix:groundtruth`
- `npm run import:pg`

I did not run the Next test/build/lint path in this review. The Markdown file is based on static repo inspection plus the attempted Python test collection.

### 17.1 What should be tested next

High-value test coverage:

1. **Backend contract tests**
   - valid Texas seeded address returns matched districts and races
   - invalid/short/control-char address returns friendly 422
   - `GEOCODER_DISABLED=1` still works for seed cache addresses
   - no API key means Google Civic fields are omitted, not errors
   - missing insights + no OpenRouter returns `mode: unavailable`

2. **JSON/Postgres parity tests**
   - same ballot response from JSON and Postgres for golden districts
   - same insight response from JSON and Postgres for base and archetype blocks
   - same `inputs_hash` across modes

3. **Frontend contract tests**
   - `/api/ballot` forwards 422 correctly
   - fallback mode is labeled and does not look district-specific
   - `/api/match` handles missing stance data as unknown, not conflict
   - selected race candidate filtering survives name punctuation/suffixes

4. **Scoring tests**
   - unknown issues lower confidence only
   - high-quality official records beat low-quality news reports
   - old evidence gets recency penalty
   - broken promise/integrity/contradiction warnings appear

5. **LLM-output tests**
   - invalid issue ids are dropped
   - stance without URL is dropped
   - verifier overcorrection is rejected
   - explanation fallback works on malformed JSON
   - Q&A refuses to answer outside evidence pack

6. **Pipeline gates**
   - minimum finance/vote/position/source coverage thresholds
   - no duplicate candidate ids
   - no race without candidates unless explicitly marked uncontested/unavailable
   - no insight bullet without source URL where required
   - stale `inputs_hash` detection

---

## 18. Current implementation gaps and architecture risks

### 18.1 Two frontend systems exist

The repo has:

- `app/static/index.html` served by FastAPI root
- full Next.js app under `civic-match/`

The static page may be useful as a hackathon demo fallback, but it creates deployment ambiguity. A future maintainer could change one UI and not the other. The Next app should be treated as the primary product surface, and the FastAPI static page should either be removed, renamed as legacy, or kept only as a diagnostic/demo page.

### 18.2 Two storage models and two Postgres schemas

FastAPI has fixed relational tables. Next has a generic KV table.

This is workable, but needs documentation and namespacing. If both apps share one `DATABASE_URL`, migrations must create both the civic tables and `kv`. If they use different databases, deployment docs should say so.

### 18.3 Candidate ids are not unified

Backend ids and Next profile slugs differ by convention. The frontend compensates with name matching. This is the largest data-contract risk in the current architecture.

Recommended fix:

- introduce a canonical `person_id`
- store aliases: FEC id, Bioguide id, TEC id, slug, display name, official ballot name
- make backend race candidates refer to `person_id`
- make frontend profile ids either equal to `person_id` or carry a required `person_id`

### 18.4 UI does not yet collect the full backend insight profile

The backend supports granular archetypes. The main ballot wizard currently captures a narrower set of data. That means many users will fall to `base` even when the backend supports more relevant archetype insights.

Recommended fix: either collect the fields with clear opt-in copy or reduce the backend archetype list to what the UI actually captures.

### 18.5 Generated surfaces need stronger provenance display

Scenarios, graph connections, motivation cards, debates, explanations, and Q&A all use model output. Some distinguish fact/inference in schema, but the UI must make that distinction hard to miss.

Recommended display rule:

- official record: show as fact with source
- model interpretation of record: show as interpretation
- future projection: show likelihood and assumptions
- missing evidence: show as missing, not as neutral/clean

### 18.6 Backend fallback ballot can blur exact-ballot vs statewide data

The Next `/api/ballot` route can fall back to cached statewide election data when the backend is unavailable. That is useful for uptime, but it should be labeled. A statewide fallback is not a user’s exact ballot.

### 18.7 Research jobs should move to a queue

SSE research inside route handlers is fine for demos. For production:

- queue long jobs
- persist job state
- let user resume or reload
- rate limit expensive research
- store rejected outputs and validation failures

### 18.8 Source validation is structural, not evidentiary

The code often requires URLs, but does not always prove the URL supports the claim. For a voter product, this distinction matters.

Recommended next step:

- source fetcher with cached page snapshots
- quote/excerpt extraction
- claim-to-source support labels
- official-source priority scoring
- broken/dead URL detection

---

## 19. Recommended target architecture after hardening

The current repo is good enough for a hackathon MVP and a focused Texas demo. The next architecture should keep the same broad shape but tighten contracts.

```mermaid
flowchart TD
  Browser[Browser]
  Next[Next.js UI + product API]
  Backend[FastAPI civic data API]
  Queue[Research/job queue]
  Worker[Research workers]
  RelDB[(Postgres civic relational tables)]
  KV[(Postgres KV/artifact cache)]
  Object[(Evidence snapshots/object store)]
  Search[(Search/vector index optional)]
  Pipeline[Offline official-data pipeline]
  Official[Official/public sources]
  Models[Model provider]

  Browser --> Next
  Next --> Backend
  Next --> KV
  Next --> Queue
  Queue --> Worker
  Worker --> Models
  Worker --> RelDB
  Worker --> KV
  Worker --> Object
  Pipeline --> Official
  Pipeline --> RelDB
  Pipeline --> Object
  Backend --> RelDB
  Backend --> KV
  Backend --> Object
  Backend --> Search
```

Target principles:

1. **One canonical civic entity model**  
   `person_id`, `race_id`, `office_id`, `district_id`, `source_id`, `claim_id`.

2. **Official data pipeline remains primary**  
   LLMs can interpret, classify, and explain. They should not be the main source of race existence or official candidate records.

3. **Generated artifacts are cached with input hashes**  
   Explanations, insights, debates, scenarios, and graph edges should all carry input hashes and source versions.

4. **Source snapshots back claims**  
   Every claim shown to the user should trace to source metadata, URL, captured text/excerpt, access time, and support status.

5. **Unknowns are first-class**  
   Missing evidence should affect confidence and be visible in the UI.

6. **Exact ballot is separate from general election context**  
   Never let fallback/statewide/demo data look like address-specific ballot data.

---

## 20. Endpoint appendix

| Surface | Method | Path | Handler | Purpose |
|---|---:|---|---|---|
| FastAPI backend | GET | `/` | `app/main.py::read_index` | Serves the legacy static ballot UI from `app/static/index.html`. |
| FastAPI backend | GET | `/healthz` | `app/main.py::healthz` | Healthcheck and data-load status for Railway. |
| FastAPI backend | GET | `/api/ballot?address=` | `app/main.py::api_ballot` | Address validation, geocode cache lookup, Census geocode on miss, district extraction, ballot assembly, optional Google Civic enrichment. |
| FastAPI backend | POST | `/api/insights` | `app/main.py::api_insights` | Archetype selection, cached insight lookup, OpenRouter fallback only if cache is missing and key is present. |
| Next app | GET | `/api/config` | `civic-match/app/api/config/route.ts` | Returns issue taxonomy and UI copy/config from the file/KV config store. |
| Next app | GET/POST | `/api/election` | `civic-match/app/api/election/route.ts` | Gets cached state election metadata or runs live election discovery. |
| Next app | GET | `/api/politicians` | `civic-match/app/api/politicians/route.ts` | Lists cached politician profile summaries. |
| Next app | POST | `/api/research` | `civic-match/app/api/research/route.ts` | Server-sent research stream for a candidate profile. Uses cached profile unless forced. |
| Next app | POST | `/api/match` | `civic-match/app/api/match/route.ts` | Scores candidate profiles against user preferences. |
| Next app | POST | `/api/explain` | `civic-match/app/api/explain/route.ts` | Generates or retrieves cached explanation for one match result. |
| Next app | POST | `/api/qa` | `civic-match/app/api/qa/route.ts` | Evidence-only Q&A over one cached candidate profile. |
| Next app | GET | `/api/ballot?address=` | `civic-match/app/api/ballot/route.ts` | Server-side proxy to FastAPI `/api/ballot`; cached statewide fallback if backend is down. |
| Next app | POST | `/api/voter-insights` | `civic-match/app/api/voter-insights/route.ts` | Maps frontend voter profile shape to backend profile and proxies insight generation/lookup. |
| Next app | GET | `/api/scenario` | `civic-match/app/api/scenario/route.ts` | Lists or returns scenario trees. |
| Next app | GET | `/api/graph` | `civic-match/app/api/graph/route.ts` | Returns full graph or focus-node neighborhood. |
| Next app | GET | `/api/stakes` | `civic-match/app/api/stakes/route.ts` | Returns election stakes copy/data. |
| Next app | POST | `/api/motivate` | `civic-match/app/api/motivate/route.ts` | Generates cached civic motivation cards from preferences and cached profile version. |
| Next app | POST | `/api/debate` | `civic-match/app/api/debate/route.ts` | Streams candidate-agent debate using evidence packs. |


---

## 21. File appendix

### 21.1 FastAPI backend

| File | Responsibility |
|---|---|
| `app/main.py` | FastAPI app, endpoints, address validation, Census geocoder, insight archetype selection, middleware registration. |
| `app/datastore.py` | Backend data access, JSON/Postgres fallback, geocode cache, ballot assembly, insight persistence. |
| `app/insights.py` | OpenRouter fallback insight generation. |
| `app/google_civic.py` | Optional Google Civic enrichment. |
| `app/middleware.py` | Body size cap, rate limit, security headers. |
| `app/static/index.html` | Legacy/static UI served by FastAPI root. |

### 21.2 Next core modules

| File | Responsibility |
|---|---|
| `civic-match/lib/types.ts` | Shared product/domain types. |
| `civic-match/lib/scoring.ts` | Match scoring engine. |
| `civic-match/lib/store.ts` | File/KV persistence abstraction. |
| `civic-match/lib/db.ts` | Politician profile storage helpers and slugging. |
| `civic-match/lib/config.ts` | Issue taxonomy and UI config loading. |
| `civic-match/lib/prefs.ts` | Browser localStorage preferences. |
| `civic-match/lib/dataBackend.ts` | Server-side client for FastAPI backend. |
| `civic-match/lib/llm.ts` | OpenRouter chat helper and JSON extraction. |
| `civic-match/lib/agents.ts` | Candidate research agent orchestration and validation. |
| `civic-match/lib/discovery.ts` | Election discovery. |
| `civic-match/lib/scenario.ts` | Scenario tree generation and storage. |
| `civic-match/lib/graph.ts` | Civic graph construction/merge/neighborhood. |

### 21.3 Primary product pages

| Page | Role |
|---|---|
| `civic-match/app/page.tsx` | Landing page. |
| `civic-match/app/ballot/page.tsx` | Main ballot and match wizard. |
| `civic-match/app/intake/page.tsx` | Older/preference-first intake flow. |
| `civic-match/app/results/page.tsx` | Results page with match cards, explanations, ballot, stakes, motivation, insights. |
| `civic-match/app/p/[id]/page.tsx` | Candidate profile page. |
| `civic-match/app/future/page.tsx` | Scenario tree view. |
| `civic-match/app/graph/page.tsx` | Civic graph view. |
| `civic-match/app/debate/page.tsx` | Candidate debate simulation. |

### 21.4 Main UI components

| Component area | Role |
|---|---|
| `components/ballot/BallotSection.tsx` | Groups and renders races/candidates from backend ballot data. |
| `components/ballot/InsightsPanel.tsx` | Fetches and renders race insight bullets and horizon projections. |
| `components/MotivationCard.tsx` | Renders generated voting motivation cards. |
| `components/StakesBanner.tsx` | Renders election stakes context. |

---

## 22. Practical next build order

For the next engineering pass, the best order is not to add more model features. It is to stabilize contracts and data trust.

1. **Unify candidate ids**  
   Add canonical `person_id` across backend candidates, frontend profiles, graph nodes, race candidates, and URLs.

2. **Make exact-ballot state explicit**  
   Add `mode: exact | seeded_cache | statewide_fallback | unavailable` to ballot responses and render it in the UI.

3. **Collect only the insight profile fields you actually use**  
   Either add the missing archetype fields to the wizard or remove unused backend archetypes from the current UX.

4. **Create a release gate from `quality_report.json`**  
   Fail builds or at least block “ready” status when candidate source coverage drops below thresholds.

5. **Add JSON/Postgres parity tests**  
   This repo’s fallback story is good. Prove it with tests.

6. **Move long research to jobs**  
   Keep SSE for progress, but make it read from job state instead of holding all work inside the route lifecycle.

7. **Separate fact, interpretation, and projection in every generated surface**  
   The backend and schema already point this way. Make the UI enforce it.

8. **Delete or quarantine the legacy static UI**  
   Keep one primary frontend path.

9. **Add source snapshot/support checks**  
   URL presence is not enough for a voter product. Claims need support status.

10. **Document provider modes**  
   Create a small operator doc showing what works with no keys, with OpenRouter only, with Google Civic only, with Postgres only, and with all providers enabled.

---

## 23. Bottom-line technical read

The repo has the right skeleton for a source-grounded voter alignment product:

- precomputed official-ish race/candidate data
- address-to-district ballot lookup
- cached insight blocks
- explainable match scoring
- visible unknowns/confidence
- profile research agents with validation
- optional Postgres
- JSON fallback for fast local/demo work
- graph/scenario/debate surfaces as richer product experiments

The main technical debt is not missing features. It is contract discipline:

- canonical ids
- exact-ballot vs fallback state
- source support beyond URL presence
- consistent storage boundaries
- generated artifact freshness
- one primary frontend path

Fix those before expanding coverage or adding more LLM surfaces.
