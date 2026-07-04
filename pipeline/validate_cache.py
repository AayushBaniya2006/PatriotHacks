#!/usr/bin/env python3
"""
validate_cache.py -- one-command cache-integrity check for all three cache
layers documented in data.md's "Cache robustness" section:

  1. Geocode cache (app/datastore.py): the committed seed
     (data/tx/geocode_seed.json) must cover every demo address -- the 3
     pipeline/precache_demo.py addresses plus the 5 QUALITY.md golden demo
     districts (mirrors pipeline/build_geocode_seed.py's own address-list
     resolution, so this can never silently drift from what that script
     actually seeds).
  2. Demo cache (data/demo_cache/**): every file must parse as JSON, and
     every race_id it references (a ballot.json's embedded races, or an
     insights_<race_id>.json's filename) must be a real race in the CURRENT
     gold dataset -- never a stale/renamed/deleted one.
  3. Insights cache (app/datastore.py::compute_inputs_hash +
     pipeline/load_postgres.py::_race_inputs_hash): the hash must be
     reproducible (same race, same call, twice, same digest) for every race,
     AND the two independent copies of the hashing algorithm must agree --
     a drift here would silently break the incremental-upsert hash gate
     load_postgres.py relies on to avoid clobbering a live write-through
     cached row.

No server, no database connection, no network -- pure filesystem + the
normal app/datastore.py JSON-fallback read path (or Postgres, if
DATABASE_URL happens to be set and reachable, exactly like the real app), so
this is safe and fast to run any time, including on a bare checkout with no
Postgres provisioned. Complements (does not replace)
pipeline/demo_readiness_gate.py, which additionally needs a live server and
checks live-content/informativeness, not just cache-layer integrity.

Usage:
    python3 pipeline/validate_cache.py

Prints one PASS/FAIL line per check (with up to 20 offending items listed on
a FAIL) and a final "CACHE VALIDATION: PASS"/"FAIL" verdict line. Exit code 0
on overall PASS, 1 otherwise.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import datastore  # noqa: E402

DATA_TX = ROOT / "data" / "tx"
RACES_JSON_PATH = DATA_TX / "races.json"
CANDIDATES_JSON_PATH = DATA_TX / "candidates.json"
GEOCODE_SEED_PATH = DATA_TX / "geocode_seed.json"
QUALITY_REPORT_PATH = DATA_TX / "quality_report.json"
DEMO_CACHE_DIR = ROOT / "data" / "demo_cache"
PRECACHE_DEMO_PATH = ROOT / "pipeline" / "precache_demo.py"
LOAD_POSTGRES_PATH = ROOT / "pipeline" / "load_postgres.py"

# Mirrors pipeline/build_geocode_seed.py's own FALLBACK_GOLDEN_ADDRESSES
# exactly -- used only if data/tx/quality_report.json is unavailable, same as
# that script and tests/test_e2e_demo.py's FALLBACK_GOLDEN.
FALLBACK_GOLDEN_ADDRESSES = [
    "1100 E Monroe St, Brownsville, TX 78520",
    "1000 Houston St, Laredo, TX 78040",
    "100 W Cano St, Edinburg, TX 78539",
    "500 E San Antonio Ave, El Paso, TX 79901",
    "255 Parkway Blvd, Coppell, TX 75019",
]

CheckResult = tuple[bool, list[str]]


def _load_module(mod_name: str, path: Path) -> ModuleType:
    """Load a sibling pipeline script as a module by file path -- mirrors the
    identical helper duplicated across pipeline/demo_readiness_gate.py,
    pipeline/build_geocode_seed.py, and tests/test_e2e_demo.py (there is no
    pipeline/__init__.py, so plain `import pipeline.x` isn't available)."""
    spec = importlib.util.spec_from_file_location(mod_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load spec for {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    return module


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def resolve_demo_addresses() -> list[str]:
    """3 precache + 5 golden addresses -- the exact set
    pipeline/build_geocode_seed.py seeds and tests/test_e2e_demo.py exercises."""
    precache_demo = _load_module("validate_cache_precache_demo", PRECACHE_DEMO_PATH)
    addresses = list(precache_demo.ADDRESSES)

    if QUALITY_REPORT_PATH.exists():
        try:
            report = _load_json(QUALITY_REPORT_PATH)
            golden = report.get("golden_demo_districts") or []
            golden_addrs = [g["address"] for g in golden if isinstance(g, dict) and g.get("address")]
            if golden_addrs:
                return addresses + golden_addrs
        except (OSError, json.JSONDecodeError, KeyError):
            pass
    return addresses + list(FALLBACK_GOLDEN_ADDRESSES)


# ---------------------------------------------------------------------------
# Check 1: geocode seed covers every demo address
# ---------------------------------------------------------------------------


def check_geocode_seed_coverage() -> CheckResult:
    if not GEOCODE_SEED_PATH.exists():
        return False, [f"{GEOCODE_SEED_PATH} does not exist -- run pipeline/build_geocode_seed.py"]
    try:
        seed = _load_json(GEOCODE_SEED_PATH)
    except (json.JSONDecodeError, OSError) as exc:
        return False, [f"{GEOCODE_SEED_PATH} does not parse: {exc}"]
    if not isinstance(seed, dict):
        return False, [f"{GEOCODE_SEED_PATH} is not a JSON object"]

    problems: list[str] = []
    for address in resolve_demo_addresses():
        norm = datastore._normalize_address(address)
        entry = seed.get(norm)
        if not isinstance(entry, dict) or not entry.get("cd"):
            problems.append(f"missing/incomplete geocode_seed.json entry for {address!r} (key={norm!r})")
    return (not problems), problems


# ---------------------------------------------------------------------------
# Check 2: every demo_cache file parses + matches a real, current race
# ---------------------------------------------------------------------------


def check_demo_cache_integrity() -> CheckResult:
    if not DEMO_CACHE_DIR.exists():
        return False, [f"{DEMO_CACHE_DIR} does not exist -- run pipeline/precache_demo.py"]
    files = sorted(p for p in DEMO_CACHE_DIR.rglob("*.json") if p.is_file())
    if not files:
        return False, [f"{DEMO_CACHE_DIR} contains no cache files -- run pipeline/precache_demo.py"]

    problems: list[str] = []
    for path in files:
        rel = path.relative_to(ROOT)
        try:
            doc = _load_json(path)
        except (json.JSONDecodeError, OSError) as exc:
            problems.append(f"{rel}: does not parse as JSON: {exc}")
            continue
        if not isinstance(doc, dict):
            problems.append(f"{rel}: top-level JSON is not an object")
            continue

        if path.name == "ballot.json":
            races = doc.get("races")
            if not isinstance(races, list) or not races:
                problems.append(f"{rel}: no races[] in cached ballot")
                continue
            for race in races:
                race_id = race.get("race_id") if isinstance(race, dict) else None
                if not race_id:
                    problems.append(f"{rel}: a race entry has no race_id")
                elif datastore.get_race(race_id) is None:
                    problems.append(f"{rel}: race_id {race_id!r} does not exist in the current gold dataset")
        elif path.name.startswith("insights_") and path.name.endswith(".json"):
            race_id = path.name[len("insights_") : -len(".json")]
            if datastore.get_race(race_id) is None:
                problems.append(f"{rel}: race_id {race_id!r} (from filename) does not exist in the current gold dataset")
            if "candidates" not in doc:
                problems.append(f"{rel}: cached insights response has no 'candidates' key")
        else:
            problems.append(f"{rel}: unrecognized demo_cache file naming pattern (not ballot.json or insights_*.json)")

    return (not problems), problems


# ---------------------------------------------------------------------------
# Check 3: inputs_hash is reproducible, and agrees with the independent
# pipeline/load_postgres.py copy of the same algorithm.
# ---------------------------------------------------------------------------


def check_inputs_hash_reproducible() -> CheckResult:
    if not RACES_JSON_PATH.exists() or not CANDIDATES_JSON_PATH.exists():
        return False, [f"{RACES_JSON_PATH} or {CANDIDATES_JSON_PATH} missing -- run pipeline/build_dataset.py"]
    try:
        races_doc = _load_json(RACES_JSON_PATH)
        candidates_doc = _load_json(CANDIDATES_JSON_PATH)
    except (json.JSONDecodeError, OSError) as exc:
        return False, [f"could not parse gold JSON: {exc}"]

    races = races_doc.get("races", []) if isinstance(races_doc, dict) else []
    if not races:
        return False, [f"{RACES_JSON_PATH} has no races"]

    try:
        load_postgres = _load_module("validate_cache_load_postgres", LOAD_POSTGRES_PATH)
    except Exception as exc:  # noqa: BLE001 -- report, don't crash the whole check suite
        return False, [f"could not load pipeline/load_postgres.py: {exc}"]

    races_by_id = {r["race_id"]: r for r in races if isinstance(r, dict) and r.get("race_id")}
    problems: list[str] = []
    for race_id, race in races_by_id.items():
        try:
            h1 = datastore.compute_inputs_hash(race_id)
            h2 = datastore.compute_inputs_hash(race_id)
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{race_id}: compute_inputs_hash raised: {exc}")
            continue
        if h1 != h2:
            problems.append(f"{race_id}: compute_inputs_hash not reproducible across two calls ({h1} != {h2})")
            continue
        h_loader = load_postgres._race_inputs_hash(race, candidates_doc)
        if h1 != h_loader:
            problems.append(
                f"{race_id}: app/datastore.py::compute_inputs_hash disagrees with "
                f"pipeline/load_postgres.py::_race_inputs_hash ({h1} != {h_loader})"
            )
    return (not problems), problems


CHECKS: list[tuple[str, "Any"]] = [
    ("geocode_seed_covers_demo_addresses", check_geocode_seed_coverage),
    ("demo_cache_parses_and_matches_races", check_demo_cache_integrity),
    ("inputs_hash_reproducible", check_inputs_hash_reproducible),
]


def main() -> int:
    overall = True
    for name, check in CHECKS:
        passed, problems = check()
        overall = overall and passed
        status = "PASS" if passed else "FAIL"
        print(f"[{status}] {name}")
        if not passed:
            for problem in problems[:20]:
                print(f"    - {problem}")
            if len(problems) > 20:
                print(f"    ... and {len(problems) - 20} more")

    print()
    print("CACHE VALIDATION:", "PASS" if overall else "FAIL")
    return 0 if overall else 1


if __name__ == "__main__":
    raise SystemExit(main())
