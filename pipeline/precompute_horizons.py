#!/usr/bin/env python3
"""
Precompute CONSEQUENCE HORIZONS for the 8 marquee statewide races
(district == null in data/tx/races.json) plus the two flagged U.S. House
races, tx-cd28-2026 and tx-cd34-2026.

Per CLAUDE.md's "Insight engine rules" (Consequence horizons contract):
this adds a `horizons` key -- a sibling of `candidates`/`summary`/
`caveats` -- to EVERY block already present in each target race's
data/tx/insights/{race_id}.json: the "base" block and each of the 8
"archetypes" blocks. Exact shape:

    horizons: {
      <candidate_id>: {
        "now":       [{"text": str, "source": url, "basis": str}, ...],
        "long_term": [{"text": str, "source": url, "basis": str,
                        "assumption": str}, ...]
      },
      ...
    }

This is a pure authoring pass over our own gold data
(data/tx/races.json + data/tx/candidates.json) -- NO external LLM calls.

Authoring rules:
  - "now" (1-2 bullets/candidate): a direct restatement of what a
    candidate's OWN recorded position or roll-call vote means THIS term
    for the given archetype's concern (or, in the "base" block, for the
    issue generically -- base has no single archetype audience).
  - "long_term" (1-2 bullets/candidate): explicitly CONDITIONAL,
    decade-scale projections. Every one:
      (a) opens with a conditional ("If <name>'s recorded position on
          <issue> holds and becomes sustained policy..." / the
          vote-equivalent "If <name>'s vote on <bill> reflects how they
          would vote on similar bills in the future...")
      (b) carries "assumption": one sentence naming exactly what is
          being assumed
      (c) carries "source": the same URL as the recorded evidence it
          extends (verifiable in that candidate's own JSON)
      (d) carries "basis": "position: <issue>" or "vote: <bill>"
    Never a fact -- always explicitly labeled a projection.
  - Campaign finance is deliberately EXCLUDED as horizons evidence:
    receipts/disbursements are fundraising context, not a policy
    "stance" that can be restated as present impact or extended into a
    sustained-policy projection (this mirrors how
    pipeline/precompute_marquee_insights.py already treats finance as
    non-committal context, never a stance proxy).
  - Where a candidate has no recorded position/vote matching a given
    archetype's concern (or, for "base", no recorded position/vote at
    all): exactly ONE honest bullet -- "No recorded evidence in our set
    to project from..." -- goes in "now", sourced to that candidate's
    own top-level source; "long_term" stays empty. Projecting a decade
    forward from zero evidence would be inventing, not extending.
  - Never invents a position, a vote, or an outcome. Every projection is
    the direct, hedged, logical extension of one specific recorded
    datum, explicitly labeled as a projection, never presented as fact.

Idempotent: re-running replaces the "horizons" key this script owns in
each block via plain dict assignment (never appends/duplicates); every
other key in the file is left untouched.
Atomic: each race file is written to a temp file in the same directory
and then os.replace()'d over the original, so a crash mid-run never
leaves a half-written insight file.

Run:
    python3 pipeline/precompute_horizons.py
"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RACES_PATH = os.path.join(ROOT, "data", "tx", "races.json")
CANDIDATES_PATH = os.path.join(ROOT, "data", "tx", "candidates.json")
INSIGHTS_DIR = os.path.join(ROOT, "data", "tx", "insights")

# The two named U.S. House races, in addition to every district==null
# (statewide) race, per the task spec.
TARGET_EXTRA_RACE_IDS = {"tx-cd28-2026", "tx-cd34-2026"}

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

# Plain-English label for "who this is" -- used only to phrase bullets,
# never to invent a candidate's stance.
ARCHETYPE_LABELS = {
    "renter_young_worker": "renters and young workers",
    "homeowner_parent": "homeowners with kids in public school",
    "small_business_owner": "small business owners",
    "healthcare_aca_or_uninsured": "people on ACA marketplace plans or without insurance",
    "medicare_retiree": "Medicare-age retirees",
    "veteran": "veterans",
    "student": "students",
    "rural_agriculture": "rural and agricultural voters",
}

# Plain-English description of what this archetype cares about -- used to
# phrase both the "connects to you" framing and the honest "no data"
# fallback. Matches pipeline/precompute_marquee_insights.py's phrasing.
ARCHETYPE_ISSUE_PHRASE = {
    "renter_young_worker": "housing costs, rent, or renters' protections",
    "homeowner_parent": "property taxes or public school funding",
    "small_business_owner": "small business taxes or regulation",
    "healthcare_aca_or_uninsured": "health coverage, the ACA, or Medicaid",
    "medicare_retiree": "Medicare, Social Security, or retiree benefits",
    "veteran": "veterans' benefits or services",
    "student": "higher education funding or student costs",
    "rural_agriculture": "farming, ranching, water rights, or rural infrastructure",
}

# archetype -> positions[].issue values that are a DIRECT, honest match to
# that archetype's concern (pure tag match -- same convention as
# pipeline/precompute_marquee_insights.py's ARCHETYPE_ISSUE_MATCH).
# "infrastructure" is added for rural_agriculture on the strength of the
# recorded position carrying that tag being explicitly framed as rural
# infrastructure investment in its own summary text (verified against
# data/tx/candidates.json, not assumed).
ARCHETYPE_ISSUE_MATCH = {
    "renter_young_worker": {"housing", "jobs", "labor"},
    "homeowner_parent": {"housing", "education", "taxes"},
    "small_business_owner": {"small business", "taxes", "labor"},
    "healthcare_aca_or_uninsured": {"healthcare"},
    "medicare_retiree": {"medicare medicaid", "social security"},
    "student": {"education"},
    "rural_agriculture": {"infrastructure"},
    # veteran: intentionally absent -- no issue tag in our current
    # taxonomy is a direct match; forcing one would be stretching a loose
    # topic into a claim the record doesn't support.
}

# archetype -> record.key_votes[].bill values that are a direct, honest
# match (same curated set/order as
# pipeline/build_insights_tx20_38.py's ARCHETYPE_RELEVANT_BILLS).
ARCHETYPE_RELEVANT_BILLS = {
    "renter_young_worker": ["H R 1"],
    "homeowner_parent": ["H R 4758", "H R 1"],
    "small_business_owner": ["H R 1"],
    "healthcare_aca_or_uninsured": ["H R 6703", "H R 498", "H R 1"],
    "medicare_retiree": [],
    "veteran": [],
    "student": [],
    "rural_agriculture": ["H R 26", "H R 7744"],
}

# issue slug -> nicer display text, only for slugs that would otherwise
# read awkwardly. Never changes meaning, purely cosmetic.
ISSUE_DISPLAY = {
    "medicare medicaid": "Medicare and Medicaid",
    "social security": "Social Security",
    "ai tech": "AI and technology policy",
    "debt spending": "government debt and spending",
    "lgbtq": "LGBTQ policy",
}


def humanize_issue(issue):
    if not issue:
        return "this issue"
    return ISSUE_DISPLAY.get(issue, issue)


def load_json(path):
    with open(path) as f:
        return json.load(f)


def atomic_write_json(path, obj):
    tmp_path = path + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(obj, f, indent=2)
        f.write("\n")
    os.replace(tmp_path, path)


def candidate_top_level_source(c):
    """Best available 'this candidate, generally' source -- used only for
    the honest no-evidence bullet, never for a position/vote-grounded one."""
    srcs = c.get("sources") or []
    if srcs:
        return srcs[0]
    fin = c.get("finance") or {}
    if fin.get("source"):
        return fin["source"]
    rec = c.get("record") or {}
    if rec.get("source"):
        return rec["source"]
    return None


def matching_positions(c, archetype):
    """positions[] entries whose issue directly matches this archetype,
    highest-confidence first. Empty list if the archetype has no defined
    match set or the candidate has no matching position -- never a filler."""
    match_issues = ARCHETYPE_ISSUE_MATCH.get(archetype)
    if not match_issues:
        return []
    positions = c.get("positions") or []
    matches = [p for p in positions if isinstance(p, dict) and p.get("issue") in match_issues]
    matches.sort(key=lambda p: p.get("confidence", 0), reverse=True)
    return matches


def matching_votes(c, archetype):
    """record.key_votes[] entries whose bill is in this archetype's
    curated relevant-bill list, in that list's preference order."""
    bills = ARCHETYPE_RELEVANT_BILLS.get(archetype) or []
    if not bills:
        return []
    key_votes = (c.get("record") or {}).get("key_votes") or []
    by_bill = {}
    for v in key_votes:
        if isinstance(v, dict) and v.get("bill") and v["bill"] not in by_bill:
            by_bill[v["bill"]] = v
    return [by_bill[bill] for bill in bills if bill in by_bill]


def top_position(c):
    positions = [p for p in (c.get("positions") or []) if isinstance(p, dict)]
    if not positions:
        return None
    return max(positions, key=lambda p: p.get("confidence", 0))


def first_vote(c):
    key_votes = [v for v in (c.get("record") or {}).get("key_votes") or [] if isinstance(v, dict)]
    return key_votes[0] if key_votes else None


def now_bullet_from_position(name, p, audience_phrase):
    issue = p.get("issue") or ""
    issue_disp = humanize_issue(issue)
    summary = p.get("summary") or ""
    if audience_phrase:
        text = (
            f"On {issue_disp}, {name}'s recorded position is: \"{summary}\" "
            f"That's what people focused on {audience_phrase} can expect from "
            f"{name} this term."
        )
    else:
        text = (
            f"On {issue_disp}, {name}'s recorded position is: \"{summary}\" "
            f"That's where {name} stands right now, this term."
        )
    return {"text": text, "source": p.get("source"), "basis": f"position: {issue}"}


def long_term_bullet_from_position(name, p, audience_phrase):
    issue = p.get("issue") or ""
    issue_disp = humanize_issue(issue)
    target = audience_phrase if audience_phrase else "this issue"
    text = (
        f"If {name}'s recorded position on {issue_disp} holds and becomes "
        f"sustained policy, it would likely keep shaping {target} the same way "
        f"over the next decade. This is a projection, not a guarantee."
    )
    assumption = (
        f"Assumes {name} keeps this position and it turns into lasting policy, "
        f"rather than changing later or staying just talk."
    )
    return {
        "text": text,
        "source": p.get("source"),
        "basis": f"position: {issue}",
        "assumption": assumption,
    }


def now_bullet_from_vote(name, v, audience_phrase):
    bill = v.get("bill") or ""
    position = v.get("position") or ""
    date_ = v.get("date") or ""
    plain = v.get("plain_english") or ""
    if audience_phrase:
        text = (
            f"{name} already voted {position} on {bill} ({date_}). {plain} "
            f"That's already decided for the current term and relates to "
            f"{audience_phrase}."
        )
    else:
        text = (
            f"{name} already voted {position} on {bill} ({date_}). {plain} "
            f"That's already decided for the current term."
        )
    return {"text": text, "source": v.get("source"), "basis": f"vote: {bill}"}


def long_term_bullet_from_vote(name, v, audience_phrase):
    bill = v.get("bill") or ""
    target = audience_phrase if audience_phrase else "this issue"
    text = (
        f"If {name}'s vote on {bill} reflects how they would vote on similar "
        f"bills in the future, that pattern would likely keep shaping {target} "
        f"over the next decade. This is a projection, not a guarantee."
    )
    assumption = f"Assumes {name} keeps voting the same way on similar bills in future terms."
    return {
        "text": text,
        "source": v.get("source"),
        "basis": f"vote: {bill}",
        "assumption": assumption,
    }


def no_evidence_bullet(name, c, audience_phrase):
    src = candidate_top_level_source(c)
    if not src:
        return None
    if audience_phrase:
        text = (
            f"No recorded evidence in our set to project from for {name} on "
            f"{audience_phrase}."
        )
    else:
        text = f"No recorded evidence in our set to project from for {name}."
    return {"text": text, "source": src, "basis": "none"}


def build_candidate_horizons(c, archetype):
    """archetype=None builds the audience-neutral 'base' horizons entry;
    otherwise archetype is one of ARCHETYPE_KEYS."""
    name = c.get("name", "This candidate")
    audience_phrase = ARCHETYPE_ISSUE_PHRASE.get(archetype) if archetype else None

    if archetype:
        pos_matches = matching_positions(c, archetype)[:2]
        evidence = [("position", p) for p in pos_matches]
        remaining = 2 - len(evidence)
        if remaining > 0:
            vote_matches = matching_votes(c, archetype)[:remaining]
            evidence += [("vote", v) for v in vote_matches]
        evidence = evidence[:2]
    else:
        tp = top_position(c)
        if tp is not None:
            evidence = [("position", tp)]
        else:
            fv = first_vote(c)
            evidence = [("vote", fv)] if fv is not None else []

    now = []
    long_term = []
    seen_now_text = set()

    for kind, item in evidence:
        if kind == "position":
            nb = now_bullet_from_position(name, item, audience_phrase)
            lb = long_term_bullet_from_position(name, item, audience_phrase)
        else:
            nb = now_bullet_from_vote(name, item, audience_phrase)
            lb = long_term_bullet_from_vote(name, item, audience_phrase)

        if not nb.get("source") or nb["text"] in seen_now_text:
            continue
        seen_now_text.add(nb["text"])
        now.append(nb)
        if lb.get("source"):
            long_term.append(lb)

    if not now:
        neb = no_evidence_bullet(name, c, audience_phrase)
        if neb:
            now = [neb]
        # long_term stays [] -- zero evidence means nothing to project.

    return {"now": now, "long_term": long_term}


def build_horizons_for_block(candidate_ids, candidates, archetype):
    horizons = {}
    for cid in candidate_ids:
        c = candidates.get(cid)
        if not c:
            continue
        horizons[cid] = build_candidate_horizons(c, archetype)
    return horizons


def process_race_file(race, candidates):
    race_id = race["race_id"]
    path = os.path.join(INSIGHTS_DIR, f"{race_id}.json")
    if not os.path.exists(path):
        print(f"SKIP {race_id}: no insight file at {path}")
        return None

    doc = load_json(path)
    cand_ids = race.get("candidate_ids", [])

    base = doc.get("base")
    base_count = 0
    if isinstance(base, dict):
        base["horizons"] = build_horizons_for_block(cand_ids, candidates, None)
        base_count = len(base["horizons"])
    else:
        print(f"WARN {race_id}: no 'base' block found, skipping base horizons")

    archetypes = doc.get("archetypes")
    n_archetype_blocks = 0
    if isinstance(archetypes, dict):
        for key in ARCHETYPE_KEYS:
            block = archetypes.get(key)
            if isinstance(block, dict):
                block["horizons"] = build_horizons_for_block(cand_ids, candidates, key)
                n_archetype_blocks += 1
            else:
                print(f"WARN {race_id}: archetype block '{key}' missing, skipping")
    else:
        print(f"WARN {race_id}: no 'archetypes' block found")

    atomic_write_json(path, doc)
    return {
        "race_id": race_id,
        "base_horizons_candidates": base_count,
        "archetype_blocks_updated": n_archetype_blocks,
    }


def main():
    races_data = load_json(RACES_PATH)
    candidates = load_json(CANDIDATES_PATH)

    target_races = [
        r for r in races_data["races"]
        if r.get("district") is None or r["race_id"] in TARGET_EXTRA_RACE_IDS
    ]

    report = []
    for race in target_races:
        result = process_race_file(race, candidates)
        if result:
            report.append(result)
            print(
                f"wrote horizons -> {result['race_id']}.json "
                f"(base candidates={result['base_horizons_candidates']}, "
                f"archetype blocks updated={result['archetype_blocks_updated']})"
            )

    print(f"\n{len(report)} / {len(target_races)} target race files updated with horizons.")


if __name__ == "__main__":
    main()
