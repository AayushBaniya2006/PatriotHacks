#!/usr/bin/env python3
"""
demo_readiness_gate.py -- the pre-demo gate. Run this LAST, right before
going on stage (see DEMO_PLAYBOOK.md's setup checklist). Exits non-zero on
ANY failure, with precise per-check PASS/FAIL output.

Checks (each reported individually):

  0. Backend liveness -- if http://<base-url>/healthz isn't already
     answering, starts `uvicorn app.main:app --port <port>` in the
     background (nohup-style, left running for the demo -- this gate does
     NOT shut down a server it started) and waits for /healthz.

  1. Live /api/ballot, for the 3 precache addresses (imported directly from
     pipeline/precache_demo.py's ADDRESSES -- never duplicated/hardcoded, so
     the two scripts can never drift apart) AND the 5 current golden
     addresses (read live from data/tx/quality_report.json's
     golden_demo_districts, which pipeline/score_quality.py regenerates
     every pipeline run; falls back to the values committed in
     data/tx/QUALITY.md if that file is unavailable). For all 8 addresses:
       - HTTP 200
       - districts.cd matches that address's expected CD
       - every race's `candidates` field is a JSON array (never an object
         keyed by candidate_id -- the historical bug documented in
         schema.md's MIGRATION note)
       - every candidate has non-null/non-empty name, party, candidate_id

  2. Marquee insight completeness -- the 8 marquee (district-less
     statewide/US Senate) races plus tx-cd28-2026 and tx-cd34-2026: the
     base block and all 8 archetype blocks each have >=1 non-empty bullet
     per race candidate; every bullet has non-empty text AND source; no
     literal 'None' / 'null' / 'undefined' / '{' inside any bullet text.
     Consequence-horizons completeness (>=1 valid 'now' bullet per
     candidate, every block) is layered on top of that SAME check -- but
     only enforced if pipeline/validate_horizons.py exists in this
     checkout (feature-detected at runtime; an older checkout without the
     horizons agent's work landed is not penalized for a feature that
     doesn't exist yet).

  3. Attribution truth -- scans data/tx/insights/*.json directly (not via
     the API) for the literal substring "per FEC filings" inside any bullet
     belonging to a candidate whose data/tx/candidates.json finance.source
     contains "ethics.state.tx.us" (Texas Ethics Commission, not the FEC --
     a factual misattribution, not a wording nitpick).

  4. Freshness -- every file under data/demo_cache/** must have an mtime >=
     data/tx/candidates.json's mtime. If the gold dataset changed after the
     demo cache was captured, the cache is stale stage-crash insurance that
     would show pre-cleaning data if the live backend/network ever failed
     during the demo. Fix: rerun pipeline/precache_demo.py.

Usage:
    python3 pipeline/demo_readiness_gate.py [--base-url http://127.0.0.1:8010]

Exit 0 only if every single check passes.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path
from types import ModuleType
from typing import Any, Optional
from urllib.parse import urlparse

import httpx

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / "tx"
CANDIDATES_PATH = DATA_DIR / "candidates.json"
RACES_PATH = DATA_DIR / "races.json"
INSIGHTS_DIR = DATA_DIR / "insights"
QUALITY_REPORT_PATH = DATA_DIR / "quality_report.json"
DEMO_CACHE_DIR = ROOT / "data" / "demo_cache"
VALIDATE_HORIZONS_PATH = ROOT / "pipeline" / "validate_horizons.py"
PRECACHE_DEMO_PATH = ROOT / "pipeline" / "precache_demo.py"

DEFAULT_BASE_URL = "http://127.0.0.1:8010"
BACKEND_START_TIMEOUT_SECONDS = 30.0
REQUEST_TIMEOUT = httpx.Timeout(15.0, connect=5.0)
BACKEND_LOG_PATH = Path("/tmp/demo_readiness_gate_backend.log")

ARCHETYPE_KEYS = [
    "renter_young_worker",
    "homeowner_parent",
    "small_business_owner",
    "healthcare_aca_or_uninsured",
    "medicare_retiree",
    "veteran",
    "student",
    "rural_agriculture",
]
EXTRA_TARGET_RACE_IDS = {"tx-cd28-2026", "tx-cd34-2026"}
BAD_LITERAL_TOKENS = ["None", "null", "undefined", "{"]

# Ground truth for the 3 precache addresses' expected CD -- verified against
# data/demo_cache/*/ballot.json (itself captured from a live Census geocoder
# run) and mirrors the addresses in pipeline/precache_demo.py's ADDRESSES
# (imported dynamically below; this dict supplies ONLY the expected-CD
# ground truth, never the address strings themselves, so the two files
# cannot silently drift on the address text).
PRECACHE_EXPECTED_CD = {
    "601 University Dr, San Marcos, TX 78666": "TX-35",
    "1100 Congress Ave, Austin, TX 78701": "TX-37",
    "901 Bagby St, Houston, TX 77002": "TX-18",
}

# Fallback golden-address list, used only if data/tx/quality_report.json is
# missing/unreadable. Mirrors the committed data/tx/QUALITY.md snapshot.
FALLBACK_GOLDEN_ADDRESSES = [
    ("1100 E Monroe St, Brownsville, TX 78520", "TX-34"),
    ("1000 Houston St, Laredo, TX 78040", "TX-28"),
    ("100 W Cano St, Edinburg, TX 78539", "TX-15"),
    ("500 E San Antonio Ave, El Paso, TX 79901", "TX-16"),
    ("255 Parkway Blvd, Coppell, TX 75019", "TX-24"),
]


class GateFailure(Exception):
    pass


# ---------------------------------------------------------------------------
# Module loading helper (no pipeline/__init__.py exists, so plain `import
# pipeline.x` isn't available -- load by file path instead, exactly the way
# the stdlib intends for "import a script as a module without a package").
# ---------------------------------------------------------------------------


def _load_module(mod_name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(mod_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load spec for {path}")
    module = importlib.util.module_from_spec(spec)
    # Register in sys.modules BEFORE exec_module: precache_demo.py declares a
    # @dataclass, and the dataclasses machinery looks up cls.__module__ in
    # sys.modules while resolving it -- skipping this step raises a
    # confusing 'NoneType' object has no attribute '__dict__' deep inside
    # dataclasses, not an ImportError, so it's easy to miss.
    sys.modules[mod_name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(mod_name, None)
        raise
    return module


# ---------------------------------------------------------------------------
# 0. Backend liveness
# ---------------------------------------------------------------------------


def _healthz_ok(base_url: str) -> tuple[bool, Optional[dict[str, Any]]]:
    try:
        resp = httpx.get(f"{base_url.rstrip('/')}/healthz", timeout=httpx.Timeout(3.0, connect=2.0))
    except httpx.HTTPError:
        return False, None
    if resp.status_code != 200:
        return False, None
    try:
        return True, resp.json()
    except ValueError:
        return True, None


def ensure_backend_running(base_url: str) -> str:
    """Returns a human-readable status string. Raises GateFailure if the
    backend cannot be reached and cannot be started. Never stops a server it
    starts -- the whole point of this gate is that the backend is left
    ready to serve the actual demo."""
    ok, _ = _healthz_ok(base_url)
    if ok:
        return "already running"

    parsed = urlparse(base_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 8010
    cmd = [sys.executable, "-m", "uvicorn", "app.main:app", "--host", host, "--port", str(port)]
    print(f"Backend not reachable at {base_url}; starting: {' '.join(cmd)} (log: {BACKEND_LOG_PATH})")

    with open(BACKEND_LOG_PATH, "ab") as log_file:
        process = subprocess.Popen(
            cmd,
            cwd=str(ROOT),
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

    deadline = time.monotonic() + BACKEND_START_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise GateFailure(
                f"uvicorn exited early (code {process.returncode}); see {BACKEND_LOG_PATH} for the traceback"
            )
        ok, _ = _healthz_ok(base_url)
        if ok:
            return f"started uvicorn (pid {process.pid}), left running for the demo"
        time.sleep(0.5)

    raise GateFailure(f"backend did not answer /healthz within {BACKEND_START_TIMEOUT_SECONDS:.0f}s; see {BACKEND_LOG_PATH}")


# ---------------------------------------------------------------------------
# 1. Live /api/ballot checks
# ---------------------------------------------------------------------------


def resolve_precache_addresses() -> list[tuple[str, Optional[str], str]]:
    try:
        mod = _load_module("gate_precache_demo", PRECACHE_DEMO_PATH)
        addresses = list(mod.ADDRESSES)
    except Exception as exc:  # noqa: BLE001 -- any import failure falls back
        print(f"WARNING: could not import ADDRESSES from {PRECACHE_DEMO_PATH} ({exc}); using hardcoded mirror")
        addresses = list(PRECACHE_EXPECTED_CD.keys())

    out = []
    for addr in addresses:
        expected = PRECACHE_EXPECTED_CD.get(addr)
        if expected is None:
            print(f"WARNING: no known expected CD configured for precache address {addr!r}")
        out.append((addr, expected, "precache"))
    return out


def resolve_golden_addresses() -> list[tuple[str, Optional[str], str]]:
    if QUALITY_REPORT_PATH.exists():
        try:
            with open(QUALITY_REPORT_PATH, "r", encoding="utf-8") as f:
                report = json.load(f)
            golden = report.get("golden_demo_districts") or []
            out = [
                (g["address"], g["district"], "golden")
                for g in golden
                if isinstance(g, dict) and g.get("address") and g.get("district")
            ]
            if out:
                return out
            print(f"WARNING: {QUALITY_REPORT_PATH} has no usable golden_demo_districts entries; using fallback list")
        except (OSError, json.JSONDecodeError, KeyError) as exc:
            print(f"WARNING: could not read {QUALITY_REPORT_PATH} ({exc}); using fallback golden list")
    else:
        print(f"WARNING: {QUALITY_REPORT_PATH} does not exist; using fallback golden list")
    return [(addr, cd, "golden-fallback") for addr, cd in FALLBACK_GOLDEN_ADDRESSES]


def check_ballot_address(client: httpx.Client, address: str, expected_cd: Optional[str]) -> dict[str, tuple[bool, str]]:
    checks: dict[str, tuple[bool, str]] = {}

    try:
        resp = client.get("/api/ballot", params={"address": address})
    except httpx.HTTPError as exc:
        checks["http_200"] = (False, f"request failed: {exc}")
        return checks

    checks["http_200"] = (resp.status_code == 200, f"status={resp.status_code}")
    if resp.status_code != 200:
        return checks

    try:
        payload = resp.json()
    except ValueError:
        checks["json_parseable"] = (False, "response body was not valid JSON")
        return checks

    districts = payload.get("districts") if isinstance(payload, dict) else None
    actual_cd = districts.get("cd") if isinstance(districts, dict) else None
    if expected_cd is None:
        checks["expected_cd"] = (True, "skipped (no expected CD configured)")
    else:
        checks["expected_cd"] = (actual_cd == expected_cd, f"expected={expected_cd} actual={actual_cd!r}")

    races = payload.get("races") if isinstance(payload, dict) else None
    races_is_list = isinstance(races, list)
    checks["races_is_array"] = (races_is_list, f"type={type(races).__name__}")

    candidates_are_arrays = True
    fields_nonnull = True
    problems: list[str] = []
    if races_is_list:
        for race in races:
            if not isinstance(race, dict):
                candidates_are_arrays = False
                problems.append("race entry is not an object")
                continue
            race_id = race.get("race_id", "?")
            cands = race.get("candidates")
            if not isinstance(cands, list):
                candidates_are_arrays = False
                problems.append(f"{race_id}.candidates is {type(cands).__name__}, not an array")
                continue
            for cand in cands:
                if not isinstance(cand, dict):
                    fields_nonnull = False
                    problems.append(f"{race_id}: candidate entry is not an object")
                    continue
                cid = cand.get("candidate_id")
                name = cand.get("name")
                party = cand.get("party")
                if not (isinstance(cid, str) and cid.strip()):
                    fields_nonnull = False
                    problems.append(f"{race_id}: candidate has null/empty candidate_id")
                if not (isinstance(name, str) and name.strip()):
                    fields_nonnull = False
                    problems.append(f"{race_id}/{cid}: null/empty name")
                if not (isinstance(party, str) and party.strip()):
                    fields_nonnull = False
                    problems.append(f"{race_id}/{cid}: null/empty party")

    checks["candidates_are_arrays"] = (candidates_are_arrays, "ok" if candidates_are_arrays else "; ".join(problems))
    checks["candidate_fields_nonnull"] = (fields_nonnull, "ok" if fields_nonnull else "; ".join(problems))
    return checks


# ---------------------------------------------------------------------------
# 2. Marquee insight completeness (+ consequence horizons, feature-detected)
# ---------------------------------------------------------------------------


def _bullet_ok(b: Any) -> tuple[bool, str]:
    if not isinstance(b, dict):
        return False, "not an object"
    text = b.get("text")
    source = b.get("source")
    if not (isinstance(text, str) and text.strip()):
        return False, "empty/missing text"
    if not (isinstance(source, str) and source.strip()):
        return False, "empty/missing source"
    for tok in BAD_LITERAL_TOKENS:
        if tok in text:
            return False, f"literal {tok!r} found in text"
    return True, ""


def target_marquee_race_ids(races: list[dict[str, Any]]) -> list[str]:
    ids = [r["race_id"] for r in races if r.get("district") is None]
    for extra in EXTRA_TARGET_RACE_IDS:
        if extra not in ids:
            ids.append(extra)
    return ids


def check_marquee_insights(
    races_by_id: dict[str, dict[str, Any]], horizons_enabled: bool
) -> tuple[list[str], int, int]:
    problems: list[str] = []
    files_checked = 0
    bullets_checked = 0

    for race_id in target_marquee_race_ids(list(races_by_id.values())):
        race = races_by_id.get(race_id)
        if race is None:
            problems.append(f"{race_id}: race not found in races.json")
            continue
        path = INSIGHTS_DIR / f"{race_id}.json"
        if not path.exists():
            problems.append(f"{race_id}: insight file missing at {path}")
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                doc = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            problems.append(f"{race_id}: unreadable insight file ({exc})")
            continue
        files_checked += 1

        cand_ids = race.get("candidate_ids", [])
        blocks: dict[str, Any] = {"base": doc.get("base")}
        archetypes_doc = doc.get("archetypes") or {}
        for key in ARCHETYPE_KEYS:
            blocks[f"archetypes.{key}"] = archetypes_doc.get(key)

        for block_name, block in blocks.items():
            if not isinstance(block, dict):
                problems.append(f"{race_id}/{block_name}: block missing")
                continue
            cand_map = block.get("candidates") or {}
            for cid in cand_ids:
                bullets = cand_map.get(cid)
                if not isinstance(bullets, list) or not bullets:
                    problems.append(f"{race_id}/{block_name}/{cid}: no bullets")
                    continue
                any_ok = False
                for b in bullets:
                    bullets_checked += 1
                    ok, reason = _bullet_ok(b)
                    if ok:
                        any_ok = True
                    else:
                        problems.append(f"{race_id}/{block_name}/{cid}: bad bullet ({reason})")
                if not any_ok:
                    problems.append(f"{race_id}/{block_name}/{cid}: zero valid bullets")

            if horizons_enabled:
                horizons = block.get("horizons")
                if not isinstance(horizons, dict):
                    problems.append(f"{race_id}/{block_name}: horizons missing")
                    continue
                for cid in cand_ids:
                    h = horizons.get(cid)
                    if not isinstance(h, dict):
                        problems.append(f"{race_id}/{block_name}/{cid}: horizons entry missing")
                        continue
                    now_list = h.get("now")
                    if not isinstance(now_list, list) or not now_list:
                        problems.append(f"{race_id}/{block_name}/{cid}: horizons.now empty")
                        continue
                    if not any(
                        isinstance(b, dict)
                        and isinstance(b.get("text"), str)
                        and b["text"].strip()
                        and isinstance(b.get("source"), str)
                        and b["source"].strip()
                        for b in now_list
                    ):
                        problems.append(f"{race_id}/{block_name}/{cid}: horizons.now has no valid bullet")

    return problems, files_checked, bullets_checked


# ---------------------------------------------------------------------------
# 3. Attribution truth
# ---------------------------------------------------------------------------


def check_attribution_truth(candidates: dict[str, Any]) -> list[str]:
    ethics_cids = set()
    for cid, c in candidates.items():
        finance = c.get("finance") if isinstance(c, dict) else None
        source = finance.get("source") if isinstance(finance, dict) else None
        if isinstance(source, str) and "ethics.state.tx.us" in source:
            ethics_cids.add(cid)

    violations: list[str] = []
    if not INSIGHTS_DIR.exists():
        return violations

    for path in sorted(INSIGHTS_DIR.glob("*.json")):
        try:
            with open(path, "r", encoding="utf-8") as f:
                doc = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            violations.append(f"{path.name}: unreadable ({exc})")
            continue

        blocks: dict[str, Any] = {}
        if isinstance(doc.get("base"), dict):
            blocks["base"] = doc["base"]
        for key, val in (doc.get("archetypes") or {}).items():
            if isinstance(val, dict):
                blocks[f"archetypes.{key}"] = val

        for block_name, block in blocks.items():
            cand_map = block.get("candidates") or {}
            for cid, bullets in cand_map.items():
                if cid not in ethics_cids:
                    continue
                for b in bullets or []:
                    text = b.get("text", "") if isinstance(b, dict) else ""
                    if "per FEC filings" in text:
                        violations.append(
                            f"{path.name}/{block_name}/candidates/{cid}: "
                            f"'per FEC filings' but finance.source is ethics.state.tx.us"
                        )

            horizons = block.get("horizons") or {}
            for cid, h in horizons.items():
                if cid not in ethics_cids or not isinstance(h, dict):
                    continue
                for list_name in ("now", "long_term"):
                    for b in h.get(list_name) or []:
                        text = b.get("text", "") if isinstance(b, dict) else ""
                        if "per FEC filings" in text:
                            violations.append(
                                f"{path.name}/{block_name}/horizons.{list_name}/{cid}: "
                                f"'per FEC filings' but finance.source is ethics.state.tx.us"
                            )
    return violations


# ---------------------------------------------------------------------------
# 4. Freshness
# ---------------------------------------------------------------------------


def check_freshness() -> tuple[bool, list[str]]:
    if not CANDIDATES_PATH.exists():
        return False, [f"{CANDIDATES_PATH} does not exist"]
    reference_mtime = CANDIDATES_PATH.stat().st_mtime

    if not DEMO_CACHE_DIR.exists():
        return False, [f"{DEMO_CACHE_DIR} does not exist -- run pipeline/precache_demo.py"]

    files = [p for p in DEMO_CACHE_DIR.rglob("*") if p.is_file()]
    if not files:
        return False, [f"{DEMO_CACHE_DIR} contains no files -- run pipeline/precache_demo.py"]

    stale = [str(p.relative_to(ROOT)) for p in files if p.stat().st_mtime < reference_mtime]
    if stale:
        detail = [f"stale demo cache: {len(stale)} file(s) older than {CANDIDATES_PATH.relative_to(ROOT)}"]
        detail.extend(stale[:20])
        if len(stale) > 20:
            detail.append(f"... and {len(stale) - 20} more")
        return False, detail

    return True, []


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help=f"API base URL, default {DEFAULT_BASE_URL}")
    args = parser.parse_args(argv)
    base_url = args.base_url.rstrip("/")

    results: list[tuple[str, bool, str]] = []

    def record(name: str, passed: bool, detail: str = "") -> None:
        results.append((name, passed, detail))
        status = "PASS" if passed else "FAIL"
        print(f"[{status}] {name}" + (f" -- {detail}" if detail else ""))

    print("=== demo_readiness_gate.py ===")
    print(f"base_url = {base_url}\n")

    print("-- 0. Backend liveness --")
    backend_up = False
    try:
        status = ensure_backend_running(base_url)
        record("backend_reachable", True, status)
        backend_up = True
    except GateFailure as exc:
        record("backend_reachable", False, str(exc))

    if backend_up:
        ok, health = _healthz_ok(base_url)
        record("healthz_data_loaded", bool(health and health.get("data_loaded")), json.dumps(health) if health else "no body")

    print("\n-- 1. Live /api/ballot: 3 precache + 5 golden addresses --")
    addresses = resolve_precache_addresses() + resolve_golden_addresses()
    if backend_up:
        with httpx.Client(base_url=base_url, timeout=REQUEST_TIMEOUT) as client:
            for address, expected_cd, label in addresses:
                checks = check_ballot_address(client, address, expected_cd)
                all_ok = all(ok for ok, _ in checks.values())
                failing = [f"{k}: {detail}" for k, (ok, detail) in checks.items() if not ok]
                record(f"ballot[{label}] {address}", all_ok, "ok" if all_ok else "; ".join(failing))
    else:
        for address, _expected_cd, label in addresses:
            record(f"ballot[{label}] {address}", False, "skipped: backend unreachable")

    print("\n-- 2. Marquee insight completeness (+ horizons if landed) --")
    horizons_enabled = VALIDATE_HORIZONS_PATH.exists()
    print(f"  horizons enforcement: {'ENABLED' if horizons_enabled else 'SKIPPED (pipeline/validate_horizons.py not present)'}")
    try:
        with open(RACES_PATH, "r", encoding="utf-8") as f:
            races = json.load(f).get("races", [])
        with open(CANDIDATES_PATH, "r", encoding="utf-8") as f:
            candidates = json.load(f)
        races_by_id = {r["race_id"]: r for r in races}
        problems, files_checked, bullets_checked = check_marquee_insights(races_by_id, horizons_enabled)
        detail = f"{files_checked} files / {bullets_checked} bullets checked"
        if problems:
            detail += f"; {len(problems)} problem(s): " + "; ".join(problems[:8])
            if len(problems) > 8:
                detail += f" ... and {len(problems) - 8} more"
        record("marquee_insight_completeness", not problems, detail)
    except (OSError, json.JSONDecodeError) as exc:
        record("marquee_insight_completeness", False, f"could not read gold JSON: {exc}")
        candidates = {}

    print("\n-- 3. Attribution truth --")
    violations = check_attribution_truth(candidates)
    detail = f"{len(violations)} violation(s)"
    if violations:
        detail += ": " + "; ".join(violations[:5])
        if len(violations) > 5:
            detail += f" ... and {len(violations) - 5} more"
    record("attribution_truth", not violations, detail)

    print("\n-- 4. Freshness --")
    fresh_ok, fresh_detail = check_freshness()
    record("demo_cache_freshness", fresh_ok, "ok" if fresh_ok else "; ".join(fresh_detail))

    overall = all(passed for _, passed, _ in results)
    print("\n=== FINAL VERDICT:", "PASS" if overall else "FAIL", "===")
    if not overall:
        print("Failing checks:")
        for name, passed, detail in results:
            if not passed:
                print(f"  - {name}: {detail}")
    return 0 if overall else 1


if __name__ == "__main__":
    sys.exit(main())
