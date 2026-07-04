# TX Voter Data Backend — Schema & Contract

Authoritative contract for the repo-root FastAPI data backend and its integration
with `civic-match/` (the Next.js product frontend). If code and this document
disagree, this document wins for anything marked **LOCKED**; anything marked
**PLANNED** or **MIGRATION** describes where the code is headed but hasn't
landed yet. Keep this file in sync with `app/`, `pipeline/`, and `data/tx/`.

---

## 1. System overview

```
Official APIs                pipeline/fetch_*.py       data/tx/raw/*.json
 Census Geocoder, OpenFEC,  ─────────────────────►     (BRONZE, gitignored)
 Congress.gov, Clerk.house.gov,                                │
 Wikipedia (all keyless or free-key)                           ▼
                                                    pipeline/build_dataset.py
                                                                │
                                                                ▼
                                       data/tx/races.json + candidates.json
                                          (GOLD, committed, source of truth)
                                                                │
                             ┌──────────────────────────────────┴───┐
                             ▼                                      ▼
              pipeline/build_insights_*.py            pipeline/load_postgres.py
              pipeline/precompute_marquee_*.py               (PLANNED)
                             │                                      │
                             ▼                                      ▼
              data/tx/insights/{race_id}.json               PostgreSQL
                             │                        (Railway prod / docker-compose local)
                             └──────────────┬───────────────────────┘
                                            ▼
                          app/datastore.py  (ONLY data-access layer;
                          Postgres when DATABASE_URL set, else gold JSON)
                                            │
                                            ▼
                     FastAPI app/main.py — GET /healthz, /api/ballot, POST /api/insights
                                            │
                                            ▼   (server-to-server; no browser CORS hop)
            civic-match Next.js same-origin proxy routes  (planned: /api/ballot, /api/voter-insights)
                                            │  reads DATA_BACKEND_URL
                                            ▼
                                         Browser
```

**Precompute-first rationale**: the demo has a 2-3 hour build budget and must
survive flaky/rate-limited government APIs live on stage, so every fact that
*can* be known ahead of time — race rosters, finance, voting records, and
even the plain-English insight bullets for all 8 voter archetypes — is
fetched once, validated, and frozen into committed gold JSON and precomputed
insight files. Runtime work shrinks to: geocode the address (cached), look
up districts in the frozen dataset, and select precomputed insight text. The
only live network call in the hot path is the Census geocoder, on a cache
miss only; OpenRouter is a pure fallback for races nobody precomputed, and
the app is fully functional with zero LLM key.

---

## 2. Database — PostgreSQL

### 2.1 DDL (locked contract)

This is the exact, locked schema. `pipeline/load_postgres.py` creates it
idempotently and loads gold JSON into it (see §2.4).

```sql
CREATE TABLE IF NOT EXISTS races (
  race_id TEXT PRIMARY KEY,
  office TEXT NOT NULL,
  level TEXT NOT NULL CHECK (level IN ('federal','state','state_leg')),
  district TEXT,
  election_date DATE NOT NULL DEFAULT '2026-11-03',
  context JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_races_district ON races(district);
CREATE INDEX IF NOT EXISTS idx_races_level ON races(level);

CREATE TABLE IF NOT EXISTS candidates (
  candidate_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  party TEXT,
  office TEXT,
  district TEXT,
  incumbent BOOLEAN,
  fec_id TEXT,
  finance JSONB,
  record JSONB,
  positions JSONB NOT NULL DEFAULT '[]'::jsonb,
  sources JSONB NOT NULL DEFAULT '[]'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_cand_district ON candidates(district);
CREATE INDEX IF NOT EXISTS idx_cand_name ON candidates(name);

CREATE TABLE IF NOT EXISTS race_candidates (
  race_id TEXT NOT NULL REFERENCES races(race_id) ON DELETE CASCADE,
  candidate_id TEXT NOT NULL REFERENCES candidates(candidate_id) ON DELETE CASCADE,
  PRIMARY KEY (race_id, candidate_id)
);

-- One row per (race_id, archetype) block ('base' plus each precomputed
-- voter archetype) rather than one row per race, so a single block can be
-- hash-gated and write-through cached independently of the rest of its
-- race (app/datastore.py::put_insight_block, called after a live LLM
-- generation). inputs_hash is a sha256 over that race's candidates'
-- canonical JSON (json.dumps sort_keys=True) -- same hash for every block
-- belonging to a race; pipeline/load_postgres.py skips rewriting a row
-- when its stored inputs_hash still matches (latest-wins ON CONFLICT
-- otherwise, default incremental upsert, --reset to force a full reload).
CREATE TABLE IF NOT EXISTS insights (
  race_id TEXT NOT NULL,
  archetype TEXT NOT NULL,
  payload JSONB NOT NULL,
  generated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  inputs_hash TEXT,
  PRIMARY KEY (race_id, archetype)
);

CREATE TABLE IF NOT EXISTS geocode_cache (
  address_norm TEXT PRIMARY KEY,
  matched_address TEXT,
  cd TEXT, sd TEXT, hd TEXT, county TEXT,
  civic JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE geocode_cache ADD COLUMN IF NOT EXISTS civic JSONB;
```

`race_id` examples actually in `data/tx/races.json`: `tx-gov-2026`,
`tx-sen-2026`, `tx-ag-2026`, `tx-cd02-2026` (US House pattern is
`tx-cd{NN}-2026`, zero-padded, for TX-01..TX-38). `candidate_id` is a
`lastname-firstname` slug, e.g. `abbott-greg`, `crenshaw-daniel`,
`paxton-ken` — note this is the **opposite** convention from civic-match's
`firstname-lastname` slug (see §5).

### 2.2 JSONB column shapes

#### `races.context`

Free-form per-race context. Currently just prior-cycle result + sourcing.
Real example (`tx-gov-2026`):

```json
{
  "sources": ["https://en.wikipedia.org/wiki/2026_Texas_gubernatorial_election"],
  "last_result": "Incumbent prior to 2026: Greg Abbott"
}
```

House-race contexts additionally carry `margin_pct` from 2024 (used by the
insight pipeline to decide "competitive" races — see §3). Field is present
only where the 2024 Wikipedia district table had a usable number; never
invented.

#### `candidates.finance`

| field | type | notes |
|---|---|---|
| `receipts` | number | total campaign receipts, FEC cycle-to-date |
| `disbursements` | number | total spending |
| `cash_on_hand` | number \| null | `null` when FEC didn't report it for that filer |
| `as_of` | string (date) | pull date, not filing date |
| `source` | string (URL) | FEC candidate page, e.g. `https://www.fec.gov/data/candidate/H8TX02166/` |

Real example (`crenshaw-daniel`):

```json
"finance": {
  "receipts": 2671297.23,
  "disbursements": 3097368.05,
  "cash_on_hand": null,
  "as_of": "2026-07-04",
  "source": "https://www.fec.gov/data/candidate/H8TX02166/"
}
```

Only federal candidates (US House/Senate) have `finance` — TX statewide
offices don't file with the FEC, and Texas Ethics Commission state-finance
data was a Tier-2/stretch source not pulled. 39 of 96 candidates have no
`finance` field at all — omitted, never zero-filled.

#### `candidates.record`

| field | type | notes |
|---|---|---|
| `key_votes` | array | see below |
| `sponsored_highlights` | array of strings | legislation the member sponsored; empty pipeline-wide today (Congress.gov 429'd on `DEMO_KEY` for the whole build window) |
| `source` | string (URL) | roster/background source, e.g. legislators-current.yaml or Congress.gov |

`record.key_votes[]` real shape (richer than the simplified stub in early
planning notes — it also carries `question` and `result`, both present in
actual pipeline output and used in insight text):

```json
{
  "bill": "H R 29",
  "question": "On Passage",
  "plain_english": "A Yea vote required federal detention of unauthorized immigrants charged with theft, burglary, larceny, or assaulting a law enforcement officer, and let state attorneys general sue the federal government over certain immigration enforcement decisions.",
  "position": "Yea",
  "date": "7-Jan-2025",
  "result": "Passed",
  "source": "https://clerk.house.gov/evs/2025/roll006.xml"
}
```

`crenshaw-daniel` has 7 `key_votes` entries — one of the few candidates with
both `finance` and populated `record.key_votes` (most House incumbents do;
challengers/statewide candidates generally don't, since roll-call votes
only exist for sitting House/Senate members).

#### `candidates.positions[]`

Contract shape: `{"issue": string, "summary": string, "source": string}`.
**Honest gap**: `positions` is `[]` for all 96 candidates today — no
Tier-1 API surfaced issue-by-issue stances within the build window, so
nothing was invented. `civic-match`'s own Kimi research swarm *does*
produce issue stances (`Stance[]` in `lib/types.ts`); a planned
reverse-bridge imports their researched stances into this field
non-destructively — not landed yet.

#### `candidates.sources[]`

Flat array of URLs backing the candidate's name/party/office/district/
incumbency facts, independent of the more specific `finance.source` /
`record.*.source` / `positions[].source`. Example (`crenshaw-daniel`):

```json
[
  "https://clerk.house.gov/Votes",
  "https://raw.githubusercontent.com/unitedstates/congress-legislators/main/legislators-current.yaml",
  "https://www.fec.gov/data/candidate/H8TX02166/"
]
```

### 2.3 `insights` table / files

One row (Postgres) or one file `data/tx/insights/{race_id}.json` (JSON
fallback) per race. Real shape, from `data/tx/insights/tx-sen-2026.json`:

```json
{
  "race_id": "tx-sen-2026",
  "generated_at": "2026-07-03",
  "base": {
    "candidates": {
      "paxton-ken": [
        {"text": "Ken Paxton is a candidate for United States Senator from Texas, running with Republican Party (United States).",
         "source": "https://en.wikipedia.org/wiki/2026_United_States_Senate_election_in_Texas"},
        {"text": "As of 2026-07-04, Ken Paxton's campaign had raised $7,605,209 in campaign receipts and spent $5,257,746, per FEC filings.",
         "source": "https://www.fec.gov/data/candidate/S6TX00388/"}
      ]
    },
    "summary": "United States Senator from Texas race: Ken Paxton, James Talarico. ...",
    "caveats": "Our data set for this race covers candidate name, party, incumbency, background summary, and (for federal candidates only) FEC campaign finance totals. ..."
  },
  "archetypes": {
    "renter_young_worker": {
      "candidates": { "...": [ {"text": "No public data in our set connects Ken Paxton's recorded background or positions specifically to housing costs, rent, or renters' protections.", "source": "..."} ] },
      "summary": "...",
      "caveats": "..."
    }
  }
}
```

**MIGRATION note**: `app/main.py`'s `_select_cached_bullets` currently reads
`cached.get("candidates", {})` at the *top level* of this file, but the real
file (and every `pipeline/build_insights_*.py` / `precompute_marquee_*.py`
writer) nests candidates under `base` and `archetypes.{key}` instead. This
is a known, tracked mismatch (CLAUDE.md: "insights-shape selection" queued
as a contract fix) — the reader needs to select `payload["archetypes"].get(archetype, payload["base"])["candidates"]`
with fallback to `base`. Until fixed, `POST /api/insights` returns empty
candidate bullets for every cached race. Base-vs-archetype depth rule: only
"competitive" races (last_result margin_pct < 10, or no incumbent in the
race) get all 8 archetypes precomputed; safe races get `base` only.

### 2.4 Load path

- `pipeline/load_postgres.py` — **present.** Reads `data/tx/races.json` +
  `candidates.json` + `insights/*.json`, runs the DDL above
  (`CREATE TABLE IF NOT EXISTS`), then reloads all gold-derived tables in one
  transaction (idempotent, safe to rerun after every gold-data change);
  `geocode_cache` is left untouched (live runtime cache). Driven entirely by
  `DATABASE_URL`; `--dry-run` validates the inputs without touching a DB.
  `requirements.txt` ships the `psycopg[binary,pool]` client it needs.
- **JSON fallback**: `app/datastore.py` is Postgres-when-set — it connects
  via `DATABASE_URL` (psycopg3 + connection pool) and falls back to reading
  `races.json` + `candidates.json` directly when the var is unset, psycopg is
  missing, or the first connection fails (logged once, never fatal). Same
  logical schema either way — one JSON object per race/candidate, keyed the
  same way. SQLite is fully removed. If neither source is reachable, every
  call degrades to empty results and `stats()`/`get_ballot()` surface
  `data_pending: true` rather than erroring — the app must still boot.

---

## 3. Pipeline (`pipeline/*.py`)

| Script | Fetches | From | Output |
|---|---|---|---|
| `fetch_statewide.py` | Gov, Lt Gov, AG, Comptroller, Land/Ag Comm candidates + bios | Wikipedia `action=parse` (keyless) | `data/tx/raw/statewide.json` |
| `fetch_fec.py` | TX federal (House+Senate) 2026 candidates + finance | OpenFEC `/v1`, `FEC_API_KEY` or `DEMO_KEY` | `data/tx/raw/fec.json` |
| `fetch_votes.py` | TX delegation roster, 8 House roll calls, senator sponsored-legislation | Congress.gov `/v3` + `congress-legislators` YAML fallback + `clerk.house.gov` XML | `data/tx/raw/incumbent_votes.json` |
| `fetch_context.py` | 2024 prior-cycle results/toplines (`context.last_result`/`margin_pct`) | Wikipedia (not OpenElections CSVs — see gap below) | `data/tx/raw/district_context.json` |
| `build_dataset.py` | bronze → gold merge, heuristic joins (FEC filer ↔ incumbent, dedup) | all 4 `raw/*.json` | `races.json`, `candidates.json`, legacy `app.db`, `unjoined_report.json` |
| `build_insights_house.py` / `build_insights_tx20_38.py` | authors base+archetype bullets, no LLM | TX-01..19 / TX-20..38 gold data | `data/tx/insights/tx-cd{NN}-2026.json` |
| `precompute_marquee_insights.py` | same, statewide + US Senate | gold data, `district == null` | `data/tx/insights/{tx-gov,tx-sen,...}-2026.json` |
| `validate_data.py` | schema/source/join integrity checks | gold JSON + sqlite | PASS/FAIL to stdout |
| `validate_insights_*.py` | verifies every bullet's `source` traces to that candidate's JSON, drops/rewrites any that don't | `data/tx/insights/*.json` | rewrites in place |
| `precache_demo.py` | hits live app for 3 fixed addresses (San Marcos, Austin, Houston), freezes responses as stage-crash safety net | running FastAPI | `data/demo_cache/*.json` |
| `smoke_backend.py` | in-process FastAPI smoke test | — | PASS/FAIL to stdout |
| `load_postgres.py` | creates schema + upserts all gold rows | gold JSON + insights | Postgres via `DATABASE_URL` |
| `export_civic_match.py` **(planned)** | not present yet | our candidate evidence | merges into `civic-match/data/politicians/*.json` |

All rerun as `python3 pipeline/<script>.py`; each is idempotent/deterministic and never mutates `raw/`.

### Honest data gaps (from `data/tx/unjoined_report.json` + CLAUDE.md status log)

- **7 incumbents lost their FEC join to 2025 redistricting** (`incumbent_added_without_fec_match`) — e.g. Al Green (TX-09), Randy Weber (TX-14), Beth Van Duyne (TX-24), Roger Williams (TX-25): found in the legislators roster but no matching 2026 FEC filer for the *current* district lines; carry roster/vote data but no `finance`.
- **30 ambiguous same-party filer groups** (`ambiguous_same_party_filers`) — resolved by heuristic "prefer `incumbent_challenge='Incumbent'`, then highest receipts," alternates logged, never silently dropped.
- **9 districts needed a looser FEC filter** (`house_district_zero_party_coverage`) — e.g. TX-01 force-included a `has_activity=false` incumbent row so the real `fec_id` wins over a synthetic one; TX-13 fell back to `candidate_status='C'` regardless of activity.
- **`positions[]` and `sponsored_highlights` are empty pipeline-wide** — no Tier-1 source surfaced issue stances; Congress.gov `/sponsored-legislation` 429'd on `DEMO_KEY` the whole build window (logged in `upstream_fetch_gaps`, not guessed).
- **TX-23 has no current House member in the roster fallback** — `legislators-current.yaml` lag / vacant-seat ambiguity; omitted rather than guessed.
- **2024 "last_result" context deliberately avoids OpenElections CSVs** — an earlier attempt aggregated only ~184/254 TX counties and produced a verifiably wrong statewide topline (showed Harris winning TX). Switched to Wikipedia's district-by-district tables, which match known 2024 outcomes.
- Current totals (validated): **46 races / 96 candidates / 290 vote records**, 39/96 candidates missing `finance`, 0 with non-empty `positions` or `sponsored_highlights`.

---

## 4. HTTP API

Base: FastAPI app, `app/main.py`. No auth, stateless — the request body is
never persisted.

### `GET /healthz`

No params. Response 200:

| field | type |
|---|---|
| `status` | `"ok"` |
| `data_loaded` | bool — `false` only if neither Postgres nor gold JSON is reachable |
| `races` | int |
| `candidates` | int |
| `insights_cached` | int — count of `data/tx/insights/*.json` files |

```json
{"status": "ok", "data_loaded": true, "races": 46, "candidates": 96, "insights_cached": 46}
```

### `GET /api/ballot?address=<free text>`

Query param: `address` (required, `min_length=3`, free text — e.g.
`"601 University Dr, San Marcos, TX 78666"`).

Flow: normalize + check `geocode_cache` (Postgres table / `data/geocode_cache.json`
fallback) → on miss, call the Census geocoder (`geocoding.geo.census.gov`,
8s timeout) → extract CD/SD/HD/county from the `119th Congressional
Districts` / `2024 State Legislative Districts - Upper` / `- Lower` /
`Counties` geography layers → cache the result → `datastore.get_ballot`.

Response 200:

| field | type | notes |
|---|---|---|
| `matched_address` | string | Census-normalized address |
| `districts.cd` | string \| null | `"TX-35"` pattern |
| `districts.sd` | string \| null | `"SD-21"` pattern (TX Senate — stretch goal data, may have no matching race) |
| `districts.hd` | string \| null | `"HD-45"` pattern (TX House — stretch goal) |
| `districts.county` | string \| null | |
| `races[]` | array | statewide races + the race matching `districts.cd` (+ `sd`/`hd` if populated) |
| `races[].race_id`, `.office`, `.level`, `.district`, `.context` | — | per §2.1/§2.2 |
| `races[].candidates` | **array** of candidate objects (see migration note below) | |
| `candidates[].candidate_id`, `.name`, `.party`, `.incumbent`, `.fec_id` | — | |
| `candidates[].finance` | object \| omitted | §2.2 |
| `candidates[].record.key_votes[]` | array | `{bill, question, plain_english, position, date, result, source}` |
| `candidates[].record.sponsored_highlights` | array of strings | currently always `[]` |
| `candidates[].positions[]` | array | currently always `[]` |
| `candidates[].sources[]` | array of URLs | |
| `warning` | string, optional | `"data_pending: race/candidate data not yet loaded for this district"` |
| `voting_info` | object, **OPTIONAL — enrichment** | only present when `GOOGLE_CIVIC_API_KEY` is set AND Google has data for this address; see below |
| `division_check` | object, **OPTIONAL — enrichment** | only present when the above key is set AND Google returned at least one OCD division with a comparable congressional-district number; see below |

Example (truncated to 1 race, 1 candidate, `key_votes` truncated to 1):

```json
{
  "matched_address": "601 UNIVERSITY DR, SAN MARCOS, TX, 78666",
  "districts": {"cd": "TX-37", "sd": "SD-21", "hd": "HD-45", "county": "Hays"},
  "races": [
    {
      "race_id": "tx-cd02-2026",
      "office": "U.S. Representative, TX-02",
      "level": "federal",
      "district": "TX-02",
      "context": {"last_result": "...", "sources": ["..."]},
      "candidates": [
        {
          "candidate_id": "crenshaw-daniel",
          "name": "Daniel Crenshaw",
          "party": "Republican",
          "office": "U.S. Representative, TX-02",
          "district": "TX-02",
          "incumbent": true,
          "fec_id": "H8TX02166",
          "finance": {"receipts": 2671297.23, "disbursements": 3097368.05, "cash_on_hand": null, "as_of": "2026-07-04", "source": "https://www.fec.gov/data/candidate/H8TX02166/"},
          "record": {
            "key_votes": [
              {"bill": "H R 29", "question": "On Passage", "plain_english": "A Yea vote required federal detention of unauthorized immigrants charged with theft, burglary, larceny, or assaulting a law enforcement officer...", "position": "Yea", "date": "7-Jan-2025", "result": "Passed", "source": "https://clerk.house.gov/evs/2025/roll006.xml"}
            ],
            "sponsored_highlights": []
          },
          "positions": [],
          "sources": ["https://clerk.house.gov/Votes", "https://www.fec.gov/data/candidate/H8TX02166/"]
        }
      ]
    }
  ]
}
```

**MIGRATION note**: the contract is `races[].candidates` as an **array of
candidate objects**. The current code (`app/datastore.py:_embed_candidates`)
builds a **dict keyed by `candidate_id`** instead
(`{"crenshaw-daniel": {...}, ...}`) — a migration agent is converting this
to the array shape in parallel; treat the array as authoritative for any new
client code.

#### `voting_info` / `division_check` — OPTIONAL Google Civic enrichment

Added 2026-07-03 (`app/google_civic.py`), gracefully degrading and entirely
additive: absent `GOOGLE_CIVIC_API_KEY`, the response is byte-identical to
the contract above. Backed by the Google Civic Information API's
`elections`/`voterInfoQuery` endpoints only — its `representatives` resource
was shut down in 2025 and is never called (see
`data/endpoint_inventory.json`'s `google-civic` entry, the ground truth for
this integration).

`voting_info` (present only when the key is set AND Google has *useful*
data for this address — an election name/date or at least one location;
an all-empty hit is treated the same as no coverage and the field is
omitted):

| field | type | notes |
|---|---|---|
| `voting_info.election.name` | string \| null | |
| `voting_info.election.date` | string \| null | e.g. `"2026-11-03"` |
| `voting_info.polling_locations[]` | array of `{name, address, hours}` | possibly empty |
| `voting_info.early_vote_sites[]` | array of `{name, address, hours}` | possibly empty |
| `voting_info.dropoff_locations[]` | array of `{name, address, hours}` | possibly empty |
| `voting_info.contests_present` | bool | whether Google has ballot contests loaded for this address |
| `voting_info.source` | string (URL) | always `"https://developers.google.com/civic-information"` |

`division_check` (present only when Google returned at least one OCD
division ID with a parseable `cd:NN` congressional-district number — a live
cross-validation of our own Census-derived resolver, not fabricated when
there's nothing comparable on either side):

| field | type | notes |
|---|---|---|
| `division_check.consistent` | bool | whether `districts.cd`'s district number matches one of Google's OCD division IDs for this address |
| `division_check.ocd_ids[]` | array of strings | Google's OCD division IDs for this address, e.g. `"ocd-division/country:us/state:tx/cd:35"` |

Example (both fields populated):

```json
{
  "voting_info": {
    "election": {"name": "Texas General Election 2026", "date": "2026-11-03"},
    "polling_locations": [{"name": "San Marcos City Hall", "address": "630 E Hopkins St, San Marcos TX 78666", "hours": "7:00am-7:00pm"}],
    "early_vote_sites": [],
    "dropoff_locations": [],
    "contests_present": true,
    "source": "https://developers.google.com/civic-information"
  },
  "division_check": {"consistent": true, "ocd_ids": ["ocd-division/country:us/state:tx/cd:35"]}
}
```

Both fields are cached per normalized address alongside the Census geocode
result (`datastore.geocode_cache_get_civic`/`put_civic` — a `civic_json`
column/key riding on the same `geocode_cache` row/entry as §2.1's table, so
a repeat address never re-hits the Civic API, including a repeat "no
coverage yet" result). Failure modes (no key, 403, quota exceeded, timeout,
no election data loaded this far from Nov 2026) all degrade to the fields
simply being omitted — never a 4xx/5xx caused by this enrichment.

### `POST /api/insights`

Body:

```json
{"profile": {"veteran": true, "occupation": "nurse"}, "race_id": "tx-sen-2026"}
```

`profile` — see §5 for the full field list; every field optional, `{}` is
valid. `race_id` — required string, must match a `races.race_id`.

Response 200:

| field | type |
|---|---|
| `mode` | `"cached"` \| `"live"` \| `"unavailable"` |
| `archetype_used` | one of the 8 archetype keys or `"base"` |
| `candidates` | object keyed by `candidate_id` → array of `{text, source}` bullets |
| `summary` | string |
| `caveats` | string |

Example (cached, 1 candidate, bullets truncated to 1):

```json
{
  "mode": "cached",
  "archetype_used": "veteran",
  "candidates": {
    "paxton-ken": [
      {"text": "Ken Paxton is a candidate for United States Senator from Texas, running with Republican Party (United States).",
       "source": "https://en.wikipedia.org/wiki/2026_United_States_Senate_election_in_Texas"}
    ]
  },
  "summary": "United States Senator from Texas race: Ken Paxton, James Talarico. This overview lists each candidate's party, background, and campaign finance where available in our data set.",
  "caveats": "Our data set for this race covers candidate name, party, incumbency, background summary, and (for federal candidates only) FEC campaign finance totals. We do not have recorded voting histories or issue-by-issue policy positions for these candidates in this data set..."
}
```

When `mode: "unavailable"`, the response is instead
`{"mode": "unavailable", "detail": "Insights not yet generated for this race"}`
(no `candidates`/`summary`/`caveats` keys).

### Error table

| Status | Endpoint | Trigger | Body |
|---|---|---|---|
| 400 | `/api/ballot` | geocoder matched an address outside Texas | `{"detail": "This demo covers Texas addresses"}` |
| 422 | `/api/ballot` | Census geocoder returned zero address matches | `{"detail": "We couldn't match that address. Please check it and try again (include city, state, ZIP)."}` |
| 503 | `/api/ballot` | geocoder timeout / HTTP error / unparseable response | `{"detail": "District lookup unavailable, try again"}` |
| 404 | `/api/insights` | `race_id` unknown AND no OpenRouter key path taken (only reachable inside the live-generation branch) | `{"detail": "Unknown race_id '<id>'"}` |
| 502 | `/api/insights` | live OpenRouter generation raised (`ValueError` or other exception) | `{"detail": "Could not generate insights right now, try again"}` |

---

## 5. Frontend integration

### Profile object (from CLAUDE.md § API contract; all fields optional)

| field | type / allowed values |
|---|---|
| `occupation` | free text |
| `age_bracket` | `"18_24"` \| `"25_34"` \| `"35_49"` \| `"50_64"` \| `"65_plus"` |
| `income_bracket` | `"under_35k"` \| `"35_75k"` \| `"75_150k"` \| `"150k_plus"` |
| `housing` | `"renter"` \| `"homeowner"` |
| `kids_public_school` | bool |
| `health_coverage` | `"employer"` \| `"aca"` \| `"medicare"` \| `"uninsured"` |
| `veteran` | bool |
| `small_business_owner` | bool |
| `student` | bool |

`app/main.py`'s `_profile_archetype` is slightly more permissive than this
list, harmlessly: it also accepts `small_business` as a synonym for
`small_business_owner`, and a bare `renter` boolean flag alongside/instead
of `housing: "renter"`.

### Deterministic profile → archetype precedence (exact order, first match wins)

1. `veteran: true` → `veteran`
2. `small_business_owner` (or `small_business`) truthy → `small_business_owner`
3. `student: true` → `student`
4. `health_coverage` in `{"aca", "uninsured"}` → `healthcare_aca_or_uninsured`
5. `health_coverage == "medicare"` OR age bracket implies 65+ → `medicare_retiree`
6. `kids_public_school: true` → `homeowner_parent`
7. `renter` flag true AND parsed age-bracket lower bound < 40 → `renter_young_worker`
8. `occupation` contains `farm`/`ranch`/`agri` (case-insensitive) → `rural_agriculture`
9. otherwise → `base`

### civic-match integration pattern

```
Browser
  │  fetch("/api/ballot?address=...")   ── same-origin, no CORS needed
  ▼
civic-match Next.js route handler (planned: app/api/ballot/route.ts,
  app/api/voter-insights/route.ts — not present in the repo yet)
  │  server-to-server fetch, reads DATA_BACKEND_URL env var
  ▼
FastAPI  GET /api/ballot | POST /api/insights   (this repo, CORS opened for
  civic-match's origins as a defense-in-depth measure, but not required on
  this path since the browser never calls FastAPI directly)
```

`civic-match/lib/dataBackend.ts` (planned, not present yet) is meant to be
the single typed client wrapping these two calls — analogous to how
`civic-match/lib/types.ts` (exists today) already defines the frontend's own
`PoliticianProfile` / `VoterProfile` / `MatchResult` shapes; read it for the
target TS types the exporter must translate our JSON into. Until the proxy
routes and `dataBackend.ts` land, civic-match consumes only its own
Kimi-researched `data/politicians/*.json`, not this backend.

Slug convention mismatch to translate in the exporter: this backend uses
`lastname-firstname` (`crenshaw-daniel`), civic-match's `lib/db.ts slugify`
uses `firstname-lastname` (`daniel-crenshaw`). `pipeline/
export_civic_match.py` (planned) translates this when it merges our
sourced evidence into their `PoliticianProfile` shape, non-destructively,
and must never rewrite civic-match's own `texas.json` — new district-level
House races go in a separate `civic-match/data/elections/texas-house.json`.

---

## 6. Environment & ops

| Var | Side | Required? | Purpose |
|---|---|---|---|
| `DATABASE_URL` | backend | optional | Postgres connection string; unset → JSON/sqlite fallback, app still fully functional |
| `OPENROUTER_API_KEY` | backend | optional | live insight generation fallback only; unset → precomputed-only, `mode: "unavailable"` for uncached races |
| `CORS_ORIGINS` | backend | recommended | allow civic-match's localhost:3000 + its Railway/Vercel domain |
| `FEC_API_KEY` | pipeline only | optional | `pipeline/fetch_fec.py`; `DEMO_KEY` works meanwhile |
| `CONGRESS_GOV_API_KEY` | pipeline only | optional | `pipeline/fetch_votes.py`; `DEMO_KEY` is rate-limited (see §3 gaps) |
| `OPENSTATES_API_KEY` | pipeline only | stretch goal | TX Legislature (150 HD/~15 SD), not pulled in current dataset |
| `DATA_BACKEND_URL` | civic-match | required once proxy routes land | base URL of this FastAPI service, used by planned `app/api/ballot`, `app/api/voter-insights` route handlers |

### Local run

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload            # data backend, http://localhost:8000 (/healthz)

# optional, for Railway-parity locally:
docker compose up -d                     # local Postgres (docker-compose.yml)
python3 pipeline/load_postgres.py        # idempotent load into Postgres

cd civic-match && npm install
npm run seed                              # auto-discover TX races + research candidates
npm run dev                               # product UI, http://localhost:3000
```

### Railway deploy

Two services + Railway Postgres add-on:

- **backend**: this repo root. `railway.json` (`NIXPACKS` builder,
  `startCommand: uvicorn app.main:app --host 0.0.0.0 --port $PORT`,
  `healthcheckPath: /healthz`) + matching `Procfile`; `nixpacks.toml` pins
  `providers=["python"]` and `.python-version` pins 3.12 (a stray root
  `package.json` once flipped Nixpacks to the Node provider and broke the
  deploy — don't reintroduce one). Data ships committed in the repo (gold
  JSON + insights), so the service boots functional even without Postgres.
  Env vars: optional `OPENROUTER_API_KEY`, plus `DATABASE_URL` referencing
  the project's Postgres service (`${{Postgres.DATABASE_URL}}` — live in
  prod as of 2026-07-04, loaded via `python3 pipeline/load_postgres.py`
  against the DB's public URL; rerun after any gold-data change).
- **frontend**: `civic-match/` as its own Railway (or Vercel) service,
  `DATA_BACKEND_URL` pointed at the backend service's public URL.

---

## 7. Failure modes & fallbacks

| Failure | Fallback | Residual behavior |
|---|---|---|
| Postgres unreachable / `DATABASE_URL` unset | `app/datastore.py` reads `data/tx/races.json` + `candidates.json` directly | fully functional, same logical schema, no downtime |
| Neither Postgres nor gold JSON present | every datastore query returns empty | `stats()`/`get_ballot()` surface `data_loaded: false`; `/api/ballot` returns `warning: "data_pending: ..."`; app still boots |
| Census geocoder down/timeout | `geocode_cache` (Postgres table or `data/geocode_cache.json`) still serves previously-seen addresses | uncached addresses → `503 "District lookup unavailable, try again"` |
| Census geocoder returns no match | — | `422`, never silently returns an empty ballot |
| No `OPENROUTER_API_KEY` | precomputed `data/tx/insights/{race_id}.json` only | any race without a precomputed file → `{"mode": "unavailable", "detail": "Insights not yet generated for this race"}` |
| `OPENROUTER_API_KEY` set but live generation raises | — | `502 "Could not generate insights right now, try again"` |
| Race/candidate data not yet loaded for a matched district | `get_ballot` still returns statewide races | `warning: "data_pending: ..."` flag lets the frontend degrade gracefully instead of erroring |

---

## 8. Scaling path

- **More states**: `race_id`/`candidate_id` are already state-agnostic
  string slugs (`tx-cd02-2026`, `crenshaw-daniel`) — extending beyond Texas
  means adding a `state` column to `races`/`candidates` (or encoding it in
  the existing `race_id` prefix, e.g. `oh-sen-2026`) and running the same
  bronze→gold pipeline per state. `district` string patterns (`TX-NN`,
  `SD-NN`, `HD-NN`) would need a state prefix too to stay globally unique.
- **Postgres growth**: the DDL's `idx_races_district`, `idx_races_level`,
  `idx_cand_district`, `idx_cand_name` cover the current query patterns
  (`get_ballot` by district triple, `search_candidates` by name); a
  read-replica in front of `app/datastore.py`'s Postgres path is a drop-in
  scaling step since every query in that module is already read-only except
  the geocode cache writes.
- **MCP-shaped primitives**: `app/datastore.py`'s functions
  (`get_ballot`, `get_race`, `get_candidate`, `list_races`,
  `search_candidates`, `get_insights`, `stats`) were deliberately kept as a
  narrow, storage-agnostic query API — no endpoint touches storage
  directly — specifically so a post-hackathon FastMCP wrapper can expose
  the same primitives as MCP tools without touching the data-access layer.
