"""FastAPI backend for the Texas voter-info tool.

Built PRECOMPUTE-FIRST: everything is served from precomputed data (Postgres
when DATABASE_URL is set, else the JSON files under data/tx/) via
app/datastore.py, the only data-access layer. Live network calls happen only
where unavoidable:
  - Census geocoder, to turn an address into CD/SD/HD districts (cached
    after the first lookup -- Postgres geocode_cache table, or the JSON file
    data/geocode_cache.json when Postgres isn't configured).
  - OpenRouter (via app/insights.py), only as a fallback when a race has no
    precomputed insights file AND OPENROUTER_API_KEY is set.
  - Google Civic Information API (via app/google_civic.py), OPTIONAL
    enrichment only, only when GOOGLE_CIVIC_API_KEY is set: adds
    `voting_info` (polling/early-vote/drop-off locations) and
    `division_check` (cross-validates our Census-derived district against
    Google's OCD division data) to /api/ballot. Absent that key, the
    response is byte-identical to before this feature existed.

Endpoints:
  GET  /                -> app/static/index.html
  GET  /healthz         -> Railway healthcheck + data-load status
  GET  /api/ballot      -> geocode (cached) + datastore.get_ballot
  POST /api/insights    -> cached insights first, live OpenRouter fallback
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from pathlib import Path
from typing import Any, Optional

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app import datastore, google_civic, insights
from app.middleware import (
    MAX_BODY_BYTES,
    BodySizeLimitMiddleware,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
)

logger = logging.getLogger(__name__)

load_dotenv()

APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"

CENSUS_GEOCODER_URL = "https://geocoding.geo.census.gov/geocoder/geographies/onelineaddress"
# Explicit per-phase timeouts (connect/read/write/pool) rather than one bare
# float, so the intent is unambiguous in code, not just "some number."
GEOCODER_TIMEOUT = httpx.Timeout(connect=5.0, read=8.0, write=8.0, pool=5.0)
GEOCODER_RETRY_BACKOFF_SECONDS = 1.0

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")

# Optional enrichment (app/google_civic.py). Unset (the default -- this key
# does not exist in .env yet) means /api/ballot's response is byte-identical
# to before this feature existed; see that module's docstring for the full
# degradation contract (no key, 403, quota, no coverage -> all silently
# omitted, never an error).
GOOGLE_CIVIC_API_KEY = os.environ.get("GOOGLE_CIVIC_API_KEY")

DEFAULT_CORS_ORIGINS = "http://localhost:3000,http://127.0.0.1:3000"

app = FastAPI(title="TX Voter Info API")

# Hardening middleware (body-size cap, per-IP rate limit, security headers).
# Registered before CORS so CORS ends up outermost (Starlette: the LAST
# middleware added is the OUTERMOST) -- see app/middleware.py's module
# docstring for why that ordering matters. None of this changes any
# endpoint's response shape; it's all cross-cutting request/response policy.
app.add_middleware(BodySizeLimitMiddleware, max_bytes=MAX_BODY_BYTES)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(SecurityHeadersMiddleware)


@app.exception_handler(Exception)
async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all for anything that isn't already an HTTPException (i.e. a
    genuine bug, not an expected 4xx). Logs method+path and the traceback
    server-side only -- never the query string or body, since an address or
    voter profile could be in either -- and the client only ever sees a
    generic, stack-trace-free 500."""
    logger.exception("Unhandled error handling %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "internal error"})


# civic-match (the product frontend) calls this API cross-origin from
# localhost:3000 in dev and its Railway/Vercel domain in prod. Registered
# LAST (outermost) so CORS headers still land on the 429/413 responses the
# hardening middleware above produces directly -- without them, a
# cross-origin `fetch` can't read those responses at all.
_cors_origins = [
    origin.strip()
    for origin in os.environ.get("CORS_ORIGINS", DEFAULT_CORS_ORIGINS).split(",")
    if origin.strip()
]
# Defense in depth: never pair a wildcard origin with credentials, even if
# CORS_ORIGINS is misconfigured to "*" -- browsers reject the combination
# anyway, but don't even offer it.
_cors_allow_credentials = "*" not in _cors_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=_cors_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)


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


MAX_ADDRESS_LENGTH = 200
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f]")
_ADDRESS_NOT_MATCHED_DETAIL = (
    "We couldn't match that address. Please check it and try again (include city, state, ZIP)."
)


def _validate_and_clean_address(address: str) -> str:
    """Surface-level hardening on the address query param, applied before
    any cache lookup or network call. Every rejection here reuses the exact
    friendly 422 message the geocoder's own "no match" path already returns,
    so the error envelope looks the same to the frontend regardless of which
    layer rejected the address -- never a pydantic-shaped list of field
    errors for this param."""
    if _CONTROL_CHAR_RE.search(address):
        raise HTTPException(status_code=422, detail=_ADDRESS_NOT_MATCHED_DETAIL)
    if len(address) > MAX_ADDRESS_LENGTH:
        raise HTTPException(status_code=422, detail=_ADDRESS_NOT_MATCHED_DETAIL)
    cleaned = address.strip()
    if len(cleaned) < 3:
        raise HTTPException(status_code=422, detail=_ADDRESS_NOT_MATCHED_DETAIL)
    return cleaned


async def _fetch_geocoder(client: httpx.AsyncClient, params: dict[str, Any]) -> httpx.Response:
    resp = await client.get(CENSUS_GEOCODER_URL, params=params)
    resp.raise_for_status()
    return resp


async def _live_geocode(address: str) -> dict[str, Any]:
    """Call the Census geocoder. Raises HTTPException on any failure path
    (down/timeout, no match, non-TX match) per the project's error contract.

    Resilience: a single retry after a short backoff on a *timeout*
    specifically (not on other HTTP errors) before giving up with the
    existing 503 -- the geocoder is occasionally slow rather than actually
    down, and one retry meaningfully cuts spurious 503s without materially
    slowing down the genuinely-down case."""
    if os.environ.get("GEOCODER_DISABLED") == "1":
        # Ops/test escape hatch only (unset in normal operation): forces the
        # same 503 a genuinely-down geocoder produces, so app/datastore.py's
        # seed/runtime cache layers can be proven sufficient on their own --
        # see pipeline/build_geocode_seed.py.
        raise HTTPException(status_code=503, detail="District lookup unavailable, try again")
    params = {
        "address": address,
        "benchmark": "Public_AR_Current",
        "vintage": "Current_Current",
        "format": "json",
    }
    try:
        async with httpx.AsyncClient(timeout=GEOCODER_TIMEOUT) as client:
            try:
                resp = await _fetch_geocoder(client, params)
            except httpx.TimeoutException:
                await asyncio.sleep(GEOCODER_RETRY_BACKOFF_SECONDS)
                resp = await _fetch_geocoder(client, params)
    except (httpx.TimeoutException, httpx.HTTPError):
        raise HTTPException(status_code=503, detail="District lookup unavailable, try again")

    try:
        payload = resp.json()
    except ValueError:
        raise HTTPException(status_code=503, detail="District lookup unavailable, try again")

    matches = (payload.get("result") or {}).get("addressMatches") or []
    if not matches:
        raise HTTPException(status_code=422, detail=_ADDRESS_NOT_MATCHED_DETAIL)

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


# ---------------------------------------------------------------------------
# OPTIONAL Google Civic enrichment (app/google_civic.py) -- adds `voting_info`
# and `division_check` to the /api/ballot response ONLY when
# GOOGLE_CIVIC_API_KEY is set. Every branch here is best-effort: any failure,
# including one we didn't anticipate, is caught and simply omits the field --
# it never turns a working ballot lookup into an error. Both fields are
# cached per normalized address alongside the Census geocode result (see
# datastore.geocode_cache_get_civic/put_civic) so a repeat address never
# re-hits the Civic API, including a repeat "no coverage yet" result.
# ---------------------------------------------------------------------------

_OCD_CD_RE = re.compile(r"/cd:(\d+)$")
_LABEL_CD_RE = re.compile(r"(\d+)$")


def _has_useful_voting_info(voting_info: dict[str, Any]) -> bool:
    """A voterInfoQuery hit with an election name/date or at least one
    location is worth showing; an all-empty normalized shape (Google has no
    data loaded for this address/date yet) is not -- the same underlying "no
    coverage" outcome as a None, just reached via a 200 instead of an error,
    so it's filtered here rather than in app/google_civic.py (which stays a
    faithful normalizer of whatever the API actually returned)."""
    election = voting_info.get("election") or {}
    if election.get("name") or election.get("date"):
        return True
    return any(voting_info.get(key) for key in ("polling_locations", "early_vote_sites", "dropoff_locations"))


def _cd_number_from_label(cd: Optional[str]) -> Optional[int]:
    """'TX-35' -> 35. None/unparseable -> None."""
    if not cd:
        return None
    match = _LABEL_CD_RE.search(cd)
    return int(match.group(1)) if match else None


def _ocd_cd_number(ocd_id: str) -> Optional[int]:
    """'ocd-division/country:us/state:tx/cd:35' -> 35. Non-CD divisions
    (state/county/place/etc.) -> None."""
    match = _OCD_CD_RE.search(ocd_id or "")
    return int(match.group(1)) if match else None


def _build_division_check(ocd_ids: list[str], our_cd: Optional[str]) -> Optional[dict[str, Any]]:
    """Cross-validate our Census-derived congressional district against
    Google's OCD division IDs for the same address -- a live check on our
    own resolver. Returns None (field omitted entirely) when there's nothing
    comparable on one side or the other, rather than fabricating a bool we
    can't back up: same "omit, never invent" rule the rest of this project's
    data follows (CLAUDE.md)."""
    our_num = _cd_number_from_label(our_cd)
    ocd_cd_numbers = {n for n in (_ocd_cd_number(oid) for oid in ocd_ids) if n is not None}
    if our_num is None or not ocd_cd_numbers:
        return None
    return {"consistent": our_num in ocd_cd_numbers, "ocd_ids": ocd_ids}


async def _civic_enrichment(address: str, our_cd: Optional[str]) -> dict[str, Optional[dict[str, Any]]]:
    """Fetch (or read from cache) {"voting_info", "division_check"} for one
    address. Never raises: app/google_civic.py's own functions already
    degrade to None on any failure, and this adds one more layer of
    try/except so a bug here can never turn a working /api/ballot call into
    a 500 via the catch-all exception handler above (which would otherwise
    mask it as a generic error with no races at all -- strictly worse than
    simply not showing the optional enrichment)."""
    cached = datastore.geocode_cache_get_civic(address)
    if cached is not None:
        return cached

    result: dict[str, Optional[dict[str, Any]]] = {"voting_info": None, "division_check": None}
    try:
        voting_info = await google_civic.get_voter_info(address)
        if voting_info and _has_useful_voting_info(voting_info):
            result["voting_info"] = voting_info

        ocd_ids = await google_civic.get_divisions(address)
        if ocd_ids:
            division_check = _build_division_check(ocd_ids, our_cd)
            if division_check is not None:
                result["division_check"] = division_check
    except Exception:  # noqa: BLE001 -- optional enrichment must never break /api/ballot
        logger.warning("Google Civic enrichment failed unexpectedly", exc_info=True)

    datastore.geocode_cache_put_civic(address, result)
    return result


@app.get("/api/ballot")
async def get_ballot(address: str = Query(...)) -> dict[str, Any]:
    address = _validate_and_clean_address(address)
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

    # Contract-additive only: response is byte-identical to before when
    # GOOGLE_CIVIC_API_KEY is unset (the default -- see CLAUDE.md § Data sources).
    if GOOGLE_CIVIC_API_KEY:
        civic = await _civic_enrichment(address, districts.get("cd"))
        if civic.get("voting_info") is not None:
            response["voting_info"] = civic["voting_info"]
        if civic.get("division_check") is not None:
            response["division_check"] = civic["division_check"]

    return response


# ---------------------------------------------------------------------------
# POST /api/insights {profile, race_id}
# ---------------------------------------------------------------------------


_RACE_ID_RE = re.compile(r"^[a-z0-9-]{1,64}$")
MAX_OCCUPATION_LENGTH = 120


class VoterProfile(BaseModel):
    """Typed, allow-listed voter profile. Unknown keys are silently dropped
    (extra="ignore") rather than rejected, so a frontend sending a stray or
    future field never breaks the request. Known keys are the documented
    profile fields (CLAUDE.md / schema.md) plus the two loose legacy
    synonyms `_profile_archetype` below has always accepted
    (`small_business`, bare `renter`) -- kept explicit here so hardening
    doesn't silently start dropping them for an existing caller relying on
    that leniency."""

    model_config = ConfigDict(extra="ignore")

    occupation: Optional[str] = None
    age_bracket: Optional[str] = None
    income_bracket: Optional[str] = None
    housing: Optional[str] = None
    kids_public_school: Optional[bool] = None
    health_coverage: Optional[str] = None
    veteran: Optional[bool] = None
    small_business_owner: Optional[bool] = None
    student: Optional[bool] = None
    # legacy/loose synonyms -- see _profile_archetype below
    small_business: Optional[bool] = None
    renter: Optional[bool] = None

    @field_validator("occupation")
    @classmethod
    def _cap_occupation_length(cls, v: Optional[str]) -> Optional[str]:
        return v if v is None else v[:MAX_OCCUPATION_LENGTH]


class InsightsRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    profile: VoterProfile = Field(default_factory=VoterProfile)
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

    housing = str(profile.get("housing") or "").strip().lower()
    is_renter = housing == "renter" or bool(profile.get("renter"))  # "renter" bool kept for legacy callers
    if is_renter:
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
    """Select the {candidates, summary, caveats, horizons} block to serve
    from a cached insight file.

    Actual on-disk shape (data/tx/insights/{race_id}.json):
        {race_id, generated_at,
         "base": {"candidates": {cid: [{text, source}, ...]}, "summary", "caveats",
                   "horizons": {cid: {"now": [...], "long_term": [...]}}},
         "archetypes": {archetype_key: {"candidates": {...}, "summary", "caveats",
                                          "horizons": {...}}, ...}}
    ("horizons" is optional per block -- older/unmigrated files simply omit it.)

    Selection: the requested archetype's block if archetype != 'base' and
    that key is present under "archetypes", else the "base" block. Falls back
    defensively to a flat/legacy top-level {"candidates", "summary",
    "caveats"} shape so an unexpected file never crashes the request.
    "horizons" is selected from that same block, except it falls back to
    base's "horizons" specifically when the selected archetype block has none
    of its own (even though its candidates/summary/caveats did resolve).
    """
    if not isinstance(cached, dict):
        return {"candidates": {}, "summary": "", "caveats": ""}

    base_block = cached.get("base")
    archetypes_block = cached.get("archetypes")

    block: Optional[dict[str, Any]] = None
    if archetype != "base" and isinstance(archetypes_block, dict):
        candidate_block = archetypes_block.get(archetype)
        if isinstance(candidate_block, dict):
            block = candidate_block
    if block is None and isinstance(base_block, dict):
        block = base_block

    if block is None:
        # Defensive fallback: an unexpected/legacy flat shape.
        block = cached

    candidates_field = block.get("candidates", {})

    # Consequence horizons: sibling of candidates/summary/caveats on the same
    # block. Same selection as above picked the block (archetype's if it has
    # one, else base); horizons additionally falls back per-field -- an
    # archetype block that has bullets but no horizons of its own still
    # inherits base's horizons rather than serving none.
    horizons_field = block.get("horizons")
    if not isinstance(horizons_field, dict):
        horizons_field = None
    if horizons_field is None and block is not base_block and isinstance(base_block, dict):
        fallback_horizons = base_block.get("horizons")
        if isinstance(fallback_horizons, dict):
            horizons_field = fallback_horizons
    if horizons_field is None:
        horizons_field = {}

    return {
        "candidates": candidates_field if isinstance(candidates_field, dict) else {},
        "summary": block.get("summary", ""),
        "caveats": block.get("caveats", ""),
        "horizons": horizons_field,
    }


@app.post("/api/insights")
def post_insights(body: InsightsRequest) -> dict[str, Any]:
    race_id = body.race_id
    if not _RACE_ID_RE.match(race_id):
        # Wrong shape entirely (injection-ish strings, wildly oversized,
        # unexpected characters) is treated the same as "no such race": 404,
        # and the raw value is never echoed back into the response.
        raise HTTPException(status_code=404, detail="Unknown race_id")

    profile = body.profile.model_dump(exclude_none=True)
    archetype = _profile_archetype(profile)

    cached = datastore.get_insights(race_id)
    if cached is not None:
        selected = _select_cached_bullets(cached, archetype)
        return {
            "mode": "cached",
            "archetype_used": archetype,
            "candidates": selected["candidates"],
            "summary": selected["summary"],
            "caveats": selected["caveats"],
            "horizons": selected.get("horizons", {}),
        }

    # Validate the race actually exists regardless of whether the live
    # OpenRouter path is available below, so a well-formed but unknown
    # race_id always 404s instead of that only being reachable when
    # OPENROUTER_API_KEY happens to be set.
    race = datastore.get_race(race_id)
    if race is None:
        raise HTTPException(status_code=404, detail=f"Unknown race_id '{race_id}'")

    if OPENROUTER_API_KEY:
        race_candidates = {}
        for cid in race.get("candidate_ids", []):
            candidate = datastore.get_candidate(cid)
            if candidate is not None:
                race_candidates[cid] = candidate
        if not race_candidates:
            return {"mode": "unavailable", "detail": "Insights not yet generated for this race"}

        try:
            result = insights.generate_insights(
                profile=profile,
                race=race,
                candidates=race_candidates,
                api_key=OPENROUTER_API_KEY,
            )
        except ValueError:
            raise HTTPException(status_code=502, detail="Could not generate insights right now, try again")
        except Exception:
            raise HTTPException(status_code=502, detail="Insight generation failed, try again")

        # Write-through cache: persist this live generation (Postgres if
        # live, else data/tx/insights/{race_id}.json) so the next request
        # for this (race_id, archetype) is served from cache instead of
        # calling the LLM again. Best-effort: a caching failure must never
        # turn an already-successful live generation into an error response.
        try:
            datastore.put_insight_block(race_id, archetype, result)
        except Exception:  # noqa: BLE001 -- best-effort write-through cache
            logger.warning("put_insight_block failed for race_id=%s archetype=%s", race_id, archetype, exc_info=True)

        return {
            "mode": "live",
            "archetype_used": archetype,
            "candidates": result.get("candidates", {}),
            "summary": result.get("summary", ""),
            "caveats": result.get("caveats", ""),
        }

    return {"mode": "unavailable", "detail": "Insights not yet generated for this race"}
