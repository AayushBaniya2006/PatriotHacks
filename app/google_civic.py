"""Optional, gracefully-degrading client for the Google Civic Information API v2.

https://developers.google.com/civic-information

Scope (per the 2026-07-03 live endpoint probe -- data/endpoint_inventory.json,
"google-civic" entry, the ground truth for this module):
  - The `representatives` resource (representativeInfoByAddress/ByDivision)
    was shut down in 2025 -- its documentation page now 404s -- and MUST NOT
    be called.
  - `elections` and `voterInfoQuery` are confirmed alive right now.
  - The surviving `divisions` resource is a NAME/OCD-ID *search*
    (query="Travis County"), not an address lookup -- there is no live
    address-keyed division endpoint left post-shutdown. So get_divisions()
    below derives OCD division IDs for an address from voterInfoQuery's
    `contests[].district.id` field (the only surviving address-keyed source
    of division IDs), rather than calling a "divisionsByAddress" endpoint
    that no longer exists in the current API.

Everything here is OPTIONAL enrichment and must be invisible without a key:
  - Requires GOOGLE_CIVIC_API_KEY (a Google Cloud API key). Unset -> every
    public function returns None immediately, no network call, no log line.
  - Every other failure mode (bad/quota-exceeded key -> 403, malformed
    response, timeout, no election data loaded yet for Nov 2026 this far
    out) ALSO returns None -- this module never raises to its callers.
    Exactly one warning is logged per failing call; the address itself is
    never included in any log message (only the request path / exception
    type are).
  - 8-second timeout per request, one retry on a transient network error.

Public functions:
  get_voter_info(address, election_id=None) -> Optional[dict]
    Normalized shape (every list possibly empty):
      {"election": {"name": str|None, "date": str|None},
       "polling_locations": [{"name","address","hours"}, ...],
       "early_vote_sites": [...], "dropoff_locations": [...],
       "contests_present": bool,
       "source": "https://developers.google.com/civic-information"}
    Returns None on no-key / any failure.

  get_divisions(address) -> Optional[list[str]]
    OCD division IDs covering this address, e.g.
    ["ocd-division/country:us/state:tx/cd:35"]. Returns [] (not None) when
    the call succeeded but no contest data is loaded for this address yet --
    a legitimate "no coverage" outcome, distinct from None, which means the
    call itself failed or no key is configured.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://www.googleapis.com/civicinfo/v2"
REQUEST_TIMEOUT_SECONDS = 8.0
SOURCE_URL = "https://developers.google.com/civic-information"
TARGET_ELECTION_DAY = "2026-11-03"  # Nov 2026 general -- see CLAUDE.md scope

# In-process cache of GET /elections, for the life of the process -- avoids
# re-fetching the full elections list on every address lookup. Populated
# only on a successful fetch; a failed fetch is simply retried on the next
# call rather than being cached as a permanent "no elections" result.
_elections_cache: Optional[list[dict[str, Any]]] = None


def _api_key() -> Optional[str]:
    return os.environ.get("GOOGLE_CIVIC_API_KEY") or None


async def _get(client: httpx.AsyncClient, path: str, params: dict[str, Any]) -> Optional[dict[str, Any]]:
    """GET {BASE_URL}/{path}; one retry on a transient network error. Never
    raises -- returns None on any failure (bad key/403, quota, 5xx, timeout,
    unparseable JSON), after logging exactly one warning that never includes
    the request params (which carry the voter's address)."""
    last_exc: Optional[BaseException] = None
    for _ in range(2):
        try:
            resp = await client.get(f"{BASE_URL}/{path}", params=params)
            resp.raise_for_status()
            return resp.json()
        except (httpx.TimeoutException, httpx.HTTPError, ValueError) as exc:
            last_exc = exc
            continue
    logger.warning("Google Civic API request to /%s failed: %s", path, type(last_exc).__name__)
    return None


async def _get_elections(client: httpx.AsyncClient, api_key: str) -> Optional[list[dict[str, Any]]]:
    global _elections_cache
    if _elections_cache is not None:
        return _elections_cache
    data = await _get(client, "elections", {"key": api_key})
    if data is None:
        return None
    elections = data.get("elections")
    if not isinstance(elections, list):
        return None
    _elections_cache = elections
    return elections


def _select_target_election(elections: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """Prefer a Nov 2026 election scoped to Texas or nationwide; else the
    first exact electionDay match; else None. None is a legitimate, expected
    outcome this far from the election -- Google typically doesn't load a
    general election's VIP data until weeks out (see endpoint probe notes)."""
    day_matches = [e for e in elections if isinstance(e, dict) and e.get("electionDay") == TARGET_ELECTION_DAY]
    if not day_matches:
        return None
    for election in day_matches:
        ocd = str(election.get("ocdDivisionId") or "")
        if "state:tx" in ocd or ocd == "ocd-division/country:us":
            return election
    return day_matches[0]


def _format_location(loc: dict[str, Any]) -> dict[str, Optional[str]]:
    addr = (loc or {}).get("address") or {}
    line = ", ".join(p for p in (addr.get("line1"), addr.get("line2"), addr.get("line3")) if p)
    city_state = " ".join(p for p in (addr.get("city"), addr.get("state")) if p)
    if addr.get("zip"):
        city_state = f"{city_state} {addr['zip']}".strip()
    full_address = ", ".join(p for p in (line, city_state) if p) or None
    return {
        "name": addr.get("locationName"),
        "address": full_address,
        "hours": (loc or {}).get("pollingHours"),
    }


def _normalize_voter_info(data: dict[str, Any]) -> dict[str, Any]:
    election = data.get("election") or {}
    return {
        "election": {"name": election.get("name"), "date": election.get("electionDay")},
        "polling_locations": [_format_location(loc) for loc in (data.get("pollingLocations") or [])],
        "early_vote_sites": [_format_location(loc) for loc in (data.get("earlyVoteSites") or [])],
        "dropoff_locations": [_format_location(loc) for loc in (data.get("dropOffLocations") or [])],
        "contests_present": bool(data.get("contests")),
        "source": SOURCE_URL,
    }


async def _voter_info_raw(address: str, election_id: Optional[str]) -> Optional[dict[str, Any]]:
    """Shared HTTP path for get_voter_info/get_divisions: resolve a target
    election (unless one was given explicitly), then call voterInfoQuery.
    Returns the raw (un-normalized) API response, or None on any failure."""
    api_key = _api_key()
    if not api_key or not address:
        return None

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        target_election_id = election_id
        if target_election_id is None:
            elections = await _get_elections(client, api_key)
            if elections:
                target = _select_target_election(elections)
                if target is not None:
                    target_election_id = target.get("id")
            # No matching election found -> fall through and call
            # voterInfoQuery without an electionId; Google's API accepts
            # that and applies its own default election for the address.
            # A "no coverage yet" outcome from here on is expected, not a bug.

        params: dict[str, Any] = {"address": address, "key": api_key}
        if target_election_id:
            params["electionId"] = target_election_id

        return await _get(client, "voterinfo", params)


async def get_voter_info(address: str, election_id: Optional[str] = None) -> Optional[dict[str, Any]]:
    if not address:
        return None
    try:
        data = await _voter_info_raw(address, election_id)
    except Exception:  # noqa: BLE001 -- this module never raises to callers
        logger.warning("Google Civic voterInfoQuery failed unexpectedly")
        return None
    if data is None:
        return None
    try:
        return _normalize_voter_info(data)
    except Exception:  # noqa: BLE001 -- a malformed response shape must not raise
        logger.warning("Google Civic voterInfoQuery returned an unexpected response shape")
        return None


async def get_divisions(address: str) -> Optional[list[str]]:
    if not address:
        return None
    try:
        data = await _voter_info_raw(address, None)
    except Exception:  # noqa: BLE001
        logger.warning("Google Civic division lookup failed unexpectedly")
        return None
    if data is None:
        return None
    try:
        contests = data.get("contests") or []
        ocd_ids: list[str] = []
        for contest in contests:
            district = (contest or {}).get("district") or {}
            ocd_id = district.get("id")
            if ocd_id and ocd_id not in ocd_ids:
                ocd_ids.append(ocd_id)
        return ocd_ids
    except Exception:  # noqa: BLE001
        logger.warning("Google Civic division lookup returned an unexpected response shape")
        return None
