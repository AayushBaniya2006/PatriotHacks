#!/usr/bin/env python3
"""
detect_contradictions.py -- SAYS-VS-VOTED contradiction / consistency detector.

We are the only dataset holding BOTH sides of this check: researched,
sourced stated positions (candidates.json's positions[], sourced to
campaign sites / news / civic-match research) and official roll-call votes
(candidates.json's record.key_votes[], sourced to House Clerk XML). This
script cross-checks the two, deterministically, with no LLM involved.

Reads:
  data/tx/candidates.json

Writes (additive-only embed, atomic temp+rename, matching
pipeline/import_civicmatch_positions.py's convention):
  data/tx/candidates.json  (+ candidate.evidence_checks = [...] -- ONLY for
  candidates where at least one check was found; a candidate with zero
  checks is left byte-for-byte untouched, no empty-list filler key)

--- Method ---

A candidate is only ever considered if they have BOTH a non-empty
positions[] AND a non-empty record.key_votes[] (the gating condition from
the spec). As of this writing that overlap is empirical, not assumed --
see the printed report for the actual count and why.

Step 1, votes -> issue + direction: reuse (not re-derive) the curated
bill -> (issue_id, yea_scalar) table from pipeline/export_civic_match.py,
KEY_VOTE_ISSUE_MAP. That table hand-classifies all 8 real bills in the
current gold set; only 4 of the 8 have a non-null yea_scalar (the bill's
direction on its issue axis is unambiguous -- the other 4 are bundled/
procedural, e.g. an appropriations vote, and stay direction-less by that
table's own design). Only those 4 curated, unambiguous bills can ever
produce a confident vote-side direction here. A "Nay" vote mirrors the
scalar (1 - yea_scalar). scalar < 0.5 => "axis0" pole, > 0.5 => "axis1"
pole, matching the same axis0/axis1 language civic-match/lib/issues.ts
uses for that issue (ISSUE_AXIS_PHRASES below is that same language,
copied not invented, so the pole names mean the same thing on both sides
of the check).

Step 2, positions -> issue + direction: ONLY for the same 4 issues (since
a check needs both sides confident, and only those 4 issues can ever get
a confident vote-side direction). A position's stated summary is scanned
for conservative, explicit keyword phrases (POSITION_DIRECTION_KEYWORDS)
grounded in that issue's actual axis0/axis1 policy content -- e.g.
"criminalize illegal entry" / "border security" for immigration's
enforcement-first pole, "expand legal immigration" / "path to citizenship"
for its expansive pole. If a summary's text matches BOTH poles' phrases
(mixed signal) or NEITHER, the direction is not textually explicit and the
position is skipped for that issue -- never guessed.

Step 3, flagging: for each issue where this candidate has exactly one
confident vote-side pole AND exactly one confident position-side pole
(if either side's own evidence disagrees with itself across multiple
votes/positions on the same issue, that issue is skipped as internally
ambiguous -- never manufactured), flag:
  - "consistency"   when the two poles match (a trust signal: they said
                     what they later did, or vice versa)
  - "contradiction" when the two poles are opposite (also a trust
                     signal -- surfaced neutrally, not punitively)

Expected volume is SMALL: most candidates have only one side of this data
(statewide/Senate candidates have researched positions but never cast a US
House roll-call vote; US House candidates' recorded votes are not, in this
data set, paired with any independently researched stated position -- see
the report this script prints for the exact current count and why). Zero
findings for most candidates, or even for every candidate, is an honest,
correct outcome -- this script never stretches a mapping to manufacture
one just to produce output.

A self-test with synthetic, in-memory-only candidates (never written
anywhere) runs before touching real data, proving the classifier logic
itself is correct independent of how much real overlap currently exists.

Re-runnable: safe to execute repeatedly; already-classified candidates
produce the same evidence_checks again (idempotent), and a rerun over
unchanged data adds nothing new.

Run:
    python3 pipeline/detect_contradictions.py
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CANDIDATES_PATH = ROOT / "data" / "tx" / "candidates.json"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from export_civic_match import KEY_VOTE_ISSUE_MAP  # noqa: E402 -- reuse, don't re-derive

# ---------------------------------------------------------------------------
# Step 1 inputs: only the bills export_civic_match.py's curators marked as
# having an unambiguous direction (yea_scalar is not None). 4 of 8 real
# bills as of 2026-07-03: H R 29 (immigration), H R 26 (energy),
# H R 4758 (climate), H R 498 (lgbtq). The other 4 (H R 1, H R 6703,
# H R 7148, H R 7744) map to an issue but carry no directional scalar in
# that table, so they can never produce a confident vote-side direction
# here -- by design, not an oversight.
# ---------------------------------------------------------------------------
CLEAR_DIRECTION_VOTES: dict[str, tuple[str, float]] = {
    bill: (issue, yea_scalar)
    for bill, (issue, yea_scalar) in KEY_VOTE_ISSUE_MAP.items()
    if yea_scalar is not None
}

# Plain-English axis0/axis1 phrasing for each of the 4 issues above, copied
# (lightly reworded for prose, never re-characterized) from
# civic-match/lib/issues.ts's own axis0/axis1 fields -- the same taxonomy
# export_civic_match.py already cites. Used only for human-readable notes;
# the actual classification logic below is independent of this dict.
ISSUE_AXIS_PHRASES: dict[str, dict[str, str]] = {
    "immigration": {
        "axis0": "stricter enforcement first, more deportations, and less legal immigration",
        "axis1": "expanded legal immigration pathways and protections for undocumented residents",
    },
    "energy": {
        "axis0": "expanding domestic oil, gas, and coal production",
        "axis1": "a rapid shift to renewables and phasing down fossil fuels",
    },
    "climate": {
        "axis0": "minimal climate mandates, prioritizing economic growth and energy costs",
        "axis1": "aggressive emissions cuts and major clean-energy mandates",
    },
    "lgbtq": {
        "axis0": "limiting recent LGBTQ+ policy changes and deferring to states/parents",
        "axis1": "expanded federal LGBTQ+ protections",
    },
}

# ---------------------------------------------------------------------------
# Step 2 inputs: conservative keyword phrases for detecting a STATED
# position's direction. Only fires on a direct, explicit phrase match tied
# to real policy content (never a bare topic word) -- e.g. "criminalize
# illegal entry", "path to citizenship", "opposes the equality act". If a
# summary matches phrases from both poles, or neither, classify_position_
# direction() returns None (skip) rather than guess. Calibrated against
# every real positions[] entry in the current gold set touching these 4
# issues (see detect_contradictions.py's self-test + the diagnostic
# calibration log this script prints for confirmation it fires on real
# text, not just synthetic examples).
# ---------------------------------------------------------------------------
POSITION_DIRECTION_KEYWORDS: dict[str, dict[str, tuple[str, ...]]] = {
    "immigration": {
        "axis0": (
            "criminalize illegal", "criminalizes illegal", "illegal entry and re-entry",
            "mandatory detention", "increase deportation", "increased deportations",
            "more deportations", "deportation orders", "deportation efforts",
            "stricter enforcement", "strict enforcement", "strict immigration enforcement",
            "tougher enforcement", "aggressive immigration enforcement", "aggressively enforce",
            "border wall", "border security", "illegal border crossing",
            "expand border security", "reduce legal immigration", "cut legal immigration",
            "limit legal immigration", "opposes amnesty", "against amnesty",
            "prosecutorial tools against unauthorized migrants", "harboring illegal criminals",
        ),
        "axis1": (
            "expand legal immigration", "expand immigration protections",
            "path to citizenship", "pathway to citizenship",
            "protections for undocumented", "supports daca", "expand asylum",
            "increase legal immigration", "oppose mass deportation", "opposes mass deportation",
            "comprehensive immigration reform", "expand guest-worker", "expanding guest-worker",
            "guest-worker programs",
        ),
    },
    "energy": {
        "axis0": (
            "expand oil", "expand domestic drilling", "expand drilling",
            "supports fracking", "support fracking", "oppose a fracking ban", "opposes a fracking ban",
            "expand oil and gas production", "increase oil and gas production", "more drilling",
            "expand fossil fuel", "fossil fuel infrastructure", "fossil fuel expansion",
            "fossil fuel power",
        ),
        "axis1": (
            "phase down fossil fuels", "phase out fossil fuels",
            "rapid transition to renewables", "shift to renewables",
            "expand renewable energy", "ban fracking", "bans fracking",
            "opposes new drilling", "oppose new drilling",
        ),
    },
    "climate": {
        "axis0": (
            "roll back emissions", "rolls back emissions", "roll back energy-efficiency",
            "rolls back energy-efficiency", "opposes clean-energy mandates", "oppose clean-energy mandates",
            "opposes clean energy mandates", "oppose clean energy mandates",
            "minimal mandates", "against clean energy mandates", "against clean-energy mandates",
            "cut climate regulations", "cuts climate regulations",
        ),
        "axis1": (
            "aggressive emissions cuts", "supports clean-energy mandates", "support clean-energy mandates",
            "supports clean energy mandates", "support clean energy mandates",
            "expand clean-energy requirements", "expand clean energy requirements",
            "rapid emissions cuts", "supports a clean energy standard",
        ),
    },
    "lgbtq": {
        "axis0": (
            "defer to states", "limit gender-transition", "limits gender-transition",
            "opposes gender-transition", "bars gender-transition", "restrict gender-transition",
            "against the equality act", "opposes the equality act", "opposes expanding lgbtq",
        ),
        "axis1": (
            "expand federal protections", "supports the equality act", "support the equality act",
            "expand lgbtq protections", "expand anti-discrimination protections",
            "supports gender-transition access", "supports transgender rights",
        ),
    },
}


def _normalize_issue(raw: str | None) -> str:
    """'debt spending' / 'debt_spending' / ' Debt-Spending ' -> 'debt_spending'.
    None of the 4 issues this script acts on ever contain a space or
    underscore, so this only matters defensively (a future curated bill
    could map to a multi-word issue id)."""
    s = (raw or "").strip().lower()
    return re.sub(r"[\s_-]+", "_", s)


def classify_vote_direction(vote: dict) -> tuple[str, str] | None:
    """Return (issue, pole) iff this key_vote maps to one of the 4 curated,
    unambiguous-direction bills AND was cast Yea or Nay (never Present /
    Not Voting / missing). pole is "axis0" or "axis1"."""
    bill = (vote.get("bill") or "").strip()
    mapped = CLEAR_DIRECTION_VOTES.get(bill)
    if mapped is None:
        return None
    issue, yea_scalar = mapped
    position = (vote.get("position") or "").strip().capitalize()
    if position == "Yea":
        scalar = yea_scalar
    elif position == "Nay":
        scalar = 1 - yea_scalar
    else:
        return None
    if scalar < 0.5:
        return issue, "axis0"
    if scalar > 0.5:
        return issue, "axis1"
    return None  # exact 0.5 -- not produced by any curated bill today


def classify_position_direction(position_entry: dict) -> tuple[str, str] | None:
    """Return (issue, pole) iff position_entry's own issue is one of the 4
    this script supports AND its summary text explicitly, unambiguously
    matches exactly one pole's keyword phrases. Mixed or no signal -> None."""
    issue = _normalize_issue(position_entry.get("issue"))
    keywords = POSITION_DIRECTION_KEYWORDS.get(issue)
    if keywords is None:
        return None
    summary = (position_entry.get("summary") or "").lower()
    if not summary:
        return None
    hit0 = any(phrase in summary for phrase in keywords["axis0"])
    hit1 = any(phrase in summary for phrase in keywords["axis1"])
    if hit0 and hit1:
        return None  # mixed signal in the candidate's own words -- not explicit
    if hit0:
        return issue, "axis0"
    if hit1:
        return issue, "axis1"
    return None


def _best_by_confidence(current: dict | None, candidate: dict) -> dict:
    if current is None:
        return candidate
    if (candidate.get("confidence") or 0) > (current.get("confidence") or 0):
        return candidate
    return current


def build_evidence_check(issue: str, kind: str, position: dict, vote: dict, position_pole: str, vote_pole: str) -> dict:
    axis = ISSUE_AXIS_PHRASES[issue]
    if kind == "consistency":
        note = (
            f"Stated position on {issue} and recorded vote on {vote.get('bill')} point in the "
            f"same direction ({axis[position_pole]})."
        )
    else:
        note = (
            f"Stated position on {issue} and recorded vote on {vote.get('bill')} point in "
            f"opposite directions (stated: {axis[position_pole]}; voted: {axis[vote_pole]})."
        )
    return {
        "issue": issue,
        "kind": kind,
        "stated": {"summary": position.get("summary"), "source": position.get("source")},
        "voted": {
            "bill": vote.get("bill"),
            "position": vote.get("position"),
            "plain_english": vote.get("plain_english"),
            "source": vote.get("source"),
        },
        "note": note,
    }


def find_candidate_evidence_checks(candidate: dict) -> list[dict]:
    """Pure function: candidate dict in, evidence_checks list out (possibly
    empty). Never mutates the input."""
    positions = candidate.get("positions") or []
    key_votes = (candidate.get("record") or {}).get("key_votes") or []
    if not positions or not key_votes:
        return []  # gating condition: needs BOTH sides of the data

    vote_poles_by_issue: dict[str, set] = {}
    vote_evidence_by_issue: dict[str, dict] = {}
    for v in key_votes:
        result = classify_vote_direction(v)
        if result is None:
            continue
        issue, pole = result
        vote_poles_by_issue.setdefault(issue, set()).add(pole)
        vote_evidence_by_issue.setdefault(issue, v)

    position_poles_by_issue: dict[str, set] = {}
    position_evidence_by_issue: dict[str, dict] = {}
    for p in positions:
        result = classify_position_direction(p)
        if result is None:
            continue
        issue, pole = result
        position_poles_by_issue.setdefault(issue, set()).add(pole)
        position_evidence_by_issue[issue] = _best_by_confidence(position_evidence_by_issue.get(issue), p)

    checks = []
    shared_issues = sorted(set(vote_poles_by_issue) & set(position_poles_by_issue))
    for issue in shared_issues:
        vpoles = vote_poles_by_issue[issue]
        ppoles = position_poles_by_issue[issue]
        if len(vpoles) != 1 or len(ppoles) != 1:
            continue  # this candidate's own votes or positions disagree with themselves -- skip
        vote_pole = next(iter(vpoles))
        position_pole = next(iter(ppoles))
        kind = "consistency" if vote_pole == position_pole else "contradiction"
        checks.append(
            build_evidence_check(
                issue, kind,
                position_evidence_by_issue[issue], vote_evidence_by_issue[issue],
                position_pole, vote_pole,
            )
        )
    return checks


# ---------------------------------------------------------------------------
# Self-test: synthetic, in-memory-only candidates. Never written to disk,
# never merged into the real `candidates` dict. Proves the classifier is
# correct independent of how much real overlap exists in the current data.
# ---------------------------------------------------------------------------
def _selftest() -> None:
    contradiction_candidate = {
        "name": "Selftest Contradiction",
        "positions": [{
            "issue": "immigration",
            "summary": "Supports expanding legal immigration and a path to citizenship for undocumented residents.",
            "source": "https://example.test/position",
            "confidence": 0.9,
        }],
        "record": {"key_votes": [{
            "bill": "H R 29", "position": "Yea",
            "plain_english": "A Yea vote required federal detention of certain criminal aliens.",
            "source": "https://clerk.house.gov/evs/2025/roll006.xml",
        }]},
    }
    checks = find_candidate_evidence_checks(contradiction_candidate)
    assert len(checks) == 1, f"expected 1 check, got {len(checks)}"
    assert checks[0]["kind"] == "contradiction", f"expected contradiction, got {checks[0]['kind']}"
    assert checks[0]["issue"] == "immigration"

    consistency_candidate = {
        "name": "Selftest Consistency",
        "positions": [{
            "issue": "lgbtq",
            "summary": "Opposes expanding LGBTQ+ protections and supports deferring to states on gender-transition policy.",
            "source": "https://example.test/position2",
            "confidence": 0.9,
        }],
        "record": {"key_votes": [{
            "bill": "H R 498", "position": "Yea",
            "plain_english": "A Yea vote barred state Medicaid programs from covering gender-transition procedures for minors.",
            "source": "https://clerk.house.gov/evs/2025/roll362.xml",
        }]},
    }
    checks = find_candidate_evidence_checks(consistency_candidate)
    assert len(checks) == 1, f"expected 1 check, got {len(checks)}"
    assert checks[0]["kind"] == "consistency", f"expected consistency, got {checks[0]['kind']}"

    unclear_candidate = {
        "name": "Selftest Unclear",
        "positions": [{
            "issue": "immigration",
            "summary": "Has discussed immigration policy in several interviews this year.",
            "source": "https://example.test/position3",
            "confidence": 0.7,
        }],
        "record": {"key_votes": [{
            "bill": "H R 29", "position": "Yea",
            "plain_english": "A Yea vote required federal detention of certain criminal aliens.",
            "source": "https://clerk.house.gov/evs/2025/roll006.xml",
        }]},
    }
    checks = find_candidate_evidence_checks(unclear_candidate)
    assert checks == [], f"expected no checks (position direction not explicit), got {checks}"

    no_scalar_candidate = {
        "name": "Selftest No-Scalar Bill",
        "positions": [{
            "issue": "taxes",
            "summary": "Supports cutting taxes for middle-class families.",
            "source": "https://example.test/position4",
            "confidence": 0.9,
        }],
        "record": {"key_votes": [{
            "bill": "H R 1", "position": "Yea",
            "plain_english": "A Yea vote passed the 2025 budget reconciliation package.",
            "source": "https://clerk.house.gov/evs/2025/roll145.xml",
        }]},
    }
    checks = find_candidate_evidence_checks(no_scalar_candidate)
    assert checks == [], f"expected no checks (H R 1 has no directional scalar), got {checks}"

    positions_only_candidate = {
        "name": "Selftest Positions Only",
        "positions": [{"issue": "immigration", "summary": "x", "source": "https://example.test/p"}],
        "record": {"key_votes": []},
    }
    assert find_candidate_evidence_checks(positions_only_candidate) == []

    votes_only_candidate = {
        "name": "Selftest Votes Only",
        "positions": [],
        "record": {"key_votes": [{"bill": "H R 29", "position": "Yea", "plain_english": "x", "source": "https://x"}]},
    }
    assert find_candidate_evidence_checks(votes_only_candidate) == []

    print("SELFTEST: 6/6 synthetic cases passed (contradiction, consistency, unclear-position-skip, "
          "no-scalar-vote-skip, positions-only-skip, votes-only-skip).")


def main() -> int:
    _selftest()

    with open(CANDIDATES_PATH, encoding="utf-8") as f:
        candidates = json.load(f)

    both_ids = [
        cid for cid, c in candidates.items()
        if (c.get("positions") or []) and ((c.get("record") or {}).get("key_votes") or [])
    ]

    total_checks = 0
    n_contradiction = 0
    n_consistency = 0
    modified_ids = []
    calibration_log = []  # diagnostic only -- never written to candidates.json

    for cid, c in candidates.items():
        checks = find_candidate_evidence_checks(c)
        if checks:
            c["evidence_checks"] = checks
            modified_ids.append(cid)
            total_checks += len(checks)
            n_contradiction += sum(1 for ch in checks if ch["kind"] == "contradiction")
            n_consistency += sum(1 for ch in checks if ch["kind"] == "consistency")

        # Diagnostic-only: what direction (if any) does each side of the
        # classifier extract from this candidate's OWN real data, whether or
        # not the other side exists to pair it with? Proves the classifier
        # fires on real text rather than never firing at all.
        for p in c.get("positions") or []:
            result = classify_position_direction(p)
            if result:
                calibration_log.append(f"  position  {cid:25s} issue={result[0]:12s} pole={result[1]}")
        for v in (c.get("record") or {}).get("key_votes") or []:
            result = classify_vote_direction(v)
            if result:
                calibration_log.append(
                    f"  vote      {cid:25s} issue={result[0]:12s} pole={result[1]} bill={v.get('bill')}"
                )

    print("\n=== detect_contradictions.py ===")
    print(f"Total candidates: {len(candidates)}")
    print(f"Candidates with BOTH non-empty positions[] AND non-empty record.key_votes[]: {len(both_ids)}")
    if both_ids:
        print(f"  -> {both_ids}")
    print(f"evidence_checks written: {total_checks} across {len(modified_ids)} candidate(s) "
          f"(contradiction={n_contradiction}, consistency={n_consistency})")

    print("\nDiagnostic calibration log (position/vote direction extraction against REAL data in this "
          "gold set, on the 4 issues with a curated confident vote-side direction -- shown whether or "
          "not that candidate has the other side to pair against; proves the classifier isn't inert):")
    if calibration_log:
        for line in calibration_log:
            print(line)
    else:
        print("  (no real position or vote in the current gold set matched the keyword/curated tables)")

    if total_checks == 0:
        print(
            "\nZERO evidence_checks produced. This is the honest, correct outcome given the gating "
            "condition (candidate needs BOTH positions[] and key_votes[] non-empty) -- see the count "
            "above for exactly how many candidates qualify and why."
        )
        print("candidates.json left unchanged (no write performed).")
        return 0

    fd, tmp_path = tempfile.mkstemp(
        dir=str(CANDIDATES_PATH.parent), prefix=".candidates.", suffix=".json.tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(candidates, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp_path, CANDIDATES_PATH)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise
    print(f"\nWrote {CANDIDATES_PATH} ({len(modified_ids)} candidate(s) gained evidence_checks)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
