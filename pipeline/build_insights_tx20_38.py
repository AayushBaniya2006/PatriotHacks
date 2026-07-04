#!/usr/bin/env python3
"""
Precompute insight content for US House races TX-20 through TX-38.

Reads gold data (data/tx/races.json + data/tx/candidates.json) and authors
plain-English, source-cited bullets directly from that data. No external
LLM calls. Writes one file per race to data/tx/insights/{race_id}.json.

Depth rule:
- base: always, for every race in range.
- archetypes (all 8): only for competitive races, defined as
  last_result margin_pct < 10 OR no incumbent among the race's candidates.

Rerun safely: this script is idempotent and only touches races in the
TX-20..TX-38 range (it does not overwrite insight files for other races).
"""
import json
import os
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data", "tx")
INSIGHTS_DIR = os.path.join(DATA_DIR, "insights")
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

# Map archetype -> list of bill numbers (as they appear in record.key_votes
# "bill" field) whose plain_english text is directly relevant to that
# archetype's stakes. Order = preference order (first found wins, up to 2).
ARCHETYPE_RELEVANT_BILLS = {
    "renter_young_worker": ["H R 1"],  # tax cuts on tips/overtime pay affect wage income
    "homeowner_parent": ["H R 4758", "H R 1"],  # homeowner energy-efficiency rules; family budget via tax/Medicaid/SNAP
    "small_business_owner": ["H R 1"],  # tax cuts / reconciliation package affects business taxes
    "healthcare_aca_or_uninsured": ["H R 6703", "H R 498", "H R 1"],  # ACA subsidies, Medicaid, Medicaid/SNAP cuts
    "medicare_retiree": [],  # no Medicare-specific roll call in our data set
    "veteran": [],  # no veteran-specific roll call in our data set
    "student": [],  # no education/student-loan roll call in our data set
    "rural_agriculture": ["H R 26", "H R 7744"],  # fracking moratorium bar; DHS border funding (border/rural districts)
}

ARCHETYPE_LABELS = {
    "renter_young_worker": "renters and young workers",
    "homeowner_parent": "homeowners with kids",
    "small_business_owner": "small business owners",
    "healthcare_aca_or_uninsured": "people on ACA marketplace plans or without insurance",
    "medicare_retiree": "Medicare-age retirees",
    "veteran": "veterans",
    "student": "students",
    "rural_agriculture": "rural and agricultural voters",
}

ARCHETYPE_NO_DATA_NOTE = {
    "medicare_retiree": "no public data in our set on Medicare-specific votes",
    "veteran": "no public data in our set on veteran-specific votes or positions",
    "student": "no public data in our set on education or student-loan votes",
}


def load_json(path):
    with open(path) as f:
        return json.load(f)


def money(x):
    if x is None:
        return None
    return f"${x:,.0f}"


def first_source(cand):
    srcs = cand.get("sources") or []
    return srcs[0] if srcs else None


def finance_bullet(cand):
    fin = cand.get("finance")
    if not fin:
        return None
    receipts = fin.get("receipts")
    disb = fin.get("disbursements")
    as_of = fin.get("as_of")
    src = fin.get("source")
    if receipts is None and disb is None:
        return None
    name = cand["name"]
    parts = []
    if receipts is not None:
        parts.append(f"raised {money(receipts)}")
    if disb is not None:
        parts.append(f"spent {money(disb)}")
    text = f"As of {as_of}, FEC filings show {name}'s campaign has {' and '.join(parts)}."
    return {"text": text, "source": src}


def vote_bullet(cand, vote):
    name = cand["name"]
    bill = vote["bill"]
    position = vote["position"]
    plain = vote["plain_english"]
    date_ = vote.get("date", "")
    text = f"On {bill} ({date_}), {name} voted {position}. {plain}"
    return {"text": text, "source": vote["source"]}


def archetype_vote_bullet(cand, vote, archetype):
    """Same recorded vote as vote_bullet(), but framed for the archetype
    reading it -- without this prefix an archetype block's vote bullet was
    indistinguishable from the base block's (same sentence, no signal for
    *why* it was picked for this reader). Matches the 'For {label}:'
    convention build_insights_house.py already uses for TX-01..19."""
    name = cand["name"]
    bill = vote["bill"]
    position = vote["position"]
    plain = vote["plain_english"]
    date_ = vote.get("date", "")
    label = ARCHETYPE_LABELS.get(archetype, archetype.replace("_", " "))
    text = f"For {label}: on {bill} ({date_}), {name} voted {position}. {plain}"
    return {"text": text, "source": vote["source"]}


def no_record_bullet(cand):
    name = cand["name"]
    src = first_source(cand)
    if not src:
        return None
    text = (
        f"No U.S. House roll-call voting record was in our data set for {name} "
        f"(non-incumbent candidates have no floor votes to record). "
        f"Public candidate filings are listed at the source below."
    )
    return {"text": text, "source": src}


def no_data_at_all_bullet(cand):
    name = cand["name"]
    party = cand.get("party", "an unlisted party")
    office = cand.get("office", "this race")
    src = first_source(cand)
    if not src:
        return None
    text = (
        f"No campaign finance or voting record was in our data set for {name}, "
        f"the {party} candidate for {office}, as of {GENERATED_AT}."
    )
    return {"text": text, "source": src}


def party_note_bullet(cand):
    name = cand["name"]
    party = cand.get("party", "an unlisted party")
    src = first_source(cand)
    if not src:
        return None
    incumbent = cand.get("incumbent")
    status = "the incumbent" if incumbent else "a challenger"
    text = f"{name} is running as {status}, {party} candidate, in {cand.get('office','this race')}."
    return {"text": text, "source": src}


def build_base_bullets(cand):
    """2-3 bullets per candidate: finance + up to 2 notable votes, else fallbacks."""
    bullets = []
    fb = finance_bullet(cand)
    key_votes = (cand.get("record") or {}).get("key_votes") or []

    if fb:
        bullets.append(fb)

    if key_votes:
        # Pick two votes with the broadest plain-English policy relevance:
        # prefer H R 1 (budget reconciliation, broad fiscal impact) and
        # H R 29 (immigration enforcement), falling back to first two listed.
        preferred_order = ["H R 1", "H R 29", "H R 6703"]
        picked = []
        for bill in preferred_order:
            for v in key_votes:
                if v["bill"] == bill and v not in picked:
                    picked.append(v)
                    break
            if len(picked) >= 2:
                break
        if len(picked) < 2:
            for v in key_votes:
                if v not in picked:
                    picked.append(v)
                if len(picked) >= 2:
                    break
        for v in picked[:2]:
            bullets.append(vote_bullet(cand, v))
    elif not fb:
        # No finance, no record at all.
        nd = no_data_at_all_bullet(cand)
        if nd:
            bullets.append(nd)
        pn = party_note_bullet(cand)
        if pn:
            bullets.append(pn)
    else:
        # Has finance but no voting record (challenger).
        nr = no_record_bullet(cand)
        if nr:
            bullets.append(nr)

    # Ensure at least 2 bullets where data allows; trim to max 3.
    if len(bullets) == 1:
        pn = party_note_bullet(cand)
        if pn and pn not in bullets:
            bullets.append(pn)
    return bullets[:3]


def build_archetype_bullets(cand, archetype):
    """1-2 bullets tailored to an archetype's stakes, from actual record/finance."""
    bullets = []
    key_votes = (cand.get("record") or {}).get("key_votes") or []
    relevant_bills = ARCHETYPE_RELEVANT_BILLS.get(archetype, [])

    matched = []
    for bill in relevant_bills:
        for v in key_votes:
            if v["bill"] == bill and v not in matched:
                matched.append(v)
                break
        if len(matched) >= 2:
            break

    for v in matched[:2]:
        bullets.append(archetype_vote_bullet(cand, v, archetype))

    if not bullets:
        # Explicit uncertainty per archetype, backed by whatever source
        # exists -- leads with the candidate's name instead of tacking it on
        # in a trailing parenthetical, and always keeps the literal
        # "no ... in our set" phrasing our no-data detectors key on (see
        # pipeline/validate_citations.py's _NO_DATA_RE).
        src = first_source(cand)
        name = cand["name"]
        label = ARCHETYPE_LABELS.get(archetype, archetype.replace("_", " "))
        note = ARCHETYPE_NO_DATA_NOTE.get(archetype, f"no public data in our set ties their record to {label}")
        if src:
            bullets.append({"text": f"{name}: {note}.", "source": src})

    # If we still have room, add the finance bullet for grounding (money is
    # relevant context for every archetype: campaign scale/access).
    if len(bullets) < 2:
        fb = finance_bullet(cand)
        if fb:
            bullets.append(fb)

    return bullets[:3] if bullets else []


def build_race_insights(race, candidates):
    race_id = race["race_id"]
    cand_ids = race["candidate_ids"]
    cands = {cid: candidates[cid] for cid in cand_ids if cid in candidates}

    base_candidates = {}
    for cid, cand in cands.items():
        bullets = build_base_bullets(cand)
        if bullets:
            base_candidates[cid] = bullets

    n_cands = len(cands)
    district = race.get("district")
    summary = (
        f"{district}: {n_cands} candidate(s) on file for {race.get('office')}. "
        f"Bullets below summarize each candidate's FEC-reported campaign finance and, "
        f"for sitting U.S. House members, selected 2025-2026 roll-call votes on file. "
        f"This is comparative, sourced information only -- it does not recommend a choice."
    )
    caveats = (
        "Only facts present in our sourced candidate data set are shown; missing fields mean no public data was on file at build time. "
        "Voting records only exist for sitting U.S. House incumbents; non-incumbent challengers have no federal roll-call history."
    )

    result = {
        "race_id": race_id,
        "generated_at": GENERATED_AT,
        "base": {
            "candidates": base_candidates,
            "summary": summary,
            "caveats": caveats,
        },
    }

    last_result = race.get("context", {}).get("last_result_detail", {})
    margin_pct = last_result.get("margin_pct")
    any_incumbent = any(c.get("incumbent") for c in cands.values())
    competitive = (margin_pct is not None and margin_pct < 10) or (not any_incumbent)

    if competitive:
        archetypes = {}
        for key in ARCHETYPE_KEYS:
            arch_candidates = {}
            for cid, cand in cands.items():
                bullets = build_archetype_bullets(cand, key)
                if bullets:
                    arch_candidates[cid] = bullets
            arch_summary = (
                f"{district}: how each candidate's on-file record connects to "
                f"{ARCHETYPE_LABELS.get(key, key)}, based only on sourced finance/voting data."
            )
            arch_caveats = (
                "Bullets only draw on this race's sourced candidate data; where no relevant vote or position was on file, that gap is stated explicitly."
            )
            archetypes[key] = {
                "candidates": arch_candidates,
                "summary": arch_summary,
                "caveats": arch_caveats,
            }
        result["archetypes"] = archetypes

    return result, competitive


def main():
    races = load_json(os.path.join(DATA_DIR, "races.json"))["races"]
    candidates = load_json(os.path.join(DATA_DIR, "candidates.json"))

    target_races = []
    for r in races:
        d = r.get("district")
        if d and str(d).startswith("TX-"):
            num = int(d.split("-")[1])
            if 20 <= num <= 38:
                target_races.append(r)

    os.makedirs(INSIGHTS_DIR, exist_ok=True)

    report = []
    for r in sorted(target_races, key=lambda r: int(r["district"].split("-")[1])):
        result, competitive = build_race_insights(r, candidates)
        out_path = os.path.join(INSIGHTS_DIR, f"{r['race_id']}.json")
        with open(out_path, "w") as f:
            json.dump(result, f, indent=2)
        n_base_bullets = sum(len(v) for v in result["base"]["candidates"].values())
        n_arch_bullets = 0
        if "archetypes" in result:
            for arch in result["archetypes"].values():
                n_arch_bullets += sum(len(v) for v in arch["candidates"].values())
        report.append({
            "race_id": r["race_id"],
            "district": r["district"],
            "competitive": competitive,
            "n_candidates": len(r["candidate_ids"]),
            "base_bullets": n_base_bullets,
            "archetype_bullets": n_arch_bullets,
        })

    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
