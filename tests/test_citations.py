"""tests/test_citations.py -- pytest wrapper around pipeline/validate_citations.py,
the permanent citation-integrity CI gate (CLAUDE.md's "no source, no claim" rule).

Three layers, cheapest first:

1. Unit tests on the pure predicate/helper functions (_is_http_url,
   _nonempty_str, _is_no_data_bullet, candidate_valid_sources) -- no gold
   data needed at all.
2. One test PER RACE (parametrized over every race_id in the committed
   data/tx/races.json, read at collection time -- never hardcoded, so a
   future race is automatically covered) asserting zero citation
   violations. Parametrizing gives one independently-named, independently
   failing pytest case per race (`test_race_citations_clean[tx-cd28-2026]`
   etc.) instead of one monolithic assertion that just says "something,
   somewhere is wrong" -- exactly the "readable failures" the task asked
   for.
3. Self-proving detector tests (testing.md #1 / #5's philosophy: "a
   detector that has never been shown to fail is not a test, it's a
   hope"). Each `test_selfproof_*` deep-copies real, unmodified gold data
   in memory, injects exactly one kind of violation, asserts the validator
   goes RED on the copy, then asserts the same code path stays GREEN on an
   untouched copy of the same data -- proof the check actually checks,
   rather than trivially passing. One of them (the literal "inject an
   empty source on a copy" case) additionally exercises the on-disk
   `main(root=...)` entrypoint against a real temp-directory copy of
   data/tx/, rather than just the in-memory pure functions, so the actual
   `python3 pipeline/validate_citations.py` contract is proven too.

Zero network, zero mutation: every test here only reads the real
data/tx/*.json once at module scope; self-proof tests operate on
`copy.deepcopy`s (or tmp_path directory copies) and never write to the
real files.

Run:
    python3 -m pytest tests/test_citations.py -q
    python3 -m pytest tests/ -q
"""

from __future__ import annotations

import copy
import json
import shutil
import subprocess
import sys
import warnings
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline import validate_citations as vc  # noqa: E402

with warnings.catch_warnings():
    warnings.simplefilter("ignore", pytest.PytestUnknownMarkWarning)
    selfproof = pytest.mark.selfproof

# ---------------------------------------------------------------------------
# Load the real, committed gold data ONCE. Deliberately not defensively
# skip-guarded (unlike e.g. app.db in test_contracts.py): races.json and
# candidates.json are committed gold artifacts (CLAUDE.md), and every
# existing validator (validate_data.py, validate_marquee_insights.py, ...)
# makes the same unconditional-presence assumption.
# ---------------------------------------------------------------------------

RACES_DOC, CANDIDATES, INSIGHTS_BY_RACE_ID, LOAD_ERRORS = vc.load_gold(REPO_ROOT)
RACES_BY_ID = {r["race_id"]: r for r in RACES_DOC.get("races", [])}
RACE_IDS = sorted(RACES_BY_ID.keys())


def _copy_gold_tree(dest_root: Path) -> None:
    """Copies data/tx/{races.json,candidates.json,insights/} into
    dest_root/data/tx/, mirroring the exact layout vc.load_gold() expects.
    Used only by the tmp_path-based self-proof test below -- everything
    else operates on in-memory copy.deepcopy()s, which is faster and
    equally conclusive for exercising the pure validation functions."""
    src = REPO_ROOT / "data" / "tx"
    dest = dest_root / "data" / "tx"
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src / "races.json", dest / "races.json")
    shutil.copy2(src / "candidates.json", dest / "candidates.json")
    shutil.copytree(src / "insights", dest / "insights")


# ---------------------------------------------------------------------------
# 1. Unit tests on the pure predicates
# ---------------------------------------------------------------------------


def test_is_http_url_accepts_only_http_and_https():
    assert vc._is_http_url("https://example.com/path")
    assert vc._is_http_url("http://example.com")
    assert vc._is_http_url("HTTPS://Example.Com")  # case-insensitive scheme
    assert not vc._is_http_url("ftp://example.com")
    assert not vc._is_http_url("example.com")
    assert not vc._is_http_url("")
    assert not vc._is_http_url("   ")
    assert not vc._is_http_url(None)
    assert not vc._is_http_url(123)


def test_nonempty_str_rejects_blank_and_non_string():
    assert vc._nonempty_str("x")
    assert not vc._nonempty_str("")
    assert not vc._nonempty_str("   \t\n  ")
    assert not vc._nonempty_str(None)
    assert not vc._nonempty_str(0)


def test_is_no_data_bullet_matches_every_real_corpus_phrasing():
    """These four exact templates are the ones build_insights_house.py,
    build_insights_tx20_38.py, and precompute_marquee_insights.py actually
    write (confirmed by grep across data/tx/insights/*.json at authoring
    time) -- if any of these stops matching, the exemption silently breaks
    for real data, not just a hypothetical."""
    assert vc._is_no_data_bullet("No public data in our set on Medicare-specific votes for this candidate.")
    assert vc._is_no_data_bullet(
        "No public FEC campaign finance data in our set for Nathaniel Quentin Moran."
    )
    assert vc._is_no_data_bullet(
        "No public voting record in our set for Dax Cornell Alexander (not currently a member of Congress)."
    )
    assert vc._is_no_data_bullet("No recorded evidence in our set to project from for Tom Oxford.")
    assert not vc._is_no_data_bullet("Greg Abbott supports property tax cuts.")
    assert not vc._is_no_data_bullet(None)
    assert not vc._is_no_data_bullet("")


def test_candidate_valid_sources_collects_every_documented_field():
    candidate = {
        "sources": ["https://a.example/"],
        "finance": {"source": "https://b.example/"},
        "record": {
            "source": "https://c.example/",
            "key_votes": [{"source": "https://d.example/"}],
        },
        "positions": [{"source": "https://e.example/"}],
        "evidence_checks": [
            {"stated": {"source": "https://e.example/"}, "voted": {"source": "https://d.example/"}}
        ],
    }
    assert vc.candidate_valid_sources(candidate) == {
        "https://a.example/",
        "https://b.example/",
        "https://c.example/",
        "https://d.example/",
        "https://e.example/",
    }
    assert vc.candidate_valid_sources({}) == set()


# ---------------------------------------------------------------------------
# 2. One test per race -- readable, independent failures
# ---------------------------------------------------------------------------


def test_gold_data_loaded_with_no_parse_errors():
    assert LOAD_ERRORS == [], f"insights file(s) failed to parse: {LOAD_ERRORS}"
    assert RACE_IDS, "expected at least one race in data/tx/races.json"


@pytest.mark.parametrize("race_id", RACE_IDS)
def test_race_citations_clean(race_id: str) -> None:
    """Every citation belonging to this one race -- its context.sources[],
    each of its candidates' finance/key_vote/position/sources fields, and
    (if present) every base/archetype insight + horizons bullet -- must be
    non-empty, http(s), and grounded in that candidate's own data."""
    race = RACES_BY_ID[race_id]
    errors, _ = vc.collect_violations_for_race(race, CANDIDATES, INSIGHTS_BY_RACE_ID.get(race_id))
    assert errors == [], f"{race_id}: {len(errors)} citation violation(s):\n" + "\n".join(errors)


def test_overall_gate_passes_on_real_data() -> None:
    """The aggregated view: collect_violations() over the whole dataset
    must agree with the per-race view above (zero violations) and its
    counts must be internally consistent -- not hardcoded magic numbers
    (which would just break the next time a race/candidate is added), but
    derived live from the same races.json/candidates.json this test loaded."""
    errors, counts = vc.collect_violations(RACES_DOC, CANDIDATES, INSIGHTS_BY_RACE_ID)
    assert errors == [], f"{len(errors)} citation violation(s) in committed gold data:\n" + "\n".join(errors)

    assert counts["races_total"] == len(RACES_DOC["races"])
    assert counts["races_with_insights"] == len(INSIGHTS_BY_RACE_ID)
    assert counts["candidates_checked"] == len(CANDIDATES)
    assert counts["insight_bullets_checked"] > 0
    assert counts["sources_checked"] > 0
    assert counts["sources_checked"] >= counts["candidate_fact_sources_checked"] + counts["race_context_sources_checked"]


def test_cli_script_passes_on_current_data() -> None:
    """Runs the actual wired command (`python3 pipeline/validate_citations.py`,
    the exact string in DEMO_PLAYBOOK.md's pre-stage gate) as a real
    subprocess against the real repo -- proves the CLI entrypoint, not just
    the importable functions, is green."""
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "pipeline" / "validate_citations.py")],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    assert "Citation Integrity Gate: PASS" in result.stdout
    assert "Violations: 0" in result.stdout


# ---------------------------------------------------------------------------
# 3. Self-proving detectors -- RED on an injected defect, GREEN on the real,
#    untouched data. See module docstring + testing.md section 5.
# ---------------------------------------------------------------------------


@selfproof
def test_selfproof_empty_source_detected() -> None:
    """The task's literal example: inject an empty source on a copy of a
    candidate's finance object -> RED; the same check on the real,
    unmodified candidates -> GREEN."""
    candidates_copy = copy.deepcopy(CANDIDATES)
    cid = next(cid for cid, c in candidates_copy.items() if c.get("finance"))
    candidates_copy[cid]["finance"]["source"] = ""

    red_errors, _ = vc.collect_violations(RACES_DOC, candidates_copy, INSIGHTS_BY_RACE_ID)
    assert any(cid in e and "finance.source" in e and "missing/empty" in e for e in red_errors), red_errors

    green_errors, _ = vc.collect_violations(RACES_DOC, copy.deepcopy(CANDIDATES), INSIGHTS_BY_RACE_ID)
    assert green_errors == []


@selfproof
def test_selfproof_fabricated_bullet_source_detected() -> None:
    """An insight bullet whose source is swapped for a URL that appears
    nowhere in that candidate's own record must be caught as a grounding
    (fabrication) violation, not silently accepted."""
    insights_copy = copy.deepcopy(INSIGHTS_BY_RACE_ID)
    race_id, cid, idx = _find_first_bullet(insights_copy)
    insights_copy[race_id]["base"]["candidates"][cid][idx]["source"] = "https://fabricated.example.invalid/not-real"

    red_errors, _ = vc.collect_violations(RACES_DOC, CANDIDATES, insights_copy)
    assert any("possible fabrication" in e for e in red_errors), red_errors

    green_errors, _ = vc.collect_violations(RACES_DOC, CANDIDATES, copy.deepcopy(INSIGHTS_BY_RACE_ID))
    assert green_errors == []


@selfproof
def test_selfproof_non_http_source_detected() -> None:
    """A well-formed but non-http(s) source (e.g. ftp://) must fail even
    though it's non-empty and even if it happens to match a real value."""
    candidates_copy = copy.deepcopy(CANDIDATES)
    cid = next(cid for cid, c in candidates_copy.items() if c.get("positions"))
    candidates_copy[cid]["positions"][0]["source"] = "ftp://not-http.example.invalid/doc"

    red_errors, _ = vc.collect_violations(RACES_DOC, candidates_copy, INSIGHTS_BY_RACE_ID)
    assert any("not http(s)" in e for e in red_errors), red_errors

    green_errors, _ = vc.collect_violations(RACES_DOC, copy.deepcopy(CANDIDATES), INSIGHTS_BY_RACE_ID)
    assert green_errors == []


@selfproof
def test_selfproof_long_term_missing_conditional_phrasing_detected() -> None:
    """A horizons long_term bullet that doesn't open with "If ..." is an
    unlabeled projection presented as fact -- must fail even though it
    still carries a real source and a real assumption."""
    insights_copy = copy.deepcopy(INSIGHTS_BY_RACE_ID)
    race_id, cid, idx = _find_first_long_term_bullet(insights_copy)
    insights_copy[race_id]["base"]["horizons"][cid]["long_term"][idx]["text"] = (
        "This will definitely happen, no hedging at all."
    )

    red_errors, _ = vc.collect_violations(RACES_DOC, CANDIDATES, insights_copy)
    assert any("not conditionally phrased" in e for e in red_errors), red_errors

    green_errors, _ = vc.collect_violations(RACES_DOC, CANDIDATES, copy.deepcopy(INSIGHTS_BY_RACE_ID))
    assert green_errors == []


@selfproof
def test_selfproof_no_data_caveat_exempt_but_normal_bullet_is_not() -> None:
    """Proves the exemption boundary precisely, both directions in one
    test: blanking the source on an honest "no data in our set" bullet is
    NOT a violation (nothing to cite), but blanking the source on an
    ordinary factual bullet IS."""
    insights_copy = copy.deepcopy(INSIGHTS_BY_RACE_ID)
    race_id, cid, idx = _find_first_no_data_bullet(insights_copy)
    insights_copy[race_id]["base"]["candidates"][cid][idx]["source"] = ""
    exempt_errors, _ = vc.collect_violations(RACES_DOC, CANDIDATES, insights_copy)
    assert not any(
        cid in e and f"[{idx}]" in e and race_id in e for e in exempt_errors
    ), "an honest no-data caveat with a blanked source should be exempt"

    insights_copy2 = copy.deepcopy(INSIGHTS_BY_RACE_ID)
    race_id2, cid2, idx2 = _find_first_normal_bullet(insights_copy2)
    insights_copy2[race_id2]["base"]["candidates"][cid2][idx2]["source"] = ""
    red_errors, _ = vc.collect_violations(RACES_DOC, CANDIDATES, insights_copy2)
    assert any(
        cid2 in e and f"[{idx2}]" in e and "missing/empty source" in e for e in red_errors
    ), red_errors


@selfproof
def test_selfproof_horizons_now_bullet_never_exempted() -> None:
    """Unlike `candidates[]` bullets, a `horizons.now[]` bullet gets NO
    no-data exemption -- even one phrased as an honest no-data caveat must
    still carry a source (the horizons generator is expected to skip a
    topic entirely rather than emit an uncited "now" bullet)."""
    insights_copy = copy.deepcopy(INSIGHTS_BY_RACE_ID)
    race_id, cid, idx = _find_first_no_data_horizons_now_bullet(insights_copy)
    insights_copy[race_id]["base"]["horizons"][cid]["now"][idx]["source"] = ""

    red_errors, _ = vc.collect_violations(RACES_DOC, CANDIDATES, insights_copy)
    assert any(
        cid in e and "horizons" in e and ".now[" in e and "missing/empty source" in e for e in red_errors
    ), red_errors

    green_errors, _ = vc.collect_violations(RACES_DOC, CANDIDATES, copy.deepcopy(INSIGHTS_BY_RACE_ID))
    assert green_errors == []


@selfproof
def test_selfproof_main_entrypoint_on_disk_copy(tmp_path: Path) -> None:
    """The most literal reading of the task's self-proof requirement:
    inject an empty source into a real ON-DISK copy of data/tx/ (not just
    an in-memory dict) and prove `main(root=...)` -- the same function
    `python3 pipeline/validate_citations.py` calls -- returns 1; an
    untouched on-disk copy of the same data returns 0. Never touches the
    real, committed data/tx/ directory."""
    red_root = tmp_path / "red"
    _copy_gold_tree(red_root)
    candidates_path = red_root / "data" / "tx" / "candidates.json"
    candidates_on_disk = json.loads(candidates_path.read_text(encoding="utf-8"))
    cid = next(cid for cid, c in candidates_on_disk.items() if c.get("finance"))
    candidates_on_disk[cid]["finance"]["source"] = ""
    candidates_path.write_text(json.dumps(candidates_on_disk), encoding="utf-8")

    assert vc.main(root=red_root) == 1

    green_root = tmp_path / "green"
    _copy_gold_tree(green_root)
    assert vc.main(root=green_root) == 0


# ---------------------------------------------------------------------------
# Helpers used only by the self-proof tests above -- find the first bullet
# of a given shape anywhere in a (possibly already-copied) insights map, so
# each test works against whatever real data looks like today rather than
# a hardcoded race/candidate that could stop existing.
# ---------------------------------------------------------------------------


def _find_first_bullet(insights_by_race_id: dict) -> tuple[str, str, int]:
    for race_id, doc in insights_by_race_id.items():
        cand_map = (doc.get("base") or {}).get("candidates") or {}
        for cid, bullets in cand_map.items():
            if bullets:
                return race_id, cid, 0
    raise AssertionError("no insight bullet found anywhere in data/tx/insights/*.json")


def _find_first_normal_bullet(insights_by_race_id: dict) -> tuple[str, str, int]:
    for race_id, doc in insights_by_race_id.items():
        cand_map = (doc.get("base") or {}).get("candidates") or {}
        for cid, bullets in cand_map.items():
            for i, b in enumerate(bullets):
                if b.get("text") and not vc._is_no_data_bullet(b.get("text")):
                    return race_id, cid, i
    raise AssertionError("no non-no-data insight bullet found")


def _find_first_no_data_bullet(insights_by_race_id: dict) -> tuple[str, str, int]:
    for race_id, doc in insights_by_race_id.items():
        cand_map = (doc.get("base") or {}).get("candidates") or {}
        for cid, bullets in cand_map.items():
            for i, b in enumerate(bullets):
                if vc._is_no_data_bullet(b.get("text")):
                    return race_id, cid, i
    raise AssertionError("no honest no-data bullet found anywhere (unexpected -- see build_insights_house.py)")


def _find_first_long_term_bullet(insights_by_race_id: dict) -> tuple[str, str, int]:
    for race_id, doc in insights_by_race_id.items():
        horizons = (doc.get("base") or {}).get("horizons") or {}
        for cid, h in horizons.items():
            lt = h.get("long_term") or []
            if lt:
                return race_id, cid, 0
    raise AssertionError("no horizons long_term bullet found -- see pipeline/precompute_horizons.py")


def _find_first_no_data_horizons_now_bullet(insights_by_race_id: dict) -> tuple[str, str, int]:
    for race_id, doc in insights_by_race_id.items():
        horizons = (doc.get("base") or {}).get("horizons") or {}
        for cid, h in horizons.items():
            for i, b in enumerate(h.get("now") or []):
                if vc._is_no_data_bullet(b.get("text")):
                    return race_id, cid, i
    raise AssertionError("no no-data-phrased horizons.now bullet found -- see pipeline/precompute_horizons.py")
