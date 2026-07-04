#!/usr/bin/env python3
"""
score_quality.py -- data-quality scoring + demo-ranking layer over the gold TX dataset.

Reads:
  data/tx/candidates.json
  data/tx/races.json
  data/tx/insights/{race_id}.json (existence + archetype coverage only)

Writes (non-destructive, additive-only embeds):
  data/tx/candidates.json  (+ candidate.data_quality = {score, tier, missing})
  data/tx/races.json       (+ race.data_quality = {score, tier, demo_rank})
  data/tx/quality_report.json  (full machine-readable scoring detail)
  data/tx/QUALITY.md           (human leaderboard)

Deterministic, no network calls, no LLM calls. Rerunnable: always recomputes
from the current gold JSON and overwrites its own prior output atomically.

--- Candidate score (0-100), weighted completeness ---
  finance present + recent as_of        25 pts (partial 15 pts if present but stale/undated)
  key_votes count, capped at 5           25 pts  (n/5 * 25)
  positions count, capped at 6           20 pts  (n/6 * 20)
  background/bio present                 10 pts
  sources count, capped at 5             10 pts  (n/5 * 10)
  incumbent flag present (5) + fec_id/bioguide id present (5)   10 pts
Tier: A >= 75, B >= 50, C >= 25, D < 25.
missing[] names exactly what's absent, e.g. 'no campaign finance', 'no voting record'.

--- Race score (0-100) ---
  mean(candidate scores)                 40%
  min(candidate scores)                  20%  -- a race is only as demoable as its weakest column
  context.last_result present            10%
  insights file exists + archetype coverage fraction (of 8 archetypes)   20%
  candidate count >= 2                   10%
Tier thresholds same as candidates.

demo_rank: races ordered by (tier, marquee group, group secondary key), where
marquee group is 0=statewide/US Senate (district is null), 1=competitive US
House (last_result margin_pct <= COMPETITIVE_MARGIN_PCT, ordered by margin
ascending -- closest race first), 2=everything else (ordered by margin
ascending as a tie-break). Best tier first; group 0 before 1 before 2 within
a tier.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "tx"
RACES_PATH = OUT_DIR / "races.json"
CANDIDATES_PATH = OUT_DIR / "candidates.json"
INSIGHTS_DIR = OUT_DIR / "insights"
QUALITY_REPORT_PATH = OUT_DIR / "quality_report.json"
QUALITY_MD_PATH = OUT_DIR / "QUALITY.md"
VALIDATE_SCRIPT = ROOT / "pipeline" / "validate_data.py"

ELECTION_DATE = date(2026, 11, 3)
ARCHETYPES = [
    "renter_young_worker",
    "homeowner_parent",
    "small_business_owner",
    "healthcare_aca_or_uninsured",
    "medicare_retiree",
    "veteran",
    "student",
    "rural_agriculture",
]
FINANCE_STALE_DAYS = 730  # finance as_of more than ~2yr before election reads as stale, not fresh
COMPETITIVE_MARGIN_PCT = 15.0  # <=15pt 2024 margin counts as a "competitive" US House seat

CENSUS_GEOCODER_URL = "https://geocoding.geo.census.gov/geocoder/geographies/onelineaddress"

TIER_RANK = {"A": 0, "B": 1, "C": 2, "D": 3}


def tier_for(score: float) -> str:
    if score >= 75:
        return "A"
    if score >= 50:
        return "B"
    if score >= 25:
        return "C"
    return "D"


# ---------------------------------------------------------------------------
# Candidate scoring
# ---------------------------------------------------------------------------


def score_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    missing: list[str] = []
    total = 0.0

    # finance present + recent as_of (25)
    finance = candidate.get("finance")
    if not finance:
        missing.append("no campaign finance")
    else:
        as_of = finance.get("as_of")
        recent = False
        if as_of:
            try:
                as_of_date = datetime.strptime(as_of, "%Y-%m-%d").date()
                recent = (ELECTION_DATE - as_of_date).days <= FINANCE_STALE_DAYS
            except ValueError:
                recent = False
        if recent:
            total += 25.0
        else:
            total += 15.0
            missing.append("stale campaign finance")

    # key_votes count, capped at 5 (25)
    key_votes = ((candidate.get("record") or {}).get("key_votes")) or []
    n_votes = min(len(key_votes), 5)
    total += (n_votes / 5.0) * 25.0
    if not key_votes:
        missing.append("no voting record")

    # positions count, capped at 6 (20)
    positions = candidate.get("positions") or []
    n_pos = min(len(positions), 6)
    total += (n_pos / 6.0) * 20.0
    if not positions:
        missing.append("no issue positions")

    # background/bio present (10)
    bio = candidate.get("background") or candidate.get("bio")
    if bio:
        total += 10.0
    else:
        missing.append("no biography")

    # sources count, capped at 5 (10)
    sources = candidate.get("sources") or []
    n_src = min(len(sources), 5)
    total += (n_src / 5.0) * 10.0
    if not sources:
        missing.append("no sources")

    # incumbent flag (5) + fec_id/bioguide identifier present (5) (10)
    if isinstance(candidate.get("incumbent"), bool):
        total += 5.0
    has_id = bool(candidate.get("fec_id") or candidate.get("bioguide_id") or candidate.get("bioguide"))
    if has_id:
        total += 5.0
    else:
        missing.append("no fec/bioguide id")

    score = round(min(total, 100.0), 1)
    return {"score": score, "tier": tier_for(score), "missing": missing}


# ---------------------------------------------------------------------------
# Race scoring
# ---------------------------------------------------------------------------


def archetype_fraction_for(race_id: str) -> tuple[float, bool]:
    """Returns (fraction of 8 archetypes covered, insights file exists)."""
    path = INSIGHTS_DIR / f"{race_id}.json"
    if not path.exists():
        return 0.0, False
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return 0.0, True
    archetypes = data.get("archetypes") or {}
    covered = sum(1 for a in ARCHETYPES if a in archetypes)
    return covered / len(ARCHETYPES), True


def score_race(race: dict[str, Any], candidate_scores: dict[str, dict[str, Any]]) -> dict[str, Any]:
    cids = race.get("candidate_ids", [])
    scores = [candidate_scores[cid]["score"] for cid in cids if cid in candidate_scores]
    mean_score = sum(scores) / len(scores) if scores else 0.0
    min_score = min(scores) if scores else 0.0

    last_result_present = bool((race.get("context") or {}).get("last_result"))
    archetype_fraction, insights_exists = archetype_fraction_for(race["race_id"])
    count_ok = len(cids) >= 2

    weighted = (
        0.40 * mean_score
        + 0.20 * min_score
        + 0.10 * (100.0 if last_result_present else 0.0)
        + 0.20 * (archetype_fraction * 100.0)
        + 0.10 * (100.0 if count_ok else 0.0)
    )
    score = round(weighted, 1)
    return {
        "score": score,
        "tier": tier_for(score),
        "detail": {
            "mean_candidate_score": round(mean_score, 1),
            "min_candidate_score": round(min_score, 1),
            "last_result_present": last_result_present,
            "insights_exists": insights_exists,
            "archetype_fraction": round(archetype_fraction, 3),
            "candidate_count": len(cids),
        },
    }


def demo_marquee_key(race: dict[str, Any], race_score: float) -> tuple[int, float]:
    """(group, secondary) where group 0 = statewide/US Senate, 1 = competitive
    US House (margin <= COMPETITIVE_MARGIN_PCT), 2 = everything else. Lower
    sorts first in each field."""
    district = race.get("district")
    if district is None:
        return (0, -race_score)  # marquee statewide/Senate races, best score first
    detail = (race.get("context") or {}).get("last_result_detail") or {}
    margin = detail.get("margin_pct")
    if margin is None:
        return (2, 999.0)
    if margin <= COMPETITIVE_MARGIN_PCT:
        return (1, margin)
    return (2, margin)


def assign_demo_ranks(races: list[dict[str, Any]], race_scores: dict[str, dict[str, Any]]) -> dict[str, int]:
    def sort_key(r):
        rs = race_scores[r["race_id"]]
        group, secondary = demo_marquee_key(r, rs["score"])
        return (TIER_RANK[rs["tier"]], group, secondary, r["race_id"])

    ordered = sorted(races, key=sort_key)
    return {r["race_id"]: i + 1 for i, r in enumerate(ordered)}


# ---------------------------------------------------------------------------
# Atomic JSON write (matches pipeline/import_civicmatch_positions.py convention)
# ---------------------------------------------------------------------------


def atomic_write_json(path: Path, data: Any) -> None:
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.stem}.", suffix=".json.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


# ---------------------------------------------------------------------------
# Census geocoder verification for the golden demo addresses (live, no key)
# ---------------------------------------------------------------------------


def geocode_cd(address: str) -> dict[str, Any]:
    """One live call to the Census geocoder (same benchmark/vintage as
    app/main.py) -- returns matched address + CD number, or an error note.
    Network failure here does not block the rest of the pipeline; it is
    reported in QUALITY.md so a human can re-verify."""
    params = {
        "address": address,
        "benchmark": "Public_AR_Current",
        "vintage": "Current_Current",
        "format": "json",
    }
    url = f"{CENSUS_GEOCODER_URL}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"ok": False, "error": str(exc)}

    matches = (payload.get("result") or {}).get("addressMatches") or []
    if not matches:
        return {"ok": False, "error": "no address match"}
    match = matches[0]
    geographies = match.get("geographies") or {}
    cd_list = geographies.get("119th Congressional Districts") or []
    cd = None
    if cd_list:
        raw = cd_list[0].get("CD119") or cd_list[0].get("GEOID", "")[-2:]
        try:
            cd = f"TX-{int(raw):02d}"
        except (TypeError, ValueError):
            cd = None
    return {
        "ok": True,
        "matched_address": match.get("matchedAddress"),
        "cd": cd,
    }


# Golden demo district street addresses: real, public, geocodable civic
# buildings (county courthouse / city hall) chosen to sit inside the target
# CD. Each was test-geocoded against the live Census geocoder
# (Public_AR_Current benchmark, 119th Congressional Districts layer) before
# being added here; the pipeline re-verifies live on every run and reports
# the actual result in QUALITY.md / quality_report.json rather than trusting
# this comment.
GOLDEN_ADDRESS_CANDIDATES: dict[str, str] = {
    "TX-16": "500 E San Antonio Ave, El Paso, TX 79901",  # El Paso County Courthouse
    "TX-28": "1000 Houston St, Laredo, TX 78040",  # Webb County Courthouse
    "TX-15": "100 W Cano St, Edinburg, TX 78539",  # Hidalgo County Courthouse
    "TX-34": "1100 E Monroe St, Brownsville, TX 78520",  # Cameron County Courthouse
    "TX-24": "255 Parkway Blvd, Coppell, TX 75019",  # Coppell City Hall
}


def pick_golden_address(district: str) -> str | None:
    return GOLDEN_ADDRESS_CANDIDATES.get(district)


# ---------------------------------------------------------------------------
# Name-collision detection: two different candidate_ids sharing the same
# normalized human name. Ground-truth risk if left silent: a future
# maintainer (or an LLM agent) sees "Sarah Eckhardt" twice and "helpfully"
# merges the records, conflating two candidacies into one and attributing
# one person's finance/votes/positions to the other. We never merge here --
# we only detect and report, every run, so the ambiguity can't quietly
# disappear. Detection is name-based only (no identity inference): whether
# the two records denote the same real person or two different people who
# share a name is explicitly NOT decided by this script.
# ---------------------------------------------------------------------------


def _normalize_name(name: str | None) -> str:
    return " ".join((name or "").strip().lower().split())


def find_name_collisions(candidates: dict[str, Any]) -> list[dict[str, Any]]:
    by_name: dict[str, list[str]] = {}
    for cid, c in candidates.items():
        by_name.setdefault(_normalize_name(c.get("name")), []).append(cid)

    collisions = []
    for norm, cids in sorted(by_name.items()):
        if len(cids) < 2:
            continue
        collisions.append(
            {
                "name": candidates[cids[0]].get("name"),
                "candidate_ids": sorted(cids),
                "offices": {cid: candidates[cid].get("office") for cid in cids},
                "note": (
                    "Same normalized name, different candidate_id. Kept as separate "
                    "records -- identity (same real person vs. two different people "
                    "sharing a name) is NOT confirmed by this pipeline. Do not merge "
                    "without independent confirmation; each record's own sources "
                    "belong only to that record."
                ),
            }
        )
    return collisions


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    with open(RACES_PATH, "r", encoding="utf-8") as f:
        races_doc = json.load(f)
    with open(CANDIDATES_PATH, "r", encoding="utf-8") as f:
        candidates = json.load(f)

    races = races_doc.get("races", [])

    # 1. Score every candidate.
    candidate_quality: dict[str, dict[str, Any]] = {}
    for cid, c in candidates.items():
        candidate_quality[cid] = score_candidate(c)

    # 2. Score every race + assign demo_rank.
    race_quality: dict[str, dict[str, Any]] = {}
    for r in races:
        race_quality[r["race_id"]] = score_race(r, candidate_quality)
    demo_ranks = assign_demo_ranks(races, race_quality)
    for race_id, rq in race_quality.items():
        rq["demo_rank"] = demo_ranks[race_id]

    # 3. Embed non-destructively + atomic rewrite.
    for cid, c in candidates.items():
        c["data_quality"] = {
            "score": candidate_quality[cid]["score"],
            "tier": candidate_quality[cid]["tier"],
            "missing": candidate_quality[cid]["missing"],
        }
    for r in races:
        rq = race_quality[r["race_id"]]
        r["data_quality"] = {
            "score": rq["score"],
            "tier": rq["tier"],
            "demo_rank": rq["demo_rank"],
        }

    atomic_write_json(CANDIDATES_PATH, candidates)
    atomic_write_json(RACES_PATH, races_doc)

    # Re-run the validator against the freshly embedded gold data.
    validate_result = subprocess.run(
        [sys.executable, str(VALIDATE_SCRIPT)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    print(validate_result.stdout)
    if validate_result.returncode != 0:
        print(validate_result.stderr, file=sys.stderr)
        print("validate_data.py FAILED after embedding data_quality -- aborting report generation.", file=sys.stderr)
        return validate_result.returncode

    # --- Per-source coverage stats ---
    n_candidates = len(candidates)
    n_fec_finance = sum(1 for c in candidates.values() if c.get("finance"))
    n_clerk_votes = sum(1 for c in candidates.values() if ((c.get("record") or {}).get("key_votes")))
    n_civic_positions = sum(
        1
        for c in candidates.values()
        if any(p.get("origin") == "civic-match-research" for p in (c.get("positions") or []))
    )
    n_background = sum(1 for c in candidates.values() if c.get("background") or c.get("bio"))
    n_identifier = sum(1 for c in candidates.values() if c.get("fec_id") or c.get("bioguide_id"))

    source_coverage = {
        "total_candidates": n_candidates,
        "fec_finance": {"count": n_fec_finance, "pct": round(100 * n_fec_finance / n_candidates, 1)},
        "clerk_key_votes": {"count": n_clerk_votes, "pct": round(100 * n_clerk_votes / n_candidates, 1)},
        "civic_match_positions": {"count": n_civic_positions, "pct": round(100 * n_civic_positions / n_candidates, 1)},
        "background_bio": {"count": n_background, "pct": round(100 * n_background / n_candidates, 1)},
        "fec_or_bioguide_id": {"count": n_identifier, "pct": round(100 * n_identifier / n_candidates, 1)},
    }

    # --- Tier distributions ---
    cand_tier_counts = {"A": 0, "B": 0, "C": 0, "D": 0}
    for cq in candidate_quality.values():
        cand_tier_counts[cq["tier"]] += 1
    race_tier_counts = {"A": 0, "B": 0, "C": 0, "D": 0}
    for rq in race_quality.values():
        race_tier_counts[rq["tier"]] += 1

    races_by_rank = sorted(races, key=lambda r: race_quality[r["race_id"]]["demo_rank"])

    name_collisions = find_name_collisions(candidates)

    # --- Golden demo districts: the 5 highest demo_rank *US House districts*
    # (i.e. real congressional districts with a verifiable CD -- statewide
    # races have no district to geocode against, so they're excluded from
    # this specific section even though they outrank House races overall).
    golden_candidates = [r for r in races_by_rank if r.get("district")]
    golden = []
    for r in golden_candidates[:5]:
        district = r.get("district")
        addr = pick_golden_address(district) if district else None
        geo_result = None
        if addr:
            geo_result = geocode_cd(addr)
        golden.append(
            {
                "race_id": r["race_id"],
                "office": r["office"],
                "district": district,
                "demo_rank": race_quality[r["race_id"]]["demo_rank"],
                "tier": race_quality[r["race_id"]]["tier"],
                "score": race_quality[r["race_id"]]["score"],
                "address": addr,
                "geocoder_verification": geo_result,
            }
        )

    # --- Build full quality_report.json ---
    report = {
        "generated_by": "pipeline/score_quality.py",
        "candidates": {
            cid: {
                "name": candidates[cid].get("name"),
                **candidate_quality[cid],
            }
            for cid in candidates
        },
        "races": {
            r["race_id"]: {
                "office": r["office"],
                "level": r["level"],
                "district": r.get("district"),
                **race_quality[r["race_id"]],
            }
            for r in races
        },
        "tier_distribution": {"candidates": cand_tier_counts, "races": race_tier_counts},
        "source_coverage": source_coverage,
        "golden_demo_districts": golden,
        "name_collisions_not_merged": name_collisions,
    }
    atomic_write_json(QUALITY_REPORT_PATH, report)

    # --- QUALITY.md ---
    lines: list[str] = []
    lines.append("# Data quality + demo-readiness leaderboard")
    lines.append("")
    lines.append(
        f"Generated by `pipeline/score_quality.py` over {len(races)} races / {n_candidates} candidates. "
        "Rerun any time the gold dataset changes -- fully deterministic, no LLM calls."
    )
    lines.append("")
    lines.append("## Tier distribution")
    lines.append("")
    lines.append("| | A | B | C | D |")
    lines.append("|---|---|---|---|---|")
    lines.append(
        f"| Races | {race_tier_counts['A']} | {race_tier_counts['B']} | {race_tier_counts['C']} | {race_tier_counts['D']} |"
    )
    lines.append(
        f"| Candidates | {cand_tier_counts['A']} | {cand_tier_counts['B']} | {cand_tier_counts['C']} | {cand_tier_counts['D']} |"
    )
    lines.append("")

    lines.append("## Top 15 races (by demo_rank)")
    lines.append("")
    lines.append("| Rank | Race | Tier | Score | Why |")
    lines.append("|---|---|---|---|---|")
    for r in races_by_rank[:15]:
        rq = race_quality[r["race_id"]]
        det = rq["detail"]
        district = r.get("district")
        why_bits = []
        why_bits.append("statewide/Senate" if district is None else f"district {district}")
        if district is not None:
            last_detail = (r.get("context") or {}).get("last_result_detail") or {}
            margin = last_detail.get("margin_pct")
            if margin is not None:
                why_bits.append(f"2024 margin {margin}pts")
        why_bits.append(f"mean cand {det['mean_candidate_score']}")
        why_bits.append(f"min cand {det['min_candidate_score']}")
        why_bits.append(f"archetypes {det['archetype_fraction']*8:.0f}/8")
        why = ", ".join(why_bits)
        lines.append(f"| {rq['demo_rank']} | {r['office']} ({r['race_id']}) | {rq['tier']} | {rq['score']} | {why} |")
    lines.append("")

    lines.append("## Bottom 5 races")
    lines.append("")
    lines.append("| Race | Tier | Score | Missing / weak spots |")
    lines.append("|---|---|---|---|")
    for r in races_by_rank[-5:]:
        rq = race_quality[r["race_id"]]
        det = rq["detail"]
        reasons = []
        if det["min_candidate_score"] < 25:
            weakest_cid = min(
                (cid for cid in r["candidate_ids"] if cid in candidate_quality),
                key=lambda cid: candidate_quality[cid]["score"],
                default=None,
            )
            if weakest_cid:
                reasons.append(
                    f"weakest candidate {candidates[weakest_cid].get('name')} missing: "
                    + ", ".join(candidate_quality[weakest_cid]["missing"])
                )
        if not det["last_result_present"]:
            reasons.append("no last_result context")
        if not det["insights_exists"]:
            reasons.append("no insights file")
        elif det["archetype_fraction"] < 1.0:
            reasons.append(f"only {det['archetype_fraction']*8:.0f}/8 archetypes precomputed")
        if det["candidate_count"] < 2:
            reasons.append("only 1 candidate on file")
        if not reasons:
            reasons.append("generally low candidate completeness")
        lines.append(f"| {r['office']} ({r['race_id']}) | {rq['tier']} | {rq['score']} | {'; '.join(reasons)} |")
    lines.append("")

    lines.append("## Per-source coverage")
    lines.append("")
    lines.append("| Source | Candidates covered | % of 96 |")
    lines.append("|---|---|---|")
    lines.append(
        f"| FEC campaign finance | {source_coverage['fec_finance']['count']} | {source_coverage['fec_finance']['pct']}% |"
    )
    lines.append(
        f"| House Clerk roll-call votes | {source_coverage['clerk_key_votes']['count']} | {source_coverage['clerk_key_votes']['pct']}% |"
    )
    lines.append(
        f"| civic-match researched positions | {source_coverage['civic_match_positions']['count']} | {source_coverage['civic_match_positions']['pct']}% |"
    )
    lines.append(
        f"| Background/bio | {source_coverage['background_bio']['count']} | {source_coverage['background_bio']['pct']}% |"
    )
    lines.append(
        f"| FEC/Bioguide identifier | {source_coverage['fec_or_bioguide_id']['count']} | {source_coverage['fec_or_bioguide_id']['pct']}% |"
    )
    lines.append("")

    lines.append("## Golden demo districts (5 highest demo_rank US House districts)")
    lines.append("")
    lines.append(
        "The 5 best-scoring *actual congressional districts* (statewide races outrank these on "
        "demo_rank but have no single district to geocode against, so they're reported separately "
        "above). Each address is a real, public, geocodable civic building (county courthouse / "
        "city hall) picked to sit inside the target district. Verified with one live call per "
        "address to the Census geocoder (`Public_AR_Current` benchmark, 119th Congressional "
        "Districts layer -- no API key) at pipeline run time."
    )
    lines.append("")
    lines.append("| Rank | Race | District | Address | Geocoder-verified CD | Match |")
    lines.append("|---|---|---|---|---|---|")
    for g in golden:
        geo = g["geocoder_verification"]
        if geo is None:
            verified_cd = "n/a (statewide)"
            match = "n/a"
        elif not geo.get("ok"):
            verified_cd = f"ERROR: {geo.get('error')}"
            match = "UNVERIFIED"
        else:
            verified_cd = geo.get("cd") or "unknown"
            match = "MATCH" if verified_cd == g["district"] else "MISMATCH"
        lines.append(
            f"| {g['demo_rank']} | {g['office']} ({g['race_id']}) | {g['district'] or 'statewide'} | "
            f"{g['address'] or 'n/a'} | {verified_cd} | {match} |"
        )
    lines.append("")

    lines.append("## Known name collisions (not merged)")
    lines.append("")
    lines.append(
        "Different `candidate_id`s that share the exact same normalized human name. "
        "Detected automatically every run -- listed here so no one \"cleans up\" what "
        "looks like a duplicate by merging two records. Whether each pair is the same "
        "real person running for two offices (Texas law generally bars that in one "
        "general election) or two different people who happen to share a name is "
        "**not** determined by this pipeline; each candidate_id's sources describe "
        "only that record."
    )
    lines.append("")
    if name_collisions:
        lines.append("| Name | candidate_ids | Offices |")
        lines.append("|---|---|---|")
        for nc in name_collisions:
            offices = "; ".join(f"{cid} → {off}" for cid, off in nc["offices"].items())
            lines.append(f"| {nc['name']} | {', '.join(nc['candidate_ids'])} | {offices} |")
    else:
        lines.append("None detected in the current gold dataset.")
    lines.append("")

    QUALITY_MD_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"Wrote {QUALITY_REPORT_PATH}")
    print(f"Wrote {QUALITY_MD_PATH}")
    print(f"Candidate tiers: {cand_tier_counts}")
    print(f"Race tiers: {race_tier_counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
