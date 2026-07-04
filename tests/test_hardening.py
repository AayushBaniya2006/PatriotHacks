"""API hardening verification (GitHub issue #8).

Abuse battery for app/main.py's input validation, error envelope, rate
limiting, and security headers -- written against the locked API contract
(CLAUDE.md § API contract / schema.md), never against implementation
details. Every test here should keep passing if the contract's documented
shapes are preserved, even if the internals change.

Uses FastAPI's TestClient (in-process, no real network) so this suite is
fast, deterministic, and safe to run with NO_NETWORK=1 -- nothing here calls
the live Census geocoder or OpenRouter: invalid addresses are rejected
before any geocoder call, and every race_id used against POST /api/insights
is either malformed (rejected before any datastore lookup), a well-formed
but nonexistent id (404 before any candidate/LLM lookup), or a real race_id
chosen because it already has a precomputed insights file on disk (so the
response is always served from cache, never falls through to a live
OpenRouter call).

Run:
    pytest tests/test_hardening.py -v
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from app import datastore  # noqa: E402
from app.main import app  # noqa: E402
from app.middleware import RATE_LIMIT_HITS  # noqa: E402

client = TestClient(app)

VALID_MIN_ADDRESS_LENGTH = 3


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Every test starts and ends with a clean rate-limit slate, so no test
    in this file (or a future one added later) can be spuriously
    rate-limited by a different test's request count, and the flood test
    below always starts counting from zero regardless of run order."""
    RATE_LIMIT_HITS.clear()
    yield
    RATE_LIMIT_HITS.clear()


def _first_cached_race_id() -> str:
    """A race_id guaranteed to have a precomputed insights file on disk, so
    POST /api/insights against it is always served from cache -- never
    falls through to a live OpenRouter call regardless of whether
    OPENROUTER_API_KEY happens to be set in the environment this runs in."""
    insights_dir = REPO_ROOT / "data" / "tx" / "insights"
    files = sorted(insights_dir.glob("*.json"))
    if not files:
        pytest.skip("no precomputed insight files under data/tx/insights")
    return files[0].stem


# ---------------------------------------------------------------------------
# Address input validation (GET /api/ballot)
# ---------------------------------------------------------------------------


def test_oversized_address_returns_422():
    resp = client.get("/api/ballot", params={"address": "A" * 300})
    assert resp.status_code == 422
    assert isinstance(resp.json().get("detail"), str)


def test_control_char_address_returns_422():
    resp = client.get(
        "/api/ballot",
        params={"address": "601 University Dr\x00\x01\x1f, San Marcos, TX 78666"},
    )
    assert resp.status_code == 422
    assert isinstance(resp.json().get("detail"), str)


def test_empty_after_trim_address_returns_422():
    resp = client.get("/api/ballot", params={"address": "   "})
    assert resp.status_code == 422
    assert isinstance(resp.json().get("detail"), str)


def test_address_error_shape_matches_geocoder_no_match_shape():
    """The 422 for a hardening rejection (too long) and the 422 for a
    genuine geocoder no-match must be the exact same {"detail": str} shape
    -- not a pydantic-style list-of-errors -- so the frontend has one error
    shape to handle for this param, not two."""
    resp = client.get("/api/ballot", params={"address": "A" * 300})
    body = resp.json()
    assert set(body.keys()) == {"detail"}
    assert isinstance(body["detail"], str)


# ---------------------------------------------------------------------------
# race_id validation (POST /api/insights)
# ---------------------------------------------------------------------------


def test_unknown_race_id_returns_404():
    resp = client.post(
        "/api/insights", json={"profile": {}, "race_id": "tx-zzz-nonexistent-9999"}
    )
    assert resp.status_code == 404
    assert "detail" in resp.json()


def test_malformed_race_id_returns_404_not_500():
    resp = client.post(
        "/api/insights",
        json={"profile": {}, "race_id": "tx-gov-2026'; DROP TABLE races; --"},
    )
    assert resp.status_code == 404
    assert "detail" in resp.json()


def test_malformed_race_id_does_not_echo_raw_value():
    malformed = "'; DROP TABLE races; --"
    resp = client.post("/api/insights", json={"profile": {}, "race_id": malformed})
    assert resp.status_code == 404
    assert malformed not in resp.text


# ---------------------------------------------------------------------------
# POST body validation (profile allow-list, occupation cap, body size cap)
# ---------------------------------------------------------------------------


def test_unknown_profile_keys_are_ignored_not_rejected():
    race_id = _first_cached_race_id()
    resp = client.post(
        "/api/insights",
        json={
            "profile": {
                "veteran": True,
                "totally_bogus_key": "malicious payload",
                "__proto__": {"polluted": True},
            },
            "race_id": race_id,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    # The known key (veteran) still resolves the archetype correctly --
    # proof the unknown keys were dropped, not that the whole profile was
    # discarded.
    assert body.get("archetype_used") == "veteran"


def test_occupation_over_120_chars_is_capped_not_rejected():
    race_id = _first_cached_race_id()
    resp = client.post(
        "/api/insights",
        json={"profile": {"occupation": "farmer " + "x" * 500}, "race_id": race_id},
    )
    assert resp.status_code == 200


def test_oversized_body_rejected_with_413_or_422():
    resp = client.post(
        "/api/insights",
        json={"profile": {"occupation": "x" * 20000}, "race_id": "tx-gov-2026"},
    )
    assert resp.status_code in (413, 422)
    assert "detail" in resp.json()


def test_wrong_typed_profile_field_returns_422_not_500():
    """pydantic strict-ish types: a profile field that should be a string
    but arrives as a nested object must 422, never crash downstream code."""
    race_id = _first_cached_race_id()
    resp = client.post(
        "/api/insights",
        json={"profile": {"age_bracket": {"nested": "object"}}, "race_id": race_id},
    )
    assert resp.status_code == 422
    assert "detail" in resp.json()


# ---------------------------------------------------------------------------
# Error envelope consistency
# ---------------------------------------------------------------------------


def test_error_responses_all_have_detail_key():
    cases = [
        lambda: client.get("/api/ballot", params={"address": "A" * 300}),
        lambda: client.get("/api/ballot", params={"address": "\x00\x01"}),
        lambda: client.post(
            "/api/insights", json={"profile": {}, "race_id": "tx-nope-9999"}
        ),
        lambda: client.post(
            "/api/insights", json={"profile": {}, "race_id": "bad id!!"}
        ),
        lambda: client.post(
            "/api/insights",
            json={"profile": {"occupation": "x" * 20000}, "race_id": "tx-gov-2026"},
        ),
    ]
    for make_request in cases:
        resp = make_request()
        assert resp.status_code >= 400, f"expected an error status, got {resp.status_code}"
        body = resp.json()
        assert "detail" in body, f"error response missing 'detail': {body}"


def test_unhandled_exception_returns_generic_500_no_traceback(monkeypatch):
    """A genuine bug (simulated here) must never leak a stack trace to the
    client -- only a generic {"detail": "internal error"}. Needs its own
    TestClient with raise_server_exceptions=False since Starlette's
    ServerErrorMiddleware re-raises after sending the response (so test
    clients/servers can still log it), which would otherwise surface as a
    raised exception in this test process rather than a response to assert
    on."""
    race_id = _first_cached_race_id()

    def _boom(_race_id: str):
        raise RuntimeError("simulated internal bug")

    # This race_id must NOT already be cached, so the request reaches
    # datastore.get_race (patched to blow up) -- pick one guaranteed absent.
    monkeypatch.setattr(datastore, "get_race", _boom)
    local_client = TestClient(app, raise_server_exceptions=False)
    resp = local_client.post(
        "/api/insights", json={"profile": {}, "race_id": "tx-unknown-needs-lookup"}
    )
    assert resp.status_code == 500
    body = resp.json()
    assert body == {"detail": "internal error"}
    assert "RuntimeError" not in resp.text
    assert "Traceback" not in resp.text
    # sanity: the cached-race fast path is untouched by the patch
    assert _first_cached_race_id() == race_id


# ---------------------------------------------------------------------------
# Rate limiting (/api/* only, /healthz exempt)
# ---------------------------------------------------------------------------


def test_rapid_requests_trigger_rate_limit_with_retry_after():
    # A malformed race_id short-circuits before any datastore/network access
    # (see test_malformed_race_id_returns_404_not_500), so this flood is
    # fast and purely exercises the rate limiter's request counting.
    responses = [
        client.post("/api/insights", json={"profile": {}, "race_id": "!!!not-valid!!!"})
        for _ in range(65)
    ]
    statuses = [r.status_code for r in responses]
    assert 429 in statuses, f"expected at least one 429 in 65 rapid requests, got {set(statuses)}"

    throttled = next(r for r in responses if r.status_code == 429)
    assert "detail" in throttled.json()
    assert "Retry-After" in throttled.headers


def test_healthz_not_rate_limited_even_while_api_is_throttled():
    # Exhaust the /api/* budget first.
    for _ in range(65):
        client.post("/api/insights", json={"profile": {}, "race_id": "!!!not-valid!!!"})

    # /healthz must still work -- it's exempt because it isn't under /api/*.
    for _ in range(5):
        resp = client.get("/healthz")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Security headers / CORS (bonus coverage for hardening item 5)
# ---------------------------------------------------------------------------


def test_security_headers_present_on_api_responses():
    resp = client.get("/healthz")
    assert resp.headers.get("x-content-type-options") == "nosniff"
    assert resp.headers.get("x-frame-header", resp.headers.get("x-frame-options")) == "DENY"
    assert resp.headers.get("referrer-policy") == "no-referrer"


def test_cache_control_no_store_scoped_to_api_paths():
    api_resp = client.post(
        "/api/insights", json={"profile": {}, "race_id": _first_cached_race_id()}
    )
    assert api_resp.headers.get("cache-control") == "no-store"

    healthz_resp = client.get("/healthz")
    # /healthz is not under /api/*, so it is deliberately NOT forced no-store.
    assert healthz_resp.headers.get("cache-control") != "no-store"


def test_cors_never_pairs_wildcard_origin_with_credentials(monkeypatch):
    """Defense in depth: even if CORS_ORIGINS were ever misconfigured to a
    literal "*", allow_credentials must not be True alongside it."""
    import importlib

    import app.main as main_module

    monkeypatch.setenv("CORS_ORIGINS", "*")
    reloaded = importlib.reload(main_module)
    try:
        assert reloaded._cors_origins == ["*"]
        assert reloaded._cors_allow_credentials is False
    finally:
        importlib.reload(main_module)  # restore normal module state for any later test


def test_geocode_cache_get_falls_back_to_committed_seed(monkeypatch, tmp_path):
    """Restart-proof seed layer (kills the live-geocoder hot-path risk): with
    the runtime cache empty -- as after a cold restart, no Postgres, no
    data/geocode_cache.json -- a demo address already resolved into the
    committed data/tx/geocode_seed.json must still resolve, and that
    resolution must write through to the runtime cache so it's this cheap
    for every request after the first, restart or not."""
    seed_path = REPO_ROOT / "data" / "tx" / "geocode_seed.json"
    if not seed_path.exists():
        pytest.skip("data/tx/geocode_seed.json not generated yet (run pipeline/build_geocode_seed.py)")
    seed = json.loads(seed_path.read_text(encoding="utf-8"))

    address = "1100 E Monroe St, Brownsville, TX 78520"
    norm = datastore._normalize_address(address)
    expected = seed.get(norm)
    if expected is None:
        pytest.skip(f"{address!r} not present in the committed seed file")

    empty_runtime_cache = tmp_path / "geocode_cache.json"
    monkeypatch.setattr(datastore, "GEOCODE_CACHE_JSON_PATH", empty_runtime_cache)
    saved_memory_cache = dict(datastore._geocode_memory_cache)
    datastore._geocode_memory_cache.clear()
    try:
        result = datastore.geocode_cache_get(address)
        assert result is not None, "a seeded address must resolve even with an empty runtime cache"
        assert result["cd"] == expected["cd"]
        assert result["sd"] == expected["sd"]
        assert result["hd"] == expected["hd"]
        assert result["county"] == expected["county"]
        assert result["matched_address"] == expected["matched_address"]

        # Write-through: the previously empty runtime cache now has this
        # address, so the seed file is consulted at most once per address.
        assert empty_runtime_cache.exists()
        runtime_contents = json.loads(empty_runtime_cache.read_text(encoding="utf-8"))
        assert norm in runtime_contents

        # A never-seeded, never-cached address must still miss cleanly, so
        # app/main.py's live-geocoder fallback path stays reachable.
        assert datastore.geocode_cache_get("1 Nowhere Rd, Nonexistent, TX 00000") is None
    finally:
        datastore._geocode_memory_cache.clear()
        datastore._geocode_memory_cache.update(saved_memory_cache)
