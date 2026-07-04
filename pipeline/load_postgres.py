#!/usr/bin/env python3
"""
load_postgres.py -- idempotent loader: gold JSON -> PostgreSQL serving layer.

Creates the DDL (races, candidates, race_candidates, insights, geocode_cache)
if not already present, then loads:
  - data/tx/races.json          -> races + race_candidates
  - data/tx/candidates.json     -> candidates
  - data/tx/insights/*.json     -> insights (one row per race per archetype
                                    block -- see below)

races/candidates/race_candidates: unconditionally TRUNCATEd and reinserted
every run -- cheap, deterministic re-derivations from gold JSON, so a full
reload is always correct and always cheap. This part is unchanged.

insights: evolved from one row per race to one row per (race_id, archetype)
block ('base' plus each precomputed voter-archetype key), so a single race's
base block and each of its archetype blocks are independently addressable --
this is what lets a live LLM generation write-through cache exactly one
block (app/datastore.py::put_insight_block) without disturbing the rest of
that race's precomputed content.

Default mode is an INCREMENTAL UPSERT, hash-gated per row: each race's
current candidate data is hashed (sha256 over the canonical, sort_keys JSON
of that race's candidates from data/tx/candidates.json -- same hash reused
for every block belonging to that race). A row is only written when it
doesn't exist yet or its stored inputs_hash differs from the freshly
computed one; otherwise it is left alone and counted as skipped. This is
what protects a live write-through-cached row (which may have cost a real
LLM call) from being clobbered by a routine pipeline rerun when nothing
about that race's candidates actually changed.

Pass --reset to instead TRUNCATE the insights table first and reload every
block from disk unconditionally (a full reset of insights specifically --
races/candidates/race_candidates are truncated and reloaded every run
regardless of this flag; there is no separate flag for those).

Gold JSON stays the source of truth (per CLAUDE.md); this script is a pure
projection of it into Postgres, safe to rerun any number of times.

Usage:
    python3 pipeline/load_postgres.py             # creates schema + loads (incremental upsert)
    python3 pipeline/load_postgres.py --reset      # also wipes + reloads the insights table
    python3 pipeline/load_postgres.py --dry-run    # parses/counts only, no DB touched

Requires DATABASE_URL (see .env.example). Prints a friendly error and exits 1
if it isn't set. Exits nonzero on any failure (parse error, DB error); the
load transaction is rolled back on failure so a bad run never leaves the
table half-loaded.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / "tx"
RACES_PATH = DATA_DIR / "races.json"
CANDIDATES_PATH = DATA_DIR / "candidates.json"
INSIGHTS_DIR = DATA_DIR / "insights"

# Exact DDL contract -- also documented in CLAUDE.md / schema.md. Keep byte-
# for-byte in sync with what app/datastore.py assumes exists.
DDL = """
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
-- voter-archetype key) instead of one row per race, so a single block can
-- be hash-gated and write-through cached independently of the rest of its
-- race. NOTE: evolved from the prior one-row-per-race shape (race_id
-- PRIMARY KEY, generated_at TEXT, no inputs_hash) -- CREATE TABLE IF NOT
-- EXISTS does not migrate an already-existing old-shape table; this
-- assumes a fresh table (no live Postgres has run the old shape as of this
-- writing -- see CLAUDE.md).
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
"""


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _die(msg: str) -> "int":
    print(f"ERROR: {msg}", file=sys.stderr)
    return 1


def _race_inputs_hash(race: dict[str, Any], candidates: dict[str, Any]) -> str:
    """sha256 hex digest over this race's candidates' canonical JSON
    (json.dumps with sort_keys=True) -- the same hash is reused for every
    insight block (base + every archetype) belonging to this race, so a row
    is only rewritten when the underlying candidate data actually changed.

    The "candidate_id" field is stripped from each candidate dict before
    hashing: it's a storage-shape artifact (Postgres rows carry it
    explicitly via app/datastore.py's _candidate_row_to_dict; the raw
    candidates.json value does not) and must not perturb the hash. Keep
    this normalization in sync with app/datastore.py::compute_inputs_hash --
    both must agree so a live write-through-cached row is correctly
    recognized as unchanged (or changed) by a later bulk reload.
    """
    payload: dict[str, Any] = {}
    for cid in race.get("candidate_ids", []):
        candidate = candidates.get(cid)
        if candidate is None:
            continue
        payload[cid] = {k: v for k, v in candidate.items() if k != "candidate_id"}
    canonical = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--dry-run", action="store_true", help="Parse and count the gold JSON inputs; make no database connection"
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help=(
            "TRUNCATE the insights table before reloading, wiping every row "
            "(including any live write-through cached ones) and reinserting "
            "everything from disk unconditionally. Without this flag "
            "(default), insights are upserted incrementally: a row is only "
            "written when it doesn't exist yet or its stored inputs_hash "
            "differs from the race's current candidate data. "
            "races/candidates/race_candidates are always fully reloaded "
            "either way."
        ),
    )
    args = parser.parse_args()

    if not RACES_PATH.exists():
        return _die(f"{RACES_PATH} not found -- run pipeline/build_dataset.py first")
    if not CANDIDATES_PATH.exists():
        return _die(f"{CANDIDATES_PATH} not found -- run pipeline/build_dataset.py first")

    try:
        races_doc = _load_json(RACES_PATH)
        candidates: dict[str, Any] = _load_json(CANDIDATES_PATH)
    except (json.JSONDecodeError, OSError) as exc:
        return _die(f"could not parse gold JSON: {exc}")

    races = races_doc.get("races", [])

    # Explode each insights/{race_id}.json into one entry per (race_id,
    # archetype) block: 'base' plus each key under "archetypes". payload is
    # that block as-is (including a "horizons" key, when present) -- this
    # loader doesn't interpret block contents, just stores them.
    insight_files = sorted(INSIGHTS_DIR.glob("*.json")) if INSIGHTS_DIR.exists() else []
    insight_blocks: list[dict[str, Any]] = []
    for p in insight_files:
        try:
            doc = _load_json(p)
        except (json.JSONDecodeError, OSError) as exc:
            return _die(f"could not parse {p}: {exc}")
        race_id = doc.get("race_id") or p.stem
        base = doc.get("base")
        if isinstance(base, dict):
            insight_blocks.append({"race_id": race_id, "archetype": "base", "payload": base})
        archetypes = doc.get("archetypes")
        if isinstance(archetypes, dict):
            for key, block in archetypes.items():
                if isinstance(block, dict):
                    insight_blocks.append({"race_id": race_id, "archetype": key, "payload": block})

    race_candidate_pairs = [(r["race_id"], cid) for r in races for cid in r.get("candidate_ids", [])]

    print(
        f"Parsed from disk: races={len(races)} candidates={len(candidates)} "
        f"race_candidates={len(race_candidate_pairs)} "
        f"insight_blocks={len(insight_blocks)} (insight_files={len(insight_files)})"
    )

    if args.dry_run:
        print("--dry-run: no database connection made, no writes performed.")
        return 0

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        return _die(
            "DATABASE_URL is not set. Copy .env.example to .env and set DATABASE_URL, e.g.\n"
            "  DATABASE_URL=postgresql://postgres:postgres@localhost:5433/patriothacks"
        )

    try:
        import psycopg
        from psycopg.types.json import Jsonb
    except ImportError as exc:
        return _die(f"psycopg is not installed ({exc}). Run: pip install -r requirements.txt")

    races_by_id = {r["race_id"]: r for r in races}
    race_hash_cache: dict[str, str] = {}

    def _race_hash(race_id: str) -> str:
        if race_id not in race_hash_cache:
            race_hash_cache[race_id] = _race_inputs_hash(races_by_id.get(race_id, {}), candidates)
        return race_hash_cache[race_id]

    loaded = skipped = updated = 0

    try:
        with psycopg.connect(database_url, autocommit=False) as conn:
            with conn.cursor() as cur:
                cur.execute(DDL)

                # races/candidates/race_candidates: cheap, deterministic
                # re-derivations from gold JSON -- always fully reloaded,
                # regardless of --reset (which only concerns insights below).
                cur.execute("TRUNCATE TABLE race_candidates, candidates, races CASCADE")

                for r in races:
                    cur.execute(
                        """
                        INSERT INTO races (race_id, office, level, district, election_date, context)
                        VALUES (%s, %s, %s, %s, COALESCE(%s::date, DATE '2026-11-03'), %s)
                        """,
                        (
                            r["race_id"],
                            r["office"],
                            r["level"],
                            r.get("district"),
                            races_doc.get("election_date"),  # a "YYYY-MM-DD" string; ::date makes the cast explicit
                            Jsonb(r.get("context") or {}),
                        ),
                    )

                for cid, c in candidates.items():
                    cur.execute(
                        """
                        INSERT INTO candidates
                            (candidate_id, name, party, office, district, incumbent,
                             fec_id, finance, record, positions, sources)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            cid,
                            c["name"],
                            c.get("party"),
                            c.get("office"),
                            c.get("district"),
                            c.get("incumbent"),
                            c.get("fec_id"),
                            Jsonb(c["finance"]) if c.get("finance") else None,
                            Jsonb(c["record"]) if c.get("record") else None,
                            Jsonb(c.get("positions") or []),
                            Jsonb(c.get("sources") or []),
                        ),
                    )

                # Inserted in candidate_ids order (per race) so that a plain,
                # ORDER-BY-free SELECT against a freshly-loaded table comes
                # back in the original gold-JSON order -- see
                # app/datastore.py::_embed_candidates, which depends on
                # candidate_ids order being preserved.
                for race_id, cid in race_candidate_pairs:
                    cur.execute(
                        "INSERT INTO race_candidates (race_id, candidate_id) VALUES (%s, %s)",
                        (race_id, cid),
                    )

                # insights: default incremental upsert, hash-gated per
                # (race_id, archetype) row; --reset wipes the table first so
                # every block below is inserted fresh.
                existing_hashes: dict[tuple[str, str], str] = {}
                if args.reset:
                    cur.execute("TRUNCATE TABLE insights")
                else:
                    cur.execute("SELECT race_id, archetype, inputs_hash FROM insights")
                    for row in cur.fetchall():
                        existing_hashes[(row[0], row[1])] = row[2]

                for block in insight_blocks:
                    race_id = block["race_id"]
                    archetype = block["archetype"]
                    payload = block["payload"]
                    key = (race_id, archetype)
                    inputs_hash = _race_hash(race_id)
                    row_exists = key in existing_hashes

                    if row_exists and existing_hashes[key] == inputs_hash:
                        skipped += 1
                        continue

                    cur.execute(
                        """
                        INSERT INTO insights (race_id, archetype, payload, inputs_hash)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (race_id, archetype) DO UPDATE SET
                            payload = EXCLUDED.payload,
                            inputs_hash = EXCLUDED.inputs_hash,
                            generated_at = now()
                        """,
                        (race_id, archetype, Jsonb(payload), inputs_hash),
                    )
                    if row_exists:
                        updated += 1
                    else:
                        loaded += 1
            conn.commit()
    except Exception as exc:  # noqa: BLE001 -- any DB failure aborts the whole load
        return _die(f"load failed, transaction rolled back: {exc}")

    print(
        "Loaded into Postgres: "
        f"races={len(races)} candidates={len(candidates)} "
        f"race_candidates={len(race_candidate_pairs)} "
        f"insight_blocks: loaded={loaded} skipped={skipped} updated={updated} (total={len(insight_blocks)})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
