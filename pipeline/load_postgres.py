#!/usr/bin/env python3
"""
load_postgres.py -- idempotent loader: gold JSON -> PostgreSQL serving layer.

Creates the DDL (races, candidates, race_candidates, insights, geocode_cache)
if not already present, then loads:
  - data/tx/races.json          -> races + race_candidates
  - data/tx/candidates.json     -> candidates
  - data/tx/insights/*.json     -> insights (payload JSONB)

Idempotent: the whole load runs in a single transaction that TRUNCATEs
races/candidates/race_candidates/insights and reloads from the JSON files on
disk, so rerunning always converges to exactly what's on disk right now.
geocode_cache is deliberately never touched here -- it's live runtime cache
data, not gold data this loader owns.

Gold JSON stays the source of truth (per CLAUDE.md); this script is a pure
projection of it into Postgres, safe to rerun any number of times.

Usage:
    python3 pipeline/load_postgres.py             # creates schema + loads
    python3 pipeline/load_postgres.py --dry-run   # parses/counts only, no DB touched

Requires DATABASE_URL (see .env.example). Prints a friendly error and exits 1
if it isn't set. Exits nonzero on any failure (parse error, DB error); the
load transaction is rolled back on failure so a bad run never leaves the
table half-loaded.
"""
from __future__ import annotations

import argparse
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

CREATE TABLE IF NOT EXISTS insights (
  race_id TEXT PRIMARY KEY REFERENCES races(race_id) ON DELETE CASCADE,
  generated_at TEXT,
  payload JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS geocode_cache (
  address_norm TEXT PRIMARY KEY,
  matched_address TEXT,
  cd TEXT, sd TEXT, hd TEXT, county TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _die(msg: str) -> "int":
    print(f"ERROR: {msg}", file=sys.stderr)
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--dry-run", action="store_true", help="Parse and count the gold JSON inputs; make no database connection"
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

    insight_files = sorted(INSIGHTS_DIR.glob("*.json")) if INSIGHTS_DIR.exists() else []
    insights_docs: list[dict[str, Any]] = []
    for p in insight_files:
        try:
            doc = _load_json(p)
        except (json.JSONDecodeError, OSError) as exc:
            return _die(f"could not parse {p}: {exc}")
        race_id = doc.get("race_id") or p.stem
        insights_docs.append({"race_id": race_id, "generated_at": doc.get("generated_at"), "payload": doc})

    race_candidate_pairs = [(r["race_id"], cid) for r in races for cid in r.get("candidate_ids", [])]

    print(
        f"Parsed from disk: races={len(races)} candidates={len(candidates)} "
        f"race_candidates={len(race_candidate_pairs)} insights={len(insights_docs)}"
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

    try:
        with psycopg.connect(database_url, autocommit=False) as conn:
            with conn.cursor() as cur:
                cur.execute(DDL)

                # Idempotent reload: truncate the gold-derived tables and
                # reinsert from disk. geocode_cache is intentionally excluded
                # -- it's live cache data this loader doesn't own.
                cur.execute("TRUNCATE TABLE insights, race_candidates, candidates, races CASCADE")

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

                for doc in insights_docs:
                    cur.execute(
                        """
                        INSERT INTO insights (race_id, generated_at, payload)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (race_id) DO UPDATE SET
                            generated_at = EXCLUDED.generated_at,
                            payload = EXCLUDED.payload
                        """,
                        (doc["race_id"], doc["generated_at"], Jsonb(doc["payload"])),
                    )
            conn.commit()
    except Exception as exc:  # noqa: BLE001 -- any DB failure aborts the whole load
        return _die(f"load failed, transaction rolled back: {exc}")

    print(
        "Loaded into Postgres: "
        f"races={len(races)} candidates={len(candidates)} "
        f"race_candidates={len(race_candidate_pairs)} insights={len(insights_docs)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
