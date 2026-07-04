"""FastAPI backend for the Texas voter-info tool.

Built PRECOMPUTE-FIRST: everything is served from local data (SQLite/JSON
under data/tx/, written by other agents) via app/datastore.py, the only
data-access layer. Live network calls happen only where unavoidable:
  - Census geocoder, to turn an address into CD/SD/HD districts (cached
    after the first lookup, in data/cache.db).
  - OpenRouter (via app/insights.py), only as a fallback when a race has no
    precomputed insights file AND OPENROUTER_API_KEY is set.

Endpoints:
  GET  /                -> app/static/index.html
  GET  /healthz         -> Railway healthcheck + data-load status
  GET  /api/ballot      -> geocode (cached) + datastore.get_ballot
  POST /api/insights    -> cached insights first, live OpenRouter fallback
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app import datastore, insights

load_dotenv()

APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"

CENSUS_GEOCODER_URL = "https://geocoding.geo.census.gov/geocoder/geographies/onelineaddress"
GEOCODER_TIMEOUT_SECONDS = 8.0

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")

app = FastAPI(title="TX Voter Info API")


# ---------------------------------------------------------------------------
# GET / -> static index (written by the frontend agent)
# ---------------------------------------------------------------------------


@app.get("/")
def read_index() -> FileResponse:
    return FileResponse(str(STATIC_DIR / "index.html"))


# ---------------------------------------------------------------------------
# GET /healthz -> Railway healthcheck
# ---------------------------------------------------------------------------


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    s = datastore.stats()
    return {
        "status": "ok",
        "data_loaded": s["data_loaded"],
        "races": s["races"],
        "candidates": s["candidates"],
        "insights_cached": s["insights_cached"],
    }


# ---------------------------------------------------------------------------
# GET /api/ballot?address=...
# ---------------------------------------------------------------------------


def _district_number(geoid: str) -> Optional[int]:
    """Strip the 2-digit state FIPS prefix from a Census district GEOID and
    return the remaining digits as an int (drops leading zeros)."""
    if not geoid or len(geoid) <= 2:
        return None
    tail = geoid[2:]
    if not tail.isdigit():
        return None
    return int(tail)


def _extract_districts(geographies: dict[str, Any]) -> dict[str, Optional[str]]:
    districts: dict[str, Optional[str]] = {"cd": None, "sd": None, "hd": None, "county": None}

    cd_list = geographies.get("119th Congressional Districts") or []
    if cd_list:
        num = _district_number(cd_list[0].get("GEOID", ""))
        if num is not None:
            districts["cd"] = f"TX-{num:02d}"

    sd_list = geographies.get("2024 State Legislative Districts - Upper") or []
    if sd_list:
        num = _district_number(sd_list[0].get("GEOID", ""))
        if num is not None:
            districts["sd"] = f"SD-{num}"

    hd_list = geographies.get("2024 State Legislative Districts - Lower") or []
    if hd_list:
        num = _district_number(hd_list[0].get("GEOID", ""))
        if num is not None:
            districts["hd"] = f"HD-{num}"

    county_list = geographies.get("Counties") or []
    if county_list:
        districts["county"] = county_list[0].get("NAME")

    return districts


async def _live_geocode(address: str) -> dict[str, Any]:
    """Call the Census geocoder. Raises HTTPException on any failure path
    (down/timeout, no match, non-TX match) per the project's error contract."""
    params = {
        "address": address,
        "benchmark": "Public_AR_Current",
        "vintage": "Current_Current",
        "format": "json",
    }
    try:
        async with httpx.AsyncClient(timeout=GEOCODER_TIMEOUT_SECONDS) as client:
            resp = await client.get(CENSUS_GEOCODER_URL, params=params)
            resp.raise_for_status()
    except (httpx.TimeoutException, httpx.HTTPError):
        raise HTTPException(status_code=503, detail="District lookup unavailable, try again")

    try:
        payload = resp.json()
    except ValueError:
        raise HTTPException(status_code=503, detail="District lookup unavailable, try again")

    matches = (payload.get("result") or {}).get("addressMatches") or []
    if not matches:
        raise HTTPException(
            status_code=422,
            detail="We couldn't match that address. Please check it and try again (include city, state, ZIP).",
        )

    match = matches[0]
    address_components = match.get("addressComponents") or {}
    state = (address_components.get("state") or "").upper()
    if state != "TX":
        raise HTTPException(status_code=400, detail="This demo covers Texas addresses")

    geographies = match.get("geographies") or {}
    districts = _extract_districts(geographies)
    return {
        "matched_address": match.get("matchedAddress"),
        "districts": districts,
    }


@app.get("/api/ballot")
async def get_ballot(address: str = Query(..., min_length=3)) -> dict[str, Any]:
    cached = datastore.geocode_cache_get(address)
    if cached is not None:
        matched_address = cached["matched_address"]
        districts = {
            "cd": cached["cd"],
            "sd": cached["sd"],
            "hd": cached["hd"],
            "county": cached["county"],
        }
    else:
        geo = await _live_geocode(address)
        matched_address = geo["matched_address"]
        districts = geo["districts"]
        datastore.geocode_cache_put(
            address,
            cd=districts.get("cd"),
            sd=districts.get("sd"),
            hd=districts.get("hd"),
            county=districts.get("county"),
            matched_address=matched_address,
        )

    races = datastore.get_ballot(cd=districts.get("cd"), sd=districts.get("sd"), hd=districts.get("hd"))

    response: dict[str, Any] = {
        "matched_address": matched_address,
        "districts": districts,
        "races": races,
    }
    if datastore.data_is_pending():
        response["warning"] = "data_pending: race/candidate data not yet loaded for this district"
    return response


# ---------------------------------------------------------------------------
# POST /api/insights {profile, race_id}
# ---------------------------------------------------------------------------


class InsightsRequest(BaseModel):
    profile: dict[str, Any] = {}
    race_id: str


def _profile_archetype(profile: dict[str, Any]) -> str:
    """Deterministic profile -> archetype mapping, in precedence order."""
    if profile.get("veteran"):
        return "veteran"
    if profile.get("small_business_owner") or profile.get("small_business"):
        return "small_business_owner"
    if profile.get("student"):
        return "student"

    coverage = str(profile.get("health_coverage") or "").strip().lower()
    if coverage in ("aca", "uninsured"):
        return "healthcare_aca_or_uninsured"

    age_bracket = str(profile.get("age_bracket") or "")
    is_65_plus = "65" in age_bracket or "65+" in age_bracket
    if coverage == "medicare" or is_65_plus:
        return "medicare_retiree"

    if profile.get("kids_public_school"):
        return "homeowner_parent"

    if profile.get("renter"):
        age_num = _parse_age_lower_bound(age_bracket)
        if age_num is not None and age_num < 40:
            return "renter_young_worker"

    occupation = str(profile.get("occupation") or "").strip().lower()
    if occupation and any(kw in occupation for kw in ("farm", "ranch", "agri")):
        return "rural_agriculture"

    return "base"


def _parse_age_lower_bound(age_bracket: str) -> Optional[int]:
    """Best-effort parse of an age bracket string's lower bound, e.g. '25-34' -> 25,
    'under 25' -> 0. Returns None if unparseable (never invents an age)."""
    import re

    if not age_bracket:
        return None
    nums = re.findall(r"\d+", age_bracket)
    if not nums:
        return None
    return int(nums[0])


def _select_cached_bullets(cached: dict[str, Any], archetype: str) -> dict[str, Any]:
    """Cached insight files are expected to key candidate bullet-lists by
    archetype, e.g. {"candidates": {cid: {"base": [...], "veteran": [...]}}}.
    Falls back gracefully to a flat (non-archetype-keyed) shape if that's what
    the precompute agent produced, and to 'base' if the requested archetype
    key is absent."""
    candidates_block = cached.get("candidates", {}) if isinstance(cached, dict) else {}
    out: dict[str, Any] = {}
    for cid, entry in candidates_block.items():
        if isinstance(entry, dict):
            # archetype-keyed shape
            out[cid] = entry.get(archetype) or entry.get("base") or []
        elif isinstance(entry, list):
            # flat shape: same bullets regardless of archetype
            out[cid] = entry
        else:
            out[cid] = []
    return out


@app.post("/api/insights")
def post_insights(body: InsightsRequest) -> dict[str, Any]:
    race_id = body.race_id
    archetype = _profile_archetype(body.profile)

    cached = datastore.get_insights(race_id)
    if cached is not None:
        return {
            "mode": "cached",
            "archetype_used": archetype,
            "candidates": _select_cached_bullets(cached, archetype),
            "summary": cached.get("summary", ""),
            "caveats": cached.get("caveats", ""),
        }

    if OPENROUTER_API_KEY:
        race = datastore.get_race(race_id)
        if race is None:
            raise HTTPException(status_code=404, detail=f"Unknown race_id '{race_id}'")

        race_candidates = {}
        for cid in race.get("candidate_ids", []):
            candidate = datastore.get_candidate(cid)
            if candidate is not None:
                race_candidates[cid] = candidate
        if not race_candidates:
            return {"mode": "unavailable", "detail": "Insights not yet generated for this race"}

        try:
            result = insights.generate_insights(
                profile=body.profile,
                race=race,
                candidates=race_candidates,
                api_key=OPENROUTER_API_KEY,
            )
        except ValueError:
            raise HTTPException(status_code=502, detail="Could not generate insights right now, try again")
        except Exception:
            raise HTTPException(status_code=502, detail="Insight generation failed, try again")

        return {
            "mode": "live",
            "archetype_used": archetype,
            "candidates": result.get("candidates", {}),
            "summary": result.get("summary", ""),
            "caveats": result.get("caveats", ""),
        }

    return {"mode": "unavailable", "detail": "Insights not yet generated for this race"}
