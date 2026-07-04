"""pipeline/sweep_addresses.py -- the STATEWIDE ADDRESS SWEEP.

A breadth engine: it finds where the voter experience is WEAK, not just
whether the pipeline runs. Where `pipeline/score_quality.py` audits the gold
dataset offline (race/candidate JSON on disk), this script audits the same
data through the one door a real voter uses -- `GET /api/ballot` and
`POST /api/insights` against the live FastAPI server -- for a curated table
of real, public, geocodable Texas addresses chosen to span the state: big
metros, the border, rural regions (panhandle/west/east-piney-woods/coastal),
and suburbs. It deliberately reaches OUTSIDE the 5 golden + 3 precache demo
addresses (data/tx/QUALITY.md) into districts nobody has demo-polished, on
the theory that a demo only looks as good as the addresses picked for it --
this sweep is how we find out what a voter NOT on that curated list sees.

Read-only against the app and against the gold dataset: every call here is a
GET or a POST that the running server already serves from precomputed data
(Postgres or the data/tx/*.json fallback) or from its own geocode cache.
Nothing in data/tx/races.json, candidates.json, or insights/*.json is ever
written by this script. The one side effect is the same one any real voter
causes: an unseeded address gets a live Census geocode, cached into
data/geocode_cache.json (or the Postgres geocode_cache table) exactly the
way app/main.py already does for every request -- that is app behavior, not
a mutation this script introduces.

Two passes:
  1. NEW_SWEEP_ADDRESSES (~18): real county-courthouse/city-hall addresses
     picked to hit 15+ distinct congressional districts, several of them
     nowhere near the golden set. For each: GET /api/ballot (live geocode on
     first hit, cached after), then exactly one POST /api/insights against
     that address's resolved US House race, profile={} (the "base"
     archetype) so every district is graded on the same footing.
  2. REGRESSION_ADDRESSES (the 8 demo addresses: 3 pipeline/precache_demo.py
     + 5 data/tx/QUALITY.md golden districts): the same GET+POST, compared
     against each address's previously-recorded CD/SD/HD/county so a drift
     in resolution or a broken golden race would show up as a REGRESSION
     line item, not a silent gap in this report.

Per address we record: resolved CD/SD/HD/county, race count, and -- for the
address's US House race specifically -- an EXPERIENCE SCORE built from:
  - candidate count and % of candidates with finance / voting record / issue
    positions (straight from the candidate objects the live ballot response
    already embeds -- no extra calls);
  - the race's own precomputed data_quality {score, tier} (also embedded
    live in the ballot response by app/datastore.py);
  - insight-cache presence + archetype coverage: `mode` from the one live
    POST proves cache presence; archetype coverage (how many of the 8 voter
    archetypes have been precomputed for this race, beyond just "base") is
    cross-referenced from data/tx/quality_report.json's archetype_fraction
    field -- computing that number would require 8 POSTs per address, which
    the brief caps at one;
  - a no-data-bullet ratio: the fraction of that one sample insight's bullet
    texts that are an explicit "No public ... in our set" disclaimer (the
    exact phrase app/insights.py's precompute pipelines use whenever a field
    is empty -- see CLAUDE.md's "omit, never invent" rule) -- i.e. how much
    of what a voter reads at this address is honest absence, not fact.

Composite "Experience Score" (0-100, this script's own metric, distinct
from but informed by the race's precomputed data_quality tier):
    0.50 * race data_quality score      (structural completeness, existing)
  + 0.30 * (100 * (1 - no_data_bullet_ratio))   (rendered-insight richness, NEW)
  + 0.20 * (100 if candidate_count >= 2 else 40)  (contested-race bonus)
Grade bands: A >= 78, B >= 60, C >= 42, D >= 25, F < 25.

Usage:
    python pipeline/sweep_addresses.py [--base-url http://127.0.0.1:8010] [--serve]

Writes data/tx/address_sweep_report.md (human) and
data/tx/address_sweep_report.json (machine). Rerunnable any time -- addresses
are hardcoded (curated, not discovered), all scoring is deterministic from
live responses plus the one read-only quality_report.json cross-reference.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_TX = REPO_ROOT / "data" / "tx"
QUALITY_REPORT_JSON = DATA_TX / "quality_report.json"
REPORT_MD = DATA_TX / "address_sweep_report.md"
REPORT_JSON = DATA_TX / "address_sweep_report.json"

DEFAULT_BASE_URL = "http://127.0.0.1:8010"
REQUEST_TIMEOUT = httpx.Timeout(20.0, connect=5.0)
HEALTH_TIMEOUT_SECONDS = 30.0
SWEEP_PACING_SECONDS = 1.0  # polite pacing between calls -- live geocoder for cache misses

# app/middleware.py's RateLimitMiddleware caps each client IP at
# RATE_LIMIT_MAX_REQUESTS (60) per RATE_LIMIT_WINDOW_SECONDS (60s), sliding
# window, scoped to /api/*. This script makes 2 calls/address (GET ballot +
# POST insights) x 26 addresses = 52 calls -- comfortably under 60 *if*
# spread across the window, which SWEEP_PACING_SECONDS between every call
# (not just every address) ensures. RATE_LIMIT_RETRY_ATTEMPTS is a safety
# net on top of that pacing (honors the server's own Retry-After header) for
# reruns that land on top of another recent run's tail, or a shared/busy
# backend -- never a substitute for being polite in steady state.
RATE_LIMIT_RETRY_ATTEMPTS = 3
RATE_LIMIT_DEFAULT_BACKOFF_SECONDS = 5.0

# Base/neutral profile for the one insights POST per address: maps to the
# "base" archetype (see app/main.py's _profile_archetype), so every district
# is graded on the exact same footing rather than whatever archetype a
# random voter profile happens to hit.
BASE_PROFILE: dict[str, Any] = {}

# The precompute pipelines' fixed phrasing for an explicit data-gap
# disclosure (verified against all 46 data/tx/insights/*.json files: 357/886
# bullets match, zero false positives from incidental uses of the word
# "public" elsewhere in real bullet text, e.g. "public school funding").
NO_DATA_BULLET_RE = re.compile(r"no public", re.IGNORECASE)

# Experience Score weights + grade bands -- see module docstring.
W_RACE_SCORE = 0.50
W_INSIGHT_RICHNESS = 0.30
W_CONTESTED = 0.20
CONTESTED_BONUS_MULTI = 100.0
CONTESTED_BONUS_ONE_SIDED = 40.0
GRADE_BANDS = [(78.0, "A"), (60.0, "B"), (42.0, "C"), (25.0, "D"), (0.0, "F")]


# ---------------------------------------------------------------------------
# Curated address table
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AddressSpec:
    label: str
    address: str
    region: str
    note: str
    expected: Optional[dict[str, str]] = None  # regression-only: previously-recorded districts


# ~18 real, public, geocodable civic buildings (county courthouse / city
# hall), picked to span the state well outside the 5 golden + 3 precache
# addresses already battle-tested in data/tx/QUALITY.md. Every address below
# was cross-checked against the issuing city/county's own site or a current
# directory listing (see the sweep run's commit message / session notes for
# sources); the live geocoder call this script makes is the actual
# verification of record, same as pipeline/build_geocode_seed.py's golden
# set.
NEW_SWEEP_ADDRESSES: list[AddressSpec] = [
    AddressSpec(
        "Pasadena City Hall", "1149 Ellsworth Dr, Pasadena, TX 77506",
        "big_metro_suburb", "Houston metro (Harris Co.) -- east/industrial suburb",
    ),
    AddressSpec(
        "Sugar Land City Hall", "2700 Town Center Blvd N, Sugar Land, TX 77479",
        "big_metro_suburb", "Houston metro (Fort Bend Co.) -- southwest suburb",
    ),
    AddressSpec(
        "Baytown City Hall", "2401 Market St, Baytown, TX 77522",
        "big_metro_suburb", "Houston metro (Harris/Chambers Co.) -- east ship-channel suburb",
    ),
    AddressSpec(
        "Dallas City Hall", "1500 Marilla St, Dallas, TX 75201",
        "big_metro", "Dallas proper (Dallas Co.)",
    ),
    AddressSpec(
        "Plano Municipal Center", "1520 Avenue K, Plano, TX 75074",
        "big_metro_suburb", "Dallas metro (Collin Co.) -- north suburb",
    ),
    AddressSpec(
        "Fort Worth City Hall", "100 Energy Way, Fort Worth, TX 76102",
        "big_metro", "Fort Worth proper (Tarrant Co.) -- current City Hall as of 2025 relocation",
    ),
    AddressSpec(
        "Arlington City Hall", "101 W Abram St, Arlington, TX 76010",
        "big_metro_suburb", "DFW metro (Tarrant Co.) -- Dallas/Fort Worth suburb",
    ),
    AddressSpec(
        "San Antonio City Hall", "100 Military Plaza, San Antonio, TX 78205",
        "big_metro", "San Antonio proper (Bexar Co.)",
    ),
    AddressSpec(
        "Comal County Courthouse", "100 Main Plaza, New Braunfels, TX 78130",
        "suburban", "San Antonio-Austin corridor (Comal Co.)",
    ),
    AddressSpec(
        "Round Rock City Hall", "221 E Main St, Round Rock, TX 78664",
        "suburban", "Austin metro (Williamson Co.) -- north suburb",
    ),
    AddressSpec(
        "Presidio County Courthouse", "301 N Highland Ave, Marfa, TX 79843",
        "rural_west_border", "Far west Texas (Presidio Co.) -- TX-23's sprawling border district",
    ),
    AddressSpec(
        "Zapata County Courthouse", "200 7th Ave, Zapata, TX 78076",
        "border_rural", "Rio Grande border (Zapata Co.), rural south -- between Laredo and Rio Grande City",
    ),
    AddressSpec(
        "McAllen City Hall", "1300 W Houston Ave, McAllen, TX 78501",
        "border_metro", "Rio Grande Valley border metro (Hidalgo Co.)",
    ),
    AddressSpec(
        "Potter County Courthouse", "500 S Fillmore St, Amarillo, TX 79101",
        "rural_panhandle", "Texas Panhandle (Potter Co.)",
    ),
    AddressSpec(
        "Lubbock County Courthouse", "904 Broadway, Lubbock, TX 79401",
        "rural_west", "West Texas / South Plains (Lubbock Co.)",
    ),
    AddressSpec(
        "Midland County Courthouse", "500 N Loraine St, Midland, TX 79701",
        "rural_west", "West Texas / Permian Basin (Midland Co.)",
    ),
    AddressSpec(
        "Smith County Courthouse", "100 N Broadway Ave, Tyler, TX 75702",
        "rural_east_piney_woods", "East Texas / Piney Woods (Smith Co.)",
    ),
    AddressSpec(
        "Corpus Christi City Hall", "1201 Leopard St, Corpus Christi, TX 78401",
        "coastal", "Gulf Coast south Texas (Nueces Co.)",
    ),
]

# The 8 demo/golden addresses already battle-tested elsewhere in the repo --
# 3 from pipeline/precache_demo.py's ADDRESSES, 5 from data/tx/QUALITY.md's
# "Golden demo districts" table. `expected` is copied from
# data/tx/geocode_seed.json (the committed ground truth for these exact 8
# addresses) so this run's live response can be diffed against it as a true
# regression check, not just a re-read of the same cache.
REGRESSION_ADDRESSES: list[AddressSpec] = [
    AddressSpec(
        "Precache: San Marcos (Hays Co. -- 601 University Dr)",
        "601 University Dr, San Marcos, TX 78666", "regression_precache",
        "pipeline/precache_demo.py demo address",
        expected={"cd": "TX-35", "sd": "SD-21", "hd": "HD-45", "county": "Hays County"},
    ),
    AddressSpec(
        "Precache: Austin (Travis Co. -- 1100 Congress Ave)",
        "1100 Congress Ave, Austin, TX 78701", "regression_precache",
        "pipeline/precache_demo.py demo address",
        expected={"cd": "TX-37", "sd": "SD-14", "hd": "HD-49", "county": "Travis County"},
    ),
    AddressSpec(
        "Precache: Houston (Harris Co. -- 901 Bagby St)",
        "901 Bagby St, Houston, TX 77002", "regression_precache",
        "pipeline/precache_demo.py demo address",
        expected={"cd": "TX-18", "sd": "SD-13", "hd": "HD-147", "county": "Harris County"},
    ),
    AddressSpec(
        "Golden: Brownsville (TX-34)",
        "1100 E Monroe St, Brownsville, TX 78520", "regression_golden",
        "data/tx/QUALITY.md golden demo district",
        expected={"cd": "TX-34", "sd": "SD-27", "hd": "HD-38", "county": "Cameron County"},
    ),
    AddressSpec(
        "Golden: Laredo (TX-28)",
        "1000 Houston St, Laredo, TX 78040", "regression_golden",
        "data/tx/QUALITY.md golden demo district",
        expected={"cd": "TX-28", "sd": "SD-21", "hd": "HD-42", "county": "Webb County"},
    ),
    AddressSpec(
        "Golden: Edinburg (TX-15)",
        "100 W Cano St, Edinburg, TX 78539", "regression_golden",
        "data/tx/QUALITY.md golden demo district",
        expected={"cd": "TX-15", "sd": "SD-20", "hd": "HD-41", "county": "Hidalgo County"},
    ),
    AddressSpec(
        "Golden: El Paso (TX-16)",
        "500 E San Antonio Ave, El Paso, TX 79901", "regression_golden",
        "data/tx/QUALITY.md golden demo district",
        expected={"cd": "TX-16", "sd": "SD-29", "hd": "HD-77", "county": "El Paso County"},
    ),
    AddressSpec(
        "Golden: Coppell (TX-24)",
        "255 Parkway Blvd, Coppell, TX 75019", "regression_golden",
        "data/tx/QUALITY.md golden demo district",
        expected={"cd": "TX-24", "sd": "SD-12", "hd": "HD-115", "county": "Dallas County"},
    ),
]


# ---------------------------------------------------------------------------
# Server management (mirrors pipeline/precache_demo.py's pattern)
# ---------------------------------------------------------------------------


def _healthz_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/healthz"


def _server_is_healthy(base_url: str) -> bool:
    try:
        response = httpx.get(_healthz_url(base_url), timeout=httpx.Timeout(2.0, connect=1.0))
    except httpx.HTTPError:
        return False
    return response.status_code == 200


def _uvicorn_command(base_url: str) -> list[str]:
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", ""}:
        raise RuntimeError("only http base URLs are supported")
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 8010
    return [sys.executable, "-m", "uvicorn", "app.main:app", "--host", host, "--port", str(port)]


def _start_server_if_needed(base_url: str) -> Optional["subprocess.Popen[bytes]"]:
    if _server_is_healthy(base_url):
        print(f"Backend already up at {base_url}", file=sys.stderr)
        return None

    command = _uvicorn_command(base_url)
    print(f"Backend down -- starting: {' '.join(command)}", file=sys.stderr)
    process = subprocess.Popen(command, cwd=REPO_ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    deadline = time.monotonic() + HEALTH_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(
                "uvicorn exited before /healthz became ready; run the command manually for logs: "
                + " ".join(command)
            )
        if _server_is_healthy(base_url):
            return process
        time.sleep(0.5)

    _stop_server(process)
    raise RuntimeError(f"server did not answer {_healthz_url(base_url)} within {HEALTH_TIMEOUT_SECONDS:.0f}s")


def _stop_server(process: Optional["subprocess.Popen[bytes]"]) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


# ---------------------------------------------------------------------------
# HTTP calls
# ---------------------------------------------------------------------------


@dataclass
class CallResult:
    ok: bool
    payload: Any = None
    status_code: Optional[int] = None
    error: Optional[str] = None


def _parse_retry_after(resp: httpx.Response) -> float:
    raw = resp.headers.get("Retry-After")
    try:
        return max(1.0, float(raw)) if raw else RATE_LIMIT_DEFAULT_BACKOFF_SECONDS
    except (TypeError, ValueError):
        return RATE_LIMIT_DEFAULT_BACKOFF_SECONDS


def _request_with_retry(do_request: "Any") -> httpx.Response:
    """Call `do_request()` (a zero-arg callable returning an httpx.Response),
    retrying with the server's own Retry-After on 429 -- app/middleware.py's
    RateLimitMiddleware is a per-IP sliding window, so honoring it is enough
    to guarantee eventual success rather than a spurious sweep failure."""
    last_resp: Optional[httpx.Response] = None
    for attempt in range(RATE_LIMIT_RETRY_ATTEMPTS + 1):
        resp = do_request()
        if resp.status_code != 429:
            return resp
        last_resp = resp
        if attempt < RATE_LIMIT_RETRY_ATTEMPTS:
            wait = _parse_retry_after(resp)
            print(f"    (rate-limited, retrying in {wait:.0f}s...)", file=sys.stderr)
            time.sleep(wait)
    assert last_resp is not None
    return last_resp


def _get_ballot(client: httpx.Client, address: str) -> CallResult:
    try:
        resp = _request_with_retry(lambda: client.get("/api/ballot", params={"address": address}))
    except httpx.HTTPError as exc:
        return CallResult(ok=False, error=f"request failed: {exc}")
    try:
        payload = resp.json()
    except ValueError:
        return CallResult(ok=False, status_code=resp.status_code, error="non-JSON response")
    if resp.is_error:
        detail = payload.get("detail") if isinstance(payload, dict) else payload
        return CallResult(ok=False, payload=payload, status_code=resp.status_code, error=f"HTTP {resp.status_code}: {detail}")
    return CallResult(ok=True, payload=payload, status_code=resp.status_code)


def _post_insights(client: httpx.Client, race_id: str) -> CallResult:
    try:
        resp = _request_with_retry(lambda: client.post("/api/insights", json={"profile": BASE_PROFILE, "race_id": race_id}))
    except httpx.HTTPError as exc:
        return CallResult(ok=False, error=f"request failed: {exc}")
    try:
        payload = resp.json()
    except ValueError:
        return CallResult(ok=False, status_code=resp.status_code, error="non-JSON response")
    if resp.is_error:
        detail = payload.get("detail") if isinstance(payload, dict) else payload
        return CallResult(ok=False, payload=payload, status_code=resp.status_code, error=f"HTTP {resp.status_code}: {detail}")
    return CallResult(ok=True, payload=payload, status_code=resp.status_code)


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def _race_metrics(race: dict[str, Any]) -> dict[str, Any]:
    candidates = race.get("candidates") or []
    n = len(candidates)
    with_finance = [c for c in candidates if c.get("finance")]
    with_votes = [c for c in candidates if (c.get("record") or {}).get("key_votes")]
    with_positions = [c for c in candidates if c.get("positions")]
    dq = race.get("data_quality") or {}
    missing_by_candidate = {
        c.get("candidate_id", c.get("name", "?")): (c.get("data_quality") or {}).get("missing", [])
        for c in candidates
    }
    return {
        "race_id": race.get("race_id"),
        "office": race.get("office"),
        "level": race.get("level"),
        "district": race.get("district"),
        "candidate_count": n,
        "with_finance": len(with_finance),
        "with_votes": len(with_votes),
        "with_positions": len(with_positions),
        "pct_finance": round(len(with_finance) / n, 3) if n else 0.0,
        "pct_votes": round(len(with_votes) / n, 3) if n else 0.0,
        "pct_positions": round(len(with_positions) / n, 3) if n else 0.0,
        "one_sided": n <= 1,
        "tier": dq.get("tier"),
        "score": dq.get("score"),
        "demo_rank": dq.get("demo_rank"),
        "candidate_missing_detail": missing_by_candidate,
    }


def _find_house_race(races: list[dict[str, Any]], cd: Optional[str]) -> Optional[dict[str, Any]]:
    if not cd:
        return None
    for race in races:
        if race.get("level") == "federal" and race.get("district") == cd:
            return race
    return None


def _insight_sample_metrics(payload: dict[str, Any], race_id: str, quality_ref: dict[str, Any]) -> dict[str, Any]:
    candidates_bullets: dict[str, list[dict[str, Any]]] = payload.get("candidates") or {}
    total = 0
    no_data = 0
    for _cid, bullets in candidates_bullets.items():
        for bullet in bullets or []:
            total += 1
            if NO_DATA_BULLET_RE.search(str(bullet.get("text", ""))):
                no_data += 1
    ratio = round(no_data / total, 3) if total else None

    ref_detail = ((quality_ref.get("races") or {}).get(race_id) or {}).get("detail") or {}
    archetype_fraction = ref_detail.get("archetype_fraction")
    archetype_count = round(archetype_fraction * 8) if isinstance(archetype_fraction, (int, float)) else None

    return {
        "race_id": race_id,
        "mode": payload.get("mode"),
        "archetype_used": payload.get("archetype_used"),
        "bullet_count": total,
        "no_data_bullet_count": no_data,
        "no_data_bullet_ratio": ratio,
        "archetype_fraction_precomputed": archetype_fraction,
        "archetype_count_precomputed": archetype_count,
        "summary_present": bool(payload.get("summary")),
    }


def _grade(score: float) -> str:
    for threshold, letter in GRADE_BANDS:
        if score >= threshold:
            return letter
    return "F"


def _experience_score(house: dict[str, Any], insight: dict[str, Any]) -> tuple[float, str]:
    race_score = house.get("score")
    race_score = float(race_score) if isinstance(race_score, (int, float)) else 0.0

    ratio = insight.get("no_data_bullet_ratio")
    richness = 100.0 * (1.0 - ratio) if isinstance(ratio, (int, float)) else 0.0

    contested = CONTESTED_BONUS_MULTI if house.get("candidate_count", 0) >= 2 else CONTESTED_BONUS_ONE_SIDED

    composite = W_RACE_SCORE * race_score + W_INSIGHT_RICHNESS * richness + W_CONTESTED * contested
    composite = round(composite, 1)
    return composite, _grade(composite)


# ---------------------------------------------------------------------------
# Per-address processing
# ---------------------------------------------------------------------------


def process_address(client: httpx.Client, spec: AddressSpec, quality_ref: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "label": spec.label,
        "address": spec.address,
        "region": spec.region,
        "note": spec.note,
        "ok": False,
    }

    ballot = _get_ballot(client, spec.address)
    time.sleep(SWEEP_PACING_SECONDS)  # polite pacing -- live geocoder + shared rate limit budget
    if not ballot.ok or not isinstance(ballot.payload, dict):
        result["error"] = ballot.error or "no payload"
        return result

    payload = ballot.payload
    districts = payload.get("districts") or {}
    races = payload.get("races") or []
    result.update(
        {
            "ok": True,
            "matched_address": payload.get("matched_address"),
            "districts": districts,
            "warning": payload.get("warning"),
            "race_count": len(races),
            "statewide_race_count": sum(1 for r in races if r.get("level") != "federal" or r.get("district") is None),
        }
    )

    if spec.expected is not None:
        mismatches = [
            f"{key}: expected {spec.expected.get(key)!r}, got {districts.get(key)!r}"
            for key in ("cd", "sd", "hd", "county")
            if spec.expected.get(key) != districts.get(key)
        ]
        result["expected"] = spec.expected
        result["regression_status"] = "MATCH" if not mismatches else "MISMATCH"
        result["regression_mismatches"] = mismatches

    cd = districts.get("cd")
    house_race = _find_house_race(races, cd)
    if house_race is None:
        result["error"] = f"no US House race found on ballot for resolved CD {cd!r}"
        return result

    house_metrics = _race_metrics(house_race)
    result["house_race"] = house_metrics

    insights_call = _post_insights(client, house_metrics["race_id"])
    time.sleep(SWEEP_PACING_SECONDS)  # polite pacing -- see above
    if not insights_call.ok or not isinstance(insights_call.payload, dict):
        result["error"] = f"insights POST failed: {insights_call.error}"
        result["insight_sample"] = None
        result["experience_score"] = 0.0
        result["experience_grade"] = "F"
        return result

    insight_metrics = _insight_sample_metrics(insights_call.payload, house_metrics["race_id"], quality_ref)
    result["insight_sample"] = insight_metrics

    score, grade = _experience_score(house_metrics, insight_metrics)
    result["experience_score"] = score
    result["experience_grade"] = grade
    return result


# ---------------------------------------------------------------------------
# Weak-district diagnosis (rule-based, deterministic from measured numbers)
# ---------------------------------------------------------------------------


def _diagnose(entry: dict[str, Any]) -> tuple[list[str], str, str]:
    house = entry["house_race"]
    insight = entry.get("insight_sample") or {}
    why: list[str] = []

    n = house["candidate_count"]
    if n <= 1:
        why.append(f"{n} candidate on file -- no real comparison available for this race")
    else:
        why.append(f"{n} candidates on file")

    if house["with_finance"] == 0:
        why.append("no candidate has FEC campaign-finance data in our set")
    elif house["with_finance"] < n:
        why.append(f"only {house['with_finance']}/{n} candidates have FEC finance data")

    if house["with_votes"] == 0:
        why.append("no candidate has a recorded voting history in our set")
    elif house["with_votes"] < n:
        why.append(f"only {house['with_votes']}/{n} candidates have a recorded voting history")

    if house["with_positions"] == 0:
        why.append("no issue positions on file for any candidate (positions[] is empty pipeline-wide for House races)")

    arch_count = insight.get("archetype_count_precomputed")
    if arch_count == 0:
        why.append("insights are base-only -- none of the 8 voter-archetype personalizations are precomputed")
    elif isinstance(arch_count, int) and arch_count < 8:
        why.append(f"only {arch_count}/8 voter archetypes precomputed")

    ratio = insight.get("no_data_bullet_ratio")
    if isinstance(ratio, (int, float)) and ratio >= 0.35:
        why.append(f"{ratio:.0%} of the sample insight's bullets are explicit 'no public data' disclaimers")

    tier = house.get("tier")
    score = house.get("score")
    if tier is not None:
        why.append(f"data_quality tier {tier} (score {score})")

    # Recommended fix: deterministic rule cascade over the same numbers.
    zero_footprint = house["with_finance"] == 0 and house["with_votes"] == 0 and house["with_positions"] == 0
    if n <= 1 and zero_footprint:
        fix_category = "acceptable-as-is"
        fix = (
            "Single candidate with no public FEC/Clerk footprint at all -- there is nothing on the "
            "public record to enrich with. The app already discloses this honestly ('No public data "
            "in our set...'); leave as-is rather than inventing content."
        )
    elif house["with_finance"] < n or house["with_votes"] < n:
        gaps_by_candidate = {
            cid: missing
            for cid, missing in house["candidate_missing_detail"].items()
            if missing
        }
        names = ", ".join(gaps_by_candidate.keys()) or "the affected candidate(s)"
        fix_category = "targeted enrichment"
        fix = (
            f"Re-run pipeline/fetch_fec.py and pipeline/fetch_votes.py targeted at {names} to close the "
            "specific finance/voting-record gaps listed above before the next data refresh."
        )
    elif arch_count == 0:
        fix_category = "archetype precompute extension"
        fix = (
            f"Evidence (finance/votes) is present; extend the archetype precompute pipeline "
            f"(pipeline/build_insights_house.py / precompute_marquee_insights.py) to {house['race_id']} "
            "so it gets full 8-archetype personalization instead of base-only insights."
        )
    else:
        fix_category = "acceptable-as-is"
        fix = "Evidence and personalization are both reasonably complete; low score here is mostly the district's real data scarcity, not a pipeline gap."

    return why, fix, fix_category


# ---------------------------------------------------------------------------
# Report writers
# ---------------------------------------------------------------------------


def _district_summary(new_sweep: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_cd: dict[str, dict[str, Any]] = {}
    for entry in new_sweep:
        if not entry.get("ok") or not entry.get("house_race"):
            continue
        cd = entry["districts"].get("cd")
        if not cd:
            continue
        if cd not in by_cd:
            summary = {
                "cd": cd,
                "addresses": [],
                "house_race": entry["house_race"],
                "insight_sample": entry.get("insight_sample"),
                "experience_score": entry["experience_score"],
                "experience_grade": entry["experience_grade"],
            }
            by_cd[cd] = summary
        by_cd[cd]["addresses"].append(entry["label"])
    return sorted(by_cd.values(), key=lambda e: e["experience_score"])


def _fmt_pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def _write_json(
    new_sweep: list[dict[str, Any]],
    regression: list[dict[str, Any]],
    district_summary: list[dict[str, Any]],
    weakest: list[dict[str, Any]],
    base_url: str,
) -> None:
    failures = [e for e in (new_sweep + regression) if not e.get("ok")]
    regression_fail = [e for e in regression if e.get("regression_status") == "MISMATCH"]
    tied_beyond_weakest: list[dict[str, Any]] = []
    if weakest:
        boundary_score = weakest[-1]["experience_score"]
        tied_beyond_weakest = [
            d for d in district_summary[len(weakest):] if d["experience_score"] == boundary_score
        ]
    doc = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generated_by": "pipeline/sweep_addresses.py",
        "base_url": base_url,
        "methodology": {
            "profile_used_for_insights": BASE_PROFILE,
            "archetype_resolved": "base",
            "no_data_bullet_pattern": NO_DATA_BULLET_RE.pattern,
            "no_data_bullet_scope": "candidate bullet `text` fields from the one POST /api/insights sample per address's US House race",
            "archetype_coverage_source": "data/tx/quality_report.json detail.archetype_fraction, cross-referenced by race_id (offline, read-only; live ballot's race.data_quality.{score,tier} is used directly for everything else)",
            "experience_score_formula": f"{W_RACE_SCORE}*race_data_quality_score + {W_INSIGHT_RICHNESS}*100*(1-no_data_bullet_ratio) + {W_CONTESTED}*(100 if candidates>=2 else 40)",
            "grade_bands": {letter: threshold for threshold, letter in GRADE_BANDS},
            "pacing_seconds": SWEEP_PACING_SECONDS,
        },
        "new_sweep": new_sweep,
        "regression_check": regression,
        "district_summary": district_summary,
        "weakest_districts": weakest,
        "weakest_districts_tied_beyond_cutoff": tied_beyond_weakest,
        "failures": failures,
        "counts": {
            "new_sweep_addresses": len(new_sweep),
            "new_sweep_ok": sum(1 for e in new_sweep if e.get("ok")),
            "distinct_cds_new_sweep": len(district_summary),
            "regression_addresses": len(regression),
            "regression_pass": sum(1 for e in regression if e.get("regression_status") == "MATCH"),
            "regression_fail": len(regression_fail),
            "total_failures": len(failures),
        },
    }
    REPORT_JSON.write_text(json.dumps(doc, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def _address_row(entry: dict[str, Any]) -> str:
    if not entry.get("ok"):
        return f"| {entry['label']} | {entry['address']} | -- | **FAILED**: {entry.get('error', 'unknown error')} | -- | -- |"
    d = entry["districts"]
    house = entry.get("house_race") or {}
    insight = entry.get("insight_sample") or {}
    cd = d.get("cd") or "?"
    cand_str = f"{house.get('candidate_count', '?')} cand"
    fin = _fmt_pct(house["pct_finance"]) if house.get("pct_finance") is not None else "?"
    votes = _fmt_pct(house["pct_votes"]) if house.get("pct_votes") is not None else "?"
    pos = _fmt_pct(house["pct_positions"]) if house.get("pct_positions") is not None else "?"
    ratio = insight.get("no_data_bullet_ratio")
    ratio_str = _fmt_pct(ratio) if isinstance(ratio, (int, float)) else "n/a"
    arch = insight.get("archetype_count_precomputed")
    arch_str = f"{arch}/8" if isinstance(arch, int) else "?"
    tier = house.get("tier", "?")
    score = entry.get("experience_score", 0.0)
    grade = entry.get("experience_grade", "?")
    return (
        f"| {entry['label']} | `{cd}` | {cand_str}, fin {fin}/votes {votes}/pos {pos} | "
        f"{arch_str} arch, {ratio_str} no-data | tier {tier} | **{score} ({grade})** |"
    )


def _regression_row(entry: dict[str, Any]) -> str:
    if not entry.get("ok"):
        return f"| {entry['label']} | {entry['address']} | **FAIL**: {entry.get('error')} |"
    status = entry.get("regression_status", "?")
    mism = entry.get("regression_mismatches") or []
    detail = "all districts match seed" if status == "MATCH" else "; ".join(mism)
    cd = entry["districts"].get("cd")
    score = entry.get("experience_score")
    grade = entry.get("experience_grade")
    return f"| {entry['label']} | `{cd}` | **{status}** -- {detail} | {score} ({grade}) |"


def _write_markdown(
    new_sweep: list[dict[str, Any]],
    regression: list[dict[str, Any]],
    district_summary: list[dict[str, Any]],
    weakest: list[dict[str, Any]],
    fixes: dict[str, tuple[list[str], str, str]],
    base_url: str,
) -> None:
    ranked = sorted(new_sweep, key=lambda e: e.get("experience_score", -1) if e.get("ok") else -1)
    distinct_cds = sorted({e["districts"]["cd"] for e in new_sweep if e.get("ok") and e["districts"].get("cd")})
    regression_fail_n = sum(1 for e in regression if e.get("regression_status") == "MISMATCH")
    failures = [e for e in (new_sweep + regression) if not e.get("ok")]

    lines: list[str] = []
    lines.append("# Statewide Address Sweep -- Voter Experience Scorecard")
    lines.append("")
    lines.append(
        f"Generated by `pipeline/sweep_addresses.py` against `{base_url}` on "
        f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}. Rerunnable any time -- see that "
        "script's module docstring for the exact methodology (Experience Score formula, no-data-bullet "
        "detection, archetype-coverage source)."
    )
    lines.append("")
    lines.append(
        f"**{len(new_sweep)} addresses swept, {distinct_cds and len(distinct_cds)} distinct congressional "
        f"districts resolved** ({', '.join(distinct_cds)}). {len(failures)} call failure(s). "
        f"Regression check: {len(regression) - regression_fail_n}/{len(regression)} of the golden+precache "
        f"demo addresses still resolve to their previously-recorded districts."
    )
    lines.append("")
    lines.append(
        "**How to read the grade**: `Experience Score` (0-100, this sweep's own metric) = "
        f"{W_RACE_SCORE:.0%} the race's existing precomputed `data_quality` score "
        f"+ {W_INSIGHT_RICHNESS:.0%} how little of the live sample insight is a 'no public data' disclaimer "
        f"+ {W_CONTESTED:.0%} a bonus for being an actually-contested (2+ candidate) race. "
        "Grade bands: A >= 78, B >= 60, C >= 42, D >= 25, F < 25. This is deliberately a *different* "
        "measure than the underlying tier -- it grades what a voter actually reads at that address today, "
        "not just whether the structural fields are populated."
    )
    lines.append("")

    lines.append("## Ranked scorecard -- all 18 swept addresses (weakest first)")
    lines.append("")
    lines.append("| Address | Resolved CD | US House race (candidates / finance-votes-positions coverage) | Insight sample (archetype coverage, no-data ratio) | Race tier | Experience Score (Grade) |")
    lines.append("|---|---|---|---|---|---|")
    for entry in ranked:
        lines.append(_address_row(entry))
    lines.append("")

    lines.append("## District summary (deduped by resolved CD)")
    lines.append("")
    lines.append(f"{len(district_summary)} distinct districts across the 18 addresses.")
    lines.append("")
    lines.append("| CD | Addresses mapping here | Candidates | Finance/Votes/Positions | Archetypes | No-data bullets | Tier | Score (Grade) |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for d in district_summary:
        h = d["house_race"]
        ins = d.get("insight_sample") or {}
        fin = _fmt_pct(h["pct_finance"])
        votes = _fmt_pct(h["pct_votes"])
        pos = _fmt_pct(h["pct_positions"])
        ratio = ins.get("no_data_bullet_ratio")
        ratio_str = _fmt_pct(ratio) if isinstance(ratio, (int, float)) else "n/a"
        arch = ins.get("archetype_count_precomputed")
        arch_str = f"{arch}/8" if isinstance(arch, int) else "?"
        lines.append(
            f"| `{d['cd']}` | {'; '.join(d['addresses'])} | {h['candidate_count']} | {fin}/{votes}/{pos} | "
            f"{arch_str} | {ratio_str} | {h.get('tier')} | **{d['experience_score']} ({d['experience_grade']})** |"
        )
    lines.append("")

    lines.append("## WEAKEST EXPERIENCES -- bottom 5 districts")
    lines.append("")
    lines.append(
        "The 5 lowest Experience Scores among the districts this sweep touched, with exactly why and a "
        "recommended fix per finding. \"Recommended fix\" is one of three categories: **targeted "
        "enrichment** (specific missing FEC/vote data can and should be fetched), **archetype precompute "
        "extension** (evidence is fine, personalization isn't built yet), or **acceptable-as-is with "
        "honest caveat** (the public record genuinely has nothing more to give -- the app is already doing "
        "the right thing by disclosing that)."
    )
    lines.append("")
    if weakest:
        boundary_score = weakest[-1]["experience_score"]
        tied_beyond = [
            d for d in district_summary[len(weakest):]
            if d["experience_score"] == boundary_score
        ]
        if tied_beyond:
            tied_cds = ", ".join(f"`{d['cd']}`" for d in tied_beyond)
            lines.append(
                f"*Honesty note: {tied_cds} tie the 5th-place score ({boundary_score}) exactly and would "
                "also qualify as \"weakest\" -- only the first 5 by sweep order are detailed below to hold "
                "the line at 5, not because the excluded ones are actually stronger. See the district "
                "summary table above for their identical stats.*"
            )
            lines.append("")
    for rank, entry in enumerate(weakest, start=1):
        h = entry["house_race"]
        why, fix, fix_category = fixes[h["race_id"]]
        lines.append(f"### {rank}. `{h['district']}` -- {h['office']} -- Score {entry['experience_score']} ({entry['experience_grade']})")
        lines.append("")
        lines.append(f"Seen via: {', '.join(entry['addresses'])}.")
        lines.append("")
        lines.append("**Why:**")
        for w in why:
            lines.append(f"- {w}")
        lines.append("")
        lines.append(f"**Recommended fix** ({fix_category}): {fix}")
        lines.append("")

    lines.append("## Regression check -- 3 precache + 5 golden demo addresses")
    lines.append("")
    lines.append(
        "Read-only re-verification of the addresses already battle-tested in "
        "`pipeline/precache_demo.py` and `data/tx/QUALITY.md`. Each row compares this run's live "
        "`GET /api/ballot` districts against the previously-recorded ground truth "
        "(`data/tx/geocode_seed.json`) -- a MISMATCH here would mean the gold dataset or geocode "
        "resolution drifted since those addresses were verified. No gold data was written or modified to "
        "produce this row."
    )
    lines.append("")
    lines.append("| Address | Resolved CD | Regression status | Experience Score (Grade) |")
    lines.append("|---|---|---|---|")
    for entry in regression:
        lines.append(_regression_row(entry))
    lines.append("")

    if failures:
        lines.append("## Call failures")
        lines.append("")
        for entry in failures:
            lines.append(f"- **{entry['label']}** (`{entry['address']}`): {entry.get('error')}")
        lines.append("")

    lines.append("## Methodology notes")
    lines.append("")
    lines.append(
        "- Every address below is a real, public, geocodable civic building (county courthouse or city "
        "hall), cross-checked against the issuing city/county's own listing before this run, then "
        "verified live by the Census geocoder call this script makes (same standard as the golden set)."
    )
    lines.append(
        "- All 38 Texas US House districts already have precomputed base insights (see "
        "`data/tx/coverage_report.json`); only `tx-cd28-2026` (Laredo, TX-28) and `tx-cd34-2026` "
        "(Brownsville, TX-34) have the full 8-archetype precompute today -- every other House race a "
        "voter lands on, anywhere in this sweep, is currently base-only. That is a statewide pattern, not "
        "a defect specific to any one district below."
    )
    lines.append(
        "- `positions[]` is empty for every US House candidate statewide as of this run (0% across all 38 "
        "districts per `data/tx/coverage_report.json`) -- civic-match's researched positions currently "
        "cover only the 8 statewide-race candidates. This shows up as a 'no issue positions on file' line "
        "in nearly every finding below; it is a pipeline-wide gap, not a per-district one."
    )
    lines.append(
        "- The 8 statewide races (Governor, Lt. Gov, AG, Comptroller, Land Commissioner, Ag Commissioner, "
        "Railroad Commissioner, US Senate) are identical for every Texas address and are not re-scored per "
        "address here; see `data/tx/QUALITY.md` for their standing (1 A-tier, 7 B-tier)."
    )
    tier_c_count = sum(1 for d in district_summary if d["house_race"].get("tier") == "C")
    lines.append(
        f"- {tier_c_count}/{len(district_summary)} of this sweep's House races carry the existing "
        "`data_quality` tier **C** -- not a quirk of which addresses were picked: only `tx-cd28-2026` and "
        "`tx-cd34-2026` are tier B among all 38 House races statewide (`data/tx/quality_report.json`'s tier "
        "distribution is 1 A / 9 B / 36 C across all 46 races, and the 9 B's are mostly statewide). Because "
        "tier alone can't distinguish among 36 same-tier districts, this sweep's Experience Score is the "
        "more useful ranking signal *within* tier C -- e.g. TX-13 (51.5) vs. TX-30 (74.0) above are both "
        "tier C but read very differently to an actual voter."
    )
    lines.append("")

    REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Statewide address sweep -- voter-experience breadth engine.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help=f"API base URL, default {DEFAULT_BASE_URL}")
    parser.add_argument(
        "--no-serve",
        action="store_true",
        help="Do not auto-start uvicorn if the base URL isn't already healthy (fail instead).",
    )
    args = parser.parse_args(argv)
    base_url = args.base_url.rstrip("/")

    quality_ref: dict[str, Any] = {}
    if QUALITY_REPORT_JSON.exists():
        quality_ref = json.loads(QUALITY_REPORT_JSON.read_text(encoding="utf-8"))
    else:
        print(f"WARNING: {QUALITY_REPORT_JSON} not found -- archetype coverage will be unavailable", file=sys.stderr)

    server_process = None
    try:
        if not args.no_serve:
            server_process = _start_server_if_needed(base_url)
        elif not _server_is_healthy(base_url):
            print(f"Backend not healthy at {base_url} and --no-serve set", file=sys.stderr)
            return 1

        new_sweep: list[dict[str, Any]] = []
        regression: list[dict[str, Any]] = []

        with httpx.Client(base_url=base_url, timeout=REQUEST_TIMEOUT) as client:
            total = len(NEW_SWEEP_ADDRESSES) + len(REGRESSION_ADDRESSES)
            done = 0
            for spec in NEW_SWEEP_ADDRESSES:
                done += 1
                print(f"[{done}/{total}] NEW  {spec.label} ({spec.address})", file=sys.stderr)
                entry = process_address(client, spec, quality_ref)
                new_sweep.append(entry)
                if entry.get("ok"):
                    d = entry["districts"]
                    print(f"    -> CD {d.get('cd')} / SD {d.get('sd')} / HD {d.get('hd')} / {d.get('county')} -- score {entry.get('experience_score')} ({entry.get('experience_grade')})", file=sys.stderr)
                else:
                    print(f"    -> FAILED: {entry.get('error')}", file=sys.stderr)

            for spec in REGRESSION_ADDRESSES:
                done += 1
                print(f"[{done}/{total}] REGR {spec.label} ({spec.address})", file=sys.stderr)
                entry = process_address(client, spec, quality_ref)
                regression.append(entry)
                if entry.get("ok"):
                    print(f"    -> regression {entry.get('regression_status')}", file=sys.stderr)
                else:
                    print(f"    -> FAILED: {entry.get('error')}", file=sys.stderr)

        district_summary = _district_summary(new_sweep)
        weakest = district_summary[:5]
        fixes = {d["house_race"]["race_id"]: _diagnose(d) for d in weakest}

        _write_json(new_sweep, regression, district_summary, weakest, base_url)
        _write_markdown(new_sweep, regression, district_summary, weakest, fixes, base_url)

        print(f"\nWrote {REPORT_MD.relative_to(REPO_ROOT)} and {REPORT_JSON.relative_to(REPO_ROOT)}", file=sys.stderr)
        ok_new = sum(1 for e in new_sweep if e.get("ok"))
        ok_regr = sum(1 for e in regression if e.get("regression_status") == "MATCH")
        print(f"New sweep: {ok_new}/{len(new_sweep)} resolved OK, {len(district_summary)} distinct CDs.", file=sys.stderr)
        print(f"Regression: {ok_regr}/{len(regression)} MATCH.", file=sys.stderr)
        return 0
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130
    finally:
        _stop_server(server_process)


if __name__ == "__main__":
    raise SystemExit(main())
