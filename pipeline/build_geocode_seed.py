#!/usr/bin/env python3
"""build_geocode_seed.py -- generate the committed geocode warm-seed layer.

Resolves TX districts (CD/SD/HD/county) for the 8 addresses the demo's
fallback path depends on -- the 3 precache addresses
(pipeline/precache_demo.py's ADDRESSES) plus the 5 QUALITY.md golden
demo-district addresses -- plus the 20 curated Austin/Central-Texas addresses
in AUSTIN_DEMO_ADDRESSES below (see data/tx/AUSTIN_DEMO.md) -- and writes
data/tx/geocode_seed.json: a small, git-committed, read-only warm layer that
app/datastore.py consults ahead of the live Census geocoder (see its
"Geocode cache" docstring section). This makes those addresses resolve
correctly even on a cold restart with an empty runtime cache and no network
access to the Census geocoder.

Contains no user data -- only our own demo/golden addresses, all real, public
civic buildings (courthouses / city halls / campuses / parks) already named
in QUALITY.md or data/tx/AUSTIN_DEMO.md.

Each address is resolved by, in order:
  1. Reusing an existing hit in the runtime cache (data/geocode_cache.json)
     if this machine already resolved it live before -- avoids a redundant
     hit on the free Census geocoder for addresses already warm.
  2. Otherwise, one live call to the Census geocoder -- same benchmark/
     vintage/layers app/main.py's _live_geocode uses, parsed the same way
     app/main.py's _extract_districts does (duplicated here, not imported,
     so this offline build script has no runtime dependency on app/main.py;
     mirrors pipeline/score_quality.py's own standalone geocode_cd, extended
     to the SD/HD/county layers this seed file also needs).

Usage:
    python3 pipeline/build_geocode_seed.py [--force]
        --force  re-resolve every address live, ignoring any runtime-cache hit.
"""

from __future__ import annotations

import argparse
import datetime
import importlib.util
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from types import ModuleType
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data" / "tx"
PRECACHE_DEMO_PATH = REPO_ROOT / "pipeline" / "precache_demo.py"
QUALITY_REPORT_PATH = DATA_DIR / "quality_report.json"
RUNTIME_CACHE_PATH = REPO_ROOT / "data" / "geocode_cache.json"
SEED_PATH = DATA_DIR / "geocode_seed.json"

CENSUS_GEOCODER_URL = "https://geocoding.geo.census.gov/geocoder/geographies/onelineaddress"

# Fallback golden-address list -- mirrors the committed data/tx/QUALITY.md
# snapshot and pipeline/demo_readiness_gate.py's FALLBACK_GOLDEN_ADDRESSES,
# used only if data/tx/quality_report.json is unavailable/unreadable.
FALLBACK_GOLDEN_ADDRESSES = [
    "1100 E Monroe St, Brownsville, TX 78520",
    "1000 Houston St, Laredo, TX 78040",
    "100 W Cano St, Edinburg, TX 78539",
    "500 E San Antonio Ave, El Paso, TX 79901",
    "255 Parkway Blvd, Coppell, TX 75019",
]

# 20 curated Austin/Central-Texas addresses (data/tx/AUSTIN_DEMO.md) -- real,
# public, geocodable civic buildings/campuses/landmarks picked because Travis
# County alone splits across several US House districts (TX-10, TX-17,
# TX-21, TX-31, TX-35, TX-37 verified below), so Austin demonstrates several
# different ballots from one metro area. Excludes "1100 Congress Ave, Austin,
# TX 78701" (Texas Capitol) and "601 University Dr, San Marcos, TX 78666"
# (San Marcos), both already covered above as a precache/golden address --
# adding them again here would just be a redundant re-resolve of the same
# normalized key. Verified live against the Census geocoder the same way as
# every other address in this file; each entry's resolved CD/SD/HD/county is
# recorded in data/tx/AUSTIN_DEMO.md.
AUSTIN_DEMO_ADDRESSES = [
    "301 W 2nd St, Austin, TX 78701",  # Austin City Hall (downtown, Travis Co)
    "110 Inner Campus Dr, Austin, TX 78712",  # UT Austin Main Building/Tower
    "10414 McKalla Pl, Austin, TX 78758",  # Q2 Stadium (Domain/North Austin)
    "900 Chicon St, Austin, TX 78702",  # Huston-Tillotson University (East Austin)
    "701 W Riverside Dr, Austin, TX 78704",  # Long Center for the Performing Arts (South Austin)
    "3600 Presidential Blvd, Austin, TX 78719",  # Austin-Bergstrom Intl Airport (SE Travis Co)
    "221 E Main St, Round Rock, TX 78664",  # Round Rock City Hall (Williamson Co)
    "450 Cypress Creek Rd, Cedar Park, TX 78613",  # Cedar Park City Hall (Williamson Co)
    "710 S Main St, Georgetown, TX 78626",  # Williamson County Courthouse (Georgetown)
    "1102 Lohmans Crossing Rd, Lakeway, TX 78734",  # Lakeway City Hall (west Travis Co, Hill Country)
    "105 E Eggleston St, Manor, TX 78653",  # Manor City Hall (east Travis Co)
    "201 E Pecan St, Pflugerville, TX 78660",  # Pflugerville City Hall (Travis Co)
    "511 Sportsplex Dr, Dripping Springs, TX 78620",  # Dripping Springs Ranch Park (Hays Co, Hill Country)
    "710 W Cesar Chavez St, Austin, TX 78701",  # Austin Central Library (downtown, Travis Co)
    "2100 Barton Springs Rd, Austin, TX 78704",  # Zilker Park (South Austin, Travis Co)
    "11410 Century Oaks Ter, Austin, TX 78758",  # The Domain (shopping/entertainment district, North Austin)
    "100 E Main St, Pflugerville, TX 78660",  # Pflugerville -- alternate downtown address (Travis Co)
    "808 Martin Luther King Jr St, Georgetown, TX 78626",  # Georgetown -- downtown/Williamson Co offices (alternate address)
    "630 E Hopkins St, San Marcos, TX 78666",  # San Marcos downtown square (Hays Co; distinct from the 601 University Dr precache address)
    "100 W Center St, Kyle, TX 78640",  # Kyle City Hall (Hays Co)
]


# ---------------------------------------------------------------------------
# Address list resolution -- both lists are read from their existing sources
# rather than re-hardcoded here, so this script can never silently drift from
# pipeline/precache_demo.py or the live quality report (same principle as
# pipeline/demo_readiness_gate.py's resolve_precache_addresses /
# resolve_golden_addresses, which this mirrors).
# ---------------------------------------------------------------------------


def _load_module(mod_name: str, path: Path) -> ModuleType:
    """Load a sibling pipeline script as a module by file path. There is no
    pipeline/__init__.py, so plain `import pipeline.x` isn't available."""
    spec = importlib.util.spec_from_file_location(mod_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load spec for {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(mod_name, None)
        raise
    return module


def resolve_precache_addresses() -> list[str]:
    mod = _load_module("seed_precache_demo", PRECACHE_DEMO_PATH)
    return list(mod.ADDRESSES)


def resolve_golden_addresses() -> list[str]:
    if QUALITY_REPORT_PATH.exists():
        try:
            with QUALITY_REPORT_PATH.open("r", encoding="utf-8") as f:
                report = json.load(f)
            golden = report.get("golden_demo_districts") or []
            out = [g["address"] for g in golden if isinstance(g, dict) and g.get("address")]
            if out:
                return out
            print(
                f"WARNING: {QUALITY_REPORT_PATH} has no usable golden_demo_districts entries; "
                "using fallback list",
                file=sys.stderr,
            )
        except (OSError, json.JSONDecodeError, KeyError) as exc:
            print(f"WARNING: could not read {QUALITY_REPORT_PATH} ({exc}); using fallback golden list", file=sys.stderr)
    else:
        print(f"WARNING: {QUALITY_REPORT_PATH} does not exist; using fallback golden list", file=sys.stderr)
    return list(FALLBACK_GOLDEN_ADDRESSES)


# ---------------------------------------------------------------------------
# Geocoding -- runtime-cache reuse first, one live Census call otherwise.
# ---------------------------------------------------------------------------


def _normalize_address(address: str) -> str:
    """Mirrors app/datastore.py's _normalize_address exactly -- the seed
    file must be keyed the same way so datastore.py's lookup is a plain dict
    get, never a second normalization scheme to keep in sync."""
    return re.sub(r"\s+", " ", address.strip().lower())


def _load_runtime_cache() -> dict[str, Any]:
    try:
        with RUNTIME_CACHE_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _district_number(geoid: str) -> Optional[int]:
    """Mirrors app/main.py's _district_number exactly."""
    if not geoid or len(geoid) <= 2:
        return None
    tail = geoid[2:]
    if not tail.isdigit():
        return None
    return int(tail)


def _extract_districts(geographies: dict[str, Any]) -> dict[str, Optional[str]]:
    """Mirrors app/main.py's _extract_districts exactly -- same layer names
    and GEOID slicing, so a seed entry is indistinguishable from one the live
    app would have produced for the same address."""
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


def _live_geocode(address: str) -> dict[str, Any]:
    """One direct call to the Census geocoder -- same benchmark/vintage/
    endpoint as app/main.py's _live_geocode, but synchronous + stdlib-only
    (urllib) since this is an offline build script, not a request handler."""
    params = {
        "address": address,
        "benchmark": "Public_AR_Current",
        "vintage": "Current_Current",
        "format": "json",
    }
    url = f"{CENSUS_GEOCODER_URL}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=15) as resp:
        payload = json.loads(resp.read().decode("utf-8"))

    matches = (payload.get("result") or {}).get("addressMatches") or []
    if not matches:
        raise ValueError(f"no address match for {address!r}")
    match = matches[0]
    address_components = match.get("addressComponents") or {}
    state = (address_components.get("state") or "").upper()
    if state != "TX":
        raise ValueError(f"{address!r} matched outside Texas (state={state!r})")

    districts = _extract_districts(match.get("geographies") or {})
    return {"matched_address": match.get("matchedAddress"), "districts": districts}


def resolve_one(address: str, runtime_cache: dict[str, Any], force: bool) -> dict[str, Any]:
    """Resolve one address's districts, reusing a runtime-cache hit unless
    --force was passed or the cached entry has no CD (incomplete)."""
    norm = _normalize_address(address)
    if not force:
        cached = runtime_cache.get(norm)
        if isinstance(cached, dict) and cached.get("cd"):
            print(f"  reuse (runtime cache): {address}", file=sys.stderr)
            return {
                "cd": cached.get("cd"),
                "sd": cached.get("sd"),
                "hd": cached.get("hd"),
                "county": cached.get("county"),
                "matched_address": cached.get("matched_address"),
            }

    print(f"  live geocoder: {address}", file=sys.stderr)
    geo = _live_geocode(address)
    districts = geo["districts"]
    return {
        "cd": districts.get("cd"),
        "sd": districts.get("sd"),
        "hd": districts.get("hd"),
        "county": districts.get("county"),
        "matched_address": geo.get("matched_address"),
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--force", action="store_true", help="re-resolve live even if already in the runtime cache")
    args = parser.parse_args(argv)

    addresses = resolve_precache_addresses() + resolve_golden_addresses() + AUSTIN_DEMO_ADDRESSES
    runtime_cache = _load_runtime_cache()
    seeded_at = datetime.date.today().isoformat()

    seed: dict[str, Any] = {}
    failures: list[str] = []
    print(f"Resolving {len(addresses)} demo addresses...", file=sys.stderr)
    for address in addresses:
        norm = _normalize_address(address)
        try:
            resolved = resolve_one(address, runtime_cache, args.force)
        except (urllib.error.URLError, OSError, ValueError, TimeoutError) as exc:
            print(f"  FAILED: {address}: {exc}", file=sys.stderr)
            failures.append(address)
            continue

        if not resolved.get("cd"):
            print(f"  WARNING: {address} resolved with no CD -- not seeding it", file=sys.stderr)
            failures.append(address)
            continue

        seed[norm] = {
            "cd": resolved["cd"],
            "sd": resolved["sd"],
            "hd": resolved["hd"],
            "county": resolved["county"],
            "matched_address": resolved["matched_address"],
            "seeded_at": seeded_at,
        }

    SEED_PATH.parent.mkdir(parents=True, exist_ok=True)
    with SEED_PATH.open("w", encoding="utf-8") as f:
        json.dump(seed, f, indent=2, sort_keys=True, ensure_ascii=False)
        f.write("\n")

    print(f"Wrote {len(seed)}/{len(addresses)} entries to {SEED_PATH.relative_to(REPO_ROOT)}", file=sys.stderr)
    if failures:
        print("Addresses NOT seeded:", file=sys.stderr)
        for address in failures:
            print(f"  - {address}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
