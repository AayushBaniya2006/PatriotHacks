"""Optional Google Civic Information API enrichment for /api/ballot.

This module is deliberately best-effort. With no GOOGLE_CIVIC_API_KEY, quota
errors, no election coverage, or malformed responses, callers get None/[] and
the core Census-backed ballot lookup remains unchanged.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://www.googleapis.com/civicinfo/v2"
TIMEOUT = httpx.Timeout(connect=3.0, read=5.0, write=5.0, pool=3.0)


def _api_key() -> Optional[str]:
    key = os.environ.get("GOOGLE_CIVIC_API_KEY")
    return key.strip() if key and key.strip() else None


async def _get_json(path: str, params: dict[str, Any]) -> Optional[dict[str, Any]]:
    key = _api_key()
    if not key:
        return None

    request_params = dict(params)
    request_params["key"] = key
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(f"{BASE_URL}/{path}", params=request_params)
        if resp.status_code in (400, 403, 404):
            return None
        resp.raise_for_status()
        payload = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.info("Google Civic request failed (%s)", type(exc).__name__)
        return None
    return payload if isinstance(payload, dict) else None


def _normalize_location(location: dict[str, Any]) -> dict[str, Any]:
    address = location.get("address") if isinstance(location.get("address"), dict) else {}
    return {
        "name": location.get("name"),
        "address": {
            "line1": address.get("line1"),
            "city": address.get("city"),
            "state": address.get("state"),
            "zip": address.get("zip"),
        },
        "polling_hours": location.get("pollingHours"),
        "notes": location.get("notes"),
        "sources": location.get("sources") if isinstance(location.get("sources"), list) else [],
    }


def _locations(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    values = payload.get(key)
    if not isinstance(values, list):
        return []
    return [_normalize_location(v) for v in values if isinstance(v, dict)]


async def get_voter_info(address: str) -> Optional[dict[str, Any]]:
    payload = await _get_json("voterinfo", {"address": address})
    if payload is None:
        return None

    election = payload.get("election") if isinstance(payload.get("election"), dict) else {}
    return {
        "election": {
            "id": election.get("id"),
            "name": election.get("name"),
            "date": election.get("electionDay"),
        },
        "polling_locations": _locations(payload, "pollingLocations"),
        "early_vote_sites": _locations(payload, "earlyVoteSites"),
        "dropoff_locations": _locations(payload, "dropOffLocations"),
        "source": "https://developers.google.com/civic-information",
    }


async def get_divisions(address: str) -> list[str]:
    payload = await _get_json("voterinfo", {"address": address})
    if payload is None:
        return []

    contests = payload.get("contests")
    if not isinstance(contests, list):
        return []

    division_ids: set[str] = set()
    for contest in contests:
        if not isinstance(contest, dict):
            continue
        district = contest.get("district")
        if not isinstance(district, dict):
            continue
        district_id = district.get("id")
        if isinstance(district_id, str) and district_id:
            division_ids.add(district_id)
    return sorted(division_ids)
