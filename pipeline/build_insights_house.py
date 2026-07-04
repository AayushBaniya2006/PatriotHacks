#!/usr/bin/env python3
"""
Precompute insight content for US House races TX-01 through TX-19.

Reads data/tx/races.json + data/tx/candidates.json (gold data, source of truth).
Writes one file per race: data/tx/insights/{race_id}.json

Rules (see CLAUDE.md):
- every bullet's claim traceable to that race's candidate JSON, ends with its source URL
  taken from that candidate's own JSON (sources / finance.source / record.*.source / positions[].source)
- neutral nonpartisan comparative tone, never endorse
- explicit "No public data in our set on X" when data is missing
- 2-3 bullets per candidate
- plain English, ~8th grade level
- base always computed; all 8 archetypes ADDED only for competitive races
  (last_result margin_pct < 10, OR no incumbent among the candidates in that race)

No external LLM calls -- all text authored deterministically from the gold JSON.
"""
import json
import os
import re
import sys

REPO = "/home/abheekp/vulcan/PatriotHacks"
RACES_PATH = os.path.join(REPO, "data/tx/races.json")
CANDIDATES_PATH = os.path.join(REPO, "data/tx/candidates.json")
OUT_DIR = os.path.join(REPO, "data/tx/insights")
GENERATED_AT = "2026-07-03"

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


def house_districts_1_to_19(races):
    out = []
    for r in races:
        d = r.get("district")
        if not d or not d.startswith("TX-"):
            continue
        m = re.match(r"TX-(\d+)$", d)
        if not m:
            continue
        n = int(m.group(1))
        if r.get("level") == "federal" and 1 <= n <= 19:
            out.append(r)
    out.sort(key=lambda r: int(re.match(r"TX-(\d+)$", r["district"]).group(1)))
    return out


def is_competitive(race, candidates):
    ctx = race.get("context", {}) or {}
    lrd = ctx.get("last_result_detail", {}) or {}
    margin = lrd.get("margin_pct")
    margin_close = isinstance(margin, (int, float)) and margin < 10
    has_incumbent = any(
        candidates.get(cid, {}).get("incumbent") for cid in race.get("candidate_ids", [])
    )
    return margin_close or not has_incumbent


def fallback_source(cand):
    srcs = cand.get("sources") or []
    return srcs[0] if srcs else None


def money(v):
    if v is None:
        return None
    return "${:,.0f}".format(v)


def identity_bullet(cid, cand, race):
    name = cand.get("name", cid)
    party = cand.get("party", "unknown party")
    office = cand.get("office") or race.get("office", "this office")
    src = fallback_source(cand)
    if cand.get("incumbent"):
        text = f"{name} ({party}) is the current officeholder running for {office}."
    else:
        text = f"{name} ({party}) is a candidate for {office}."
    if not src:
        return None
    return {"text": text, "source": src}


def finance_bullet(cid, cand):
    fin = cand.get("finance")
    name = cand.get("name", cid)
    if fin and (fin.get("receipts") is not None or fin.get("disbursements") is not None):
        rec = money(fin.get("receipts"))
        dis = money(fin.get("disbursements"))
        as_of = fin.get("as_of", "an unspecified date")
        src = fin.get("source") or fallback_source(cand)
        if not src:
            return None
        parts = []
        if rec is not None:
            parts.append(f"raised {rec}")
        if dis is not None:
            parts.append(f"spent {dis}")
        if not parts:
            return None
        text = f"As of {as_of}, FEC records show {name} had {' and '.join(parts)} for this campaign."
        return {"text": text, "source": src}
    else:
        src = fallback_source(cand)
        if not src:
            return None
        text = f"No public FEC campaign finance data in our set for {name}."
        return {"text": text, "source": src}


def pick_votes(cand, topics=None, n=1):
    """Return up to n key_votes, optionally biased toward given topic keywords found in plain_english."""
    record = cand.get("record") or {}
    votes = record.get("key_votes") or []
    if not votes:
        return []
    if topics:
        scored = []
        for v in votes:
            pe = (v.get("plain_english") or "").lower()
            hit = any(t in pe for t in topics)
            scored.append((0 if hit else 1, v))
        scored.sort(key=lambda x: x[0])
        chosen = [v for _, v in scored[:n]]
        return chosen
    return votes[:n]


def vote_bullet(cid, cand, topics=None):
    name = cand.get("name", cid)
    votes = pick_votes(cand, topics=topics, n=1)
    if not votes:
        record = cand.get("record")
        if record is None:
            src = fallback_source(cand)
            if not src:
                return None
            text = f"No public voting record in our set for {name} (not currently a member of Congress)."
            return {"text": text, "source": src}
        return None
    v = votes[0]
    src = v.get("source") or (cand.get("record") or {}).get("source") or fallback_source(cand)
    if not src:
        return None
    bill = v.get("bill", "a bill")
    date = v.get("date", "an unspecified date")
    position = v.get("position", "an unrecorded position")
    plain = v.get("plain_english", "")
    text = f"On {date}, {name} voted {position} on {bill}. {plain}".strip()
    return {"text": text, "source": src}


def base_bullets_for_candidate(cid, cand, race):
    bullets = []
    b = identity_bullet(cid, cand, race)
    if b:
        bullets.append(b)
    b = finance_bullet(cid, cand)
    if b:
        bullets.append(b)
    b = vote_bullet(cid, cand)
    if b:
        bullets.append(b)
    # cap at 3, ensure at least something (if totally empty, add explicit gap note)
    if not bullets:
        src = fallback_source(cand)
        if src:
            bullets.append({
                "text": f"No public finance, voting-record, or position data in our set for {cand.get('name', cid)}.",
                "source": src,
            })
    return bullets[:3]


ARCHETYPE_TOPICS = {
    "renter_young_worker": ["housing", "tax", "rent", "energy", "labor", "minimum wage", "student"],
    "homeowner_parent": ["homeowner", "school", "child", "energy", "tax", "housing"],
    "small_business_owner": ["tax", "business", "regulation", "tariff", "loan"],
    "healthcare_aca_or_uninsured": ["aca", "medicaid", "health", "insurance", "subsidy", "premium"],
    "medicare_retiree": ["medicare", "social security", "senior", "retirement"],
    "veteran": ["veteran", "va ", "military", "defense"],
    "student": ["student", "education", "loan", "college", "school"],
    "rural_agriculture": ["farm", "agriculture", "rural", "fracking", "energy", "water"],
}

ARCHETYPE_LABELS = {
    "renter_young_worker": "renters and young workers",
    "homeowner_parent": "homeowners with kids in school",
    "small_business_owner": "small business owners",
    "healthcare_aca_or_uninsured": "people on ACA marketplace plans or uninsured",
    "medicare_retiree": "Medicare-age retirees",
    "veteran": "veterans",
    "student": "students",
    "rural_agriculture": "rural and agricultural households",
}


def archetype_bullets_for_candidate(cid, cand, race, archetype):
    """Archetype-tailored bullets: connect actual recorded votes/finance to the archetype's stakes."""
    name = cand.get("name", cid)
    topics = ARCHETYPE_TOPICS.get(archetype, [])
    bullets = []
    votes = pick_votes(cand, topics=topics, n=2)
    for v in votes:
        src = v.get("source") or (cand.get("record") or {}).get("source") or fallback_source(cand)
        if not src:
            continue
        bill = v.get("bill", "a bill")
        date = v.get("date", "an unspecified date")
        position = v.get("position", "an unrecorded position")
        plain = v.get("plain_english", "")
        label = ARCHETYPE_LABELS.get(archetype, "this group")
        text = (
            f"For {label}: on {date}, {name} voted {position} on {bill}. {plain}"
        ).strip()
        bullets.append({"text": text, "source": src})
    if not bullets:
        src = fallback_source(cand)
        if src:
            label = ARCHETYPE_LABELS.get(archetype, "this group")
            bullets.append({
                "text": f"No public data in our set on how {name}'s record specifically affects {label}.",
                "source": src,
            })
    return bullets[:3]


def build_race_insight(race, candidates):
    race_id = race["race_id"]
    district = race.get("district")
    cids = race.get("candidate_ids", [])
    ctx = race.get("context", {}) or {}
    ctx_src = None
    ctx_srcs = ctx.get("sources") or []
    if ctx_srcs:
        ctx_src = ctx_srcs[0]

    base_candidates = {}
    missing_data_notes = []
    for cid in cids:
        cand = candidates.get(cid)
        if not cand:
            missing_data_notes.append(f"No candidate record found for id '{cid}'.")
            continue
        base_candidates[cid] = base_bullets_for_candidate(cid, cand, race)
        if not cand.get("positions"):
            missing_data_notes.append(
                f"No public data in our set on {cand.get('name', cid)}'s policy positions."
            )
        if not cand.get("finance"):
            pass  # already surfaced in per-candidate bullet

    lrd = ctx.get("last_result_detail", {}) or {}
    if lrd:
        summary = (
            f"This is the U.S. House race for {district}. In the most recent election "
            f"({lrd.get('election_date', 'unknown date')}), {lrd.get('last_winner', 'the previous winner')} "
            f"({lrd.get('party', 'unknown party')}) won by about {lrd.get('margin_pct', 'an unknown')} points "
            f"out of {lrd.get('total_votes', 'an unknown number of')} votes cast. The bullets below "
            f"summarize each current candidate's public finance and voting-record data where available."
        )
    else:
        summary = (
            f"This is the U.S. House race for {district}. The bullets below summarize each "
            f"current candidate's public finance and voting-record data where available."
        )

    caveats = [
        "This summary only includes facts found in our sourced dataset (FEC finance filings and "
        "U.S. House Clerk roll-call votes). It omits anything we could not verify from those sources.",
        "No public data in our set on any candidate's policy positions for this race "
        "(the positions field was empty for every candidate as of this build).",
    ]
    if missing_data_notes:
        caveats.extend(sorted(set(missing_data_notes)))

    base = {
        "candidates": base_candidates,
        "summary": summary,
        "caveats": caveats,
    }

    archetypes = {}
    if is_competitive(race, candidates):
        for arch in ARCHETYPES:
            arch_candidates = {}
            for cid in cids:
                cand = candidates.get(cid)
                if not cand:
                    continue
                arch_candidates[cid] = archetype_bullets_for_candidate(cid, cand, race, arch)
            label = ARCHETYPE_LABELS.get(arch, arch)
            arch_summary = (
                f"For {label} in {district}: this view highlights each candidate's recorded votes "
                f"most relevant to that group, drawn from the same sourced data as the base summary."
            )
            arch_caveats = [
                f"No public data in our set on candidate positions specifically framed for {label}; "
                "bullets are limited to recorded votes and finance facts that plausibly relate to this group.",
            ]
            archetypes[arch] = {
                "candidates": arch_candidates,
                "summary": arch_summary,
                "caveats": arch_caveats,
            }

    return {
        "race_id": race_id,
        "generated_at": GENERATED_AT,
        "base": base,
        "archetypes": archetypes,
    }


def main():
    with open(RACES_PATH) as f:
        races_doc = json.load(f)
    with open(CANDIDATES_PATH) as f:
        candidates = json.load(f)

    races = races_doc.get("races", [])
    target_races = house_districts_1_to_19(races)
    if len(target_races) != 19:
        print(f"WARNING: expected 19 races TX-01..TX-19, found {len(target_races)}", file=sys.stderr)

    os.makedirs(OUT_DIR, exist_ok=True)

    written = []
    for race in target_races:
        insight = build_race_insight(race, candidates)
        out_path = os.path.join(OUT_DIR, f"{race['race_id']}.json")
        with open(out_path, "w") as f:
            json.dump(insight, f, indent=2)
        written.append(out_path)
        n_competitive = "yes" if insight["archetypes"] else "no"
        n_bullets = sum(len(v) for v in insight["base"]["candidates"].values())
        print(f"wrote {out_path} (competitive={n_competitive}, base_bullets={n_bullets})")

    print(f"\nTotal files written: {len(written)}")


if __name__ == "__main__":
    main()
