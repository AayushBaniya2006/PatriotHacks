"""tests/test_cache_robustness.py -- end-to-end robustness proof for all three
caching layers this app depends on:

  1. Geocode cache (app/datastore.py) -- 4-layer lookup: in-process memory LRU
     -> runtime Postgres/JSON -> committed seed (data/tx/geocode_seed.json) ->
     live Census geocoder.
  2. Insights cache (app/datastore.py::get_insights/put_insight_block +
     pipeline/load_postgres.py) -- keyed (race_id, archetype), inputs_hash
     change-detection, write-through.
  3. Demo cache (data/demo_cache/**) -- frozen full responses replayed vs. a
     fresh in-process TestClient call.

Self-proving discipline throughout (mirrors tests/test_e2e_demo.py's
`selfproof`-marked tests): every invariant that can be corrupted is corrupted
on purpose, observed to fail (RED) -- proving the check has teeth, not just a
tautology -- then the real/clean path is confirmed to pass (GREEN). See each
test's docstring for its specific RED/GREEN story.

No live network anywhere in this file: the geocode layer is proven via the
committed data/tx/geocode_seed.json plus app.main._live_geocode monkeypatched
per-test (raise / mocked success / mocked 503) -- exactly the pattern
tests/test_e2e_demo.py's `_guard_live_geocode` and tests/test_google_civic.py's
`_install_fake_civic_client` already establish, just applied per-test here
instead of module-wide autouse, since different tests in this file need
different `_live_geocode` behaviors (raise-if-called vs. mocked success vs.
mocked 503). Isolation fixtures below mirror
tests/test_e2e_demo.py::_isolate_datastore_backend and
tests/test_hardening.py's `_geocode_memory_cache`/`RATE_LIMIT_HITS`
save-clear-restore idiom exactly, so this file never touches the real
(gitignored) data/geocode_cache.json and never leaks memory-cache or
rate-limit state into any other test file's tests in the same session.

Cross-file reuse (not reimplementation) of helpers already proven correct
elsewhere in this suite: `_first_cached_race_id` (tests/test_hardening.py),
`_assert_ballot_cache_matches_fresh` / `_assert_insights_cache_matches_fresh` /
`_load_module` / the precache/golden address constants (tests/test_e2e_demo.py)
-- the same idiom test_e2e_demo.py itself already uses to import
`_first_cached_race_id` from test_hardening.py.

Run:
    python3 -m pytest tests/test_cache_robustness.py -q
    python3 -m pytest tests/ -q
"""

from __future__ import annotations

import copy
import json
import os
import re
import sys
import time
import warnings
from pathlib import Path
from typing import Any, Optional

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import datastore  # noqa: E402
from app import main as app_main  # noqa: E402
from app.middleware import RATE_LIMIT_HITS  # noqa: E402

from test_hardening import _first_cached_race_id  # noqa: E402 -- reuse, don't duplicate
from test_e2e_demo import (  # noqa: E402 -- reuse, don't duplicate
    DEMO_CACHE_DIR,
    GEOCODE_SEED,
    PRECACHE_ADDRESSES,
    PRECACHE_EXPECTED_CD,
    _assert_ballot_cache_matches_fresh,
    _assert_insights_cache_matches_fresh,
    _load_module,
    _precache_demo,
    _slug,
)

with warnings.catch_warnings():
    warnings.simplefilter("ignore", pytest.PytestUnknownMarkWarning)
    selfproof = pytest.mark.selfproof


DATA_TX = REPO_ROOT / "data" / "tx"
RACES_JSON_PATH = DATA_TX / "races.json"
CANDIDATES_JSON_PATH = DATA_TX / "candidates.json"

# A real, plausible-but-never-seeded address -- not a substring of, and not
# normalized to, any key in data/tx/geocode_seed.json. Used to prove the
# "never silently wrong" contract: this address must always reach the (real
# or mocked) live geocoder or a clean error, never a fabricated/cached-wrong
# district.
NEVER_SEEDED_ADDRESS = "4200 Fictional Fixture Ln, Nowhereville, TX 78999"

client = TestClient(app_main.app)


# ---------------------------------------------------------------------------
# Isolation fixtures (autouse) -- isolated tmp geocode cache, clean memory
# cache, clean rate limiter, for every test in this file.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_datastore_backend(monkeypatch, tmp_path):
    """Force JSON-fallback mode and redirect the runtime geocode cache to an
    isolated tmp file -- mirrors tests/test_e2e_demo.py's
    _isolate_datastore_backend / tests/test_google_civic.py's
    _isolate_geocode_cache exactly, so this suite never touches the real
    (gitignored) data/geocode_cache.json nor depends on a real
    DATABASE_URL/Postgres being reachable."""
    monkeypatch.setattr(datastore, "GEOCODE_CACHE_JSON_PATH", tmp_path / "geocode_cache.json")
    monkeypatch.setattr(datastore, "_pool", None)
    monkeypatch.setattr(datastore, "_pg_init_done", True)
    yield


@pytest.fixture(autouse=True)
def _reset_geocode_memory_cache():
    """Save/clear/restore datastore's module-level memory LRU around every
    test -- mirrors the exact save-clear-restore idiom already used inline in
    tests/test_hardening.py's geocode tests, promoted to autouse here since
    nearly every test in this file exercises the geocode memory cache."""
    saved = dict(datastore._geocode_memory_cache)
    datastore._geocode_memory_cache.clear()
    yield
    datastore._geocode_memory_cache.clear()
    datastore._geocode_memory_cache.update(saved)


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    RATE_LIMIT_HITS.clear()
    yield
    RATE_LIMIT_HITS.clear()


def _seed_geocode(address: str) -> None:
    """Pre-populate the (isolated) geocode cache for one address straight
    from the committed data/tx/geocode_seed.json -- mirrors
    tests/test_e2e_demo.py's _seed_geocode_cache fixture, applied per-test
    here rather than to all 8 demo/golden addresses at once."""
    norm = datastore._normalize_address(address)
    entry = GEOCODE_SEED[norm]
    datastore.geocode_cache_put(
        address,
        cd=entry.get("cd"),
        sd=entry.get("sd"),
        hd=entry.get("hd"),
        county=entry.get("county"),
        matched_address=entry.get("matched_address"),
    )


# ===========================================================================
# 1. GEOCODE LAYERING
# ===========================================================================


def test_seeded_address_resolves_via_seed_layer_and_write_throughs_to_runtime(monkeypatch):
    """Runtime cache starts empty (fresh tmp_path) AND the live geocoder is
    monkeypatched to raise if ever called -- the only way this can succeed is
    via the committed seed layer. Also proves the write-through: after the
    call, the runtime cache file exists and holds this address, so a repeat
    lookup never needs the seed file again."""
    address = PRECACHE_ADDRESSES[0]
    norm = datastore._normalize_address(address)
    seed_entry = GEOCODE_SEED[norm]

    assert not datastore.GEOCODE_CACHE_JSON_PATH.exists(), "runtime cache must start empty for this proof"

    async def _must_not_be_called(addr: str) -> dict[str, Any]:
        raise AssertionError(f"_live_geocode must never be called for seeded address {addr!r}")

    monkeypatch.setattr(app_main, "_live_geocode", _must_not_be_called)

    resp = client.get("/api/ballot", params={"address": address})
    assert resp.status_code == 200, resp.text[:300]
    districts = resp.json()["districts"]
    assert districts["cd"] == seed_entry["cd"]
    assert districts["sd"] == seed_entry["sd"]
    assert districts["hd"] == seed_entry["hd"]
    assert districts["county"] == seed_entry["county"]

    # Write-through: the runtime cache file now exists and carries this entry.
    assert datastore.GEOCODE_CACHE_JSON_PATH.exists(), "seed hit must write through to the runtime cache"
    on_disk = json.loads(datastore.GEOCODE_CACHE_JSON_PATH.read_text(encoding="utf-8"))
    assert norm in on_disk
    assert on_disk[norm]["cd"] == seed_entry["cd"]


def test_memory_lru_hit_avoids_runtime_cache_reread(monkeypatch):
    """After a first resolution warms the memory LRU, a second lookup for the
    same address must be served from memory alone -- proven by making the
    runtime-JSON loader itself raise if it is ever called again."""
    address = PRECACHE_ADDRESSES[1]

    first = datastore.geocode_cache_get(address)
    assert first is not None, "first lookup should resolve via the seed layer"

    def _must_not_reread_runtime_cache() -> dict[str, Any]:
        raise AssertionError(
            "a memory-cache hit must short-circuit before the runtime JSON file is read again"
        )

    monkeypatch.setattr(datastore, "_load_geocode_cache_json", _must_not_reread_runtime_cache)

    second = datastore.geocode_cache_get(address)
    assert second == first


def test_never_seeded_address_reaches_mocked_live_geocoder(monkeypatch):
    """A never-seeded address must fall all the way through to the live
    geocoder -- proven with a mocked success response, and that the response
    served is exactly what the mock returned (never a stale/wrong cached
    value from some other address)."""
    assert datastore._normalize_address(NEVER_SEEDED_ADDRESS) not in GEOCODE_SEED

    call_count = {"n": 0}

    async def _mock_live(addr: str) -> dict[str, Any]:
        call_count["n"] += 1
        assert addr == NEVER_SEEDED_ADDRESS
        return {
            "matched_address": "4200 FICTIONAL FIXTURE LN, NOWHEREVILLE, TX, 78999",
            "districts": {"cd": "TX-99", "sd": "SD-77", "hd": "HD-77", "county": "Fixture County"},
        }

    monkeypatch.setattr(app_main, "_live_geocode", _mock_live)

    resp = client.get("/api/ballot", params={"address": NEVER_SEEDED_ADDRESS})
    assert resp.status_code == 200, resp.text[:300]
    assert call_count["n"] == 1
    assert resp.json()["districts"] == {"cd": "TX-99", "sd": "SD-77", "hd": "HD-77", "county": "Fixture County"}


def test_never_seeded_address_503s_cleanly_when_live_geocoder_down(monkeypatch):
    """Same never-seeded address, but the live geocoder is down: must 503
    with a detail message -- never a 500, and never a 200 with fabricated
    data."""

    async def _mock_down(addr: str) -> dict[str, Any]:
        raise HTTPException(status_code=503, detail="District lookup unavailable, try again")

    monkeypatch.setattr(app_main, "_live_geocode", _mock_down)

    resp = client.get("/api/ballot", params={"address": NEVER_SEEDED_ADDRESS})
    assert resp.status_code == 503
    assert isinstance(resp.json().get("detail"), str)


def test_json_file_cache_last_known_good_on_corruption(tmp_path):
    """Unit-level proof of app/datastore.py::_JsonFileCache (backs races.json,
    candidates.json, AND the geocode seed file itself): a transient corrupt
    read must keep serving the last-known-good parsed value rather than
    resetting to `default` or raising, and must pick the fresh value back up
    once the file is valid again."""
    path = tmp_path / "sample.json"
    now = time.time()

    path.write_text(json.dumps({"hello": "world"}), encoding="utf-8")
    os.utime(path, (now, now))
    cache = datastore._JsonFileCache(path, default={})
    assert cache.get() == {"hello": "world"}

    # RED (by construction): confirm this write really is malformed JSON, so
    # the tolerance proven below is doing real work.
    path.write_text("{this is not valid json!!! [[[", encoding="utf-8")
    os.utime(path, (now + 1, now + 1))
    with pytest.raises(json.JSONDecodeError):
        json.loads(path.read_text(encoding="utf-8"))

    # GREEN: last-known-good is retained across the corrupt read, not reset
    # to `default={}` and not raised.
    assert cache.get() == {"hello": "world"}

    # Recovery: once fixed again (with a new mtime), the fresh value is picked up.
    path.write_text(json.dumps({"hello": "again"}), encoding="utf-8")
    os.utime(path, (now + 2, now + 2))
    assert cache.get() == {"hello": "again"}


@selfproof
def test_corrupted_runtime_geocode_cache_json_tolerated_falls_through_to_seed(monkeypatch):
    """Inject corruption into the runtime geocode_cache.json (as if the
    process crashed mid-write on some other platform, or the file was hand-
    edited) and prove app/datastore.py tolerates it: a seeded address still
    resolves (falls through to the seed layer instead of crashing), and a
    never-seeded address against the same corrupted file misses cleanly
    (None), never raising."""
    address = PRECACHE_ADDRESSES[2]
    norm = datastore._normalize_address(address)
    seed_entry = GEOCODE_SEED[norm]

    datastore.GEOCODE_CACHE_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    datastore.GEOCODE_CACHE_JSON_PATH.write_text("{not valid json !!! [[[", encoding="utf-8")

    # RED (by construction): confirm the file really is malformed.
    with pytest.raises(json.JSONDecodeError):
        json.loads(datastore.GEOCODE_CACHE_JSON_PATH.read_text(encoding="utf-8"))

    async def _must_not_be_called(addr: str) -> dict[str, Any]:
        raise AssertionError("must not need the live geocoder -- the seed layer must serve this")

    monkeypatch.setattr(app_main, "_live_geocode", _must_not_be_called)

    # GREEN: the loader tolerates the corruption and falls through to seed.
    result = datastore.geocode_cache_get(address)
    assert result is not None, "a corrupted runtime cache must not prevent the seed layer from serving a hit"
    assert result["cd"] == seed_entry["cd"]

    # Re-corrupt (the call above self-healed the file via write-through) and
    # prove a never-seeded address also misses cleanly against corruption,
    # rather than raising.
    datastore.GEOCODE_CACHE_JSON_PATH.write_text("{not valid json !!! [[[", encoding="utf-8")
    assert datastore.geocode_cache_get(NEVER_SEEDED_ADDRESS) is None


def _assert_seed_agrees_with_live(seed_entry: dict[str, Any], *, address: str, live_cd: str) -> None:
    """Consistency check: the committed geocode seed must agree with an
    independent live/ground-truth resolution for the same address. This is
    the check the task calls out explicitly -- a seed/live disagreement (e.g.
    a bad hand-edit, or a district boundary that shifted) must be caught, not
    silently served forever."""
    seed_cd = seed_entry.get("cd")
    assert seed_cd == live_cd, (
        f"geocode_seed.json disagrees with the live/ground-truth CD for {address!r}: "
        f"seed says {seed_cd!r}, live says {live_cd!r}"
    )


@selfproof
def test_seed_live_disagreement_would_be_caught():
    """GREEN: the real, committed seed entry for a precache address agrees
    with the independently-recorded ground-truth CD (tests/test_e2e_demo.py's
    PRECACHE_EXPECTED_CD, itself verified against the real Census geocoder --
    see that module's test_geocode_seed_ground_truth_matches_expected). RED:
    a seed entry with a deliberately wrong CD (a copy -- the real committed
    file is never touched) must be caught by the same consistency check."""
    address = PRECACHE_ADDRESSES[0]
    norm = datastore._normalize_address(address)
    real_seed_entry = GEOCODE_SEED[norm]
    live_cd = PRECACHE_EXPECTED_CD[address]

    _assert_seed_agrees_with_live(real_seed_entry, address=address, live_cd=live_cd)  # GREEN

    drifted = dict(real_seed_entry)
    drifted["cd"] = "TX-01" if live_cd != "TX-01" else "TX-02"
    with pytest.raises(AssertionError, match=re.escape(address)):
        _assert_seed_agrees_with_live(drifted, address=address, live_cd=live_cd)  # RED


# ===========================================================================
# 2. CIVIC_JSON PRESERVATION
# ===========================================================================


def _naive_replace_geocode_cache_put(
    address: str, *, cd: Optional[str], sd: Optional[str], hd: Optional[str], county: Optional[str], matched_address: Optional[str]
) -> None:
    """A NAIVE reimplementation of the pre-fix geocode_cache_put JSON-fallback
    branch: replaces cache[norm] wholesale instead of merge-preserving any
    existing entry (e.g. one already enriched with civic_json). Exists only
    to prove the RED case below -- production code (datastore.geocode_cache_put)
    never calls this; it merges (see its own docstring/comment)."""
    norm = datastore._normalize_address(address)
    with datastore._geocode_cache_file_lock:
        cache = datastore._load_geocode_cache_json()
        cache[norm] = {  # <-- the bug: wholesale replace, drops any existing civic_json
            "cd": cd,
            "sd": sd,
            "hd": hd,
            "county": county,
            "matched_address": matched_address,
            "ts": time.time(),
        }
        datastore._write_geocode_cache_json(cache)


@selfproof
def test_geocode_cache_put_merge_preserves_civic_json_red_then_green():
    """RED: a naive replace-not-merge geocode_cache_put clobbers an existing
    civic_json cache entry. GREEN: the real, current
    datastore.geocode_cache_put merges instead, preserving civic_json while
    still applying the new district/matched_address fields -- the
    clobber-fix regression this task calls out explicitly."""
    address = "123 Cache Robustness Test Ave, Somewhere, TX 78700"
    civic_payload = {"voting_info": {"foo": "bar"}, "division_check": {"consistent": True, "ocd_ids": ["x"]}}

    datastore.geocode_cache_put(
        address, cd="TX-50", sd="SD-1", hd="HD-1", county="Test County", matched_address="123 CACHE ROBUSTNESS TEST AVE"
    )
    datastore.geocode_cache_put_civic(address, civic_payload)
    assert datastore.geocode_cache_get_civic(address) == civic_payload  # sanity before either path runs

    # RED
    _naive_replace_geocode_cache_put(
        address,
        cd="TX-50",
        sd="SD-1",
        hd="HD-1",
        county="Test County",
        matched_address="123 CACHE ROBUSTNESS TEST AVE UPDATED",
    )
    assert datastore.geocode_cache_get_civic(address) is None, (
        "expected the naive replace to have clobbered civic_json -- if this fails, the RED "
        "case itself is broken and this test proves nothing"
    )

    # Re-seed (as if civic_json had just been looked up again) and exercise the REAL,
    # merge-preserving implementation.
    datastore.geocode_cache_put(
        address, cd="TX-50", sd="SD-1", hd="HD-1", county="Test County", matched_address="123 CACHE ROBUSTNESS TEST AVE"
    )
    datastore.geocode_cache_put_civic(address, civic_payload)

    # GREEN
    datastore.geocode_cache_put(
        address,
        cd="TX-50",
        sd="SD-1",
        hd="HD-1",
        county="Test County",
        matched_address="123 CACHE ROBUSTNESS TEST AVE UPDATED AGAIN",
    )
    assert datastore.geocode_cache_get_civic(address) == civic_payload

    norm = datastore._normalize_address(address)
    on_disk = json.loads(datastore.GEOCODE_CACHE_JSON_PATH.read_text(encoding="utf-8"))
    assert on_disk[norm]["matched_address"] == "123 CACHE ROBUSTNESS TEST AVE UPDATED AGAIN"
    assert on_disk[norm]["civic_json"] == civic_payload


# ===========================================================================
# 3. INSIGHTS INVALIDATION
# ===========================================================================


def test_compute_inputs_hash_deterministic_for_identical_data():
    race_id = _first_cached_race_id()
    h1 = datastore.compute_inputs_hash(race_id)
    h2 = datastore.compute_inputs_hash(race_id)
    assert h1 == h2
    assert isinstance(h1, str) and len(h1) == 64  # sha256 hex digest


def test_compute_inputs_hash_changes_when_candidate_data_mutates(monkeypatch):
    """Mutate a COPY of one candidate's data (never the real gold JSON on
    disk) and confirm the hash changes -- exactly the signal
    pipeline/load_postgres.py's incremental upsert relies on to decide
    upsert-vs-skip. Reproduces that exact gate condition against the two real
    hash values to prove a reload would upsert (not skip) when data actually
    changed, and would still correctly skip when it didn't."""
    race_id = _first_cached_race_id()
    race = datastore.get_race(race_id)
    assert race and race.get("candidate_ids"), f"{race_id} has no candidates to mutate"
    target_cid = race["candidate_ids"][0]
    original_candidate = datastore.get_candidate(target_cid)
    assert original_candidate is not None

    baseline_hash = datastore.compute_inputs_hash(race_id)

    mutated = copy.deepcopy(original_candidate)
    mutated["name"] = str(mutated.get("name", "")) + " (mutated-for-test)"

    real_get_candidate = datastore.get_candidate

    def _patched(cid: str) -> Optional[dict[str, Any]]:
        if cid == target_cid:
            return mutated
        return real_get_candidate(cid)

    monkeypatch.setattr(datastore, "get_candidate", _patched)
    mutated_hash = datastore.compute_inputs_hash(race_id)

    assert mutated_hash != baseline_hash, "changing a candidate's data must change the race's inputs_hash"

    # pipeline/load_postgres.py's exact gate: `row_exists and existing_hashes[key] == inputs_hash`.
    # A changed hash must flip that condition to False (upsert), not stay True (skip).
    row_exists = True
    would_skip_after_mutation = row_exists and baseline_hash == mutated_hash
    assert not would_skip_after_mutation, "a changed inputs_hash must cause load_postgres.py to upsert, not skip"


def test_inputs_hash_algorithm_matches_load_postgres_copy():
    """app/datastore.py::compute_inputs_hash and
    pipeline/load_postgres.py::_race_inputs_hash are two independent copies of
    the same algorithm (by necessity: one runs inside the serving process via
    get_race/get_candidate, the other in a standalone bulk loader reading the
    gold JSON directly) that MUST agree, or a live write-through-cached row
    would be wrongly seen as stale (or stale data wrongly seen as fresh) on
    the next bulk reload. This is exactly the drift both modules' docstrings
    warn about -- checked here across every race in the real gold dataset."""
    load_postgres = _load_module("cache_robustness_load_postgres", REPO_ROOT / "pipeline" / "load_postgres.py")
    races_doc = json.loads(RACES_JSON_PATH.read_text(encoding="utf-8"))
    candidates_doc = json.loads(CANDIDATES_JSON_PATH.read_text(encoding="utf-8"))
    races_by_id = {r["race_id"]: r for r in races_doc.get("races", [])}
    assert races_by_id, "data/tx/races.json has no races to check"

    checked = 0
    for race_id, race in races_by_id.items():
        via_datastore = datastore.compute_inputs_hash(race_id)
        via_loader = load_postgres._race_inputs_hash(race, candidates_doc)
        assert via_datastore == via_loader, (
            f"{race_id}: app/datastore.py::compute_inputs_hash and "
            "pipeline/load_postgres.py::_race_inputs_hash have drifted apart"
        )
        checked += 1
    assert checked == len(races_by_id)


class _FakeInsightsCursor:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def fetchall(self) -> list[dict[str, Any]]:
        return self._rows


class _FakeInsightsConn:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def __enter__(self) -> "_FakeInsightsConn":
        return self

    def __exit__(self, *exc: Any) -> bool:
        return False

    def execute(self, query: str, params: Any = None) -> _FakeInsightsCursor:
        return _FakeInsightsCursor(self._rows)


class _FakeInsightsPool:
    """Minimal stand-in for psycopg_pool.ConnectionPool's `with pool.connection()
    as conn: conn.execute(...).fetchall()` shape -- just enough surface for
    datastore.get_insights's Postgres branch to run for real against canned
    rows, with zero real Postgres/psycopg involved."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def connection(self, timeout: Optional[float] = None) -> _FakeInsightsConn:
        return _FakeInsightsConn(self._rows)


def test_get_insights_reassembles_keyed_rows_losslessly(monkeypatch):
    """Drives datastore.get_insights's REAL Postgres-shaped reassembly branch
    (one row per (race_id, archetype) block) via a fake pool, and confirms it
    reassembles back into the {race_id, base, archetypes} file shape with no
    data lost or altered."""
    base_payload = {
        "candidates": {"cand-a": [{"text": "t1", "source": "https://example.gov/a"}]},
        "summary": "s",
        "caveats": "c",
        "horizons": {"cand-a": {"now": [], "long_term": []}},
    }
    veteran_payload = {
        "candidates": {"cand-a": [{"text": "t2", "source": "https://example.gov/b"}]},
        "summary": "s2",
        "caveats": "c2",
    }
    rows = [
        {"archetype": "base", "payload": base_payload},
        {"archetype": "veteran", "payload": veteran_payload},
    ]
    monkeypatch.setattr(datastore, "_pool", _FakeInsightsPool(rows))
    monkeypatch.setattr(datastore, "_pg_init_done", True)

    result = datastore.get_insights("fake-race-for-reassembly-test")
    assert result == {
        "race_id": "fake-race-for-reassembly-test",
        "base": base_payload,
        "archetypes": {"veteran": veteran_payload},
    }


def test_put_insight_block_write_through_then_served_cached(monkeypatch, tmp_path):
    """Datastore-level write-through/read-back contract (the caching layer
    itself, distinct from tests/test_live_insights.py's LLM-generation-focused
    coverage of the same endpoint): a block written via put_insight_block is
    served back by get_insights on the very next call, and writing one
    archetype's block never disturbs another block already cached for that
    same race."""
    monkeypatch.setattr(datastore, "INSIGHTS_DIR", tmp_path / "insights")
    race_id = "fake-race-for-write-through-test"

    assert datastore.get_insights(race_id) is None

    base_payload = {
        "candidates": {"cand-a": [{"text": "base bullet", "source": "https://example.gov/base"}]},
        "summary": "base summary",
        "caveats": "base caveats",
        "horizons": {},
    }
    datastore.put_insight_block(race_id, "base", base_payload)

    cached = datastore.get_insights(race_id)
    # JSON-fallback get_insights returns the raw file (race_id + generated_at
    # + base -- "archetypes" is absent entirely until a non-base block is
    # ever written, unlike the Postgres-reassembly branch which always
    # synthesizes an "archetypes" key, even empty -- see
    # test_get_insights_reassembles_keyed_rows_losslessly above for that
    # branch instead).
    assert cached["race_id"] == race_id
    assert cached["base"] == base_payload
    assert not cached.get("archetypes")

    veteran_payload = {
        "candidates": {"cand-a": [{"text": "veteran bullet", "source": "https://example.gov/vet"}]},
        "summary": "veteran summary",
        "caveats": "veteran caveats",
        "horizons": {},
    }
    datastore.put_insight_block(race_id, "veteran", veteran_payload)

    cached_again = datastore.get_insights(race_id)
    assert cached_again["base"] == base_payload, "writing the veteran block must not disturb base"
    assert cached_again["archetypes"] == {"veteran": veteran_payload}

    # Served-cached: a later read returns byte-identical content with no further write.
    assert datastore.get_insights(race_id) == cached_again


# ===========================================================================
# 4. DEMO-CACHE FRESHNESS
# ===========================================================================


def test_demo_cache_staleness_detection_self_proof_ballot(tmp_path):
    """STALENESS-DETECTION proof, complementing (not duplicating)
    tests/test_e2e_demo.py's in-memory-only test_selfproof_stale_cache_divergence_detected:
    this operates on a byte-identical TMP COPY of a real committed
    data/demo_cache/**/ballot.json file -- the committed file itself is never
    opened for writing, so there is zero risk to repo state even if this test
    is interrupted mid-run. Mutate the copy -> freshness check FAILS naming
    the file and the drifted race_id -> restore the copy -> PASSES again."""
    address = PRECACHE_ADDRESSES[0]
    _seed_geocode(address)
    real_path = DEMO_CACHE_DIR / _slug(address) / "ballot.json"
    tmp_copy = tmp_path / "ballot.json"
    tmp_copy.write_text(real_path.read_text(encoding="utf-8"), encoding="utf-8")

    def _freshness_check() -> None:
        cached = json.loads(tmp_copy.read_text(encoding="utf-8"))
        fresh_resp = client.get("/api/ballot", params={"address": address})
        assert fresh_resp.status_code == 200, fresh_resp.text[:300]
        _assert_ballot_cache_matches_fresh(cached, fresh_resp.json(), context=str(tmp_copy))

    _freshness_check()  # sanity: clean copy passes before any mutation

    doc = json.loads(tmp_copy.read_text(encoding="utf-8"))
    first_race = doc["races"][0]
    assert first_race.get("candidates"), "expected at least one candidate to mutate"
    victim_race_id = first_race["race_id"]
    first_race["candidates"][0]["finance"] = {
        "receipts": 999999999.0,
        "source": "https://example.com/fabricated-for-staleness-test",
    }
    tmp_copy.write_text(json.dumps(doc), encoding="utf-8")

    with pytest.raises(AssertionError, match=re.escape(victim_race_id)):
        _freshness_check()  # RED: the check fails, naming the drifted race

    tmp_copy.write_text(real_path.read_text(encoding="utf-8"), encoding="utf-8")
    _freshness_check()  # GREEN: restored copy passes again


def test_demo_cache_staleness_detection_self_proof_insights(tmp_path):
    """Same staleness-detection proof for an insights_<race_id>.json demo
    cache file (the endpoint-response shape: {mode, archetype_used,
    candidates, summary, caveats, horizons} -- precache_demo.py saves the
    live /api/insights response verbatim, it is not the internal
    data/tx/insights/{race_id}.json shape)."""
    address = PRECACHE_ADDRESSES[0]
    _seed_geocode(address)
    slug = _slug(address)
    insight_files = sorted((DEMO_CACHE_DIR / slug).glob("insights_*.json"))
    assert insight_files, f"no insights_*.json cached for {address}"
    real_path = insight_files[0]
    race_id = real_path.name[len("insights_") : -len(".json")]
    tmp_copy = tmp_path / real_path.name
    tmp_copy.write_text(real_path.read_text(encoding="utf-8"), encoding="utf-8")

    def _freshness_check() -> None:
        cached = json.loads(tmp_copy.read_text(encoding="utf-8"))
        fresh_resp = client.post(
            "/api/insights", json={"profile": _precache_demo.HOMEOWNER_PARENT_PROFILE, "race_id": race_id}
        )
        assert fresh_resp.status_code == 200, fresh_resp.text[:300]
        _assert_insights_cache_matches_fresh(cached, fresh_resp.json(), context=str(tmp_copy))

    _freshness_check()  # sanity: clean copy passes

    doc = json.loads(tmp_copy.read_text(encoding="utf-8"))
    doc["summary"] = "STALENESS-INJECTED-FOR-SELF-PROOF: " + str(doc.get("summary", ""))
    tmp_copy.write_text(json.dumps(doc), encoding="utf-8")

    with pytest.raises(AssertionError, match=re.escape(str(tmp_copy))):
        _freshness_check()  # RED

    tmp_copy.write_text(real_path.read_text(encoding="utf-8"), encoding="utf-8")
    _freshness_check()  # GREEN: restored


VALID_TIERS = {"A", "B", "C", "D"}


def _assert_candidate_data_quality_shape(dq: Any, *, context: str) -> None:
    assert isinstance(dq, dict), f"{context}: data_quality is missing/not an object: {dq!r}"
    assert isinstance(dq.get("score"), (int, float)), f"{context}: data_quality.score missing/non-numeric: {dq!r}"
    assert dq.get("tier") in VALID_TIERS, f"{context}: data_quality.tier invalid (want one of {VALID_TIERS}): {dq!r}"
    assert isinstance(dq.get("missing"), list), f"{context}: data_quality.missing is not a list: {dq!r}"


def test_every_cached_ballot_candidate_carries_current_data_quality_shape():
    """Every candidate embedded in every cached data/demo_cache/**/ballot.json
    must carry the current pipeline/score_quality.py data_quality shape
    ({score, tier, missing}) -- candidates deliberately marked data_missing
    (see app/datastore.py::_embed_candidates) are exempt by contract, since
    they carry no other fields either."""
    ballot_files = sorted(DEMO_CACHE_DIR.rglob("ballot.json"))
    assert ballot_files, f"no ballot.json files under {DEMO_CACHE_DIR} to validate"

    checked = 0
    for path in ballot_files:
        doc = json.loads(path.read_text(encoding="utf-8"))
        for race in doc.get("races", []):
            for cand in race.get("candidates", []):
                if cand.get("data_missing"):
                    continue
                context = f"{path.relative_to(DEMO_CACHE_DIR)}/{race.get('race_id')}/{cand.get('candidate_id')}"
                _assert_candidate_data_quality_shape(cand.get("data_quality"), context=context)
                checked += 1
    assert checked > 0, "expected at least one real candidate to check across all cached ballots"


@selfproof
def test_data_quality_shape_check_catches_corruption():
    """Proves _assert_candidate_data_quality_shape is not a tautology: a real
    data_quality block (GREEN) with its tier removed, or set to an invalid
    value, must RED-flag."""
    ballot_files = sorted(DEMO_CACHE_DIR.rglob("ballot.json"))
    assert ballot_files
    real_doc = json.loads(ballot_files[0].read_text(encoding="utf-8"))

    real_dq = None
    for race in real_doc.get("races", []):
        for cand in race.get("candidates", []):
            if isinstance(cand.get("data_quality"), dict):
                real_dq = cand["data_quality"]
                break
        if real_dq:
            break
    assert real_dq is not None, "no candidate with a data_quality block found to self-proof against"

    _assert_candidate_data_quality_shape(real_dq, context="selfproof-clean")  # GREEN

    missing_tier = dict(real_dq)
    missing_tier.pop("tier", None)
    with pytest.raises(AssertionError, match="tier"):
        _assert_candidate_data_quality_shape(missing_tier, context="selfproof-injected")  # RED

    invalid_tier = dict(real_dq)
    invalid_tier["tier"] = "Z"
    with pytest.raises(AssertionError, match="tier"):
        _assert_candidate_data_quality_shape(invalid_tier, context="selfproof-injected")  # RED
