#!/usr/bin/env python3
"""Fetch all current members of the US Congress into data/politicians/us_congress.json.

Sources (unitedstates/congress-legislators project, public domain):
  - legislators-current.json          roster + ids + bio + terms
  - committees-current.json           committee thomas_id -> name (+ subcommittees)
  - committee-membership-current.json bioguide -> committee memberships + roles
  - legislators-social-media.json     bioguide -> social handles

Stdlib only. Omits fields with no data — never null-pads, never invents.
"""

import json
import re
import sys
import unicodedata
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = "https://unitedstates.github.io/congress-legislators"
ROSTER_URL = f"{BASE}/legislators-current.json"
COMMITTEES_URL = f"{BASE}/committees-current.json"
MEMBERSHIP_URL = f"{BASE}/committee-membership-current.json"
SOCIAL_URL = f"{BASE}/legislators-social-media.json"
PROJECT_URL = "https://github.com/unitedstates/congress-legislators"

OUT_PATH = Path(__file__).resolve().parent.parent / "data" / "politicians" / "us_congress.json"


def fetch_json(url: str):
    print(f"fetching {url} ...", flush=True)
    req = urllib.request.Request(url, headers={"User-Agent": "PatriotHacks-voter-info/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def slugify(text: str) -> str:
    # Strip accents (Mónica -> monica) before replacing non-alphanumerics
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def build_committee_names(committees_raw):
    """Map thomas_id -> display name, for full committees and subcommittees."""
    names = {}
    for com in committees_raw:
        tid = com.get("thomas_id")
        name = com.get("name")
        if not tid or not name:
            continue
        names[tid] = name
        # Short parent name for subcommittee prefixing: strip leading
        # "Committee on ", "Joint Committee on ", etc. is overkill — keep it simple:
        parent_short = re.sub(r"^(House |Senate |Joint )?Committee on ", "", name)
        for sub in com.get("subcommittees", []) or []:
            sub_tid = sub.get("thomas_id")
            sub_name = sub.get("name")
            if sub_tid and sub_name:
                names[tid + sub_tid] = f"{parent_short} — Subcommittee on {sub_name}" \
                    if not sub_name.lower().startswith("subcommittee") \
                    else f"{parent_short} — {sub_name}"
    return names


def build_memberships(membership_raw, committee_names):
    """Map bioguide -> list of {name, role, source}."""
    by_bioguide = {}
    for com_id, members in membership_raw.items():
        com_name = committee_names.get(com_id)
        if not com_name:
            continue
        for m in members:
            bg = m.get("bioguide")
            if not bg:
                continue
            entry = {
                "name": com_name,
                "role": (m.get("title") or "member").lower(),
                "source": PROJECT_URL,
            }
            by_bioguide.setdefault(bg, []).append(entry)
    return by_bioguide


def build_social(social_raw):
    by_bioguide = {}
    for item in social_raw:
        bg = (item.get("id") or {}).get("bioguide")
        if not bg:
            continue
        soc = item.get("social") or {}
        out = {}
        for key in ("twitter", "facebook", "youtube", "instagram"):
            val = soc.get(key)
            if val:
                out[key] = val
        if out:
            by_bioguide[bg] = out
    return by_bioguide


def build_record(leg, memberships, social):
    name_obj = leg.get("name") or {}
    ids = leg.get("id") or {}
    bio = leg.get("bio") or {}
    terms = leg.get("terms") or []
    bioguide = ids.get("bioguide")

    if not terms:
        return None, f"{bioguide}: no terms"
    term = terms[-1]

    term_type = term.get("type")  # "sen" | "rep"
    state = term.get("state")
    party = term.get("party")
    if term_type not in ("sen", "rep") or not state:
        return None, f"{bioguide}: unexpected term type/state ({term_type}/{state})"

    given = name_obj.get("first", "")
    family = name_obj.get("last", "")
    display_name = name_obj.get("official_full") or f"{given} {family}".strip()

    if term_type == "sen":
        office_code = "ussen"
        chamber = "senate"
        office = "U.S. Senator"
        district = None
    else:
        district_num = term.get("district")
        if district_num is None:
            return None, f"{bioguide}: rep with no district"
        chamber = "house"
        office_code = f"ushouse{int(district_num):02d}"
        # District label: plain number (TX-15); at-large/delegate seats as -AL
        district = f"{state}-{int(district_num)}" if int(district_num) > 0 else f"{state}-AL"
        office = f"U.S. Representative ({district})"

    politician_id = f"{slugify(f'{family}-{given}')}-{state.lower()}-{office_code}"

    rec = {
        "politician_id": politician_id,
        "name": display_name,
        "party": party,
        "level": "federal",
        "role": "legislator",
        "office": office,
        "state": state,
        "chamber": chamber,
        "jurisdiction": "US",
        "incumbent": True,
    }
    if not party:
        rec.pop("party", None)
    if district:
        rec["district"] = district

    term_out = {}
    if term.get("start"):
        term_out["start"] = term["start"]
    if term.get("end"):
        term_out["end"] = term["end"]
    if term_out:
        rec["term"] = term_out

    ids_out = {}
    for key in ("bioguide", "fec", "wikidata", "opensecrets", "govtrack", "ballotpedia"):
        val = ids.get(key)
        if val is not None and val != [] and val != "":
            ids_out[key] = val
    if ids_out:
        rec["ids"] = ids_out

    contact = {}
    if term.get("url"):
        contact["website"] = term["url"]
    if term.get("phone"):
        contact["capitol_voice"] = term["phone"]
    if term.get("contact_form"):
        contact["contact_form"] = term["contact_form"]
    if contact:
        rec["contact"] = contact

    if bioguide and bioguide in social:
        rec["social"] = social[bioguide]

    if bioguide and bioguide in memberships:
        rec["committees"] = memberships[bioguide]

    bio_out = {}
    if bio.get("birthday"):
        bio_out["birth_date"] = bio["birthday"]
    if bio.get("gender"):
        bio_out["gender"] = bio["gender"]
    if bio_out:
        rec["bio"] = bio_out

    sources = [ROSTER_URL]
    if contact.get("website"):
        sources.append(contact["website"])
    rec["sources"] = sources

    return rec, None


def main():
    roster = fetch_json(ROSTER_URL)
    committees_raw = fetch_json(COMMITTEES_URL)
    membership_raw = fetch_json(MEMBERSHIP_URL)
    social_raw = fetch_json(SOCIAL_URL)

    committee_names = build_committee_names(committees_raw)
    memberships = build_memberships(membership_raw, committee_names)
    social = build_social(social_raw)

    politicians = []
    skipped = []
    for leg in roster:
        rec, reason = build_record(leg, memberships, social)
        if rec is None:
            skipped.append(reason)
        else:
            politicians.append(rec)

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": PROJECT_URL,
        "politicians": politicians,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w") as f:
        json.dump(out, f, indent=1)
    print(f"wrote {OUT_PATH} ({OUT_PATH.stat().st_size:,} bytes)")

    if skipped:
        print(f"SKIPPED {len(skipped)}:")
        for s in skipped:
            print(f"  - {s}")
    else:
        print("skipped: none")

    # ---- verification ----
    with OUT_PATH.open() as f:
        data = json.load(f)
    pols = data["politicians"]
    assert len(pols) >= 530, f"expected >=530 members, got {len(pols)}"
    seen_ids = set()
    for p in pols:
        for field in ("politician_id", "name", "party", "state", "chamber", "sources"):
            assert p.get(field), f"{p.get('politician_id', '?')}: missing {field}"
        assert len(p["sources"]) >= 1
        assert p["politician_id"] not in seen_ids, f"duplicate id: {p['politician_id']}"
        seen_ids.add(p["politician_id"])

    by_chamber = {}
    for p in pols:
        by_chamber[p["chamber"]] = by_chamber.get(p["chamber"], 0) + 1
    tx = [p for p in pols if p["state"] == "TX"]
    print(f"VERIFY OK: total={len(pols)} by_chamber={by_chamber} TX={len(tx)}")
    tx_sen = sum(1 for p in tx if p["chamber"] == "senate")
    tx_house = sum(1 for p in tx if p["chamber"] == "house")
    print(f"TX breakdown: senate={tx_sen} house={tx_house}")


if __name__ == "__main__":
    sys.exit(main())
