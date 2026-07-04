#!/usr/bin/env python3
"""
pipeline/validate_citations.py -- the permanent citation-integrity CI gate.

CLAUDE.md's rule: "Never show an insight that can't be tied to a cited
source." This script is the deterministic, no-network enforcement of that
rule across the *entire* gold dataset in one pass. It differs from the
existing pipeline/validate_marquee_insights.py, validate_insights_house.py,
validate_insights_tx20_38.py, and validate_horizons.py in one essential way:
those are data-CLEANERS -- they drop violating bullets and rewrite the file
in place, covering only their own race subsets (marquee, TX-01..19,
TX-20..38, marquee+2 respectively). This script NEVER writes anything. It
only reads data/tx/{races,candidates}.json + data/tx/insights/*.json and
reports. A violation here is a build failure, not something to be silently
repaired -- that repair is a semantic/human job (see the task that produced
this file), not this gate's.

Checks, over EVERY race in races.json and EVERY candidate in candidates.json:

  1. Every factual insight bullet (base or archetype block's `candidates`
     map) must carry a non-empty, non-whitespace `source`. EXEMPT: an
     honest "no data in our set" caveat (e.g. "No public data in our set on
     X", "No public FEC campaign finance data in our set for X", "No public
     voting record in our set for X", "No recorded evidence in our set to
     project from for X") -- you cannot cite a source for the absence of
     data. Detected by phrasing, not by an exhaustive literal list (see
     _NO_DATA_RE below).
  2. Every `horizons.<candidate>.now[]` bullet must carry a non-empty
     `source` -- no no-data exemption (the horizons generator skips a
     topic entirely rather than emitting an uncited "no data" projection
     bullet, so an empty source here is always a real defect).
  3. Every `horizons.<candidate>.long_term[]` bullet must carry a
     non-empty `source` AND a non-empty `assumption` AND text that opens
     with conditional phrasing ("If ..."), so a projection is never
     presented as settled fact.
  4. Grounding/fabrication check: wherever a bullet (candidates[], now[],
     or long_term[]) DOES carry a source, that URL must appear somewhere
     in that *specific* candidate's own JSON record (sources[],
     finance.source, record.source, record.key_votes[].source,
     positions[].source, evidence_checks[].{stated,voted}.source) --
     never fabricated, never borrowed from another candidate in the race.
     This applies even to a "no data" bullet that happens to carry a
     source: if you cite something, it has to be real.
  5. Every candidate finance/key_vote/position object has a non-empty
     source (record.source and top-level sources[] entries are also
     format-checked when present, though -- matching the existing
     pipeline/validate_data.py precedent -- their presence isn't itself
     required).
  6. Every source string found anywhere above (plus race.context.sources[])
     must be non-empty and start with http:// or https:// -- no exceptions.

Run:
    python3 pipeline/validate_citations.py

Prints one `VIOLATION:` line per problem and exits 1 if any exist; prints a
clean PASS block with counts (bullets checked, sources checked, races
covered) and exits 0 otherwise. Deterministic: reads local JSON only, makes
no network calls, and never mutates data/tx/**.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent

_URL_RE = re.compile(r"^https?://", re.IGNORECASE)

# The family of "honest, nothing to cite" caveats the build_insights_*.py /
# precompute_*.py generators write when a candidate has no data on a topic.
# Anchored loosely ("no" ... "in our set" within an 80-char window) rather
# than one exact string so every template variant in the real corpus keeps
# matching:
#   "No public data in our set on X"
#   "No public data in our set connects X ..."
#   "No public FEC campaign finance data in our set for X."
#   "No public voting record in our set for X"
#   "No recorded evidence in our set to project from for X"
# Verified against the full data/tx/insights/*.json corpus at authoring
# time: every occurrence of "in our set" in that corpus is one of these
# no-data templates. (tests/test_e2e_demo.py's NO_DATA_MARKER =
# "no public data in our set" is a narrower sibling used for a different
# purpose -- informativeness scoring, not this exemption.)
_NO_DATA_RE = re.compile(r"\bno\b.{0,80}?\bin our set\b", re.IGNORECASE | re.DOTALL)

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


# ---------------------------------------------------------------------------
# Predicates
# ---------------------------------------------------------------------------


def _nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_http_url(value: Any) -> bool:
    return isinstance(value, str) and bool(_URL_RE.match(value.strip()))


def _is_no_data_bullet(text: Any) -> bool:
    return isinstance(text, str) and bool(_NO_DATA_RE.search(text))


def candidate_valid_sources(candidate: dict[str, Any]) -> set[str]:
    """Every source URL that legitimately appears in this candidate's own
    JSON record -- the grounding pool an insight bullet about this
    candidate must cite from. Same universe as the identically-named/-shaped
    helpers in validate_marquee_insights.py / validate_insights_house.py /
    validate_insights_tx20_38.py / validate_horizons.py (kept in sync
    deliberately), plus evidence_checks[].{stated,voted}.source -- which
    are always verbatim copies of a positions[]/key_votes[] source by
    construction (pipeline/detect_contradictions.py's build_evidence_check),
    so folding them in is a defensive superset, never a wider hole.
    """
    urls: set[str] = set()
    for u in candidate.get("sources") or []:
        if isinstance(u, str):
            urls.add(u)
    finance = candidate.get("finance")
    if finance and finance.get("source"):
        urls.add(finance["source"])
    record = candidate.get("record") or {}
    if record.get("source"):
        urls.add(record["source"])
    for vote in record.get("key_votes") or []:
        if isinstance(vote, dict) and vote.get("source"):
            urls.add(vote["source"])
    for position in candidate.get("positions") or []:
        if isinstance(position, dict) and position.get("source"):
            urls.add(position["source"])
    for check in candidate.get("evidence_checks") or []:
        if not isinstance(check, dict):
            continue
        for side in ("stated", "voted"):
            side_obj = check.get(side) or {}
            if isinstance(side_obj, dict) and side_obj.get("source"):
                urls.add(side_obj["source"])
    return urls


# ---------------------------------------------------------------------------
# Counters
# ---------------------------------------------------------------------------


def _new_counts() -> dict[str, int]:
    return {
        "races_total": 0,
        "races_with_insights": 0,
        "candidates_checked": 0,
        "candidate_fact_sources_checked": 0,
        "race_context_sources_checked": 0,
        "insight_bullets_checked": 0,
        "horizons_now_checked": 0,
        "horizons_long_term_checked": 0,
        "sources_checked": 0,
    }


# ---------------------------------------------------------------------------
# Field-level checks (append to `errors`, bump `counts` at the call site)
# ---------------------------------------------------------------------------


def _require_source(label: str, value: Any, errors: list[str]) -> None:
    """A source field that MUST be present, non-empty, and http(s) -- no
    exemption. Used for candidate finance/key_vote/position/sources[] and
    race context.sources[]."""
    if not _nonempty_str(value):
        errors.append(f"{label}: missing/empty source")
    elif not _is_http_url(value):
        errors.append(f"{label}: source is not http(s): {value!r}")


def _check_bullet(
    label: str,
    bullet: Any,
    valid_sources: set[str],
    errors: list[str],
    *,
    allow_no_data_exemption: bool,
    require_long_term_shape: bool,
) -> bool:
    """Checks one {text, source[, assumption]} bullet dict.

    Returns True iff a source value was actually examined (present and
    non-empty) -- callers use this to bump their "sources checked" counter;
    an honest no-data-exempt bullet returns False since there was nothing
    to cite in the first place.
    """
    if not isinstance(bullet, dict):
        bullet = {}
    text = bullet.get("text")
    source = bullet.get("source")

    if not _nonempty_str(source):
        if allow_no_data_exemption and _is_no_data_bullet(text):
            return False  # honest "no data in our set" caveat -- exempt
        errors.append(f"{label}: missing/empty source on factual bullet: {text!r}")
        return False

    if not _is_http_url(source):
        errors.append(f"{label}: source is not http(s): {source!r}")
    elif source not in valid_sources:
        errors.append(
            f"{label}: source not found anywhere in this candidate's own "
            f"data -- possible fabrication: {source!r}"
        )

    if require_long_term_shape:
        if not _nonempty_str(bullet.get("assumption")):
            errors.append(f"{label}: long_term bullet missing 'assumption'")
        if not (_nonempty_str(text) and text.strip().lower().startswith("if ")):
            errors.append(
                f"{label}: long_term bullet is not conditionally phrased "
                f"(must open with 'If ...'): {text!r}"
            )

    return True


def _check_candidate_facts(cid: str, candidate: dict[str, Any], errors: list[str], counts: dict[str, int]) -> None:
    for i, url in enumerate(candidate.get("sources") or []):
        counts["candidate_fact_sources_checked"] += 1
        counts["sources_checked"] += 1
        _require_source(f"candidates.json::{cid}.sources[{i}]", url, errors)

    finance = candidate.get("finance")
    if finance:  # matches pipeline/validate_data.py's precedent: presence, not just the key existing
        counts["candidate_fact_sources_checked"] += 1
        counts["sources_checked"] += 1
        _require_source(f"candidates.json::{cid}.finance.source", finance.get("source"), errors)

    record = candidate.get("record") or {}
    # record.source itself: format-checked when the key is present (even as
    # ""), but its presence is not itself required -- this gate mirrors
    # validate_data.py, which likewise only requires finance/key_vote/
    # position sources, not record.source.
    if "source" in record:
        counts["candidate_fact_sources_checked"] += 1
        counts["sources_checked"] += 1
        _require_source(f"candidates.json::{cid}.record.source", record.get("source"), errors)

    for kv in record.get("key_votes") or []:
        kv = kv if isinstance(kv, dict) else {}
        counts["candidate_fact_sources_checked"] += 1
        counts["sources_checked"] += 1
        bill = kv.get("bill", "?")
        _require_source(f"candidates.json::{cid}.record.key_votes[{bill}].source", kv.get("source"), errors)

    for p in candidate.get("positions") or []:
        p = p if isinstance(p, dict) else {}
        counts["candidate_fact_sources_checked"] += 1
        counts["sources_checked"] += 1
        issue = p.get("issue", "?")
        _require_source(f"candidates.json::{cid}.positions[{issue}].source", p.get("source"), errors)


def _check_race_context(race: dict[str, Any], errors: list[str], counts: dict[str, int]) -> None:
    ctx = race.get("context") or {}
    for i, url in enumerate(ctx.get("sources") or []):
        counts["race_context_sources_checked"] += 1
        counts["sources_checked"] += 1
        _require_source(f"races.json::{race['race_id']}.context.sources[{i}]", url, errors)


def _check_block(
    race_id: str,
    section_label: str,
    block: dict[str, Any],
    valid_sources_by_cid: dict[str, set[str]],
    errors: list[str],
    counts: dict[str, int],
) -> None:
    """Validates one insight block ("base" or one archetype): its
    `candidates` bullet map and its `horizons` (now/long_term) map, if
    present. A block with no `horizons` key at all (most non-marquee House
    races) is not a violation -- horizons is an opt-in feature, not a
    universal requirement (see CLAUDE.md's "Consequence horizons" note)."""
    candidates_map = block.get("candidates")
    if not isinstance(candidates_map, dict):
        candidates_map = {}
    for cid, bullets in candidates_map.items():
        valid = valid_sources_by_cid.get(cid, set())
        bullets = bullets if isinstance(bullets, list) else []
        for i, bullet in enumerate(bullets):
            label = f"{race_id} insights::{section_label}.candidates.{cid}[{i}]"
            counts["insight_bullets_checked"] += 1
            if _check_bullet(
                label, bullet, valid, errors, allow_no_data_exemption=True, require_long_term_shape=False
            ):
                counts["sources_checked"] += 1

    horizons = block.get("horizons")
    if isinstance(horizons, dict):
        for cid, h in horizons.items():
            if not isinstance(h, dict):
                continue
            valid = valid_sources_by_cid.get(cid, set())
            now_list = h.get("now") if isinstance(h.get("now"), list) else []
            for i, bullet in enumerate(now_list):
                label = f"{race_id} insights::{section_label}.horizons.{cid}.now[{i}]"
                counts["horizons_now_checked"] += 1
                if _check_bullet(
                    label, bullet, valid, errors, allow_no_data_exemption=False, require_long_term_shape=False
                ):
                    counts["sources_checked"] += 1

            lt_list = h.get("long_term") if isinstance(h.get("long_term"), list) else []
            for i, bullet in enumerate(lt_list):
                label = f"{race_id} insights::{section_label}.horizons.{cid}.long_term[{i}]"
                counts["horizons_long_term_checked"] += 1
                if _check_bullet(
                    label, bullet, valid, errors, allow_no_data_exemption=False, require_long_term_shape=True
                ):
                    counts["sources_checked"] += 1


# ---------------------------------------------------------------------------
# Per-race + aggregate entry points (pure functions -- no disk I/O; this is
# what makes them directly testable against an in-memory-mutated COPY of
# the gold data, never the real files on disk).
# ---------------------------------------------------------------------------


def collect_violations_for_race(
    race: dict[str, Any],
    candidates: dict[str, Any],
    insights_doc: Optional[dict[str, Any]],
) -> tuple[list[str], dict[str, int]]:
    """Violations scoped to exactly one race: its context.sources[], every
    one of its candidates' finance/key_vote/position/sources fields, and
    (if an insights file was found for it) every bullet in its base +
    archetype blocks. Shared by collect_violations (aggregated over every
    race) and tests/test_citations.py's per-race parametrized test, so the
    two can never drift apart."""
    errors: list[str] = []
    counts = _new_counts()
    race_id = race["race_id"]

    _check_race_context(race, errors, counts)

    valid_sources_by_cid: dict[str, set[str]] = {}
    for cid in race.get("candidate_ids", []) or []:
        candidate = candidates.get(cid)
        if candidate is None:
            errors.append(f"{race_id}: candidate_id '{cid}' not found in candidates.json")
            continue
        counts["candidates_checked"] += 1
        _check_candidate_facts(cid, candidate, errors, counts)
        valid_sources_by_cid[cid] = candidate_valid_sources(candidate)

    if insights_doc is not None:
        counts["races_with_insights"] += 1
        base = insights_doc.get("base")
        if isinstance(base, dict):
            _check_block(race_id, "base", base, valid_sources_by_cid, errors, counts)
        archetypes = insights_doc.get("archetypes")
        if isinstance(archetypes, dict):
            for key, block in archetypes.items():
                if isinstance(block, dict):
                    _check_block(race_id, f"archetypes.{key}", block, valid_sources_by_cid, errors, counts)

    return errors, counts


def collect_violations(
    races_doc: dict[str, Any],
    candidates: dict[str, Any],
    insights_by_race_id: dict[str, dict[str, Any]],
) -> tuple[list[str], dict[str, int]]:
    """Aggregates collect_violations_for_race over every race in
    races.json. Pure function -- callers (main() below, or tests on an
    in-memory-mutated copy) supply the three already-parsed documents."""
    all_errors: list[str] = []
    total_counts = _new_counts()
    races = races_doc.get("races") or []

    for race in races:
        race_id = race["race_id"]
        errors, counts = collect_violations_for_race(race, candidates, insights_by_race_id.get(race_id))
        all_errors.extend(errors)
        for key, value in counts.items():
            total_counts[key] += value

    total_counts["races_total"] = len(races)
    return all_errors, total_counts


# ---------------------------------------------------------------------------
# Disk I/O + CLI
# ---------------------------------------------------------------------------


def load_gold(root: Path = ROOT) -> tuple[dict[str, Any], dict[str, Any], dict[str, dict[str, Any]], list[str]]:
    """Reads races.json, candidates.json, and every data/tx/insights/{race_id}.json
    that exists for a race in races.json. Returns (races_doc, candidates,
    insights_by_race_id, load_errors).

    A race with no insights file is NOT a load error and NOT a citation
    violation (see module docstring: horizons/archetypes are opt-in
    features, and completeness is pipeline/demo_readiness_gate.py's job,
    not this gate's) -- it's simply absent from insights_by_race_id and
    reflected honestly in the "races covered" count. An insights file that
    exists but fails to parse IS an error: a file we categorically cannot
    verify the citations of cannot be allowed to pass silently.
    """
    races_path = root / "data" / "tx" / "races.json"
    candidates_path = root / "data" / "tx" / "candidates.json"
    insights_dir = root / "data" / "tx" / "insights"

    races_doc = json.loads(races_path.read_text(encoding="utf-8"))
    candidates = json.loads(candidates_path.read_text(encoding="utf-8"))

    insights_by_race_id: dict[str, dict[str, Any]] = {}
    load_errors: list[str] = []
    for race in races_doc.get("races", []):
        race_id = race["race_id"]
        path = insights_dir / f"{race_id}.json"
        if not path.exists():
            continue
        try:
            insights_by_race_id[race_id] = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            load_errors.append(f"{race_id}: insights file data/tx/insights/{race_id}.json is invalid JSON: {exc}")

    return races_doc, candidates, insights_by_race_id, load_errors


def _print_counts(counts: dict[str, int]) -> None:
    total_bullets = (
        counts["insight_bullets_checked"] + counts["horizons_now_checked"] + counts["horizons_long_term_checked"]
    )
    # "sources_checked" is a running grand total across every category below;
    # the bullet/horizons share of it is whatever's left after subtracting
    # the two non-bullet categories (candidate facts, race context).
    bullet_sources_checked = (
        counts["sources_checked"] - counts["candidate_fact_sources_checked"] - counts["race_context_sources_checked"]
    )
    print(f"Races covered: {counts['races_with_insights']}/{counts['races_total']} (insights file found + checked)")
    print(f"Candidates checked: {counts['candidates_checked']}")
    print(
        f"Bullets checked: {total_bullets} "
        f"(insight={counts['insight_bullets_checked']}, "
        f"horizons.now={counts['horizons_now_checked']}, "
        f"horizons.long_term={counts['horizons_long_term_checked']})"
    )
    print(
        f"Sources checked: {counts['sources_checked']} "
        f"(candidate facts={counts['candidate_fact_sources_checked']}, "
        f"race context={counts['race_context_sources_checked']}, "
        f"insight/horizons bullets={bullet_sources_checked})"
    )


def main(root: Path = ROOT) -> int:
    try:
        races_doc, candidates, insights_by_race_id, load_errors = load_gold(root)
    except FileNotFoundError as exc:
        print("=== Citation Integrity Gate: FAIL (setup error) ===")
        print(f"  FATAL: {exc}")
        return 1
    except json.JSONDecodeError as exc:
        print("=== Citation Integrity Gate: FAIL (setup error) ===")
        print(f"  FATAL: invalid JSON: {exc}")
        return 1

    errors, counts = collect_violations(races_doc, candidates, insights_by_race_id)
    errors = load_errors + errors

    races_missing_insights = counts["races_total"] - counts["races_with_insights"]

    if errors:
        print(f"=== Citation Integrity Gate: FAIL ({len(errors)} violation(s)) ===")
        for e in errors:
            print(f"  VIOLATION: {e}")
        print()
        _print_counts(counts)
        return 1

    print("=== Citation Integrity Gate: PASS ===")
    _print_counts(counts)
    if races_missing_insights:
        print(
            f"Note: {races_missing_insights} race(s) have no insights file yet "
            "(not a citation violation -- see pipeline/demo_readiness_gate.py for completeness checks)."
        )
    print("Violations: 0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
