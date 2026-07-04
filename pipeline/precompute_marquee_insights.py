#!/usr/bin/env python3
"""
Precompute base + 8-archetype insight content for MARQUEE races
(every race in data/tx/races.json with district == null: all TX
statewide offices + US Senate).

This is a pure authoring pass over our own gold data
(data/tx/races.json + data/tx/candidates.json) -- NO external LLM calls.
Every bullet's claim is drawn from that candidate's own JSON record and
ends with a source URL copied verbatim from that same record. When a
candidate has no recorded positions/votes/finance relevant to a topic,
we say so explicitly instead of guessing.

Output: one file per race at data/tx/insights/{race_id}.json matching:
{race_id, generated_at, base:{candidates, summary, caveats},
 archetypes:{key:{candidates, summary, caveats}}}

Re-runnable: safe to execute repeatedly; always overwrites cleanly.
"""
import json
import os
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RACES_PATH = os.path.join(ROOT, "data", "tx", "races.json")
CANDIDATES_PATH = os.path.join(ROOT, "data", "tx", "candidates.json")
OUT_DIR = os.path.join(ROOT, "data", "tx", "insights")

GENERATED_AT = "2026-07-03"

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

# Plain-English description of the stakes/topic each archetype cares about,
# used only to phrase an explicit "no data on X" statement -- never to
# invent a candidate stance.
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

# Background-text keyword -> archetype this genuinely, directly connects to.
# Keys are lowercase substrings we search for in the candidate's own
# "background" field (which itself carries the same source as the rest
# of that candidate's record).
BACKGROUND_ARCHETYPE_HINTS = [
    ("beekeeper", "rural_agriculture"),
    ("rancher", "rural_agriculture"),
    ("farm", "rural_agriculture"),
    ("small business", "small_business_owner"),
    ("certified public accountant", "small_business_owner"),
    ("teacher", "student"),
]


def money(n):
    if n is None:
        return None
    return f"${n:,.0f}"


def candidate_office_bullet(cid, c):
    party = c.get("party", "an unlisted party")
    office = c.get("office", "this office")
    src = (c.get("sources") or [None])[0]
    text = f"{c['name']} is a candidate for {office}, running with {party}."
    return {"text": text, "source": src}


def candidate_background_bullet(cid, c):
    src = (c.get("sources") or [None])[0]
    bg = c.get("background")
    if c.get("incumbent"):
        if bg:
            text = f"{c['name']} is the incumbent in this race. Recorded background: {bg}"
        else:
            text = f"{c['name']} is the incumbent officeholder in this race."
    else:
        if bg:
            text = f"{c['name']}'s recorded background: {bg}"
        else:
            text = f"No public background summary in our set for {c['name']} beyond their name and party."
    return {"text": text, "source": src}


def candidate_finance_or_missing_bullet(cid, c):
    fin = c.get("finance")
    src_fallback = (c.get("sources") or [None])[0]
    if fin:
        receipts = money(fin.get("receipts"))
        disb = money(fin.get("disbursements"))
        as_of = fin.get("as_of")
        parts = []
        if receipts is not None:
            parts.append(f"raised {receipts} in campaign receipts")
        if disb is not None:
            parts.append(f"spent {disb}")
        detail = " and ".join(parts) if parts else "reported campaign finance activity"
        text = f"As of {as_of}, {c['name']}'s campaign had {detail}, per FEC filings."
        return {"text": text, "source": fin.get("source", src_fallback)}
    else:
        text = (
            f"No public data in our set on {c['name']}'s campaign finance totals "
            f"(this office is not required to file with the FEC, or no filing was found)."
        )
        return {"text": text, "source": src_fallback}


def build_base_for_race(race, candidates):
    cand_bullets = {}
    for cid in race["candidate_ids"]:
        c = candidates.get(cid)
        if not c:
            continue
        bullets = [
            candidate_office_bullet(cid, c),
            candidate_background_bullet(cid, c),
            candidate_finance_or_missing_bullet(cid, c),
        ]
        # keep to 2-3, drop any bullet with no usable source
        bullets = [b for b in bullets if b.get("source")]
        cand_bullets[cid] = bullets[:3]

    names = [candidates[cid]["name"] for cid in race["candidate_ids"] if cid in candidates]
    summary = (
        f"{race['office']} race: {', '.join(names)}. "
        f"This overview lists each candidate's party, background, and campaign finance "
        f"where available in our data set."
    )
    caveats = (
        "Our data set for this race covers candidate name, party, incumbency, "
        "background summary, and (for federal candidates only) FEC campaign finance "
        "totals. We do not have recorded voting histories or issue-by-issue policy "
        "positions for these candidates in this data set; state executive offices "
        "generally do not file with the FEC, so campaign finance is not available "
        "for most of them here."
    )
    return {"candidates": cand_bullets, "summary": summary, "caveats": caveats}


def archetype_background_bullet(cid, c, archetype):
    """If the candidate's own recorded background genuinely mentions something
    tied to this archetype, cite it. Otherwise state plainly that we have
    no recorded connection -- never invent a stance."""
    src = (c.get("sources") or [None])[0]
    bg = (c.get("background") or "")
    bg_lower = bg.lower()
    for keyword, arch in BACKGROUND_ARCHETYPE_HINTS:
        if arch == archetype and keyword in bg_lower:
            text = (
                f"{c['name']}'s recorded background ({bg}) is directly relevant to "
                f"{archetype.replace('_', ' ')} voters, though our data set does not "
                f"include a specific stated position from them on "
                f"{ARCHETYPE_ISSUE_PHRASE[archetype]}."
            )
            return {"text": text, "source": src}
    text = (
        f"No public data in our set connects {c['name']}'s recorded background or "
        f"positions specifically to {ARCHETYPE_ISSUE_PHRASE[archetype]}."
    )
    return {"text": text, "source": src}


def archetype_positions_missing_bullet(cid, c, archetype):
    src = (c.get("sources") or [None])[0]
    text = (
        f"No public data in our set on {c['name']}'s recorded votes or stated "
        f"positions regarding {ARCHETYPE_ISSUE_PHRASE[archetype]}."
    )
    return {"text": text, "source": src}


def archetype_finance_context_bullet(cid, c, archetype):
    fin = c.get("finance")
    if not fin:
        return None
    as_of = fin.get("as_of")
    receipts = money(fin.get("receipts"))
    text = (
        f"As of {as_of}, {c['name']}'s campaign had raised {receipts} in total, per "
        f"FEC filings. That is general campaign-finance context; it does not tell us "
        f"the candidate's stance on {ARCHETYPE_ISSUE_PHRASE[archetype]}."
    )
    return {"text": text, "source": fin.get("source")}


def build_archetype_for_race(race, candidates, archetype):
    cand_bullets = {}
    for cid in race["candidate_ids"]:
        c = candidates.get(cid)
        if not c:
            continue
        bullets = [
            archetype_background_bullet(cid, c, archetype),
            archetype_positions_missing_bullet(cid, c, archetype),
        ]
        fin_bullet = archetype_finance_context_bullet(cid, c, archetype)
        if fin_bullet:
            bullets.append(fin_bullet)
        bullets = [b for b in bullets if b and b.get("source")]
        # de-duplicate identical text (can happen for candidates with no
        # background hint at all, where two bullets might otherwise repeat)
        seen = set()
        deduped = []
        for b in bullets:
            if b["text"] in seen:
                continue
            seen.add(b["text"])
            deduped.append(b)
        cand_bullets[cid] = deduped[:3]

    names = [candidates[cid]["name"] for cid in race["candidate_ids"] if cid in candidates]
    issue = ARCHETYPE_ISSUE_PHRASE[archetype]
    summary = (
        f"For a {archetype.replace('_', ' ')} voter looking at the {race['office']} race "
        f"({', '.join(names)}): our data set does not contain candidate-specific "
        f"positions or voting records on {issue} for this race. Below is what we do "
        f"have on each candidate's background and, where available, campaign finance."
    )
    caveats = (
        f"We only show a connection to {archetype.replace('_', ' ')} concerns when a "
        f"candidate's own recorded background in our data set names it directly (for "
        f"example, a farming or small-business background). Where no such record "
        f"exists, we say so rather than guess at a candidate's likely position."
    )
    return {"candidates": cand_bullets, "summary": summary, "caveats": caveats}


def main():
    with open(RACES_PATH) as f:
        races_data = json.load(f)
    with open(CANDIDATES_PATH) as f:
        candidates = json.load(f)

    marquee_races = [r for r in races_data["races"] if r.get("district") is None]

    os.makedirs(OUT_DIR, exist_ok=True)

    written = []
    for race in marquee_races:
        base = build_base_for_race(race, candidates)
        archetypes = {
            key: build_archetype_for_race(race, candidates, key)
            for key in ARCHETYPE_KEYS
        }
        out = {
            "race_id": race["race_id"],
            "generated_at": GENERATED_AT,
            "base": base,
            "archetypes": archetypes,
        }
        out_path = os.path.join(OUT_DIR, f"{race['race_id']}.json")
        with open(out_path, "w") as f:
            json.dump(out, f, indent=2)
        written.append(out_path)
        print(f"wrote {out_path}")

    print(f"\n{len(written)} marquee race insight files written.")


if __name__ == "__main__":
    main()
