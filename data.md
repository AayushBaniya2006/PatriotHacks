# Data Architecture

How this repo separates **facts** from **predictions**, where each lives, and how both get
regenerated. This is the map; the contracts live elsewhere — see **Cross-links** at the
bottom before editing anything here.

---

## 1. The one principle

**Quantitative data is a stored, immutable fact — quoted from an official source and
stamped with when it was pulled.** Finance totals, roll-call votes, district lines, 2024
margins: once fetched and joined into gold JSON, they don't change until the next pipeline
run, and every value carries its own `source` URL (and often `as_of`/`date`). **Qualitative
data is a derived prediction — regenerable and versioned, not a fact.** Archetype insights and
consequence horizons are text *authored from* the quantitative facts (or from an LLM grounded
in them); they can be thrown away and recomputed at any time without losing information,
because the facts they're derived from are what's actually durable. If it can be re-derived
from source data, treat it as a cache, not a record.

---

## 2. Storage map

| Layer | Location(s) | Nature | Written by |
|---|---|---|---|
| **Bronze** (raw fetches) | `data/tx/raw/{statewide,fec,incumbent_votes,district_context}.json` | Untouched API responses, gitignored-in-spirit but currently committed for reproducibility | `pipeline/fetch_statewide.py`, `fetch_fec.py`, `fetch_votes.py`, `fetch_context.py` |
| **Gold** (source of truth) | `data/tx/races.json`, `data/tx/candidates.json` | Merged, joined, validated — committed to git, the audit trail | `pipeline/build_dataset.py` |
| **Gold, quality-embedded** | same two files (+ `data/tx/quality_report.json`, `data/tx/QUALITY.md`) | Additive `data_quality` block appended to every race/candidate | `pipeline/score_quality.py` |
| **Derived — precomputed insights** | `data/tx/insights/{race_id}.json` (46 files, one per race) | Authored bullets, base + up to 8 archetypes, no LLM | `pipeline/build_insights_house.py`, `build_insights_tx20_38.py`, `precompute_marquee_insights.py` |
| **Serving layer** | Postgres tables `races`, `candidates`, `race_candidates`, `insights`, `geocode_cache` | Idempotent projection of the two gold files + insights dir | `pipeline/load_postgres.py` |
| **Runtime caches** | `data/geocode_cache.json` (JSON fallback) / Postgres `geocode_cache` table | Live, gitignored, never touched by the loader | `app/datastore.py` (`geocode_cache_put`) |
| **Demo safety net** | `data/demo_cache/` | Frozen full responses for 3 fixed addresses, stage-crash insurance | `pipeline/precache_demo.py` |
| **Teammate file-DB** | `civic-match/data/politicians/*.json` | Kimi-research `PoliticianProfile` JSONs — their gold data, we only read it | civic-match's own seed/backfill scripts (not ours) |

Everything above `Runtime caches` is deterministic and rerunnable from bronze; nothing in this
repo treats a cache as a record of truth.

---

## 3. Quantitative path

```
official API  →  pipeline/fetch_*.py  →  data/tx/raw/*.json  (bronze, gitignored-in-spirit)
                                                │
                                                ▼
                                pipeline/build_dataset.py  (join, dedup, heuristics)
                                                │
                                                ▼
                        data/tx/races.json + candidates.json   (GOLD — git IS the audit trail)
                                                │
                                                ▼
                                pipeline/score_quality.py  (additive data_quality embed)
                                                │
                                                ▼
                                pipeline/load_postgres.py  (idempotent TRUNCATE + reload)
                                                │
                                                ▼
                     Postgres JSONB columns: candidates.finance / .record / .positions
```

Every quantitative fact carries **`source`** (a URL) and, where the API provides it,
**`as_of`**/`date` (pull date, not necessarily filing date — see `schema.md` §2.2 for the
exact `finance`/`record.key_votes[]` shapes). Nothing is zero-filled or invented: a missing
fact is an **omitted key**, never a guessed value (`data/tx/unjoined_report.json` and
`QUALITY.md` log every known gap by name).

**Quality tiers are computed, not judged.** `score_quality.py` is deterministic and offline —
no network, no LLM — and embeds `data_quality: {score, tier, missing[]}` on every candidate
and `{score, tier, demo_rank}` on every race, purely as a weighted-completeness function of
what's already in the gold JSON (weights documented in the script's header). Tier A/B/C/D and
`demo_rank` exist to pick good addresses for a live demo, not to editorialize about candidates.

---

## 4. Qualitative path (predictions)

Insight bullets and consequence horizons are **authored from the same gold candidate JSON**,
not invented: `build_insights_house.py` / `build_insights_tx20_38.py` /
`precompute_marquee_insights.py` are pure Python authoring passes (no LLM) that read a
candidate's `finance`/`record`/`positions` and emit `{text, source}` bullets whose source URL
is copied verbatim from that same record. When a candidate has nothing relevant to a topic,
the bullet says so explicitly ("no public data in our set on X") instead of guessing.
Validators (`validate_insights_house.py`, `validate_insights_tx20_38.py`,
`validate_marquee_insights.py`) then re-check every bullet's source traces back to that
candidate's own JSON, rewriting/dropping anything that doesn't. Live generation
(`OPENROUTER_API_KEY` set, race has no cache) follows the same grounding rule at request time
in `app/insights.py` — never the network-response text, only that candidate's stored record.

### Freshness model

| | **Current state** | Still open |
|---|---|---|
| Key | `(race_id, archetype)` composite key — one row per precomputed block, not per race | — |
| Payload | one row per archetype, independently regenerable (`base` plus each of the 8 archetypes is its own row) | — |
| Regeneration | `generated_at` + `inputs_hash` (sha256 over that race's candidate data) gate every reload — `pipeline/load_postgres.py` skips a row when the hash is unchanged, upserts it when the hash differs; `--reset` forces an unconditional full reload of `insights` | — |
| Write path | latest-wins `INSERT ... ON CONFLICT (race_id, archetype) DO UPDATE`, scoped per block (`pipeline/load_postgres.py`, `app/datastore.py::put_insight_block`) | — |
| Live LLM output | write-through cached into the same keyed table on first generation (`put_insight_block`), so a later request for the same `(race_id, archetype)` is served from cache | — |
| History | none — an UPDATE overwrites the prior payload for that block | optional append-only `insights_history` table for audit/rollback |

The grain is `race × archetype`, not "whole race": a one-archetype edit (or one live
LLM write-through) upserts exactly that row without touching the other seven archetypes
or `base`.

---

## 5. Freshness & regeneration

Rerun order — each stage consumes only the previous stage's output, so a partial rerun (e.g.
just re-scoring quality) is always safe: **fetchers → build_dataset → import_civicmatch_positions
→ score_quality → precompute insights/horizons → validators → load_postgres.**

Copy-pasteable full rerun:

```bash
python3 pipeline/fetch_statewide.py
python3 pipeline/fetch_fec.py
python3 pipeline/fetch_votes.py
python3 pipeline/fetch_context.py
python3 pipeline/build_dataset.py
python3 pipeline/import_civicmatch_positions.py
python3 pipeline/score_quality.py
python3 pipeline/precompute_marquee_insights.py
python3 pipeline/build_insights_house.py
python3 pipeline/build_insights_tx20_38.py
python3 pipeline/validate_data.py
python3 pipeline/validate_insights_house.py
python3 pipeline/validate_insights_tx20_38.py
python3 pipeline/validate_marquee_insights.py
python3 pipeline/load_postgres.py --dry-run    # sanity-check counts first
python3 pipeline/load_postgres.py              # reload Postgres
```

---

## 6. Efficiency notes

- **JSONB blobs beat normalized bullet rows at this scale.** 46 races / 96 candidates / ~290
  vote records total — the entire gold dataset is a few hundred KB. A `finance` object, a
  `key_votes[]` array, an `insights` payload are each read and written whole (one race, one
  candidate, one insight doc at a time); normalizing `key_votes` into its own table would add
  join cost with no query this app actually runs benefiting from it.
- **No GIN indexes on the JSONB columns.** Nothing queries *inside* `finance`/`record`/
  `positions`/`payload` with a `WHERE jsonb_col @> ...` predicate — every read is "give me the
  whole row for this `race_id`/`candidate_id`," so a GIN index would cost write time and disk
  for zero read benefit today.
- **Indexes that do exist** are all plain B-tree, on the columns actually filtered/joined on:
  `idx_races_district`, `idx_races_level`, `idx_cand_district`, `idx_cand_name` (see
  `schema.md` §2.1 for the DDL) — these back `get_ballot`'s district lookup and
  `search_candidates`'s name search, the only two non-PK query patterns in `app/datastore.py`.
- **TOAST is irrelevant at this size.** Postgres only TOASTs values over ~2KB; the largest
  `insights.payload` (a full race with 8 archetypes) is well under that, so out-of-line
  storage/compression overhead never enters the picture.
- **Revisit when**: cross-race analytics (e.g. "which candidates voted Yea on bill X across
  all districts") or a multi-state expansion pushes row counts into the tens of thousands —
  that's when a GIN index on `record.key_votes` or a normalized `votes` table would start
  paying for itself.

---

## 7. Invariants

- **No source, no claim.** Every quantitative fact and every insight bullet carries a
  `source` URL traceable to an official API response.
- **Omit, don't invent.** A missing fact is an absent key (`positions: []`,
  `finance` omitted entirely), never a zero, a guess, or a placeholder string.
- **Projections are labeled with their assumptions.** Consequence-horizon `long_term` bullets
  are explicitly conditional ("If this position becomes sustained policy...") and each names
  the assumption plus the recorded evidence it's conditioned on — never presented as fact.
- **User data is never stored.** `POST /api/insights` and `GET /api/ballot` are stateless; the
  voter's address and profile live only in the request, never written to disk or Postgres.
- **JSON fallback = identical behavior.** With `DATABASE_URL` unset, `app/datastore.py` reads
  `data/tx/races.json` + `candidates.json` + `data/tx/insights/*.json` directly and serves the
  same shapes, same counts, same endpoints as a fully loaded Postgres — no feature is
  Postgres-only.

---

## 8. Cache robustness

All three caches — geocode (`app/datastore.py`, 4-layer: memory LRU → runtime Postgres/JSON →
committed seed `data/tx/geocode_seed.json` → live Census geocoder), insights (keyed
`(race_id, archetype)`, `inputs_hash` change-detection, write-through — see §4 above), and demo
(`data/demo_cache/**`, frozen responses replayed vs. live) — are proven end-to-end by
`tests/test_cache_robustness.py`, self-proving throughout: every invariant below is exercised by
injecting the failure, watching the relevant test go RED, then confirming it's GREEN again on the
real, uncorrupted code/data. `pipeline/validate_cache.py` is the one-command, no-server,
no-network version of the same checks (PASS/FAIL per check, wired into `DEMO_PLAYBOOK.md`'s
pre-stage checklist).

- **Geocode layering.** A seeded address resolves even with an empty runtime cache and the live
  geocoder unreachable (proves the seed layer alone is sufficient); that hit write-throughs into
  the runtime cache and warms the in-process memory LRU, so a repeat lookup never re-reads the
  runtime store. A never-seeded address always reaches the live geocoder (or a mocked
  equivalent in tests) or a clean 503 — never a silently fabricated district. A corrupted runtime
  `geocode_cache.json` is tolerated as a miss (falls through to the seed layer) rather than
  crashing the request; `_JsonFileCache` (backs `races.json`/`candidates.json`/the seed file
  itself) goes further and keeps serving its last-known-good parse across a transient bad read.
  The seed file is also cross-checked against independently-recorded ground truth so a
  seed/live disagreement (e.g. a bad hand-edit, a shifted district boundary) can't silently ship.
- **civic_json preservation.** `geocode_cache_put`'s JSON-fallback path merges into any existing
  cache entry rather than replacing it wholesale, so a re-geocode of an address already enriched
  with Google Civic data (`geocode_cache_put_civic`) can never clobber its `civic_json`. Proven
  RED (a naive replace-not-merge implementation clobbers it) then GREEN (the real code preserves
  it while still applying the new district fields).
- **Insights invalidation.** `compute_inputs_hash` (sha256 over a race's candidate JSON, sorted
  keys, `candidate_id` stripped) is deterministic for unchanged data and changes the moment
  candidate data does — the exact signal `pipeline/load_postgres.py`'s incremental upsert uses to
  decide skip-vs-rewrite per `(race_id, archetype)` row; its independent copy of the hash
  algorithm is checked against `app/datastore.py`'s own for drift on every race.
  `get_insights` reassembles Postgres's one-row-per-block storage back into the
  `{race_id, base, archetypes}` file shape losslessly, and a `put_insight_block` write-through is
  served cached on the very next call without disturbing any other block already cached for that
  race.
- **Demo-cache freshness.** Every `data/demo_cache/**` file is checked against a fresh in-process
  `TestClient` response. A staleness-detection self-proof mutates an isolated tmp copy of a real
  cached file (the committed file itself is never opened for writing) and confirms the freshness
  check fails, naming the drifted file and race, then passes again once restored. Every cached
  ballot's candidates are additionally checked against the current `pipeline/score_quality.py`
  `data_quality` shape (`{score, tier, missing}`).

---

## Cross-links

- [`CLAUDE.md`](CLAUDE.md) — project scope, locked decisions, status log.
- [`schema.md`](schema.md) — authoritative DDL, JSONB shapes, HTTP API contract (referenced,
  not duplicated, throughout this doc).
- [`database.md`](database.md) — Postgres provisioning, load/verify commands, troubleshooting.
- [`railway.md`](railway.md) — deploy configuration.
- [`data/tx/QUALITY.md`](data/tx/QUALITY.md) — generated tier leaderboard + golden demo
  addresses (regenerate with `pipeline/score_quality.py`).
