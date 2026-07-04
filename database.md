# PostgreSQL — creation & integration guide

This is a **how-to**, not a schema spec: the DDL contract lives in
[`schema.md`](schema.md) §2 (locked, byte-for-byte matched by
`pipeline/load_postgres.py`). This doc covers provisioning, loading, verifying,
and troubleshooting. Postgres is **optional** everywhere in this repo — see §4.

## 1. TL;DR — three ways to get a Postgres

Ranked by what a hackathon teammate should actually do:

1. **Railway Postgres plugin (recommended for deploy/demo).** Fully covered in
   [`railway.md`](railway.md) § "Step 1 — Project + Postgres" and § "Step 2.4
   Load the data into Postgres" — follow those steps as written, then come back
   here only for the load/verify/troubleshoot commands (§3, §6).
2. **Docker (recommended for local dev).**
   ```bash
   docker compose up -d
   ```
   This starts `postgres:16-alpine` (see `docker-compose.yml`) on host port
   `5433` (mapped to the container's `5432`) with db `patriothacks`, user
   `postgres`, password `postgres`. Resulting URL:
   ```
   postgresql://postgres:postgres@localhost:5433/patriothacks
   ```
3. **Native WSL/Ubuntu Postgres** (no Docker available).
   ```bash
   sudo apt update && sudo apt install -y postgresql postgresql-contrib
   sudo service postgresql start
   sudo -u postgres createuser -s "$USER"        # or: createuser patriothacks
   sudo -u postgres createdb patriothacks -O "$USER"
   sudo -u postgres psql -c "ALTER USER \"$USER\" PASSWORD 'postgres';"
   ```
   Native Postgres listens on the default port `5432`, not `5433` — don't
   copy the Docker URL verbatim, see §2.

## 2. `DATABASE_URL` formats

Set in `.env` (see `.env.example`, currently commented out there — Postgres is
opt-in). Format: `postgresql://<user>:<password>@<host>:<port>/<db>`.

| Path | `DATABASE_URL` |
|---|---|
| Docker (docker-compose.yml) | `postgresql://postgres:postgres@localhost:5433/patriothacks` |
| Native WSL/Ubuntu | `postgresql://<you>:postgres@localhost:5432/patriothacks` |
| Railway | `${{Postgres.DATABASE_URL}}` reference variable (auto-wired in the dashboard), or the public URL from the Postgres service's **Connect** tab when running the loader from your laptop |

**Railway `sslmode` note**: Railway's own internal reference variable already
works without extra flags when the app runs *inside* Railway. If you copy the
**public** connection string to run `pipeline/load_postgres.py` from a local
machine and hit an SSL-related connection error, append `?sslmode=require`:
```
postgresql://postgres:PASSWORD@HOST.proxy.rlwy.net:PORT/railway?sslmode=require
```

## 3. Load + verify

Always dry-run first — it parses and counts the gold JSON with **zero**
database connection, so it works even before Postgres exists:
```bash
python3 pipeline/load_postgres.py --dry-run
```
Expected output:
```
Parsed from disk: races=46 candidates=96 race_candidates=<N> insights=46
--dry-run: no database connection made, no writes performed.
```

Then load for real (creates the DDL if missing, `TRUNCATE`s and reloads the
gold-derived tables — see §5):
```bash
DATABASE_URL=postgresql://postgres:postgres@localhost:5433/patriothacks \
  python3 pipeline/load_postgres.py
```
Expected output:
```
Loaded into Postgres: races=46 candidates=96 race_candidates=<N> insights=46
```

**Verify via `psql`:**
```bash
psql "postgresql://postgres:postgres@localhost:5433/patriothacks" -c \
  "SELECT (SELECT COUNT(*) FROM races) AS races, \
          (SELECT COUNT(*) FROM candidates) AS candidates, \
          (SELECT COUNT(*) FROM insights) AS insights;"
# expect: races=46, candidates=96, insights=126 (one row per race+archetype block, not per race)
psql "postgresql://postgres:postgres@localhost:5433/patriothacks" -c "\d races"
# confirm columns/indexes match schema.md §2.1
```

**Verify via the app (`/healthz`):** (this machine's demo box runs the backend on port
8010 instead of 8000 — see `DEMO_PLAYBOOK.md`)
```bash
DATABASE_URL=postgresql://postgres:postgres@localhost:5433/patriothacks \
  uvicorn app.main:app --reload &
curl -s localhost:8000/healthz | python3 -m json.tool
```
Expected:
```json
{
  "status": "ok",
  "data_loaded": true,
  "races": 46,
  "candidates": 96,
  "insights_cached": 46
}
```

## 4. How the app uses it

`app/datastore.py` is the **only** data-access layer — endpoints never touch
storage directly. Backend selection is lazy and cached for the process
lifetime (`_get_pool()`):

- If `DATABASE_URL` is **unset**, it returns `None` immediately — no warning,
  no connection attempt. Expected local/demo case.
- If it's set but `psycopg` isn't installed, or the first connection attempt
  fails (bad host, wrong port, auth failure, Postgres down), it logs a
  warning **once** and falls back — it never retries a dead database on every
  request.
- Once the pool is live, every query (`get_ballot`, `get_race`,
  `get_candidate`, `list_races`, `search_candidates`, `get_insights`, `stats`)
  tries Postgres first and falls back to the JSON files *for that one call*
  if the query itself throws.

**geocode_cache**: Postgres `geocode_cache` table when the pool is live,
otherwise `data/geocode_cache.json` (gitignored, read-write, written
atomically via temp-file + `os.replace` so a crash mid-write can't corrupt
it). This cache is deliberately excluded from `load_postgres.py`'s reload —
it's live runtime cache data, not gold data the pipeline owns.

**Demo-safe guarantee**: with `DATABASE_URL` unset, the app reads
`data/tx/races.json`, `data/tx/candidates.json`, and
`data/tx/insights/*.json` directly and behaves **identically** to a fully
loaded Postgres — same endpoints, same response shapes, same counts. Nothing
about the demo requires a database to be provisioned.

## 5. Reload/rebuild flow after pipeline reruns

`pipeline/load_postgres.py` is idempotent: `race_candidates, candidates, races`
are unconditionally `TRUNCATE`d and reinserted every run (cheap, deterministic
re-derivations from gold JSON). `insights` defaults instead to an incremental,
hash-gated UPSERT — a row is only rewritten when its stored `inputs_hash` no
longer matches that race's current candidate data, so a live write-through-
cached block survives a routine rerun; pass `--reset` to `TRUNCATE` and reload
`insights` unconditionally too. Rerunning after `pipeline/build_dataset.py`
(or any manual edit to the gold JSON) always converges Postgres to match disk
— no manual cleanup needed:
```bash
python3 pipeline/build_dataset.py          # regenerate gold JSON (if applicable)
python3 pipeline/load_postgres.py --dry-run  # sanity-check counts first
python3 pipeline/load_postgres.py            # reload Postgres
curl -s localhost:8000/healthz | python3 -m json.tool   # confirm new counts
```
`geocode_cache` is untouched by this reload (§4). On any failure mid-load
(parse error, DB error), the transaction rolls back — a bad run never leaves
tables half-loaded.

## 6. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `connection refused` | Wrong port, or `docker compose` isn't up | `docker compose up -d`, confirm port `5433` (not `5432`) in `DATABASE_URL` |
| `password authentication failed` | Wrong user/password, or native install used a different password | Re-check `docker-compose.yml` (`postgres`/`postgres`) or reset native pw: `sudo -u postgres psql -c "ALTER USER youruser PASSWORD 'postgres';"` |
| SSL/TLS negotiation error against a Railway public URL | Railway's public proxy expects SSL | append `?sslmode=require` to `DATABASE_URL` (§2) |
| `ERROR: DATABASE_URL is not set` from `load_postgres.py` | Env var not exported / `.env` not sourced | `export DATABASE_URL=...` or copy `.env.example` → `.env` and uncomment the line, then re-run |
| App runs fine with `data_loaded: false` | No `DATABASE_URL`, or Postgres attached but never loaded | Expected if you haven't run §3 — not an error; JSON fallback is serving identical data. Run `pipeline/load_postgres.py` to fix `data_loaded` |
| No Docker available in WSL | Docker Desktop WSL integration not enabled, or Docker not installed | Use the native WSL/Ubuntu path (§1.3) instead — don't fight Docker-in-WSL for a hackathon demo |

## 7. Post-hackathon scale notes

- Indexes are already in the DDL (`idx_races_district`, `idx_races_level`,
  `idx_cand_district`, `idx_cand_name` — see `schema.md` §2.1) — no extra
  indexing work needed for the current query patterns.
- The backend is stateless (`app/datastore.py` holds only a connection pool
  and in-process caches), so it scales horizontally behind Railway/any LB;
  Postgres stays the single source of truth. Add read replicas in front of
  read-heavy `GET /api/ballot` traffic if a single instance becomes a
  bottleneck.
- One database, many states: the schema has no state column baked into table
  names — add a state by rerunning the pipeline with a new state config and
  loading into the same schema (`race_id`/`candidate_id` slugs already encode
  state via office naming, e.g. `tx-gov-2026`). No per-state database split
  needed unless row counts get enormous.
