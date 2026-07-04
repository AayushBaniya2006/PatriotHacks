"""tests/test_citation_flow.py -- proves citation/source data survives the
full backend round trip: gold JSON (data/tx/candidates.json + data/tx/races.json
+ data/tx/insights/*.json) -> app/datastore.py reassembly -> FastAPI
TestClient responses (/api/ballot, /api/insights), byte-for-byte -- no
source dropped, reordered, duplicated, or mangled anywhere along that hop.

Distinct from tests/test_citations.py (a pytest wrapper around
pipeline/validate_citations.py -- format/grounding validation on the gold
JSON itself) and from tests/test_contracts.py (URL-shape assertions) and
tests/test_e2e_demo.py (full demo-journey floors): this file's job is
narrower and more literal -- for every source string that exists in the gold
JSON, prove the exact same string, in the exact same position, comes back
out the other end of datastore.py + the FastAPI layer. A dropped source, a
swapped/reordered one, or a silently truncated list would all fail here even
if they'd pass the format/grounding checks in those other files.

JSON-fallback path (the one that always runs in this environment, since
DATABASE_URL is unset here) is exercised unconditionally by every test below
except the last. A companion NOTE test proves the PostgreSQL reassembly path
(pipeline/load_postgres.py's DDL + app/datastore.py's Postgres branch:
_candidate_row_to_dict, and get_insights' per-(race_id, archetype)-row
reassembly back into {base, archetypes}) preserves the same bytes; it is
skipped unless DATABASE_URL is set, so it activates automatically on
Railway/prod without ever requiring a live Postgres locally/in CI.

Run:
    python3 -m pytest tests/test_citation_flow.py -q
    python3 -m pytest tests/ -q
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from app import datastore  # noqa: E402
from app import main as app_main  # noqa: E402
from app.middleware import RATE_LIMIT_HITS  # noqa: E402

DATA_TX = REPO_ROOT / "data" / "tx"
CANDIDATES_JSON = DATA_TX / "candidates.json"
RACES_JSON = DATA_TX / "races.json"
INSIGHTS_DIR = DATA_TX / "insights"

client = TestClient(app_main.app)


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Every test starts and ends with a clean rate-limit slate -- mirrors
    tests/test_hardening.py's identical fixture. test_api_insights_preserves_
    every_bullet_source_byte_for_byte alone issues far more than the 60
    req/60s /api/* budget, so it additionally clears mid-loop (see below)."""
    RATE_LIMIT_HITS.clear()
    yield
    RATE_LIMIT_HITS.clear()


def _load_gold_candidates() -> dict[str, Any]:
    with CANDIDATES_JSON.open("r", encoding="utf-8") as f:
        return json.load(f)


def _load_gold_races() -> list[dict[str, Any]]:
    with RACES_JSON.open("r", encoding="utf-8") as f:
        doc = json.load(f)
    return doc.get("races", [])


def _collect_sources_ordered(obj: Any, path: str = "$") -> list[tuple[str, Any]]:
    """Walk a JSON-like structure and record (path, source_value) for every
    dict that has a "source" key, in traversal order. Dict keys are visited
    in SORTED order (so an incidental key-insertion-order difference between
    two otherwise-identical structures -- e.g. candidate_id iteration order
    across a plain dict vs. a Postgres-derived one -- never causes a false
    mismatch) while LIST order is preserved exactly (so a genuine
    reorder/drop/duplicate of bullets/positions/key_votes within one
    candidate's list is still caught). Used to diff a gold JSON block against
    whatever came back through datastore/API reassembly."""
    out: list[tuple[str, Any]] = []
    if isinstance(obj, dict):
        if "source" in obj:
            out.append((path, obj.get("source")))
        for key in sorted(obj.keys(), key=str):
            out.extend(_collect_sources_ordered(obj[key], f"{path}.{key}"))
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            out.extend(_collect_sources_ordered(item, f"{path}[{idx}]"))
    return out


# ---------------------------------------------------------------------------
# 1. datastore reassembly (JSON-fallback): every candidate's `sources` list,
#    and every position/finance/key_vote `source`, must come back from
#    app/datastore.get_candidate()/get_ballot() byte-for-byte identical to
#    the gold JSON -- this is the "data -> DB" hop.
# ---------------------------------------------------------------------------


def test_datastore_get_candidate_preserves_sources_byte_for_byte() -> None:
    gold = _load_gold_candidates()
    assert gold, "data/tx/candidates.json must not be empty for this test to be meaningful"
    checked = 0
    for cid, gold_candidate in gold.items():
        reassembled = datastore.get_candidate(cid)
        assert reassembled is not None, f"datastore.get_candidate({cid!r}) returned None"
        expected = _collect_sources_ordered(gold_candidate)
        actual = _collect_sources_ordered(reassembled)
        assert actual == expected, (
            f"{cid}: source(s) mutated by datastore reassembly\n  expected: {expected!r}\n  got:      {actual!r}"
        )
        assert reassembled.get("sources") == gold_candidate.get("sources"), (
            f"{cid}: top-level sources list mutated by datastore reassembly"
        )
        checked += 1
    assert checked == len(gold), "not every gold candidate was actually checked"


def test_datastore_get_ballot_embeds_sources_byte_for_byte() -> None:
    """get_ballot() is the exact function app/main.py's /api/ballot endpoint
    calls to assemble races+candidates -- proven again at the HTTP layer in
    test_api_ballot_embeds_sources_byte_for_byte below."""
    gold_candidates = _load_gold_candidates()
    races = _load_gold_races()
    assert races, "data/tx/races.json must not be empty for this test to be meaningful"

    checked_candidates = 0
    for race in races:
        embedded = datastore.get_ballot(cd=race.get("district")) if race.get("district") else datastore.get_ballot()
        by_id = {r["race_id"]: r for r in embedded}
        got_race = by_id.get(race["race_id"])
        assert got_race is not None, f"{race['race_id']}: missing from get_ballot() result"
        for candidate in got_race.get("candidates", []):
            cid = candidate.get("candidate_id")
            gold_candidate = gold_candidates.get(cid)
            assert gold_candidate is not None, f"{race['race_id']}: embedded candidate {cid!r} not in gold JSON"
            assert candidate.get("sources") == gold_candidate.get("sources"), (
                f"{race['race_id']}/{cid}: sources mutated between gold JSON and get_ballot() embedding"
            )
            checked_candidates += 1
    assert checked_candidates > 0


# ---------------------------------------------------------------------------
# 2. /api/ballot (full HTTP round trip via TestClient): every embedded
#    candidate's sources (and position/finance/key_vote sources) must be
#    byte-for-byte identical to gold JSON -- "data -> DB -> API" hop,
#    including FastAPI's JSON (de)serialization.
# ---------------------------------------------------------------------------


def test_api_ballot_embeds_sources_byte_for_byte(monkeypatch, tmp_path) -> None:
    # Isolate the geocode cache to a tmp file and force JSON-fallback mode --
    # mirrors tests/test_e2e_demo.py's _isolate_datastore_backend fixture --
    # so this test never touches the real gitignored data/geocode_cache.json
    # nor requires a live Census geocoder call for an address match.
    monkeypatch.setattr(datastore, "GEOCODE_CACHE_JSON_PATH", tmp_path / "geocode_cache.json")
    monkeypatch.setattr(datastore, "_pool", None)
    monkeypatch.setattr(datastore, "_pg_init_done", True)

    races = _load_gold_races()
    district_race = next((r for r in races if r.get("district")), None)
    assert district_race is not None, "expected at least one districted race in data/tx/races.json"
    test_cd = district_race["district"]

    fake_address = "1 Test St, Test City, TX 78700"
    datastore.geocode_cache_put(
        fake_address, cd=test_cd, sd=None, hd=None, county="Test County", matched_address=fake_address
    )

    response = client.get("/api/ballot", params={"address": fake_address})
    assert response.status_code == 200, response.text
    payload = response.json()

    gold_candidates = _load_gold_candidates()
    checked_candidates = 0
    for race in payload["races"]:
        for candidate in race.get("candidates", []):
            cid = candidate.get("candidate_id")
            gold_candidate = gold_candidates.get(cid)
            if gold_candidate is None:
                continue  # candidate stub with data_missing=True, not a source-bearing record
            expected = _collect_sources_ordered(gold_candidate)
            actual = _collect_sources_ordered(candidate)
            assert actual == expected, (
                f"/api/ballot race={race.get('race_id')} candidate={cid}: source(s) mutated end-to-end\n"
                f"  expected: {expected!r}\n  got:      {actual!r}"
            )
            checked_candidates += 1
    assert checked_candidates > 0, "no candidates with sources were actually checked -- test is not meaningful"


# ---------------------------------------------------------------------------
# 3. /api/insights (full HTTP round trip via TestClient): every bullet
#    source, for EVERY archetype block actually present in the gold
#    insights JSON (not just "base") must come back byte-for-byte identical.
# ---------------------------------------------------------------------------

# Deterministic profile -> archetype fixtures, one field set per precedence
# tier in app/main.py::_profile_archetype, so each maps to exactly the
# archetype named (verified via archetype_used in the response body too).
ARCHETYPE_PROFILES: dict[str, dict[str, Any]] = {
    "base": {},
    "veteran": {"veteran": True},
    "small_business_owner": {"small_business_owner": True},
    "student": {"student": True},
    "healthcare_aca_or_uninsured": {"health_coverage": "aca"},
    "medicare_retiree": {"health_coverage": "medicare"},
    "homeowner_parent": {"kids_public_school": True},
    "renter_young_worker": {"housing": "renter", "age_bracket": "25-34"},
    "rural_agriculture": {"occupation": "farmer"},
}


def test_api_insights_preserves_every_bullet_source_byte_for_byte() -> None:
    insight_files = sorted(INSIGHTS_DIR.glob("*.json"))
    assert insight_files, "data/tx/insights must contain at least one file for this test to be meaningful"

    checked_blocks = 0
    skipped_unknown_archetypes: list[str] = []
    for path in insight_files:
        race_id = path.stem
        gold = json.loads(path.read_text(encoding="utf-8"))
        blocks: dict[str, Any] = {"base": gold.get("base") or {}}
        blocks.update(gold.get("archetypes") or {})

        for archetype, gold_block in blocks.items():
            profile = ARCHETYPE_PROFILES.get(archetype)
            if profile is None:
                skipped_unknown_archetypes.append(f"{race_id}/{archetype}")
                continue

            RATE_LIMIT_HITS.clear()  # this loop issues far more than the 60/60s /api/* budget
            response = client.post("/api/insights", json={"profile": profile, "race_id": race_id})
            assert response.status_code == 200, f"{race_id}/{archetype}: {response.status_code} {response.text}"
            payload = response.json()
            assert payload.get("archetype_used") == archetype, (
                f"{race_id}: profile {profile!r} resolved to archetype_used="
                f"{payload.get('archetype_used')!r}, expected {archetype!r} (fixture/precedence drift)"
            )

            expected = _collect_sources_ordered(gold_block.get("candidates") or {})
            actual = _collect_sources_ordered(payload.get("candidates") or {})
            assert actual == expected, (
                f"/api/insights race={race_id} archetype={archetype}: bullet source(s) mutated end-to-end\n"
                f"  expected: {expected!r}\n  got:      {actual!r}"
            )
            checked_blocks += 1

    assert checked_blocks > 0
    assert not skipped_unknown_archetypes, (
        "insight file(s) contain archetype key(s) with no fixture profile in ARCHETYPE_PROFILES -- "
        f"add one so these sources are actually exercised: {skipped_unknown_archetypes}"
    )


# ---------------------------------------------------------------------------
# 4. NOTE: PostgreSQL reassembly path. Skipped unless DATABASE_URL is set
#    (never true in this dev/CI environment), so this activates automatically
#    against a real Postgres on Railway/prod without requiring one here.
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not set -- Postgres path not live here")
def test_postgres_reassembly_preserves_sources_identically() -> None:
    """Same invariant as test_datastore_get_candidate_preserves_sources_byte_for_byte
    and test_api_insights_preserves_every_bullet_source_byte_for_byte, but
    against a live Postgres connection instead of the JSON fallback --
    proves pipeline/load_postgres.py's row reassembly
    (_candidate_row_to_dict / get_insights' base+archetypes reassembly from
    one-row-per-archetype) round-trips `sources`/`positions[].source`/bullet
    `source` fields with zero mutation, exactly like the JSON path.

    NOTE for whoever runs this on Railway/prod: run
    `python3 pipeline/load_postgres.py` against DATABASE_URL first so the
    tables are populated from the same gold JSON this test compares against.
    """
    assert datastore._get_pool() is not None, (
        "DATABASE_URL is set but app/datastore.py could not open a Postgres connection "
        "-- fix connectivity before trusting this NOTE test's result"
    )

    gold_candidates = _load_gold_candidates()
    checked = 0
    for cid, gold_candidate in gold_candidates.items():
        reassembled = datastore.get_candidate(cid)
        assert reassembled is not None, (
            f"postgres: get_candidate({cid!r}) returned None -- run pipeline/load_postgres.py"
        )
        assert reassembled.get("sources") == gold_candidate.get("sources"), (
            f"postgres: {cid}.sources mutated by Postgres row reassembly"
        )
        expected = _collect_sources_ordered(gold_candidate)
        actual = _collect_sources_ordered(reassembled)
        assert actual == expected, f"postgres: {cid}: source(s) mutated by Postgres row reassembly"
        checked += 1
    assert checked == len(gold_candidates)

    insight_files = sorted(INSIGHTS_DIR.glob("*.json"))
    for path in insight_files:
        race_id = path.stem
        gold = json.loads(path.read_text(encoding="utf-8"))
        pg_reassembled = datastore.get_insights(race_id)
        assert pg_reassembled is not None, f"postgres: get_insights({race_id!r}) returned None"
        expected = _collect_sources_ordered(gold.get("base") or {})
        actual = _collect_sources_ordered(pg_reassembled.get("base") or {})
        assert actual == expected, f"postgres: {race_id}: base block source(s) mutated by Postgres reassembly"
        for archetype, gold_block in (gold.get("archetypes") or {}).items():
            actual_block = (pg_reassembled.get("archetypes") or {}).get(archetype) or {}
            assert _collect_sources_ordered(actual_block) == _collect_sources_ordered(gold_block), (
                f"postgres: {race_id}/{archetype}: source(s) mutated by Postgres reassembly"
            )
