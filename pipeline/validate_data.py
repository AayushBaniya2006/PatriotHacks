#!/usr/bin/env python3
"""
validate_data.py — gold-dataset validator.

Checks (per CLAUDE.md contract):
  1. every race has >= 1 candidate
  2. every race.candidate_ids entry exists in candidates.json
  3. every finance / key_vote / position object carries a source
  4. every district is null or matches ^TX-\\d{2}$
  5. (only when DATABASE_URL is set) Postgres row counts equal the JSON counts
  6. (only when DATABASE_URL is set) a TX-35 race -> candidates join works
     end-to-end via Postgres

Checks 5 & 6 are skipped -- not failed -- when DATABASE_URL is unset, since
the JSON fallback is a fully supported standalone mode (per CLAUDE.md). Run
pipeline/load_postgres.py first if you want those checks exercised.

Prints PASS/FAIL and counts. Exits non-zero on any failure.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "tx"

RACES_PATH = OUT_DIR / "races.json"
CANDIDATES_PATH = OUT_DIR / "candidates.json"

DISTRICT_RE = re.compile(r"^TX-\d{2}$")


def fail(errors: list[str], msg: str):
    errors.append(msg)


def main() -> int:
    errors: list[str] = []

    with open(RACES_PATH, "r", encoding="utf-8") as f:
        races_doc = json.load(f)
    with open(CANDIDATES_PATH, "r", encoding="utf-8") as f:
        candidates = json.load(f)

    races = races_doc.get("races", [])

    # 1 & 2: race candidate coverage + referential integrity
    for r in races:
        cids = r.get("candidate_ids", [])
        if len(cids) < 1:
            fail(errors, f"race {r['race_id']} has 0 candidates")
        for cid in cids:
            if cid not in candidates:
                fail(errors, f"race {r['race_id']} references unknown candidate_id '{cid}'")

    # 4: district format
    for r in races:
        d = r.get("district")
        if d is not None and not DISTRICT_RE.match(d):
            fail(errors, f"race {r['race_id']} has malformed district '{d}'")
    for cid, c in candidates.items():
        d = c.get("district")
        if d is not None and not DISTRICT_RE.match(d):
            fail(errors, f"candidate {cid} has malformed district '{d}'")

    # 3: every finance / key_vote / position object has a source
    finance_count = 0
    key_vote_count = 0
    position_count = 0
    candidates_with_votes = 0
    candidates_with_finance = 0

    for cid, c in candidates.items():
        finance = c.get("finance")
        if finance:
            finance_count += 1
            candidates_with_finance += 1
            if not finance.get("source"):
                fail(errors, f"candidate {cid} finance object missing source")

        record = c.get("record") or {}
        key_votes = record.get("key_votes") or []
        if key_votes:
            candidates_with_votes += 1
        for kv in key_votes:
            key_vote_count += 1
            if not kv.get("source"):
                fail(errors, f"candidate {cid} key_vote missing source: {kv.get('bill')}")

        positions = c.get("positions") or []
        for p in positions:
            position_count += 1
            if not p.get("source"):
                fail(errors, f"candidate {cid} position missing source: {p.get('issue')}")

    # 5 & 6: Postgres parity + TX-35 join -- only when DATABASE_URL is set.
    # The JSON fallback is a fully supported mode (CLAUDE.md), so an unset
    # DATABASE_URL is not a validation failure -- these checks are simply
    # skipped and pg_* counts stay None.
    pg_race_count = pg_cand_count = pg_rc_count = None
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("DATABASE_URL not set; skipping Postgres parity checks (JSON-only validation).")
    else:
        try:
            import psycopg
        except ImportError as exc:
            fail(errors, f"DATABASE_URL is set but psycopg is not installed: {exc}")
        else:
            try:
                with psycopg.connect(database_url, autocommit=True) as conn:
                    with conn.cursor() as cur:
                        pg_race_count = cur.execute("SELECT COUNT(*) FROM races").fetchone()[0]
                        pg_cand_count = cur.execute("SELECT COUNT(*) FROM candidates").fetchone()[0]
                        pg_rc_count = cur.execute("SELECT COUNT(*) FROM race_candidates").fetchone()[0]

                        if pg_race_count != len(races):
                            fail(errors, f"pg races count ({pg_race_count}) != json races count ({len(races)})")
                        if pg_cand_count != len(candidates):
                            fail(
                                errors,
                                f"pg candidates count ({pg_cand_count}) != json candidates count ({len(candidates)})",
                            )
                        json_rc_count = sum(len(r.get("candidate_ids", [])) for r in races)
                        if pg_rc_count != json_rc_count:
                            fail(
                                errors,
                                f"pg race_candidates count ({pg_rc_count}) != json race_candidates count ({json_rc_count})",
                            )

                        cur.execute("SELECT race_id FROM races WHERE district = 'TX-35'")
                        tx35 = cur.fetchall()
                        if not tx35:
                            fail(errors, "no race found for district TX-35 in Postgres")
                        else:
                            race_id = tx35[0][0]
                            cur.execute(
                                """SELECT c.candidate_id, c.name FROM race_candidates rc
                                   JOIN candidates c ON c.candidate_id = rc.candidate_id
                                   WHERE rc.race_id = %s""",
                                (race_id,),
                            )
                            joined = cur.fetchall()
                            if not joined:
                                fail(errors, f"TX-35 race->candidates join returned 0 rows for race_id {race_id}")
            except Exception as exc:  # noqa: BLE001 -- any connection/query failure is a validation failure
                fail(errors, f"could not validate Postgres ({exc})")

    counts = {
        "races": len(races),
        "candidates": len(candidates),
        "candidates_with_votes": candidates_with_votes,
        "candidates_with_finance": candidates_with_finance,
        "key_vote_records": key_vote_count,
        "position_records": position_count,
        "pg_races": pg_race_count,
        "pg_candidates": pg_cand_count,
        "pg_race_candidates": pg_rc_count,
    }

    verdict = "PASS" if not errors else "FAIL"
    print(f"VERDICT: {verdict}")
    print(f"COUNTS: {json.dumps(counts)}")
    if errors:
        print(f"ERRORS ({len(errors)}):")
        for e in errors:
            print(f"  - {e}")
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
