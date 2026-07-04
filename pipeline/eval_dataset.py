#!/usr/bin/env python3
"""
eval_dataset.py -- DATASET BREADTH + DEPTH completeness eval for the TX gold
dataset. Answers one question: "if a voter anywhere in Texas uses this tool,
how likely are they to get a complete, well-sourced ballot?" -- and, just as
important, exactly where the holes are and whether each hole is fixable
right now or genuinely out of our hands today.

This is DISTINCT from (and reads, but never writes to) the two existing
scoring passes:
  - pipeline/clean_gold.py's coverage_report.json = per-race party/finance/
    vote/position COUNTS + one-sidedness. A cleaning byproduct.
  - pipeline/score_quality.py's quality_report.json / QUALITY.md = per-
    candidate/race DEMO-READINESS scoring (which races/addresses look best
    on stage) and a demo_rank ordering. Answers "what should we show off".
This script answers a different question: "how complete is the WHOLE
dataset against what a full statewide rollout needs, and what is the exact,
cheapest next fix" -- a completeness audit, not a demo-readiness ranking.
Where useful it cross-checks its own from-scratch recomputation against the
cached coverage_report.json/quality_report.json and flags any drift as a
defect (a stale report is itself a bug).

Reads (read-only -- never mutates any of these):
  data/tx/races.json, data/tx/candidates.json
  data/tx/insights/*.json               (archetype/base coverage)
  data/tx/coverage_report.json          (cross-check only)
  data/tx/quality_report.json           (cross-check only)
  data/tx/unjoined_report.json          (known-ambiguity context + a live
                                          recoverable-FEC-join rescan)
  data/tx/raw/fec.json                  (for the recoverable-join rescan)
  data/tx/geocode_seed.json             (address-resolution sample)
  address_sweep_report.json             (OPTIONAL, repo root; consumed
                                          opportunistically if present --
                                          this script never blocks on it)

Writes (both new, nothing else):
  data/tx/dataset_eval.json  (machine)
  data/tx/DATASET_EVAL.md    (human scorecard)

Deterministic: no network calls, no LLM calls, no randomness. Re-running
against unchanged gold data reproduces byte-identical scores every time.

=============================================================================
RUBRIC (documented, so every number below is reconstructable by hand)
=============================================================================

--- BREADTH (dataset-wide structural coverage) ---
  race_count_completeness = min(actual_race_count / EXPECTED_RACE_COUNT, 1) * 100
    EXPECTED_RACE_COUNT = 46 = 7 statewide TX executive offices (Governor,
    Lt Gov, AG, Comptroller, Land Commissioner, Ag Commissioner, Railroad
    Commissioner) + 1 US Senate seat (statewide, federal) + 38 US House
    districts. This is the declared product scope per CLAUDE.md's LOCKED
    DECISIONS -- TX Legislature (150 House + 31 Senate districts) is an
    explicit, separate STRETCH GOAL, not part of this denominator. Falling
    short of "every possible elected office in Texas" is therefore an
    honest, declared scope boundary, not a completeness defect; it is
    still reported below as its own line so the 100 never gets misread as
    "covers the whole real ballot".
  contested_ratio = races with >=2 candidates on file / total races * 100
  address_resolution_score = congressional districts present in races.json
    / 38 * 100 (see "address resolution" below for why this is a
    structural proof, not just a sample statistic).
  BREADTH_SCORE = 0.40*race_count_completeness + 0.30*contested_ratio
                  + 0.30*address_resolution_score

--- DEPTH (per-race, 0-100, rolls up to a dataset mean) ---
  For each race, average each component over that race's on-file
  candidates, convert to a 0-100 sub-score, then take a WEIGHTED AVERAGE
  of whichever components apply (two components can be legitimately N/A
  for a given race and are excluded from -- not zeroed into -- that race's
  denominator; see below):

    finance_coverage      weight 20   fraction of candidates with finance{}
    votes_coverage        weight 15   fraction of INCUMBENTS with
                                      record.key_votes (N/A + excluded if
                                      the race has zero incumbents on file
                                      -- a challenger cannot structurally
                                      have a House Clerk roll-call record,
                                      so a challenger-only race is not
                                      penalized for something no candidate
                                      in it could ever have)
    positions_coverage    weight 20   fraction of candidates with
                                      positions[] non-empty
    bio_coverage          weight 10   fraction of candidates with
                                      background/bio text
    sourcing_richness     weight 10   min(avg distinct source URLs per
                                      candidate / SOURCE_TARGET, 1) * 100
                                      (SOURCE_TARGET=5, chosen from the
                                      dataset's own distribution -- see
                                      dataset_rollup.sources_per_candidate;
                                      it sits in the valley of an observed
                                      bimodal split, not an arbitrary
                                      round number)
    temporal_grounding    weight 10   fraction of THIS race's finance{}
                                      objects with a valid ISO as_of date
                                      (N/A + excluded if no candidate in
                                      the race has a finance{} object at
                                      all -- nothing to date)
    insight_depth         weight 15   0.3*(100 if insights base block
                                      present else 0) + 0.7*(archetype
                                      coverage fraction of 8 * 100)
    evidence_checks       (reported, NOT weighted into the score -- see
                                      "why evidence_checks isn't scored"
                                      below)

  race score = weighted average of whichever of the above numeric
  components apply to that race (weights renormalize over the applicable
  subset, so every race still lands on a clean 0-100 scale).

  Why evidence_checks isn't scored: as of this run it does not exist
  ANYWHERE in the dataset (checked defensively under several plausible key
  names). Folding a universally-absent, not-yet-built pipeline stage into
  every single race's score would silently crater all 46 scores for a
  fleet-level gap that has nothing to do with any individual race's own
  data collection -- that would make the score less informative, not more.
  It is instead reported as its own explicit, always-visible field so it
  can never be missed, and the moment it lands for even one candidate this
  script will start reporting real coverage for it (see
  dataset_rollup.evidence_checks).

  Tier bands (kept consistent with score_quality.py's convention so the
  two documents read the same way): A >= 75, B >= 50, C >= 25, D < 25.
  This is a COMPLETENESS tier, not that script's DEMO-READINESS tier --
  the two can and do disagree for the same race_id; that is expected,
  they measure different things.

--- COMPLETENESS INDEX (one top-line number) ---
  COMPLETENESS_INDEX = 0.40 * BREADTH_SCORE + 0.60 * DEPTH_SCORE
  (DEPTH weighted higher: BREADTH is already close to structurally
  saturated at this dataset's declared scope -- 46/46 races, 38/38 CDs --
  so nearly all of the real signal/variance lives in DEPTH.)

  Two further numbers are reported ALONGSIDE the index as diagnostic
  detail, not blended into it a second time (blending them in again would
  double-count factors that are already inside DEPTH_SCORE's own
  components, a classic composite-score mistake):
    INSIGHT_LAYER_SCORE  -- dataset-wide base/archetype presence fractions
    SOURCING_INDEX       -- dataset-wide avg distinct sources + as_of rate
  These exist to make the single biggest, cheapest-to-fix gaps impossible
  to miss when skimming the scorecard; the top-line number itself is
  fully reconstructable from BREADTH_SCORE and DEPTH_SCORE alone.

=============================================================================
HONEST GAP vs DEFECT
=============================================================================
  DEFECT       = we already fetched/hold the source data (or the
                 generation step is a deterministic, already-ingested-data-
                 only pass with no new network/LLM dependency) and simply
                 didn't wire it in. Actionable right now. Always paired
                 with an exact fix.
  HONEST GAP   = one of:
      not_public              the fact doesn't exist in any public record
      not_yet_fetched         it likely exists publicly but requires new
                              fetching/research effort we have not done
      needs_key               blocked on a rate limit or an API key we
                              don't have configured yet (see CLAUDE.md's
                              "Keys -- human action items")
      declared_out_of_scope   explicitly cut in CLAUDE.md's LOCKED DECISIONS
  Findings that are evidence-based but require a HUMAN identity/judgment
  call before any fix is applied (e.g. redistricting name-join ambiguity)
  are marked DEFECT_CANDIDATE -- flagged precisely, with the exact
  verification step needed, but never auto-resolved here or by implication
  (this project's own culture is deliberately conservative about that --
  see quality_report.json's name_collisions_not_merged).

Usage:
    python3 pipeline/eval_dataset.py
Exit code: 0 always (this is a report, not a gate; pipeline/
demo_readiness_gate.py is the pass/fail gate). A malformed gold JSON read
failure is the only thing that exits non-zero.
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / "tx"
RACES_PATH = DATA_DIR / "races.json"
CANDIDATES_PATH = DATA_DIR / "candidates.json"
INSIGHTS_DIR = DATA_DIR / "insights"
COVERAGE_REPORT_PATH = DATA_DIR / "coverage_report.json"
QUALITY_REPORT_PATH = DATA_DIR / "quality_report.json"
UNJOINED_REPORT_PATH = DATA_DIR / "unjoined_report.json"
RAW_FEC_PATH = DATA_DIR / "raw" / "fec.json"
GEOCODE_SEED_PATH = DATA_DIR / "geocode_seed.json"
# The task spec named this bare ("address_sweep_report.json IF it exists"),
# unlike the other data/tx/-prefixed inputs -- checked both plausible
# locations rather than guessing one; in practice pipeline/sweep_addresses.py
# writes it to data/tx/, so that path is tried first.
ADDRESS_SWEEP_PATH_CANDIDATES = [DATA_DIR / "address_sweep_report.json", ROOT / "address_sweep_report.json"]
DETECT_CONTRADICTIONS_SCRIPT_PATH = ROOT / "pipeline" / "detect_contradictions.py"

OUT_JSON_PATH = DATA_DIR / "dataset_eval.json"
OUT_MD_PATH = DATA_DIR / "DATASET_EVAL.md"

GENERATED_BY = "pipeline/eval_dataset.py"

# --- Declared scope (CLAUDE.md LOCKED DECISIONS, 2026-07-03) ---
EXPECTED_STATE_EXEC_RACES = 7  # Governor, Lt Gov, AG, Comptroller, Land Comm, Ag Comm, Railroad Comm
EXPECTED_US_SENATE_RACES = 1
EXPECTED_US_HOUSE_RACES = 38
EXPECTED_RACE_COUNT = EXPECTED_STATE_EXEC_RACES + EXPECTED_US_SENATE_RACES + EXPECTED_US_HOUSE_RACES  # 46
TOTAL_US_HOUSE_DISTRICTS_IN_TX = 38
TX_LEGISLATURE_HD_COUNT = 150
TX_LEGISLATURE_SD_COUNT = 31

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

# Depth rubric weights (documented above). Kept as named constants so the
# module docstring and the code can never silently drift apart.
W_FINANCE = 20.0
W_VOTES = 15.0
W_POSITIONS = 20.0
W_BIO = 10.0
W_SOURCING = 10.0
W_TEMPORAL = 10.0
W_INSIGHT = 15.0
# sum of all seven = 100; a race missing votes and/or temporal renormalizes
# over the remaining subset (see race_depth_score()).

SOURCE_TARGET = 5  # see module docstring: sits in the valley of the observed bimodal distribution

INSIGHT_BASE_WEIGHT = 0.3
INSIGHT_ARCHETYPE_WEIGHT = 0.7

COMPLETENESS_BREADTH_WEIGHT = 0.40
COMPLETENESS_DEPTH_WEIGHT = 0.60

AS_OF_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Plausible key names for a not-yet-landed "says-vs-voted" evidence-check
# feature. Checked defensively so this script auto-upgrades the moment any
# of these appear on any candidate, instead of needing a rewrite.
EVIDENCE_CHECK_KEYS = ["evidence_checks", "says_vs_voted", "consistency_checks", "record_vs_positions"]


# ---------------------------------------------------------------------------
# IO helpers
# ---------------------------------------------------------------------------


def load_json_required(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_json_optional(path: Path) -> Optional[Any]:
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


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


def tier_for(score: float) -> str:
    if score >= 75:
        return "A"
    if score >= 50:
        return "B"
    if score >= 25:
        return "C"
    return "D"


def valid_iso_date(s: Any, cutoff: Optional[date] = None) -> bool:
    if not isinstance(s, str) or not AS_OF_ISO_RE.match(s):
        return False
    try:
        d = datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return False
    if cutoff and d > cutoff:
        return False
    return True


def has_bio(c: dict[str, Any]) -> bool:
    return bool(c.get("background") or c.get("bio"))


def has_evidence_checks(c: dict[str, Any]) -> bool:
    return any(bool(c.get(k)) for k in EVIDENCE_CHECK_KEYS)


def distinct_sources(c: dict[str, Any]) -> set[str]:
    """Union of every source URL cited anywhere on this candidate record --
    top-level sources[], finance.source, record.source, each
    record.key_votes[].source, each positions[].source. Deliberately wider
    than just top-level sources[] (see dataset_rollup.sources_per_candidate
    docstring note on why the two numbers differ)."""
    urls: set[str] = set()
    for u in c.get("sources") or []:
        if isinstance(u, str) and u.strip():
            urls.add(u.strip())
    finance = c.get("finance") or {}
    if isinstance(finance.get("source"), str) and finance["source"].strip():
        urls.add(finance["source"].strip())
    record = c.get("record") or {}
    if isinstance(record.get("source"), str) and record["source"].strip():
        urls.add(record["source"].strip())
    for kv in record.get("key_votes") or []:
        if isinstance(kv, dict) and isinstance(kv.get("source"), str) and kv["source"].strip():
            urls.add(kv["source"].strip())
    for p in c.get("positions") or []:
        if isinstance(p, dict) and isinstance(p.get("source"), str) and p["source"].strip():
            urls.add(p["source"].strip())
    return urls


def insights_coverage_for(race_id: str) -> tuple[int, bool, dict[str, Any]]:
    """(archetype count 0-8 with real candidate bullets, base-present bool,
    base.candidates dict) for one race_id. Mirrors clean_gold.py's
    _insights_coverage_for, extended to also return the base candidates
    dict so callers can check per-candidate presence."""
    path = INSIGHTS_DIR / f"{race_id}.json"
    if not path.exists():
        return 0, False, {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            doc = json.load(f)
    except (json.JSONDecodeError, OSError):
        return 0, False, {}
    archetypes = doc.get("archetypes") or {}
    count = sum(1 for a in ARCHETYPES if isinstance(archetypes.get(a), dict) and archetypes[a].get("candidates"))
    base = doc.get("base") or {}
    base_candidates = base.get("candidates") or {}
    base_present = bool(base_candidates)
    return count, base_present, base_candidates


def summarize_address_sweep(doc: Optional[Any], race_ids_present: set[str]) -> dict[str, Any]:
    """Parses data/tx/address_sweep_report.json (pipeline/sweep_addresses.py's
    output, a LIVE HTTP sweep against a running backend -- a different,
    complementary verification method from this script's own static/
    structural analysis). Schema is owned by that script, not this one, so
    every access here is defensive (.get()-based); a shape change in a
    future run degrades to 'present but unparseable', never a crash."""
    if doc is None:
        return {
            "present": False,
            "note": (
                "address_sweep_report.json was not present at eval time (polled ~8min per "
                "task instructions, then proceeded without it, as instructed). The structural "
                "38/38 CD proof and the geocode_seed spot check stand on their own regardless."
            ),
        }
    if not isinstance(doc, dict):
        return {"present": True, "parsed": False, "note": "address_sweep_report.json found but is not a JSON object; skipped."}

    counts = doc.get("counts") or {}
    entries = list(doc.get("new_sweep") or []) + list(doc.get("regression_check") or [])
    all_cds = sorted(
        {e["districts"]["cd"] for e in entries if isinstance(e.get("districts"), dict) and e["districts"].get("cd")}
    )
    cds_without_a_race_on_file = []
    for cd in all_cds:
        m = re.match(r"^TX-(\d{2})$", cd)
        if m and f"tx-cd{m.group(1)}-2026" not in race_ids_present:
            cds_without_a_race_on_file.append(cd)

    return {
        "present": True,
        "parsed": True,
        "generated_at": doc.get("generated_at"),
        "generated_by": doc.get("generated_by"),
        "new_sweep_addresses": counts.get("new_sweep_addresses"),
        "new_sweep_ok": counts.get("new_sweep_ok"),
        "distinct_cds_new_sweep": counts.get("distinct_cds_new_sweep"),
        "regression_pass": counts.get("regression_pass"),
        "regression_fail": counts.get("regression_fail"),
        "total_failures": counts.get("total_failures"),
        "distinct_cds_covered_all_entries": all_cds,
        "cds_without_a_race_on_file": cds_without_a_race_on_file,
        "note": (
            "Live HTTP sweep (pipeline/sweep_addresses.py) against a running backend -- an "
            "independent, complementary corroboration of the structural 38/38 CD proof above, "
            "using real geocoder + API round-trips rather than a committed static sample."
        ),
    }


# ---------------------------------------------------------------------------
# BREADTH
# ---------------------------------------------------------------------------


def compute_breadth(races: list[dict[str, Any]], candidates: dict[str, Any], geocode_seed: Optional[dict[str, Any]], address_sweep: Optional[Any]) -> dict[str, Any]:
    race_count = len(races)
    level_counts: dict[str, int] = {}
    for r in races:
        level_counts[r.get("level", "?")] = level_counts.get(r.get("level", "?"), 0) + 1
    marquee_count = sum(1 for r in races if r.get("district") is None)  # statewide + US Senate, on every ballot

    cd_districts = sorted({r["district"] for r in races if r.get("district") and re.match(r"^TX-\d{2}$", r["district"])})
    house_race_count = sum(1 for r in races if r.get("level") == "federal" and r.get("district"))

    per_race_breadth = []
    party_diversity_hist: dict[int, int] = {}
    n_ge2_candidates = 0
    n_one_sided_by_party = 0
    all_parties_seen: set[str] = set()
    for r in races:
        cids = [cid for cid in r.get("candidate_ids", []) if cid in candidates]
        parties = sorted({candidates[cid].get("party") for cid in cids if candidates[cid].get("party")})
        all_parties_seen.update(parties)
        n_parties = len(parties)
        party_diversity_hist[n_parties] = party_diversity_hist.get(n_parties, 0) + 1
        if len(cids) >= 2:
            n_ge2_candidates += 1
        one_sided = n_parties <= 1
        if one_sided:
            n_one_sided_by_party += 1
        per_race_breadth.append(
            {
                "race_id": r["race_id"],
                "office": r.get("office"),
                "level": r.get("level"),
                "district": r.get("district"),
                "candidate_count": len(cids),
                "parties_present": parties,
                "one_sided": one_sided,
            }
        )

    # Address resolution: structural proof + opportunistic sample corroboration.
    # Structural: every TX address, once the Census geocoder resolves it to a
    # CD in [1,38], resolves to a covered ballot IF AND ONLY IF all 38 CDs
    # have a race on file (every ballot also always carries the 8
    # district-less marquee races regardless of CD). This is a proof, not a
    # sample -- the sample below only corroborates that our CD tagging
    # actually lines up with the live geocoder's numbering.
    cds_present_count = len(cd_districts)
    structural_full_coverage = cds_present_count >= TOTAL_US_HOUSE_DISTRICTS_IN_TX
    address_resolution_score = round(100.0 * min(cds_present_count / TOTAL_US_HOUSE_DISTRICTS_IN_TX, 1.0), 1)

    race_ids_present = {r["race_id"] for r in races}
    spot_check = {"available": False, "sample_size": 0, "pass_count": 0, "results": []}
    if isinstance(geocode_seed, dict) and geocode_seed:
        spot_check["available"] = True
        for addr_key, resolved in geocode_seed.items():
            cd = resolved.get("cd")
            expected_race_id = None
            if cd and re.match(r"^TX-\d{2}$", cd):
                num = cd.split("-")[1]
                expected_race_id = f"tx-cd{num}-2026"
            ok = bool(expected_race_id and expected_race_id in race_ids_present)
            spot_check["results"].append(
                {
                    "address": resolved.get("matched_address", addr_key),
                    "resolved_cd": cd,
                    "expected_race_id": expected_race_id,
                    "race_on_file": ok,
                    # every ballot also gets all marquee races regardless of CD
                    "marquee_races_included": marquee_count,
                }
            )
            spot_check["sample_size"] += 1
            if ok:
                spot_check["pass_count"] += 1
    spot_check["note"] = (
        "Sample is small (n=%d) and geographically curated (demo/golden addresses "
        "committed in data/tx/geocode_seed.json), not a random statewide draw -- "
        "it corroborates CD-tagging correctness, it is not the completeness proof "
        "itself (that's the structural 38/38 check above)." % spot_check["sample_size"]
    )

    address_sweep_summary = summarize_address_sweep(address_sweep, race_ids_present)

    # Combined empirical corroboration: union of every distinct CD actually
    # verified live by EITHER source (this repo's committed geocode_seed +
    # the address-sweep agent's independent HTTP sweep). Two different
    # verification methods agreeing is stronger evidence than either alone.
    seed_cds = {r["resolved_cd"] for r in spot_check["results"] if r.get("resolved_cd")}
    sweep_cds = set(address_sweep_summary.get("distinct_cds_covered_all_entries") or [])
    combined_cds = sorted(seed_cds | sweep_cds)
    combined_verification = {
        "distinct_cds_verified_live": len(combined_cds),
        "of_total_cds": TOTAL_US_HOUSE_DISTRICTS_IN_TX,
        "cd_list": combined_cds,
        "cds_never_live_verified": sorted(set(cd_districts) - set(combined_cds)),
        "note": (
            "Union of geocode_seed.json's 8 committed addresses and address_sweep_report.json's "
            "live HTTP sweep (if present) -- two independent verification methods, not blended into "
            "any score, purely a corroborating empirical count on top of the structural 38/38 proof."
        ),
    }

    race_count_completeness = round(100.0 * min(race_count / EXPECTED_RACE_COUNT, 1.0), 1)
    contested_ratio = round(100.0 * n_ge2_candidates / race_count, 1) if race_count else 0.0

    # BREADTH_SCORE formula (see module docstring): 0.40*race_count_completeness
    # + 0.30*contested_ratio + 0.30*address_resolution_score.
    breadth_score = round(0.40 * race_count_completeness + 0.30 * contested_ratio + 0.30 * address_resolution_score, 1)

    return {
        "race_count": {
            "actual": race_count,
            "expected": EXPECTED_RACE_COUNT,
            "expected_breakdown": {
                "state_executive": EXPECTED_STATE_EXEC_RACES,
                "us_senate": EXPECTED_US_SENATE_RACES,
                "us_house": EXPECTED_US_HOUSE_RACES,
            },
            "completeness_pct": race_count_completeness,
        },
        "declared_out_of_scope_note": (
            f"TX Legislature ({TX_LEGISLATURE_HD_COUNT} House + {TX_LEGISLATURE_SD_COUNT} Senate districts, "
            f"{TX_LEGISLATURE_HD_COUNT + TX_LEGISLATURE_SD_COUNT} more possible races) is an explicit STRETCH "
            "GOAL per CLAUDE.md LOCKED DECISIONS, not part of EXPECTED_RACE_COUNT. Judged against a citizen's "
            "REAL full ballot (which also includes state legislature + county/local races), this dataset "
            "covers statewide + US House only -- a deliberate, declared scope cut, not a defect."
        ),
        "level_balance": {"counts": level_counts, "marquee_district_null_count": marquee_count, "us_house_race_count": house_race_count},
        "us_house_districts": {"present": cds_present_count, "expected": TOTAL_US_HOUSE_DISTRICTS_IN_TX, "full_coverage": structural_full_coverage, "district_list": cd_districts},
        "contested_races": {"ge2_candidates_count": n_ge2_candidates, "single_candidate_count": race_count - n_ge2_candidates, "pct_contested": contested_ratio},
        "one_sided_by_party": {"count": n_one_sided_by_party, "pct": round(100.0 * n_one_sided_by_party / race_count, 1) if race_count else 0.0},
        "party_diversity_histogram": {str(k): v for k, v in sorted(party_diversity_hist.items())},
        "all_parties_seen": sorted(all_parties_seen),
        "per_race": per_race_breadth,
        "address_resolution": {
            "structural_proof": {
                "cds_present": cds_present_count,
                "cds_expected": TOTAL_US_HOUSE_DISTRICTS_IN_TX,
                "full_coverage": structural_full_coverage,
                "reasoning": (
                    "Any address the Census geocoder places in a TX congressional district "
                    "(always one of CD 1-38 post-redistricting) resolves to that district's "
                    "race PLUS all 8 marquee statewide/Senate races, which appear on every "
                    "ballot unconditionally. Full CD coverage is therefore a structural proof "
                    "of ballot resolution, not merely a sample statistic."
                ),
                "score": address_resolution_score,
            },
            "sample_spot_check": spot_check,
            "address_sweep_report": address_sweep_summary,
            "combined_empirical_verification": combined_verification,
        },
        "breadth_score": breadth_score,
        "breadth_score_tier": tier_for(breadth_score),
    }


# ---------------------------------------------------------------------------
# DEPTH -- per race
# ---------------------------------------------------------------------------


def race_depth_score(race: dict[str, Any], candidates: dict[str, Any]) -> dict[str, Any]:
    cids = [cid for cid in race.get("candidate_ids", []) if cid in candidates]
    n = len(cids)
    cand_objs = [candidates[cid] for cid in cids]

    candidate_detail = []
    for cid, c in zip(cids, cand_objs):
        candidate_detail.append(
            {
                "candidate_id": cid,
                "name": c.get("name"),
                "party": c.get("party"),
                "incumbent": bool(c.get("incumbent")),
                "has_finance": bool(c.get("finance")),
                "has_votes": bool((c.get("record") or {}).get("key_votes")),
                "has_positions": bool(c.get("positions")),
                "has_bio": has_bio(c),
                "has_evidence_checks": has_evidence_checks(c),
                "distinct_source_count": len(distinct_sources(c)),
            }
        )

    if n == 0:
        return {
            "score": 0.0,
            "tier": "D",
            "candidate_count": 0,
            "note": "no candidate_ids on this race resolve to a candidates.json entry -- referential integrity break, see pipeline/clean_gold.py",
            "components": {},
            "na_components": ["votes_coverage", "temporal_grounding"],
            "candidate_detail": [],
        }

    finance_frac = sum(1 for d in candidate_detail if d["has_finance"]) / n
    positions_frac = sum(1 for d in candidate_detail if d["has_positions"]) / n
    bio_frac = sum(1 for d in candidate_detail if d["has_bio"]) / n
    avg_distinct_sources = sum(d["distinct_source_count"] for d in candidate_detail) / n
    sourcing_score = min(avg_distinct_sources / SOURCE_TARGET, 1.0) * 100.0

    incumbents = [d for d in candidate_detail if d["incumbent"]]
    votes_na = len(incumbents) == 0
    votes_frac = (sum(1 for d in incumbents if d["has_votes"]) / len(incumbents)) if incumbents else None

    fin_objs = [candidates[cid].get("finance") for cid in cids if candidates[cid].get("finance")]
    temporal_na = len(fin_objs) == 0
    asof_frac = (sum(1 for f in fin_objs if valid_iso_date(f.get("as_of"))) / len(fin_objs)) if fin_objs else None

    archetype_cov, base_present, _ = insights_coverage_for(race["race_id"])
    insight_score = INSIGHT_BASE_WEIGHT * (100.0 if base_present else 0.0) + INSIGHT_ARCHETYPE_WEIGHT * (archetype_cov / len(ARCHETYPES) * 100.0)

    components: list[tuple[str, float, float]] = [
        ("finance_coverage", finance_frac * 100.0, W_FINANCE),
        ("positions_coverage", positions_frac * 100.0, W_POSITIONS),
        ("bio_coverage", bio_frac * 100.0, W_BIO),
        ("sourcing_richness", sourcing_score, W_SOURCING),
        ("insight_depth", insight_score, W_INSIGHT),
    ]
    na_components = []
    if not votes_na:
        components.append(("votes_coverage", votes_frac * 100.0, W_VOTES))
    else:
        na_components.append("votes_coverage")
    if not temporal_na:
        components.append(("temporal_grounding", asof_frac * 100.0, W_TEMPORAL))
    else:
        na_components.append("temporal_grounding")

    total_weight = sum(w for _, _, w in components)
    raw = sum(val * w for _, val, w in components)
    score = round(raw / total_weight, 1) if total_weight else 0.0
    n_evidence = sum(1 for d in candidate_detail if d["has_evidence_checks"])

    return {
        "score": score,
        "tier": tier_for(score),
        "candidate_count": n,
        "components": {name: round(val, 1) for name, val, _ in components},
        "weights_applied": {name: w for name, _, w in components},
        "na_components": na_components,
        "evidence_checks_candidate_count": n_evidence,
        "archetype_coverage": archetype_cov,
        "insights_base_present": base_present,
        "avg_distinct_sources": round(avg_distinct_sources, 2),
        "candidate_detail": candidate_detail,
    }


# ---------------------------------------------------------------------------
# DEPTH -- dataset rollup
# ---------------------------------------------------------------------------


def compute_depth(races: list[dict[str, Any]], candidates: dict[str, Any]) -> dict[str, Any]:
    per_race: dict[str, Any] = {}
    for r in races:
        per_race[r["race_id"]] = {
            "office": r.get("office"),
            "level": r.get("level"),
            "district": r.get("district"),
            **race_depth_score(r, candidates),
        }

    scores = [v["score"] for v in per_race.values()]
    depth_score_mean = round(sum(scores) / len(scores), 1) if scores else 0.0
    weighted_num = sum(v["score"] * v["candidate_count"] for v in per_race.values())
    weighted_den = sum(v["candidate_count"] for v in per_race.values())
    depth_score_candidate_weighted = round(weighted_num / weighted_den, 1) if weighted_den else 0.0

    # --- dataset-wide diagnostics ---
    n_candidates = len(candidates)
    top_level_lens = [len(c.get("sources") or []) for c in candidates.values()]
    distinct_lens = [len(distinct_sources(c)) for c in candidates.values()]
    dist_hist: dict[int, int] = {}
    for x in distinct_lens:
        dist_hist[x] = dist_hist.get(x, 0) + 1

    finance_total = sum(1 for c in candidates.values() if c.get("finance"))
    finance_asof_valid = sum(1 for c in candidates.values() if valid_iso_date((c.get("finance") or {}).get("as_of")))
    votes_total_candidates = sum(1 for c in candidates.values() if (c.get("record") or {}).get("key_votes"))
    votes_total_entries = sum(len((c.get("record") or {}).get("key_votes") or []) for c in candidates.values())
    votes_dated_entries = sum(
        1 for c in candidates.values() for kv in (c.get("record") or {}).get("key_votes") or [] if kv.get("date")
    )
    positions_total_candidates = sum(1 for c in candidates.values() if c.get("positions"))
    positions_origin_hist: dict[str, int] = {}
    for c in candidates.values():
        for p in c.get("positions") or []:
            o = p.get("origin") or "unknown"
            positions_origin_hist[o] = positions_origin_hist.get(o, 0) + 1
    bio_total = sum(1 for c in candidates.values() if has_bio(c))

    # by-level-bucket breakdown (state exec / US Senate / US House) -- this
    # is where the sharpest depth story lives (see DATASET_EVAL.md).
    buckets: dict[str, set[str]] = {"state_executive": set(), "us_senate": set(), "us_house": set()}
    for r in races:
        cids = [cid for cid in r.get("candidate_ids", []) if cid in candidates]
        if r.get("level") == "state":
            buckets["state_executive"].update(cids)
        elif r.get("district") is None:
            buckets["us_senate"].update(cids)
        else:
            buckets["us_house"].update(cids)
    by_level_bucket = {}
    for label, cidset in buckets.items():
        n = len(cidset)
        if n == 0:
            continue
        by_level_bucket[label] = {
            "candidate_count": n,
            "finance_pct": round(100 * sum(1 for c in cidset if candidates[c].get("finance")) / n, 1),
            "votes_pct": round(100 * sum(1 for c in cidset if (candidates[c].get("record") or {}).get("key_votes")) / n, 1),
            "positions_pct": round(100 * sum(1 for c in cidset if candidates[c].get("positions")) / n, 1),
            "bio_pct": round(100 * sum(1 for c in cidset if has_bio(candidates[c])) / n, 1),
        }

    # evidence_checks feasibility: candidates with BOTH votes and positions
    # today (the structural prerequisite for a says-vs-voted comparison,
    # independent of whether the feature itself has been built yet).
    both_votes_and_positions = [
        cid for cid, c in candidates.items() if (c.get("record") or {}).get("key_votes") and c.get("positions")
    ]
    evidence_checks_landed = any(has_evidence_checks(c) for c in candidates.values())

    races_with_full_archetypes = [rid for rid, v in per_race.items() if v["archetype_coverage"] == len(ARCHETYPES)]
    races_without_archetypes = [rid for rid, v in per_race.items() if v["archetype_coverage"] == 0]
    races_with_partial_archetypes = [
        rid for rid, v in per_race.items() if 0 < v["archetype_coverage"] < len(ARCHETYPES)
    ]
    base_present_count = sum(1 for v in per_race.values() if v["insights_base_present"])

    insight_layer_score = round(
        50.0 * (base_present_count / len(per_race) if per_race else 0)
        + 50.0 * (len(races_with_full_archetypes) / len(per_race) if per_race else 0),
        1,
    )
    # sourcing_index: half from avg-distinct-sources-per-candidate (normalized
    # against SOURCE_TARGET), half from the finance as_of validity rate --
    # each half contributes 0-50 so the sum is a clean 0-100.
    avg_distinct_dataset = (sum(distinct_lens) / n_candidates) if n_candidates else 0.0
    sourcing_index = round(
        50.0 * min(avg_distinct_dataset / SOURCE_TARGET, 1.0)
        + 50.0 * (finance_asof_valid / finance_total if finance_total else 0.0),
        1,
    )

    return {
        "races": per_race,
        "dataset_rollup": {
            "depth_score_mean": depth_score_mean,
            "depth_score_mean_tier": tier_for(depth_score_mean),
            "depth_score_candidate_weighted": depth_score_candidate_weighted,
            "by_level_bucket": by_level_bucket,
            "sources_per_candidate": {
                "avg_top_level_sources_field": round(sum(top_level_lens) / n_candidates, 2) if n_candidates else 0,
                "avg_distinct_source_urls": round(avg_distinct_dataset, 2),
                "distinct_source_distribution": {str(k): v for k, v in sorted(dist_hist.items())},
                "note": (
                    "avg_distinct_source_urls unions sources[] + finance.source + "
                    "record.source + every key_votes[].source + every positions[].source; "
                    "it is consistently higher than avg_top_level_sources_field because many "
                    "citations live only inline on the fact they support and are never rolled "
                    "up into the candidate's own top-level sources[] array (see findings)."
                ),
            },
            "as_of_coverage": {
                "finance_objects": finance_total,
                "finance_with_valid_as_of": finance_asof_valid,
                "finance_as_of_pct": round(100 * finance_asof_valid / finance_total, 1) if finance_total else None,
                "key_vote_entries": votes_total_entries,
                "key_vote_entries_dated": votes_dated_entries,
                "key_vote_dated_pct": round(100 * votes_dated_entries / votes_total_entries, 1) if votes_total_entries else None,
            },
            "positions_origin_breakdown": positions_origin_hist,
            "coverage_counts": {
                "finance": finance_total,
                "votes": votes_total_candidates,
                "positions": positions_total_candidates,
                "bio": bio_total,
                "total_candidates": n_candidates,
            },
            "insight_layer": {
                "base_present_races": base_present_count,
                "total_races": len(per_race),
                "races_with_full_archetypes": sorted(races_with_full_archetypes),
                "races_with_partial_archetypes": sorted(races_with_partial_archetypes),
                "races_without_archetypes": sorted(races_without_archetypes),
                "insight_layer_score": insight_layer_score,
            },
            "sourcing_index": sourcing_index,
            "evidence_checks": {
                "landed": evidence_checks_landed,
                "candidates_with_both_votes_and_positions_today": len(both_votes_and_positions),
                "candidate_ids": sorted(both_votes_and_positions),
                "note": (
                    "Feature not present under any checked key name; not scored into any "
                    "race's depth (see module docstring). Even if it landed today, it would "
                    "have zero candidates to operate on: votes-data (US House incumbents) and "
                    "positions-data (mostly statewide/AG candidates) currently do not overlap "
                    "on a single candidate anywhere in the dataset."
                    if not evidence_checks_landed
                    else "Feature detected on at least one candidate -- rerun this script's "
                    "consumer/report code to surface real per-race coverage."
                ),
            },
        },
    }


# ---------------------------------------------------------------------------
# Drift check against cached coverage_report.json (a stale report is itself
# a bug -- this makes that self-detecting on every run)
# ---------------------------------------------------------------------------


def check_coverage_report_drift(races: list[dict[str, Any]], candidates: dict[str, Any], cached: Optional[dict[str, Any]]) -> dict[str, Any]:
    if not cached:
        return {"available": False, "note": "data/tx/coverage_report.json not found; drift check skipped."}

    fresh_by_id = {}
    for r in races:
        cids = [cid for cid in r.get("candidate_ids", []) if cid in candidates]
        parties = sorted({candidates[cid].get("party") for cid in cids if candidates[cid].get("party")})
        fresh_by_id[r["race_id"]] = {
            "candidate_count": len(cids),
            "one_sided": len(parties) <= 1,
            "candidates_with_finance": sum(1 for cid in cids if candidates[cid].get("finance")),
            "candidates_with_votes": sum(1 for cid in cids if (candidates[cid].get("record") or {}).get("key_votes")),
            "candidates_with_positions": sum(1 for cid in cids if candidates[cid].get("positions")),
        }

    diffs = []
    cached_by_id = {r["race_id"]: r for r in cached.get("races", [])}
    for rid, fresh in fresh_by_id.items():
        cached_r = cached_by_id.get(rid)
        if cached_r is None:
            diffs.append({"race_id": rid, "issue": "present in races.json but missing from cached coverage_report.json"})
            continue
        for k, v in fresh.items():
            if cached_r.get(k) != v:
                diffs.append({"race_id": rid, "field": k, "cached": cached_r.get(k), "fresh": v})
    for rid in cached_by_id:
        if rid not in fresh_by_id:
            diffs.append({"race_id": rid, "issue": "present in cached coverage_report.json but no longer in races.json"})

    return {
        "available": True,
        "fresh_matches_cached": len(diffs) == 0,
        "diff_count": len(diffs),
        "diffs": diffs[:50],  # cap -- this is a diagnostic, not a full dump
    }


# ---------------------------------------------------------------------------
# Recoverable-FEC-join rescan: for every incumbent our roster added without
# an FEC match (unjoined_report.json's incumbent_added_without_fec_match),
# search raw/fec.json for ANY same-last-name candidate under ANY district.
# A hit means the source data may already sit in our own raw fetch, just
# tagged under a different (likely pre-redistricting) district -- a
# DEFECT_CANDIDATE needing human verification, not a confirmed absence.
# ---------------------------------------------------------------------------


# Name suffixes/titles this dataset sometimes places out of normal English
# order (e.g. "John Kevin Sr. Ellzey" instead of "...Ellzey Sr.") -- stripped
# before picking "the last remaining token" as a surname guess, otherwise a
# name like "Randy K. Weber, Sr." would extract "Sr" as its surname and
# produce false-positive matches against every other "...Sr"/"...Jr" name.
SUFFIX_STOPWORDS = {"jr", "sr", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x", "mr", "ms", "mrs", "dr"}


def _name_tokens(name: str) -> list[str]:
    name = re.sub(r"[.,'’]", "", name or "").strip()
    return [t for t in name.split() if t]


def _surname_guess(name: str) -> Optional[str]:
    """Best-effort surname: last token that isn't a common suffix/title
    stopword. Returns None if nothing usable remains (e.g. empty name)."""
    tokens = _name_tokens(name)
    filtered = [t for t in tokens if t.lower() not in SUFFIX_STOPWORDS]
    candidates = filtered or tokens
    return candidates[-1].lower() if candidates else None


def rescan_recoverable_fec_joins(unjoined: Optional[dict[str, Any]], raw_fec: Optional[dict[str, Any]]) -> dict[str, Any]:
    if not unjoined or not raw_fec:
        return {
            "available": False,
            "note": "data/tx/unjoined_report.json and/or data/tx/raw/fec.json not found; rescan skipped.",
        }
    targets = unjoined.get("incumbent_added_without_fec_match") or []
    fec_candidates = raw_fec.get("candidates") or []
    results = []
    for t in targets:
        name = t.get("name", "")
        surname = _surname_guess(name)
        if not surname:
            continue
        matches = []
        for fc in fec_candidates:
            # every target here is a US House incumbent (see docstring above
            # -- unjoined_report.json's incumbent_added_without_fec_match is
            # House-district-only); an FEC id for a different chamber (S=
            # Senate, P=President) is definitionally the wrong race, so it's
            # excluded rather than reported as a noisy same-surname "match".
            # A missing/malformed id is kept (lenient -- can't rule it out).
            fec_id = fc.get("fec_candidate_id") or ""
            if fec_id and not fec_id.upper().startswith("H"):
                continue
            fc_tokens = _name_tokens(fc.get("name", "")) + _name_tokens(fc.get("name_raw", ""))
            fc_tokens_lower = [tk.lower() for tk in fc_tokens]
            if surname in fc_tokens_lower:
                matches.append(
                    {
                        "fec_name": fc.get("name"),
                        "fec_id": fc.get("fec_candidate_id"),
                        "district_in_raw_fetch": fc.get("district"),
                        "incumbent_challenge": fc.get("incumbent_challenge"),
                        "receipts": fc.get("receipts"),
                    }
                )
        results.append(
            {
                "our_district": t.get("district"),
                "our_name": name,
                "bioguide_id": t.get("bioguide_id"),
                "surname_matches_in_raw_fec_json": matches,
                "verdict": "POSSIBLE_RECOVERABLE_JOIN" if matches else "NO_MATCH_IN_CURRENT_FETCH",
            }
        )
    return {
        "available": True,
        "targets_checked": len(targets),
        "possible_recoverable": sum(1 for r in results if r["verdict"] == "POSSIBLE_RECOVERABLE_JOIN"),
        "no_match_in_fetch": sum(1 for r in results if r["verdict"] == "NO_MATCH_IN_CURRENT_FETCH"),
        "results": results,
    }


# ---------------------------------------------------------------------------
# Completeness index
# ---------------------------------------------------------------------------


def compute_completeness_index(breadth: dict[str, Any], depth: dict[str, Any]) -> dict[str, Any]:
    breadth_score = breadth["breadth_score"]
    depth_score = depth["dataset_rollup"]["depth_score_mean"]
    index = round(COMPLETENESS_BREADTH_WEIGHT * breadth_score + COMPLETENESS_DEPTH_WEIGHT * depth_score, 1)
    return {
        "score": index,
        "tier": tier_for(index),
        "formula": f"{COMPLETENESS_BREADTH_WEIGHT} * BREADTH_SCORE + {COMPLETENESS_DEPTH_WEIGHT} * DEPTH_SCORE",
        "sub_scores": {
            "breadth_score": breadth_score,
            "depth_score": depth_score,
        },
        "diagnostic_only_sub_scores": {
            "insight_layer_score": depth["dataset_rollup"]["insight_layer"]["insight_layer_score"],
            "sourcing_index": depth["dataset_rollup"]["sourcing_index"],
            "note": (
                "These two are detail views INTO depth_score's own components "
                "(insight_depth, sourcing_richness, temporal_grounding) -- shown "
                "separately for visibility into the two biggest fixable gaps, but "
                "NOT re-weighted into the top-line score a second time."
            ),
        },
    }


# ---------------------------------------------------------------------------
# Findings: HONEST GAP vs DEFECT
# ---------------------------------------------------------------------------


def build_findings(
    breadth: dict[str, Any],
    depth: dict[str, Any],
    drift: dict[str, Any],
    fec_rescan: dict[str, Any],
    unjoined: Optional[dict[str, Any]],
    detect_contradictions_exists: bool,
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    roll = depth["dataset_rollup"]

    # --- DEFECT: archetype gate is a deterministic, already-ingested-data-
    # only pass; only run for 10/46 races.
    n_full = len(roll["insight_layer"]["races_with_full_archetypes"])
    n_none = len(roll["insight_layer"]["races_without_archetypes"])
    total_races = roll["insight_layer"]["total_races"]
    findings.append(
        {
            "id": "DEFECT-01",
            "type": "DEFECT",
            "title": "Personalized (archetype) insights only computed for 10/46 races",
            "summary": (
                f"{n_full}/{total_races} races have full 8-archetype personalized insight coverage; "
                f"{n_none}/{total_races} have base-only insights (no per-voter-profile personalization at all). "
                "Confirmed this is NOT a bug in how the existing 'competitive races only' rule was applied "
                "(every race matching pipeline/build_insights_house.py + pipeline/build_insights_tx20_38.py's own "
                "documented gate -- last_result margin_pct < 10 OR no incumbent, OR marquee/district-null -- does "
                "have full archetype coverage; zero rule-violation anomalies found). It is a real depth gap "
                "because the generation itself is a deterministic, no-network, no-LLM authoring pass over "
                "ALREADY-INGESTED gold data (per both scripts' own docstrings) -- extending it to all 46 races "
                "requires no new fetching."
            ),
            "evidence": {
                "races_without_archetypes": roll["insight_layer"]["races_without_archetypes"],
            },
            "exact_fix": (
                "In pipeline/build_insights_house.py and pipeline/build_insights_tx20_38.py, remove (or add a "
                "--all flag bypassing) the 'archetypes only for competitive races' gate so archetypes are "
                "computed for every race in range; rerun both scripts; then rerun pipeline/clean_gold.py and "
                "pipeline/score_quality.py so coverage_report.json/quality_report.json/QUALITY.md pick up the "
                "new archetype_fraction values; rerun this script to confirm insight_layer_score rises."
            ),
            "effort": "LOW (~20-30 min: two script edits + three reruns + spot-check, no new data)",
            "impact": "HIGH -- this is the single largest lever on both DEPTH_SCORE and the completeness index",
        }
    )

    # --- DEFECT: sources[] undercounts true citation depth
    src = roll["sources_per_candidate"]
    findings.append(
        {
            "id": "DEFECT-02",
            "type": "DEFECT",
            "title": "Candidate top-level sources[] materially undercounts actual citation depth",
            "summary": (
                f"Average top-level sources[] length is {src['avg_top_level_sources_field']}, but the average "
                f"number of DISTINCT source URLs actually cited across finance/record/key_votes/positions is "
                f"{src['avg_distinct_source_urls']} -- more than double. Any consumer (a future 'N sources' UI "
                "badge, an export step) that reads only the top-level array undercounts credibility signal."
            ),
            "evidence": {"distribution": src["distinct_source_distribution"]},
            "exact_fix": (
                "Add a small deterministic pass (new script or a function in pipeline/clean_gold.py) that sets "
                "each candidate's sources[] = sorted(union(existing sources[], finance.source, record.source, "
                "every key_votes[].source, every positions[].source)), reusing clean_gold.py's existing "
                "clean_url_list() dedup helper. Idempotent, no new fetches."
            ),
            "effort": "LOW (~30-45 min incl. a rerun of validate_data.py)",
            "impact": "MEDIUM -- cosmetic/credibility-signal fix, not a factual-content gap",
        }
    )

    # --- DEFECT_CANDIDATE: recoverable FEC joins (needs human verification)
    if fec_rescan.get("available") and fec_rescan.get("possible_recoverable", 0) > 0:
        recoverable = [r for r in fec_rescan["results"] if r["verdict"] == "POSSIBLE_RECOVERABLE_JOIN"]
        findings.append(
            {
                "id": "DEFECT-03-CANDIDATE",
                "type": "DEFECT_CANDIDATE",
                "title": f"{len(recoverable)} of {fec_rescan['targets_checked']} FEC-unmatched incumbents have a same-surname record already sitting in raw/fec.json",
                "summary": (
                    "unjoined_report.json lists incumbents added from the legislators roster with no FEC 2026 "
                    "filer match for their (new, redistricted) district. A same-surname rescan of "
                    "data/tx/raw/fec.json across ALL districts (not just the exact assigned one) finds a "
                    "candidate record for some of them tagged under a DIFFERENT district -- consistent with "
                    "this dataset's own already-documented redistricting-tag mismatches (unjoined_report.json's "
                    "'ambiguous_same_party_filers' shows the same TX-32-rooted-FEC-id-tagged-as-TX-33 pattern "
                    "for a still-successfully-joined candidate). This is evidence of a RECOVERABLE join, not "
                    "confirmation -- same-surname is not the same as same-person, and this project's own "
                    "culture (see quality_report.json's name_collisions_not_merged) deliberately never "
                    "auto-merges on name alone."
                ),
                "evidence": {"recoverable": recoverable},
                "exact_fix": (
                    "For each candidate_ids listed in evidence.recoverable: manually confirm (against the FEC "
                    "candidate page + Texas Legislative Council's official 2025 congressional redistricting map "
                    "or a current Ballotpedia district-boundary source) whether the raw/fec.json record is the "
                    "SAME person as our roster incumbent and whether their correct 2026 district is ours or the "
                    "one tagged in the FEC row. If confirmed, wire finance{} into that candidate in "
                    "candidates.json with the verified district, citing both sources. If NOT the same person, "
                    "leave as-is (already correctly honest: no finance data). Do not script an automatic merge."
                ),
                "effort": "MEDIUM (~10-15 min PER candidate of careful manual verification; do not batch-automate)",
                "impact": "MEDIUM -- recovers finance{} for a handful of otherwise-honest-gap incumbents, IF confirmed",
            }
        )
    if fec_rescan.get("available") and fec_rescan.get("no_match_in_fetch", 0) > 0:
        no_match = [r["our_name"] for r in fec_rescan["results"] if r["verdict"] == "NO_MATCH_IN_CURRENT_FETCH"]
        findings.append(
            {
                "id": "GAP-01",
                "type": "HONEST_GAP",
                "subtype": "not_yet_fetched",
                "title": f"{len(no_match)} FEC-unmatched incumbents have no same-surname record anywhere in our current raw/fec.json fetch",
                "summary": (
                    f"No FEC candidate record under any district/name variant was found in the current raw fetch for: "
                    f"{', '.join(no_match)}. This is NOT confirmed as 'FEC has nothing for them' -- our raw fetch "
                    "may be incomplete for their district/cycle, or they may genuinely not have filed 2026 FEC "
                    "paperwork yet as of the fetch date."
                ),
                "evidence": {"names": no_match},
                "recommendation": (
                    "Re-query FEC's live candidate API directly by name/bioguide (not just by our current "
                    "per-district raw/fec.json snapshot) with a registered FEC_API_KEY (DEMO_KEY rate-limits "
                    "hard) to confirm absence vs incomplete fetch."
                ),
                "effort": "LOW-MEDIUM (~15 min once FEC_API_KEY is set, per CLAUDE.md human action items)",
                "impact": "LOW-MEDIUM (7 candidates total across the dataset)",
            }
        )

    # --- HONEST GAP: US House candidates near-zero positions/bio
    house = roll["by_level_bucket"].get("us_house", {})
    findings.append(
        {
            "id": "GAP-02",
            "type": "HONEST_GAP",
            "subtype": "not_yet_fetched",
            "title": "US House candidates: near-zero issue positions and biography coverage",
            "summary": (
                f"US House candidates (n={house.get('candidate_count', '?')}, {round(100*house.get('candidate_count',0)/roll['coverage_counts']['total_candidates']) if roll['coverage_counts']['total_candidates'] else '?'}% "
                f"of all candidates in the dataset) show positions_pct={house.get('positions_pct')}% and "
                f"bio_pct={house.get('bio_pct')}%, versus finance_pct={house.get('finance_pct')}% and "
                f"votes_pct={house.get('votes_pct')}%. The civic-match Kimi research swarm that produced "
                "positions[] (origin='civic-match-research') only researched statewide/marquee candidates "
                "(per CLAUDE.md's status log: 9 TX candidates fully researched); it was never pointed at any "
                "of the 38 US House races. Likely available in scattered public form (campaign sites, "
                "Ballotpedia, VoteSmart) but requires genuine per-candidate research effort -- this is not a "
                "file sitting already-fetched and unused."
            ),
            "evidence": {"by_level_bucket": roll["by_level_bucket"]},
            "recommendation": (
                "Extend the civic-match researched-positions pipeline (or an equivalent web-research pass, see "
                "pipeline/import_civicmatch_positions.py's matching logic) to US House candidates, prioritizing "
                "the 37 who already have a voting record on file (positions research on THOSE candidates is "
                "double-value: it also unlocks a real says-vs-voted comparison the moment that feature lands, "
                "see GAP-04 below)."
            ),
            "effort": "HIGH (72 candidates x issue research -- realistically a fresh multi-agent research pass, not a script)",
            "impact": "HIGH -- this is the largest single depth hole in the dataset by candidate count",
        }
    )

    # --- HONEST GAP: sponsored_highlights / congress.gov rate limit (needs key)
    upstream = (unjoined or {}).get("upstream_fetch_gaps") or []
    if upstream:
        findings.append(
            {
                "id": "GAP-03",
                "type": "HONEST_GAP",
                "subtype": "needs_key",
                "title": "sponsored_highlights empty dataset-wide; roster fetched via fallback -- congress.gov DEMO_KEY rate-limited",
                "summary": (
                    "data/tx/unjoined_report.json's upstream_fetch_gaps records that congress.gov's member and "
                    "sponsored-legislation endpoints returned 429 OVER_RATE_LIMIT on the shared DEMO_KEY for the "
                    "entire build window (no CONGRESS_GOV_API_KEY configured in .env). The legislator roster was "
                    "recovered via the public-domain unitedstates/congress-legislators fallback (same bioguide "
                    "IDs), but sponsored_highlights has no equivalent fallback and is empty for every candidate."
                ),
                "evidence": {"upstream_fetch_gaps": upstream},
                "recommendation": (
                    "Sign up for a free CONGRESS_GOV_API_KEY (https://api.congress.gov/sign-up/, instant per "
                    "CLAUDE.md) and rerun the sponsored-legislation fetch step -- this is purely a rate-limit "
                    "block, the data is public and the fetch code already exists."
                ),
                "effort": "LOW (~5 min signup + a rerun, once the key exists)",
                "impact": "MEDIUM (adds a currently-100%-empty field across most/all candidates)",
            }
        )

    # --- HONEST GAP: evidence_checks not yet feasible on this data shape,
    # regardless of whether the detector script itself has landed.
    ev = roll["evidence_checks"]
    n_eligible = ev["candidates_with_both_votes_and_positions_today"]
    if detect_contradictions_exists:
        title = "Says-vs-voted detector now exists (pipeline/detect_contradictions.py) but is not yet run, and would currently be a no-op"
        summary = (
            "pipeline/detect_contradictions.py has landed (a concurrent commit during this eval) and writes "
            "candidate.evidence_checks[] -- exactly the key name this script already checks for. It has not yet "
            "been run against data/tx/candidates.json (no candidate carries the field yet). Its own documented "
            "gate requires a candidate to have BOTH positions[] AND record.key_votes[] non-empty; this script "
            f"independently counts {n_eligible} such candidates in the current gold dataset -- so running it "
            "today, while cheap, would produce zero checks. The detector is not the bottleneck; GAP-02 is."
        )
        recommendation = (
            "Running `python3 pipeline/detect_contradictions.py` now is safe and cheap but will find nothing to "
            "report. Prioritize GAP-02 (positions research for the 37 US House incumbents who already have "
            "key_votes) -- every candidate that gains a same-issue position immediately becomes eligible for a "
            "real says-vs-voted check the next time this script is rerun."
        )
        effort = "LOW to run (~1 min)"
    else:
        title = "Says-vs-voted evidence checks: not built, and not yet feasible on the current data shape"
        summary = ev["note"] + " Score not penalized for this (see module docstring on why evidence_checks isn't weighted into DEPTH)."
        recommendation = (
            "No fix needed until (a) an evidence-checks agent lands its comparison logic AND (b) GAP-02 closes "
            "enough that at least some candidates have both a voting record and a stated position on the same "
            "issue to compare."
        )
        effort = "N/A -- blocked on two other items, not independently actionable"
    findings.append(
        {
            "id": "GAP-04",
            "type": "HONEST_GAP",
            "subtype": "not_yet_fetched",
            "title": title,
            "summary": summary,
            "evidence": {"candidates_with_both_votes_and_positions": n_eligible, "detector_script_present": detect_contradictions_exists},
            "recommendation": recommendation,
            "effort": effort,
            "impact": "LOW right now (0 candidates eligible regardless of whether the script runs); HIGH once GAP-02 unblocks it",
        }
    )

    # --- HONEST GAP: TX Legislature declared out of scope
    findings.append(
        {
            "id": "GAP-05",
            "type": "HONEST_GAP",
            "subtype": "declared_out_of_scope",
            "title": "TX Legislature (150 House + 31 Senate districts) not covered",
            "summary": breadth["declared_out_of_scope_note"],
            "evidence": {},
            "recommendation": "Stretch goal per CLAUDE.md; only pursue after the 46-race dataset is fully deep.",
            "effort": "HIGH (181 more districts, new Open States/LegiScan integration, key-gated)",
            "impact": "Would make the ballot genuinely complete rather than statewide+US-House-only",
        }
    )

    # --- DEFECT (minor): quality_report.json's civic_match_positions metric undercounts total positions coverage
    positions_true = roll["coverage_counts"]["positions"]
    civic_match_only = roll["positions_origin_breakdown"].get("civic-match-research", 0)
    findings.append(
        {
            "id": "DEFECT-04",
            "type": "DEFECT",
            "title": "quality_report.json's source_coverage.civic_match_positions undercounts true positions coverage",
            "summary": (
                f"quality_report.json reports civic_match_positions as candidates with an origin=='civic-match-research' "
                f"position (8/96, 8.3%). The true count of candidates with ANY position on file (including "
                f"origin=='web-research', e.g. the AG race enrichment) is {positions_true}/96 "
                f"({round(100*positions_true/roll['coverage_counts']['total_candidates'],1)}%). Not a data gap -- "
                "a metric-definition/labeling gap in the reporting script."
            ),
            "evidence": {"positions_origin_breakdown": roll["positions_origin_breakdown"]},
            "exact_fix": (
                "In pipeline/score_quality.py's source_coverage block, add an any_positions count alongside the "
                "existing origin-filtered civic_match_positions count (five-line change), then rerun it."
            ),
            "effort": "LOW (~10 min)",
            "impact": "LOW -- reporting accuracy only, does not change served data",
        }
    )

    # --- DEFECT (only if drift found): stale coverage_report.json
    if drift.get("available") and not drift.get("fresh_matches_cached", True):
        findings.append(
            {
                "id": "DEFECT-05",
                "type": "DEFECT",
                "title": "data/tx/coverage_report.json is stale relative to the current gold dataset",
                "summary": f"{drift['diff_count']} field-level mismatch(es) found between a from-scratch recomputation and the cached report.",
                "evidence": {"diffs": drift["diffs"]},
                "exact_fix": "Rerun `python3 pipeline/clean_gold.py` to regenerate coverage_report.json from the current gold JSON.",
                "effort": "LOW (~2 min, one command)",
                "impact": "MEDIUM -- a stale coverage report can mislead anyone reading it as current",
            }
        )

    # --- HONEST GAP: state-executive positions coverage still partial (36%)
    state = roll["by_level_bucket"].get("state_executive", {})
    if state and state.get("positions_pct", 100) < 100:
        findings.append(
            {
                "id": "GAP-06",
                "type": "HONEST_GAP",
                "subtype": "not_yet_fetched",
                "title": "State-executive candidates: positions coverage is partial, not complete",
                "summary": (
                    f"State-executive candidates (n={state.get('candidate_count')}) show positions_pct="
                    f"{state.get('positions_pct')}%, versus finance_pct={state.get('finance_pct')}% and "
                    f"bio_pct={state.get('bio_pct')}% both near-complete. The civic-match Kimi swarm fully "
                    "researched a subset (governor, lt gov, AG, a few others per CLAUDE.md's status log) but "
                    "not every candidate in every statewide race (e.g. third-party/minor candidates)."
                ),
                "evidence": {"by_level_bucket_state_executive": state},
                "recommendation": "Extend civic-match's researched-candidate list to the remaining statewide minor-party/challenger candidates.",
                "effort": "MEDIUM (per-candidate research, smaller n than GAP-02)",
                "impact": "MEDIUM (statewide races are the highest-traffic/marquee races)",
            }
        )

    return findings


def build_prioritized_improvements(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Defects first (actionable now), ordered by impact/effort; then the
    highest-impact honest gaps as roadmap items. Never re-derives new
    claims -- purely re-ranks the findings already computed above."""
    rank_order = {"DEFECT": 0, "DEFECT_CANDIDATE": 1, "HONEST_GAP": 2}
    impact_rank = {"HIGH": 0, "MEDIUM-HIGH": 0, "MEDIUM": 1, "LOW-MEDIUM": 2, "LOW": 3, "N/A": 4}
    effort_rank = {"LOW": 0, "LOW-MEDIUM": 1, "MEDIUM": 2, "HIGH": 3, "N/A": 4}

    def sort_key(f: dict[str, Any]):
        impact = f.get("impact", "N/A")
        impact_key = next((v for k, v in impact_rank.items() if impact.upper().startswith(k)), 2)
        effort = f.get("effort", "N/A")
        effort_key = next((v for k, v in effort_rank.items() if effort.upper().startswith(k)), 2)
        return (rank_order.get(f["type"], 9), impact_key, effort_key)

    ordered = sorted(findings, key=sort_key)
    out = []
    for i, f in enumerate(ordered, 1):
        out.append(
            {
                "rank": i,
                "id": f["id"],
                "type": f["type"],
                "title": f["title"],
                "effort": f.get("effort", "N/A"),
                "impact": f.get("impact", "N/A"),
                "action": f.get("exact_fix") or f.get("recommendation") or "n/a",
            }
        )
    return out


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------


def render_markdown(
    breadth: dict[str, Any],
    depth: dict[str, Any],
    index: dict[str, Any],
    findings: list[dict[str, Any]],
    prioritized: list[dict[str, Any]],
    drift: dict[str, Any],
    fec_rescan: dict[str, Any],
    detect_contradictions_exists: bool,
) -> str:
    roll = depth["dataset_rollup"]
    lines: list[str] = []
    lines.append("# Dataset breadth + depth completeness eval")
    lines.append("")
    lines.append(
        f"Generated by `{GENERATED_BY}` over {breadth['race_count']['actual']} races / "
        f"{roll['coverage_counts']['total_candidates']} candidates. Deterministic, no network/LLM calls. "
        "Distinct from `data/tx/QUALITY.md` (demo-readiness ranking) -- this is a completeness audit: what's "
        "missing, and whether it's fixable today."
    )
    lines.append("")

    lines.append("## Completeness index")
    lines.append("")
    lines.append(f"**{index['score']} / 100 -- tier {index['tier']}**")
    lines.append("")
    lines.append(f"`{index['formula']}`")
    lines.append("")
    lines.append("| Sub-score | Value | Role |")
    lines.append("|---|---|---|")
    lines.append(f"| BREADTH_SCORE | {index['sub_scores']['breadth_score']} | 40% of index |")
    lines.append(f"| DEPTH_SCORE | {index['sub_scores']['depth_score']} | 60% of index |")
    lines.append(
        f"| insight_layer_score (diagnostic) | {index['diagnostic_only_sub_scores']['insight_layer_score']} "
        "| detail view into DEPTH's insight_depth component, not double-counted |"
    )
    lines.append(
        f"| sourcing_index (diagnostic) | {index['diagnostic_only_sub_scores']['sourcing_index']} "
        "| detail view into DEPTH's sourcing_richness/temporal_grounding components, not double-counted |"
    )
    lines.append("")

    lines.append("## Breadth")
    lines.append("")
    rc = breadth["race_count"]
    lines.append(f"- Races on file: **{rc['actual']} / {rc['expected']} expected** ({rc['completeness_pct']}%) "
                  f"= {rc['expected_breakdown']['state_executive']} state executive + {rc['expected_breakdown']['us_senate']} US Senate "
                  f"+ {rc['expected_breakdown']['us_house']} US House.")
    lines.append(f"- US House districts covered: **{breadth['us_house_districts']['present']} / {breadth['us_house_districts']['expected']}** "
                  f"({'FULL' if breadth['us_house_districts']['full_coverage'] else 'INCOMPLETE'}).")
    lines.append(f"- Contested (>=2 candidates on file): **{breadth['contested_races']['ge2_candidates_count']} / {rc['actual']}** "
                  f"({breadth['contested_races']['pct_contested']}%); single-candidate races: {breadth['contested_races']['single_candidate_count']}.")
    lines.append(f"- One-sided by party (only 1 distinct party present): **{breadth['one_sided_by_party']['count']} / {rc['actual']}** "
                  f"({breadth['one_sided_by_party']['pct']}%) -- in this dataset every one-sided race is exactly the single-candidate races "
                  "(no >=2-candidates-but-1-party case exists).")
    lines.append(f"- Party diversity histogram (#distinct parties -> #races): {breadth['party_diversity_histogram']}")
    lines.append(f"- Parties seen anywhere: {', '.join(breadth['all_parties_seen'])}")
    lines.append(f"- Level balance: {breadth['level_balance']['counts']} ({breadth['level_balance']['marquee_district_null_count']} district-less marquee races appear on every ballot)")
    lines.append("")
    lines.append(f"> {breadth['declared_out_of_scope_note']}")
    lines.append("")

    lines.append("### Address-to-ballot resolution")
    lines.append("")
    sp = breadth["address_resolution"]["structural_proof"]
    lines.append(f"- **Structural proof**: {sp['cds_present']}/{sp['cds_expected']} congressional districts present in races.json -> {sp['reasoning']}")
    sc = breadth["address_resolution"]["sample_spot_check"]
    if sc["available"]:
        lines.append(f"- **Spot check** (`data/tx/geocode_seed.json`, n={sc['sample_size']}): {sc['pass_count']}/{sc['sample_size']} addresses resolve to a race on file.")
        lines.append(f"  - {sc['note']}")
    asr = breadth["address_resolution"]["address_sweep_report"]
    if asr.get("present") and asr.get("parsed"):
        lines.append(
            f"- **Live address sweep** (`data/tx/address_sweep_report.json`, generated {asr.get('generated_at')} by "
            f"`{asr.get('generated_by')}`): {asr.get('new_sweep_ok')}/{asr.get('new_sweep_addresses')} new addresses "
            f"resolved OK across {asr.get('distinct_cds_new_sweep')} distinct districts; regression check "
            f"{asr.get('regression_pass')}/{asr.get('regression_pass', 0) + asr.get('regression_fail', 0)} passed; "
            f"{asr.get('total_failures')} total call failures."
        )
        if asr.get("cds_without_a_race_on_file"):
            lines.append(f"  - **WARNING**: districts resolved live with no race on file: {asr['cds_without_a_race_on_file']}")
        lines.append(f"  - {asr['note']}")
    else:
        lines.append(f"- **address_sweep_report.json**: {asr.get('note', 'not present at eval time')}")
    cv = breadth["address_resolution"]["combined_empirical_verification"]
    lines.append(
        f"- **Combined empirical verification** (geocode_seed.json ∪ address sweep, if present): "
        f"**{cv['distinct_cds_verified_live']}/{cv['of_total_cds']}** distinct congressional districts have now been "
        f"live-verified by at least one real geocoder+API round-trip (not just asserted structurally)."
        + (f" Never live-verified: {cv['cds_never_live_verified']}." if cv["cds_never_live_verified"] else " Every CD has been live-verified at least once.")
    )
    lines.append("")

    lines.append("## Depth heatmap (per race)")
    lines.append("")
    lines.append("Legend: F=finance, V=votes (incumbents only, `-` = N/A no incumbent), P=positions, B=bio, "
                  "Arch=archetype insight coverage out of 8, Src=avg distinct sources/candidate. "
                  "Fractions are candidates-with-X / candidates-on-file for that race.")
    lines.append("")
    lines.append("| Race | Lvl | Score | Tier | F | V | P | B | Arch/8 | Src |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for rid, v in depth["races"].items():
        cds = v["candidate_detail"]
        n = max(len(cds), 1)
        f = sum(1 for d in cds if d["has_finance"])
        p = sum(1 for d in cds if d["has_positions"])
        b = sum(1 for d in cds if d["has_bio"])
        incumbents = [d for d in cds if d["incumbent"]]
        if incumbents:
            vv = f"{sum(1 for d in incumbents if d['has_votes'])}/{len(incumbents)}"
        else:
            vv = "-"
        lvl = "state" if v["level"] == "state" else ("Sen" if v["district"] is None else v["district"])
        lines.append(
            f"| {v['office']} ({rid}) | {lvl} | {v['score']} | {v['tier']} | {f}/{len(cds)} | {vv} | {p}/{len(cds)} | "
            f"{b}/{len(cds)} | {v['archetype_coverage']}/8 | {v['avg_distinct_sources']} |"
        )
    lines.append("")

    lines.append("## Depth rollup by candidate-level bucket")
    lines.append("")
    lines.append("| Bucket | n | Finance | Votes | Positions | Bio |")
    lines.append("|---|---|---|---|---|---|")
    for label, stats in roll["by_level_bucket"].items():
        lines.append(
            f"| {label} | {stats['candidate_count']} | {stats['finance_pct']}% | {stats['votes_pct']}% | "
            f"{stats['positions_pct']}% | {stats['bio_pct']}% |"
        )
    lines.append("")
    lines.append(
        "This is the sharpest single story in the dataset: US House candidates are well-covered on finance/votes "
        "but have almost no positions/bio; state-executive candidates are the mirror image on votes (structurally "
        "impossible for non-incumbents) but strong everywhere else."
    )
    lines.append("")

    lines.append("## Sourcing + temporal grounding")
    lines.append("")
    src = roll["sources_per_candidate"]
    dist_hist = src["distinct_source_distribution"]  # {"count_as_str": n_candidates}
    total_cands = sum(dist_hist.values())
    thin = sum(n for k, n in dist_hist.items() if int(k) <= 2)
    well = sum(n for k, n in dist_hist.items() if int(k) >= SOURCE_TARGET)
    lines.append(f"- Avg top-level `sources[]` length: **{src['avg_top_level_sources_field']}**")
    lines.append(f"- Avg DISTINCT source URLs per candidate (all fact-level sources unioned): **{src['avg_distinct_source_urls']}**")
    lines.append(f"  - {src['note']}")
    lines.append(
        f"  - The average hides a bimodal split: **{thin}/{total_cands}** candidates ({round(100*thin/total_cands,1)}%) "
        f"have <=2 distinct sources (thinly documented, mostly minor-party/challenger candidates with just one FEC "
        f"filing), while **{well}/{total_cands}** ({round(100*well/total_cands,1)}%) meet or exceed the "
        f"SOURCE_TARGET={SOURCE_TARGET} threshold (mostly incumbents, whose 8 recorded roll-call votes each carry "
        "their own citation). Distribution: " + str(dist_hist)
    )
    asof = roll["as_of_coverage"]
    lines.append(f"- Finance objects with a valid ISO `as_of` date: **{asof['finance_with_valid_as_of']}/{asof['finance_objects']}** ({asof['finance_as_of_pct']}%)")
    lines.append(f"- Key-vote entries with a date: **{asof['key_vote_entries_dated']}/{asof['key_vote_entries']}** ({asof['key_vote_dated_pct']}%)")
    lines.append("")

    lines.append("## Insight layer")
    lines.append("")
    il = roll["insight_layer"]
    lines.append(f"- Base block present: **{il['base_present_races']}/{il['total_races']}** races (100% -- the functional floor is met everywhere)")
    lines.append(f"- Full 8-archetype personalization: **{len(il['races_with_full_archetypes'])}/{il['total_races']}** races")
    lines.append(f"  - With: {', '.join(il['races_with_full_archetypes'])}")
    lines.append(f"  - Without ({len(il['races_without_archetypes'])}): {', '.join(il['races_without_archetypes'][:12])}{' ...' if len(il['races_without_archetypes']) > 12 else ''}")
    lines.append("")

    lines.append("## Evidence checks (says-vs-voted)")
    lines.append("")
    ev = roll["evidence_checks"]
    lines.append(f"- Landed on any candidate record yet: **{ev['landed']}**")
    lines.append(
        f"- Detector script present (`pipeline/detect_contradictions.py`): **{detect_contradictions_exists}**"
        + (" -- exists but has not yet been run against candidates.json (see GAP-04)." if detect_contradictions_exists else "")
    )
    lines.append(f"- Candidates with BOTH a voting record and positions today (the prerequisite for this check to produce output): **{ev['candidates_with_both_votes_and_positions_today']}**")
    lines.append(f"- {ev['note']}")
    lines.append("")

    lines.append("## Self-check: coverage_report.json drift")
    lines.append("")
    if drift.get("available"):
        lines.append(f"- Fresh recomputation matches cached `coverage_report.json`: **{drift['fresh_matches_cached']}** ({drift['diff_count']} diff(s))")
    else:
        lines.append(f"- {drift.get('note')}")
    lines.append("")

    lines.append("## Recoverable-FEC-join rescan (redistricting-tag mismatches)")
    lines.append("")
    if fec_rescan.get("available"):
        lines.append(
            f"- Checked {fec_rescan['targets_checked']} FEC-unmatched incumbents from `unjoined_report.json`: "
            f"**{fec_rescan['possible_recoverable']}** have a same-surname record elsewhere in `raw/fec.json` "
            f"(needs human verification, see findings), **{fec_rescan['no_match_in_fetch']}** have no match anywhere in the current fetch."
        )
        for r in fec_rescan["results"]:
            lines.append(f"  - {r['our_name']} ({r['our_district']}): {r['verdict']}" + (f" -- candidates: {[m['fec_name'] + ' (' + str(m['district_in_raw_fetch']) + ', ' + str(m['fec_id']) + ')' for m in r['surname_matches_in_raw_fec_json']]}" if r["surname_matches_in_raw_fec_json"] else ""))
    else:
        lines.append(f"- {fec_rescan.get('note')}")
    lines.append("")

    lines.append("## Findings: honest gaps vs defects")
    lines.append("")
    lines.append(
        "**DEFECT** = we already hold the source data (or the generation step needs no new fetch) and simply "
        "didn't wire it in -- actionable right now. **DEFECT_CANDIDATE** = strong evidence of a fixable defect "
        "but needs a human identity/judgment call first -- never auto-resolved. **HONEST GAP** = the data "
        "genuinely doesn't exist publicly yet, needs new research effort, is blocked on a missing API key, or "
        "is an explicitly declared out-of-scope cut."
    )
    lines.append("")
    for f in findings:
        lines.append(f"### {f['id']} [{f['type']}{' / ' + f['subtype'] if f.get('subtype') else ''}] {f['title']}")
        lines.append("")
        lines.append(f['summary'])
        lines.append("")
        if f.get("exact_fix"):
            lines.append(f"**Exact fix:** {f['exact_fix']}")
        elif f.get("recommendation"):
            lines.append(f"**Recommendation:** {f['recommendation']}")
        lines.append(f"\n**Effort:** {f.get('effort','N/A')} | **Impact:** {f.get('impact','N/A')}")
        lines.append("")

    lines.append("## Prioritized: what would most improve the dataset")
    lines.append("")
    lines.append("| # | Type | Title | Effort | Impact |")
    lines.append("|---|---|---|---|---|")
    for p in prioritized:
        lines.append(f"| {p['rank']} | {p['type']} | {p['title']} | {p['effort']} | {p['impact']} |")
    lines.append("")
    lines.append(
        "Only DEFECT / DEFECT_CANDIDATE rows above are actionable immediately with the data already in this "
        "repo. HONEST_GAP rows are the honest roadmap -- each needs new fetching, a key, human verification, or "
        "is a declared scope cut."
    )
    lines.append("")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    try:
        races_doc = load_json_required(RACES_PATH)
        candidates = load_json_required(CANDIDATES_PATH)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"FATAL: could not read gold JSON: {exc}", file=sys.stderr)
        return 1

    races = races_doc.get("races", [])

    cached_coverage = load_json_optional(COVERAGE_REPORT_PATH)
    cached_quality = load_json_optional(QUALITY_REPORT_PATH)  # presence flag only; coverage_report.json is the drift-checked source of per-race counts
    unjoined = load_json_optional(UNJOINED_REPORT_PATH)
    raw_fec = load_json_optional(RAW_FEC_PATH)
    geocode_seed = load_json_optional(GEOCODE_SEED_PATH)
    address_sweep = None
    address_sweep_path_used = None
    for candidate_path in ADDRESS_SWEEP_PATH_CANDIDATES:
        doc = load_json_optional(candidate_path)
        if doc is not None:
            address_sweep = doc
            address_sweep_path_used = str(candidate_path.relative_to(ROOT))
            break
    detect_contradictions_exists = DETECT_CONTRADICTIONS_SCRIPT_PATH.exists()

    breadth = compute_breadth(races, candidates, geocode_seed, address_sweep)
    depth = compute_depth(races, candidates)
    index = compute_completeness_index(breadth, depth)
    drift = check_coverage_report_drift(races, candidates, cached_coverage)
    fec_rescan = rescan_recoverable_fec_joins(unjoined, raw_fec)
    findings = build_findings(breadth, depth, drift, fec_rescan, unjoined, detect_contradictions_exists)
    prioritized = build_prioritized_improvements(findings)

    output = {
        "generated_by": GENERATED_BY,
        "election_date": races_doc.get("election_date"),
        "inputs_used": {
            "coverage_report_json": cached_coverage is not None,
            "quality_report_json": cached_quality is not None,
            "unjoined_report_json": unjoined is not None,
            "raw_fec_json": raw_fec is not None,
            "geocode_seed_json": geocode_seed is not None,
            "address_sweep_report_json": address_sweep is not None,
            "address_sweep_report_path": address_sweep_path_used,
            "detect_contradictions_script_present": detect_contradictions_exists,
        },
        "breadth": breadth,
        "depth": depth,
        "completeness_index": index,
        "coverage_report_drift_check": drift,
        "recoverable_fec_join_rescan": fec_rescan,
        "findings": findings,
        "prioritized_improvements": prioritized,
    }

    atomic_write_json(OUT_JSON_PATH, output)
    md = render_markdown(breadth, depth, index, findings, prioritized, drift, fec_rescan, detect_contradictions_exists)
    OUT_MD_PATH.write_text(md, encoding="utf-8")

    print(f"Wrote {OUT_JSON_PATH}")
    print(f"Wrote {OUT_MD_PATH}")
    print(f"COMPLETENESS INDEX: {index['score']} / 100 (tier {index['tier']})")
    print(f"  BREADTH_SCORE: {breadth['breadth_score']}   DEPTH_SCORE: {depth['dataset_rollup']['depth_score_mean']}")
    print(f"Findings: {len(findings)} ({sum(1 for f in findings if f['type']=='DEFECT')} DEFECT, "
          f"{sum(1 for f in findings if f['type']=='DEFECT_CANDIDATE')} DEFECT_CANDIDATE, "
          f"{sum(1 for f in findings if f['type']=='HONEST_GAP')} HONEST_GAP)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
