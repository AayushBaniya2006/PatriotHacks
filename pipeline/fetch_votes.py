#!/usr/bin/env python3
"""
Fetch the TX congressional delegation roster, 8 high-salience 2025-2026 House
roll-call votes (with every TX member's position), and sponsored-legislation
highlights for the 2 TX senators (+ any House member running for Senate).

Writes data/tx/raw/incumbent_votes.json.

Roster source (primary attempt): congress.gov /v3/member/congress/119/TX.
  Fallback (used when the DEMO_KEY shared rate limit is exhausted, which it
  was for the entire ~20 min build window on 2026-07-03): the public-domain
  unitedstates/congress-legislators dataset (legislators-current.yaml),
  which carries the same bioguide IDs congress.gov uses. Every roster record
  still cites its actual source URL.

Votes source: clerk.house.gov roll-call XML (keyless, no rate limit hit).
  The name-id attribute on each <legislator> IS the bioguide ID.

Sponsored-legislation source: congress.gov /v3/member/{bioguide}/sponsored-legislation.
  Skipped gracefully (recorded in the `gaps` field, omitted from `sponsored`)
  when congress.gov keeps returning 429 OVER_RATE_LIMIT on DEMO_KEY.

Rerunnable. Uses CONGRESS_GOV_API_KEY from .env if present, else DEMO_KEY.
Budget: ~1 roster call + 8 roll XML fetches + <=6 sponsored-legislation calls
(2 senators x up to 3 pages) = well under 30 requests.
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(REPO_ROOT, ".env")
OUT_PATH = os.path.join(REPO_ROOT, "data", "tx", "raw", "incumbent_votes.json")

CONGRESS_BASE = "https://api.congress.gov/v3"
LEGISLATORS_YAML_URL = (
    "https://raw.githubusercontent.com/unitedstates/congress-legislators/"
    "main/legislators-current.yaml"
)

GAPS = []


def load_api_key():
    key = None
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH) as f:
            for line in f:
                line = line.strip()
                if line.startswith("CONGRESS_GOV_API_KEY="):
                    key = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    return key or "DEMO_KEY"


API_KEY = load_api_key()


def http_get(url, timeout=20, headers=None):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "PatriotHacks-voter-tool/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def congress_get(path, params=""):
    """GET from congress.gov v3 API. Returns parsed JSON dict or None on failure."""
    sep = "&" if "?" in path else "?"
    url = f"{CONGRESS_BASE}{path}{sep}api_key={API_KEY}&format=json{params}"
    try:
        raw = http_get(url)
        return json.loads(raw)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "ignore")
        print(f"  congress.gov HTTPError {e.code} for {path}: {body[:200]}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"  congress.gov error for {path}: {e}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# (a) Roster
# ---------------------------------------------------------------------------

def fetch_roster_congress_gov():
    """Try congress.gov member roster. Returns list[dict] or None."""
    data = congress_get("/member/congress/119/TX", "&limit=250")
    if not data or "members" not in data:
        return None
    members = []
    for m in data["members"]:
        bioguide = m.get("bioguideId")
        name = m.get("name")
        party = m.get("partyName")
        district = m.get("district")
        terms = (m.get("terms") or {}).get("item") or []
        chamber = None
        if terms:
            last = terms[-1].get("chamber", "")
            chamber = "Senate" if "Senate" in last else "House"
        district_fmt = None
        if chamber == "House" and district is not None:
            district_fmt = f"TX-{int(district):02d}"
        members.append({
            "bioguide_id": bioguide,
            "name": name,
            "party": party,
            "district": district_fmt,
            "chamber": chamber,
            "source": "https://api.congress.gov/v3/member/congress/119/TX",
        })
    return members


def fetch_roster_fallback_yaml():
    """Fallback: unitedstates/congress-legislators current YAML, filtered to TX."""
    import yaml  # local import; only needed for the fallback path
    raw = http_get(LEGISLATORS_YAML_URL, timeout=30)
    data = yaml.safe_load(raw)
    members = []
    for leg in data:
        terms = leg.get("terms", [])
        if not terms:
            continue
        cur = terms[-1]
        if cur.get("state") != "TX":
            continue
        bioguide = leg.get("id", {}).get("bioguide")
        name = leg.get("name", {})
        full = name.get("official_full") or f"{name.get('first', '')} {name.get('last', '')}".strip()
        chamber = "Senate" if cur.get("type") == "sen" else "House"
        district = None
        if chamber == "House":
            d = cur.get("district")
            if d is not None:
                district = f"TX-{int(d):02d}" if d != 0 else "TX-AL"
        members.append({
            "bioguide_id": bioguide,
            "name": full,
            "party": cur.get("party"),
            "district": district,
            "chamber": chamber,
            "source": LEGISLATORS_YAML_URL,
        })
    members.sort(key=lambda m: (m["chamber"], m["district"] or "", m["name"]))
    districts = {m["district"] for m in members if m["chamber"] == "House"}
    missing = [f"TX-{i:02d}" for i in range(1, 39) if f"TX-{i:02d}" not in districts]
    if missing:
        GAPS.append(
            f"legislators-current.yaml fallback has no current House member listed for "
            f"{', '.join(missing)} (vacant seat or dataset lag) — omitted rather than guessed."
        )
    return members


def fetch_roster():
    members = fetch_roster_congress_gov()
    if members:
        return members
    GAPS.append(
        "congress.gov /v3/member/congress/119/TX returned 429 OVER_RATE_LIMIT on "
        "DEMO_KEY for the entire build window (no CONGRESS_GOV_API_KEY in .env); "
        "used unitedstates/congress-legislators legislators-current.yaml as a "
        "public-domain fallback for the roster (same bioguide IDs)."
    )
    return fetch_roster_fallback_yaml()


# ---------------------------------------------------------------------------
# (b) High-salience House roll calls, 2025-2026
# ---------------------------------------------------------------------------
# Selected by scanning the clerk.house.gov yearly roll-call indexes
# (https://clerk.house.gov/evs/2025/index.asp, .../2026/index.asp and their
# ROLL_*.asp pagination pages) for "On Passage" votes on major substantive
# legislation (budget/reconciliation, healthcare, immigration/border, taxes,
# energy) rather than procedural/rules votes.
VOTE_PICKS = [
    {"year": 2025, "roll": 6,
     "plain_english": "A Yea vote required federal detention of unauthorized immigrants "
                       "charged with theft, burglary, larceny, or assaulting a law "
                       "enforcement officer, and let state attorneys general sue the "
                       "federal government over certain immigration enforcement decisions."},
    {"year": 2025, "roll": 35,
     "plain_english": "A Yea vote barred the President from declaring or enforcing a "
                       "moratorium on hydraulic fracturing (fracking) for oil and gas "
                       "without prior congressional approval."},
    {"year": 2025, "roll": 145,
     "plain_english": "A Yea vote passed the 2025 budget reconciliation package extending "
                       "the 2017 tax cuts, adding new tax breaks (e.g. on tips and overtime "
                       "pay), cutting projected Medicaid and SNAP spending, boosting border "
                       "and defense funding, and raising the debt limit."},
    {"year": 2025, "roll": 349,
     "plain_english": "A Yea vote passed a Republican-backed alternative to extending the "
                       "enhanced ACA marketplace subsidies, restructuring health-insurance "
                       "premium subsidy rules for individual-market plans."},
    {"year": 2025, "roll": 362,
     "plain_english": "A Yea vote barred state Medicaid programs from using federal Medicaid "
                       "funds to cover gender-transition procedures for minors."},
    {"year": 2026, "roll": 45,
     "plain_english": "A Yea vote passed the Consolidated Appropriations Act, 2026, funding "
                       "most of the federal government for the fiscal year and averting a "
                       "shutdown."},
    {"year": 2026, "roll": 78,
     "plain_english": "A Yea vote passed the Homeowner Energy Freedom Act, rolling back "
                       "certain federal energy-efficiency and appliance/equipment "
                       "regulations that affect homeowners."},
    {"year": 2026, "roll": 87,
     "plain_english": "A Yea vote passed the Department of Homeland Security Appropriations "
                       "Act, 2026, funding DHS (including CBP and ICE border security and "
                       "immigration enforcement operations) for the fiscal year."},
]


def fetch_roll_call(year, roll, plain_english):
    nnn = f"{roll:03d}"
    url = f"https://clerk.house.gov/evs/{year}/roll{nnn}.xml"
    raw = http_get(url, timeout=25)
    root = ET.fromstring(raw)
    md = root.find("vote-metadata")
    meta = {c.tag: c.text for c in md}
    positions = {}
    for rv in root.iter("recorded-vote"):
        leg = rv.find("legislator")
        vote = rv.find("vote")
        if leg is None or vote is None:
            continue
        if leg.get("state") != "TX":
            continue
        bioguide = leg.get("name-id")
        if bioguide:
            positions[bioguide] = vote.text

    return {
        "roll": roll,
        "year": year,
        "bill": meta.get("legis-num"),
        "question": meta.get("vote-question"),
        "plain_english": plain_english,
        "date": meta.get("action-date"),
        "result": meta.get("vote-result"),
        "source": url,
        "positions": positions,
    }


# ---------------------------------------------------------------------------
# (c) Sponsored-legislation highlights (senators + any House member running for Senate)
# ---------------------------------------------------------------------------
# TX has 2 senators (Cornyn, Cruz) as of 2026-07-03. No sitting TX House member
# is a declared 2026 Senate candidate as of this build (Wesley Hunt exited the
# primary in 2025), so only the 2 senators are covered here.
SPONSOR_TARGETS = ["C001056", "C001098"]  # Cornyn, Cruz


def fetch_sponsored(bioguide):
    data = congress_get(f"/member/{bioguide}/sponsored-legislation", "&limit=10")
    if not data or "sponsoredLegislation" not in data:
        return None
    items = data["sponsoredLegislation"][:3]
    out = []
    for it in items:
        bill_type = (it.get("type") or "").lower()
        num = it.get("number")
        congress = it.get("congress")
        title = it.get("title")
        latest_action = (it.get("latestAction") or {}).get("text")
        date = (it.get("latestAction") or {}).get("actionDate") or it.get("introducedDate")
        source = None
        if bill_type and num and congress:
            source = f"https://www.congress.gov/bill/{congress}th-congress/{bill_type}/{num}"
        out.append({
            "title": title,
            "plain_english": latest_action or "Sponsored legislation; see source for status.",
            "date": date,
            "source": source or f"https://api.congress.gov/v3/member/{bioguide}/sponsored-legislation",
        })
    return out


def main():
    print("Fetching TX roster...")
    members = fetch_roster()
    print(f"  {len(members)} members")

    print("Fetching 8 roll-call votes...")
    votes = []
    for pick in VOTE_PICKS:
        try:
            v = fetch_roll_call(pick["year"], pick["roll"], pick["plain_english"])
            votes.append(v)
            print(f"  roll {pick['year']}-{pick['roll']}: {v['bill']} ({len(v['positions'])} TX positions)")
        except Exception as e:
            GAPS.append(f"Failed to fetch roll {pick['year']}-{pick['roll']}: {e}")
            print(f"  FAILED roll {pick['year']}-{pick['roll']}: {e}", file=sys.stderr)
        time.sleep(0.5)

    print("Fetching sponsored-legislation for TX senators...")
    sponsored = {}
    for bioguide in SPONSOR_TARGETS:
        items = fetch_sponsored(bioguide)
        if items:
            sponsored[bioguide] = items
        else:
            GAPS.append(
                f"congress.gov /v3/member/{bioguide}/sponsored-legislation unavailable "
                "(429 OVER_RATE_LIMIT on DEMO_KEY); omitted."
            )
        time.sleep(0.5)

    out = {
        "members": members,
        "votes": votes,
        "sponsored": sponsored,
        "gaps": GAPS,
        "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump(out, f, indent=2)
    print(f"Wrote {OUT_PATH}")
    if GAPS:
        print("GAPS:")
        for g in GAPS:
            print(f"  - {g}")


if __name__ == "__main__":
    main()
