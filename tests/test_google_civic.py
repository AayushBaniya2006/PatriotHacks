"""Tests for the OPTIONAL Google Civic Information API enrichment.

Covers exactly the cases the integration is required to handle gracefully:
  - no GOOGLE_CIVIC_API_KEY -> /api/ballot response has no voting_info key
  - 403 from the API (bad/quota-exceeded key) -> same, no error surfaced
  - happy-path mock -> get_voter_info/get_divisions normalize correctly
  - a real division mismatch -> division_check.consistent is False

Plus one honest live smoke call, only if GOOGLE_CIVIC_API_KEY actually exists
in the environment at test-run time (skipped, never failed, otherwise -- see
CLAUDE.md: as of 2026-07-03 this key does not exist in .env yet).

httpx is mocked via a fake AsyncClient built from real httpx.Response
objects (so raise_for_status()/json() behave exactly like the real thing),
monkeypatched only onto app.google_civic's own reference to the httpx
module -- app.main's separate `import httpx` (used for the real Census
geocoder call) is completely unaffected, so these tests never risk
silently redirecting a different module's network calls.
"""

from __future__ import annotations

import asyncio
import os
import sys
import types
from pathlib import Path
from typing import Any, Callable, Optional, Union

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from app import datastore, google_civic, main  # noqa: E402
from app.middleware import RATE_LIMIT_HITS  # noqa: E402

SAN_MARCOS_ADDRESS = "601 University Dr, San Marcos, TX 78666"

# handler(url, params) -> (status_code, json_body) or an Exception instance to raise
Handler = Callable[[str, dict[str, Any]], Union[tuple, BaseException]]


# ---------------------------------------------------------------------------
# Isolation fixtures -- these tests must never depend on run order, a real
# database, the real on-disk geocode cache, or requests other test files
# already made against the (shared, in-process) rate limiter.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_geocode_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(datastore, "GEOCODE_CACHE_JSON_PATH", tmp_path / "geocode_cache.json")
    monkeypatch.setattr(datastore, "_pool", None)
    monkeypatch.setattr(datastore, "_pg_init_done", True)  # force JSON-fallback mode deterministically
    yield


@pytest.fixture(autouse=True)
def _reset_elections_cache(monkeypatch):
    monkeypatch.setattr(google_civic, "_elections_cache", None)
    yield


@pytest.fixture(autouse=True)
def _reset_rate_limit():
    RATE_LIMIT_HITS.clear()
    yield


def _seed_geocode_cache(address: str, *, cd="TX-35", sd="SD-21", hd="HD-45", county="Hays County") -> None:
    """Pre-populate the base geocode cache so /api/ballot never needs a live
    Census geocoder call in these tests."""
    datastore.geocode_cache_put(address, cd=cd, sd=sd, hd=hd, county=county, matched_address=address.upper())


def _install_fake_civic_client(monkeypatch, handler: Handler) -> None:
    """Monkeypatch app.google_civic's own `httpx` reference to a stand-in
    whose AsyncClient.get() is driven by `handler`. Everything else on the
    namespace (TimeoutException, HTTPError, ...) is the real httpx module's,
    so google_civic._get()'s except clause still catches real exceptions
    (including the real HTTPStatusError a real Response.raise_for_status()
    raises) exactly as it would in production."""

    class _FakeAsyncClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> "_FakeAsyncClient":
            return self

        async def __aexit__(self, *exc: Any) -> bool:
            return False

        async def get(self, url: str, params: Optional[dict[str, Any]] = None, **kwargs: Any) -> httpx.Response:
            outcome = handler(url, params or {})
            if isinstance(outcome, BaseException):
                raise outcome
            status_code, json_body = outcome
            request = httpx.Request("GET", url, params=params)
            return httpx.Response(status_code, json=json_body, request=request)

    fake_httpx = types.SimpleNamespace(**vars(httpx))
    fake_httpx.AsyncClient = _FakeAsyncClient
    monkeypatch.setattr(google_civic, "httpx", fake_httpx)


# ---------------------------------------------------------------------------
# 1. No key -> ballot response has NO voting_info / division_check key
# ---------------------------------------------------------------------------


def test_no_key_ballot_has_no_voting_info(monkeypatch):
    monkeypatch.setattr(main, "GOOGLE_CIVIC_API_KEY", None)
    monkeypatch.delenv("GOOGLE_CIVIC_API_KEY", raising=False)
    _seed_geocode_cache(SAN_MARCOS_ADDRESS)

    client = TestClient(main.app)
    resp = client.get("/api/ballot", params={"address": SAN_MARCOS_ADDRESS})

    assert resp.status_code == 200
    body = resp.json()
    assert "voting_info" not in body
    assert "division_check" not in body


# ---------------------------------------------------------------------------
# 2. 403 from the API -> same result, no error surfaced to the caller
# ---------------------------------------------------------------------------


def test_403_from_api_degrades_silently(monkeypatch):
    monkeypatch.setattr(main, "GOOGLE_CIVIC_API_KEY", "fake-key")
    monkeypatch.setenv("GOOGLE_CIVIC_API_KEY", "fake-key")
    _seed_geocode_cache(SAN_MARCOS_ADDRESS)

    def handler(url: str, params: dict[str, Any]):
        return (403, {"error": {"code": 403, "message": "quota exceeded", "status": "PERMISSION_DENIED"}})

    _install_fake_civic_client(monkeypatch, handler)

    client = TestClient(main.app)
    resp = client.get("/api/ballot", params={"address": SAN_MARCOS_ADDRESS})

    assert resp.status_code == 200
    body = resp.json()
    assert "voting_info" not in body
    assert "division_check" not in body


# ---------------------------------------------------------------------------
# 3. Happy-path mock -> normalized shape is correct
# ---------------------------------------------------------------------------


def _happy_elections_body() -> dict[str, Any]:
    return {
        "elections": [
            {
                "id": "9001",
                "name": "Texas General Election 2026",
                "electionDay": "2026-11-03",
                "ocdDivisionId": "ocd-division/country:us/state:tx",
            }
        ]
    }


def _happy_voterinfo_body() -> dict[str, Any]:
    return {
        "election": {"id": "9001", "name": "Texas General Election 2026", "electionDay": "2026-11-03"},
        "pollingLocations": [
            {
                "address": {
                    "locationName": "San Marcos City Hall",
                    "line1": "630 E Hopkins St",
                    "city": "San Marcos",
                    "state": "TX",
                    "zip": "78666",
                },
                "pollingHours": "7:00am-7:00pm",
            }
        ],
        "earlyVoteSites": [],
        "dropOffLocations": [],
        "contests": [
            {
                "type": "General",
                "office": "US House",
                "district": {
                    "name": "Congressional District 35",
                    "scope": "congressional",
                    "id": "ocd-division/country:us/state:tx/cd:35",
                },
            }
        ],
    }


def _install_happy_path(monkeypatch) -> None:
    def handler(url: str, params: dict[str, Any]):
        if url.endswith("/elections"):
            return (200, _happy_elections_body())
        if url.endswith("/voterinfo"):
            assert params.get("electionId") == "9001", "should target the discovered Nov 2026 election"
            return (200, _happy_voterinfo_body())
        raise AssertionError(f"unexpected Civic API path requested: {url}")

    _install_fake_civic_client(monkeypatch, handler)


def test_happy_path_normalized_shape(monkeypatch):
    monkeypatch.setenv("GOOGLE_CIVIC_API_KEY", "fake-key")
    _install_happy_path(monkeypatch)

    result = asyncio.run(google_civic.get_voter_info(SAN_MARCOS_ADDRESS))

    assert result is not None
    assert result["election"] == {"name": "Texas General Election 2026", "date": "2026-11-03"}
    assert result["contests_present"] is True
    assert result["source"] == "https://developers.google.com/civic-information"

    assert result["early_vote_sites"] == []
    assert result["dropoff_locations"] == []
    assert len(result["polling_locations"]) == 1
    loc = result["polling_locations"][0]
    assert loc["name"] == "San Marcos City Hall"
    assert loc["address"] is not None and "630 E Hopkins St" in loc["address"]
    assert "78666" in loc["address"]
    assert loc["hours"] == "7:00am-7:00pm"

    ocd_ids = asyncio.run(google_civic.get_divisions(SAN_MARCOS_ADDRESS))
    assert ocd_ids == ["ocd-division/country:us/state:tx/cd:35"]


def test_no_key_returns_none_without_network(monkeypatch):
    """Belt-and-suspenders unit-level check on the module itself (distinct
    from the endpoint-level test above): no key means no network call is
    even attempted."""
    monkeypatch.delenv("GOOGLE_CIVIC_API_KEY", raising=False)

    def handler(url: str, params: dict[str, Any]):
        raise AssertionError("must not make a network call when no API key is configured")

    _install_fake_civic_client(monkeypatch, handler)

    assert asyncio.run(google_civic.get_voter_info(SAN_MARCOS_ADDRESS)) is None
    assert asyncio.run(google_civic.get_divisions(SAN_MARCOS_ADDRESS)) is None


# ---------------------------------------------------------------------------
# 4. Division mismatch -> division_check.consistent is False
# ---------------------------------------------------------------------------


def test_division_mismatch_consistent_false(monkeypatch):
    monkeypatch.setattr(main, "GOOGLE_CIVIC_API_KEY", "fake-key")
    monkeypatch.setenv("GOOGLE_CIVIC_API_KEY", "fake-key")
    # Our Census-derived cd for this address is TX-35 (seeded below), but
    # Google's OCD division below says cd:07 -- an intentional mismatch.
    _seed_geocode_cache(SAN_MARCOS_ADDRESS, cd="TX-35")

    def handler(url: str, params: dict[str, Any]):
        if url.endswith("/elections"):
            return (200, {"elections": []})
        if url.endswith("/voterinfo"):
            return (
                200,
                {
                    "election": {},
                    "pollingLocations": [],
                    "earlyVoteSites": [],
                    "dropOffLocations": [],
                    "contests": [{"district": {"id": "ocd-division/country:us/state:tx/cd:07"}}],
                },
            )
        raise AssertionError(f"unexpected Civic API path requested: {url}")

    _install_fake_civic_client(monkeypatch, handler)

    client = TestClient(main.app)
    resp = client.get("/api/ballot", params={"address": SAN_MARCOS_ADDRESS})

    assert resp.status_code == 200
    body = resp.json()
    assert "division_check" in body
    assert body["division_check"] == {
        "consistent": False,
        "ocd_ids": ["ocd-division/country:us/state:tx/cd:07"],
    }
    # No useful voting_info in this fixture (empty election + no locations).
    assert "voting_info" not in body


def test_division_match_consistent_true(monkeypatch):
    monkeypatch.setattr(main, "GOOGLE_CIVIC_API_KEY", "fake-key")
    monkeypatch.setenv("GOOGLE_CIVIC_API_KEY", "fake-key")
    _seed_geocode_cache(SAN_MARCOS_ADDRESS, cd="TX-35")

    def handler(url: str, params: dict[str, Any]):
        if url.endswith("/elections"):
            return (200, {"elections": []})
        if url.endswith("/voterinfo"):
            return (
                200,
                {
                    "election": {},
                    "pollingLocations": [],
                    "earlyVoteSites": [],
                    "dropOffLocations": [],
                    "contests": [{"district": {"id": "ocd-division/country:us/state:tx/cd:35"}}],
                },
            )
        raise AssertionError(f"unexpected Civic API path requested: {url}")

    _install_fake_civic_client(monkeypatch, handler)

    client = TestClient(main.app)
    resp = client.get("/api/ballot", params={"address": SAN_MARCOS_ADDRESS})

    assert resp.status_code == 200
    body = resp.json()
    assert body["division_check"]["consistent"] is True


# ---------------------------------------------------------------------------
# 5. Second identical request is served from the civic cache (no 2nd fetch)
# ---------------------------------------------------------------------------


def test_second_request_served_from_civic_cache(monkeypatch):
    monkeypatch.setattr(main, "GOOGLE_CIVIC_API_KEY", "fake-key")
    monkeypatch.setenv("GOOGLE_CIVIC_API_KEY", "fake-key")
    _seed_geocode_cache(SAN_MARCOS_ADDRESS)

    call_count = {"n": 0}

    def handler(url: str, params: dict[str, Any]):
        call_count["n"] += 1
        if url.endswith("/elections"):
            return (200, _happy_elections_body())
        if url.endswith("/voterinfo"):
            return (200, _happy_voterinfo_body())
        raise AssertionError(f"unexpected Civic API path requested: {url}")

    _install_fake_civic_client(monkeypatch, handler)

    client = TestClient(main.app)
    resp1 = client.get("/api/ballot", params={"address": SAN_MARCOS_ADDRESS})
    assert resp1.status_code == 200
    first_calls = call_count["n"]
    assert first_calls > 0

    resp2 = client.get("/api/ballot", params={"address": SAN_MARCOS_ADDRESS})
    assert resp2.status_code == 200
    assert call_count["n"] == first_calls, "second lookup for the same address must be served from cache"
    assert resp1.json().get("voting_info") == resp2.json().get("voting_info")


# ---------------------------------------------------------------------------
# 6. Optional live smoke call -- only runs if a real key is actually set.
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not os.environ.get("GOOGLE_CIVIC_API_KEY"),
    reason="GOOGLE_CIVIC_API_KEY not set in the environment -- live smoke skipped (see CLAUDE.md § Keys)",
)
def test_live_smoke_if_key_present():
    """One honest live call against the real Google Civic API. No-coverage-
    yet is an explicitly valid, PASSING outcome here (see
    data/endpoint_inventory.json's google-civic entry: Google typically
    doesn't load a general election's VIP data until weeks out) -- this only
    asserts the *shape* when data does come back, never that data must
    exist."""
    result = asyncio.run(google_civic.get_voter_info(SAN_MARCOS_ADDRESS))
    if result is None:
        print("[live smoke] get_voter_info: None (no coverage yet, or API error -- both are valid outcomes)")
        return

    assert isinstance(result.get("election"), dict)
    assert isinstance(result.get("polling_locations"), list)
    assert isinstance(result.get("early_vote_sites"), list)
    assert isinstance(result.get("dropoff_locations"), list)
    assert isinstance(result.get("contests_present"), bool)
    assert result.get("source") == "https://developers.google.com/civic-information"
    print(f"[live smoke] get_voter_info returned data: election={result.get('election')}")

    ocd_ids = asyncio.run(google_civic.get_divisions(SAN_MARCOS_ADDRESS))
    print(f"[live smoke] get_divisions returned: {ocd_ids}")
