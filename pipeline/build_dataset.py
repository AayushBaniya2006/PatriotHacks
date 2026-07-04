#!/usr/bin/env python3
"""
build_dataset.py — bronze -> gold merge for the TX voter-info dataset.

Reads data/tx/raw/{statewide,fec,incumbent_votes,district_context}.json
Writes:
  data/tx/races.json
  data/tx/candidates.json
  data/tx/app.db          (sqlite serving layer, schema is a contract with app/datastore.py)
  data/tx/unjoined_report.json  (every heuristic join decision / gap, logged not guessed)

Rerunnable: safe to run multiple times, always overwrites outputs deterministically
from the raw/*.json inputs (never mutates raw/).

Rule: every stored fact carries a source URL and (where applicable) an as_of/date.
Missing data is OMITTED, never invented. Every heuristic tie-break is logged to
unjoined_report.json instead of guessed silently.
"""
from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "tx" / "raw"
OUT_DIR = ROOT / "data" / "tx"

STATEWIDE_PATH = RAW / "statewide.json"
FEC_PATH = RAW / "fec.json"
VOTES_PATH = RAW / "incumbent_votes.json"
CONTEXT_PATH = RAW / "district_context.json"

RACES_OUT = OUT_DIR / "races.json"
CANDIDATES_OUT = OUT_DIR / "candidates.json"
DB_OUT = OUT_DIR / "app.db"
UNJOINED_OUT = OUT_DIR / "unjoined_report.json"

ELECTION_DATE = "2026-11-03"

# race_id -> (short slug used in ids, level)
STATEWIDE_RACE_META = {
    "tx-gov-2026": "state",
    "tx-ltgov-2026": "state",
    "tx-ag-2026": "state",
    "tx-sen-2026": "federal",
    "tx-comptroller-2026": "state",
    "tx-landcomm-2026": "state",
    "tx-agcomm-2026": "state",
    "tx-railroad-2026": "state",
}

SUFFIX_TOKENS = {
    "jr", "sr", "ii", "iii", "iv", "v", "mr", "mrs", "ms", "dr", "phd", "esq", "sr.", "jr.",
}

# ---------------------------------------------------------------------------
# name helpers
# ---------------------------------------------------------------------------

def _clean_tokens(name: str) -> list[str]:
    name = name.replace(",", " ").replace(".", " ")
    tokens = [t for t in re.split(r"\s+", name.strip()) if t]
    return [t for t in tokens if t.lower() not in SUFFIX_TOKENS]


def first_last(name: str) -> tuple[str, str]:
    tokens = _clean_tokens(name)
    if not tokens:
        return name, name
    return tokens[0], tokens[-1]


def name_key(name: str) -> str:
    """Full-name identity key (order-preserving), used to collapse literal
    duplicate FEC registrations of the same person in the same district/party."""
    return " ".join(t.lower() for t in _clean_tokens(name))


def last_name_key(name: str) -> str:
    _, last = first_last(name)
    return last.lower()


def slugify_ascii(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^a-zA-Z0-9]+", "", s)
    return s.lower()


def make_slug(name: str, used: set[str], disambiguator: str | None = None) -> str:
    first, last = first_last(name)
    base = f"{slugify_ascii(last)}-{slugify_ascii(first)}"
    if not base.strip("-"):
        base = slugify_ascii(name) or "candidate"
    slug = base
    if slug in used and disambiguator:
        slug = f"{base}-{slugify_ascii(disambiguator)}"
    n = 2
    while slug in used:
        slug = f"{base}-{n}"
        n += 1
    used.add(slug)
    return slug


PARTY_FAMILY = {
    "democratic": "DEM", "democrat": "DEM",
    "republican": "REP",
    "libertarian": "LIB",
    "green": "GRN",
    "independent": "IND", "ind": "IND",
}


def party_family(party: str | None) -> str:
    if not party:
        return "UNK"
    p = party.lower()
    for k, v in PARTY_FAMILY.items():
        if k in p:
            return v
    return "OTH"


# ---------------------------------------------------------------------------
# load raw
# ---------------------------------------------------------------------------

def load_json(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    statewide = load_json(STATEWIDE_PATH)
    fec = load_json(FEC_PATH)
    votes_data = load_json(VOTES_PATH)
    context = load_json(CONTEXT_PATH)

    unjoined = {
        "ambiguous_same_party_filers": [],
        "duplicate_fec_registrations_collapsed": [],
        "incumbent_added_without_fec_match": [],
        "incumbent_fec_flag_no_bioguide_match": [],
        "statewide_finance_unmatched": [],
        "house_district_zero_party_coverage": [],
        "upstream_fetch_gaps": votes_data.get("gaps", []),
    }

    races: list[dict] = []
    candidates: dict[str, dict] = {}
    used_slugs: set[str] = set()

    fec_candidates = fec["candidates"]
    fec_house = [c for c in fec_candidates if c["office"] == "H"]
    fec_senate = [c for c in fec_candidates if c["office"] == "S"]

    house_members = {
        m["district"]: m for m in votes_data["members"] if m["chamber"] == "House"
    }
    votes = votes_data["votes"]
    sponsored = votes_data.get("sponsored", {})

    def key_votes_for(bioguide_id: str) -> list[dict]:
        out = []
        for v in votes:
            pos = v["positions"].get(bioguide_id)
            if pos is None:
                continue
            out.append({
                "bill": v["bill"],
                "question": v["question"],
                "plain_english": v["plain_english"],
                "position": pos,
                "date": v["date"],
                "result": v["result"],
                "source": v["source"],
            })
        return out

    # -----------------------------------------------------------------
    # 1) statewide races (incl. US Senate) from statewide.json
    # -----------------------------------------------------------------
    for r in statewide["races"]:
        race_id = r["race_id"]
        level = STATEWIDE_RACE_META.get(race_id, r.get("level", "state"))
        candidate_ids = []
        for c in r["candidates"]:
            cid = make_slug(c["name"], used_slugs)
            candidate_ids.append(cid)

            rec = {
                "name": c["name"],
                "party": c["party"],
                "office": r["office"],
                "district": None,
                "incumbent": bool(c.get("incumbent", False)),
                "fec_id": None,
                "positions": c.get("positions", []),
                "sources": c.get("sources", []),
                "background": c.get("background"),
            }

            # Senate: attach FEC finance by normalized last-name + party-family match.
            if race_id == "tx-sen-2026":
                lk = last_name_key(c["name"])
                fam = party_family(c["party"])
                match = None
                for fc in fec_senate:
                    if last_name_key(fc["name"]) == lk and party_family(fc["party"]) == fam:
                        match = fc
                        break
                if match:
                    rec["fec_id"] = match["fec_candidate_id"]
                    if match.get("receipts") is not None:
                        rec["finance"] = {
                            "receipts": match["receipts"],
                            "disbursements": match["disbursements"],
                            "cash_on_hand": match["cash_on_hand"],
                            "as_of": match["as_of"],
                            "source": match["source"],
                        }
                else:
                    unjoined["statewide_finance_unmatched"].append({
                        "race_id": race_id, "name": c["name"], "party": c["party"],
                        "reason": "no FEC Senate filer matched by last name + party family",
                    })

            candidates[cid] = rec

        races.append({
            "race_id": race_id,
            "office": r["office"],
            "level": level,
            "district": None,
            "candidate_ids": candidate_ids,
            "context": r.get("context", {}),
        })

    # -----------------------------------------------------------------
    # 2) House races TX-01..TX-38
    # -----------------------------------------------------------------
    for i in range(1, 39):
        district = f"TX-{i:02d}"
        pool = [c for c in fec_house if c["district"] == district]

        member = house_members.get(district)

        plausible = [c for c in pool if c["has_activity"] and c["candidate_status"] == "C"]
        used_fallback = False
        if not plausible:
            # relax to candidate_status == 'C' regardless of reported financial activity
            plausible = [c for c in pool if c["candidate_status"] == "C"]
            used_fallback = bool(plausible)
            if used_fallback:
                unjoined["house_district_zero_party_coverage"].append({
                    "district": district,
                    "note": "no has_activity=true candidates; fell back to candidate_status='C' regardless of activity",
                    "candidate_ids": [c["fec_candidate_id"] for c in plausible],
                })

        # make sure the sitting incumbent's own FEC row is in the pool even if it was
        # filtered out for low/no reported financial activity (very common for safe
        # incumbents early in a cycle) — otherwise we'd wrongly fabricate a fec_id-less
        # synthetic entry for someone who actually has a real FEC filing.
        if member:
            lk = last_name_key(member["name"])
            if not any(last_name_key(c["name"]) == lk for c in plausible):
                raw_matches = [c for c in pool if last_name_key(c["name"]) == lk]
                raw_matches_c = [c for c in raw_matches if c["candidate_status"] == "C"]
                chosen = (raw_matches_c or raw_matches)
                if chosen:
                    plausible = plausible + [chosen[0]]
                    unjoined["house_district_zero_party_coverage"].append({
                        "district": district,
                        "note": "sitting incumbent's FEC row had has_activity=false/status!='C' and was excluded by the standard filter; force-included so the real fec_id is used instead of a synthetic entry",
                        "candidate_ids": [chosen[0]["fec_candidate_id"]],
                    })

        # group by party
        by_party: dict[str, list[dict]] = {}
        for c in plausible:
            by_party.setdefault(c["party"], []).append(c)

        finalists: list[dict] = []
        for party, group in by_party.items():
            # collapse literal duplicate registrations of the same person (same name_key)
            by_name: dict[str, list[dict]] = {}
            for c in group:
                by_name.setdefault(name_key(c["name"]), []).append(c)
            distinct_people = []
            for nk, dupes in by_name.items():
                if len(dupes) > 1:
                    dupes_sorted = sorted(
                        dupes, key=lambda x: (x["receipts"] or -1), reverse=True
                    )
                    winner = dupes_sorted[0]
                    unjoined["duplicate_fec_registrations_collapsed"].append({
                        "district": district, "party": party, "name": winner["name"],
                        "kept_fec_id": winner["fec_candidate_id"],
                        "dropped_fec_ids": [d["fec_candidate_id"] for d in dupes_sorted[1:]],
                    })
                    distinct_people.append(winner)
                else:
                    distinct_people.append(dupes[0])

            if len(distinct_people) > 1:
                member_lk = last_name_key(member["name"]) if member else None

                def sort_key(x):
                    is_member = 1 if member_lk and last_name_key(x["name"]) == member_lk else 0
                    is_incumbent = 1 if x["incumbent_challenge"] == "Incumbent" else 0
                    return (is_member, is_incumbent, x["receipts"] or -1)
                ranked = sorted(distinct_people, key=sort_key, reverse=True)
                winner = ranked[0]
                unjoined["ambiguous_same_party_filers"].append({
                    "district": district, "party": party,
                    "picked": {"name": winner["name"], "fec_id": winner["fec_candidate_id"],
                               "incumbent_challenge": winner["incumbent_challenge"],
                               "receipts": winner["receipts"]},
                    "alternates": [
                        {"name": a["name"], "fec_id": a["fec_candidate_id"],
                         "incumbent_challenge": a["incumbent_challenge"], "receipts": a["receipts"]}
                        for a in ranked[1:]
                    ],
                    "heuristic": "prefer incumbent_challenge='Incumbent', then highest receipts",
                })
                finalists.append(winner)
            elif distinct_people:
                finalists.append(distinct_people[0])

        # attach incumbent bioguide/votes: match district's sitting member to a finalist by last name
        matched_member = False
        for fc in finalists:
            fc["_incumbent_bioguide"] = None
            if member and last_name_key(fc["name"]) == last_name_key(member["name"]):
                fc["_incumbent_bioguide"] = member["bioguide_id"]
                matched_member = True

        if member and not matched_member:
            # FEC data has no filer matching the sitting incumbent's last name in this
            # district (redistricting-era ambiguity, or incumbent hasn't filed FEC docs
            # in our snapshot). Add the incumbent as a candidate from real, sourced
            # legislators-current.yaml + clerk.house.gov data (no financials invented).
            finalists.append({
                "fec_candidate_id": None,
                "name": member["name"],
                "party": member["party"],
                "office": "H",
                "district": district,
                "incumbent_challenge": "Incumbent",
                "candidate_status": None,
                "has_activity": False,
                "receipts": None, "disbursements": None, "cash_on_hand": None,
                "as_of": None,
                "source": member["source"],
                "_incumbent_bioguide": member["bioguide_id"],
                "_no_fec_match": True,
            })
            unjoined["incumbent_added_without_fec_match"].append({
                "district": district, "name": member["name"], "bioguide_id": member["bioguide_id"],
                "reason": "sitting incumbent found in legislators-current.yaml roster but no matching FEC 2026 filer in fec.json for this district",
            })
        elif any(fc["incumbent_challenge"] == "Incumbent" for fc in finalists) and not matched_member:
            for fc in finalists:
                if fc["incumbent_challenge"] == "Incumbent":
                    unjoined["incumbent_fec_flag_no_bioguide_match"].append({
                        "district": district, "name": fc["name"],
                        "reason": "FEC flags this filer as 'Incumbent' but no bioguide match found in legislators-current.yaml roster for this district (possible redistricting mismatch)",
                    })

        if not finalists:
            unjoined["house_district_zero_party_coverage"].append({
                "district": district,
                "note": "no plausible candidates found at all (even with fallback) and no roster incumbent to fall back on",
                "candidate_ids": [],
            })

        candidate_ids = []
        for fc in finalists:
            disamb = district
            cid = make_slug(fc["name"], used_slugs, disambiguator=disamb)
            candidate_ids.append(cid)

            rec = {
                "name": fc["name"],
                "party": fc["party"],
                "office": f"U.S. Representative, {district}",
                "district": district,
                "incumbent": fc["incumbent_challenge"] == "Incumbent" or bool(fc.get("_incumbent_bioguide")),
                "fec_id": fc["fec_candidate_id"],
                "sources": [],
                "positions": [],
            }
            sources = set()
            if fc.get("source"):
                sources.add(fc["source"])
            if fc.get("receipts") is not None:
                rec["finance"] = {
                    "receipts": fc["receipts"],
                    "disbursements": fc["disbursements"],
                    "cash_on_hand": fc["cash_on_hand"],
                    "as_of": fc["as_of"],
                    "source": fc["source"],
                }

            bioguide = fc.get("_incumbent_bioguide")
            if bioguide:
                kv = key_votes_for(bioguide)
                spons = sponsored.get(bioguide, [])
                if kv or spons:
                    record = {}
                    if kv:
                        record["key_votes"] = kv
                        sources.add("https://clerk.house.gov/Votes")
                    if spons:
                        record["sponsored_highlights"] = spons
                    record["source"] = "https://raw.githubusercontent.com/unitedstates/congress-legislators/main/legislators-current.yaml"
                    rec["record"] = record
                    sources.add(record["source"])

            rec["sources"] = sorted(sources)
            candidates[cid] = rec

        ctx = {}
        d_ctx = context.get("districts", {}).get(district)
        if d_ctx:
            ctx["last_result"] = (
                f"2024 winner: {d_ctx['last_winner']} ({d_ctx['party']}), "
                f"margin {d_ctx['margin_pct']} pts of {d_ctx['total_votes']} votes cast"
            )
            ctx["last_result_detail"] = d_ctx
            ctx["sources"] = [d_ctx["source"]]

        races.append({
            "race_id": f"tx-cd{i:02d}-2026",
            "office": f"U.S. House of Representatives, {district}",
            "level": "federal",
            "district": district,
            "candidate_ids": candidate_ids,
            "context": ctx,
        })

    # -----------------------------------------------------------------
    # write races.json / candidates.json
    # -----------------------------------------------------------------
    races_doc = {"state": "TX", "election_date": ELECTION_DATE, "races": races}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(RACES_OUT, "w", encoding="utf-8") as f:
        json.dump(races_doc, f, indent=2, ensure_ascii=False)
    with open(CANDIDATES_OUT, "w", encoding="utf-8") as f:
        json.dump(candidates, f, indent=2, ensure_ascii=False)
    with open(UNJOINED_OUT, "w", encoding="utf-8") as f:
        json.dump(unjoined, f, indent=2, ensure_ascii=False)

    # -----------------------------------------------------------------
    # sqlite serving layer (contract with app/datastore.py)
    # -----------------------------------------------------------------
    if DB_OUT.exists():
        DB_OUT.unlink()
    conn = sqlite3.connect(DB_OUT)
    cur = conn.cursor()
    cur.executescript(
        """
        CREATE TABLE races (
            race_id TEXT PRIMARY KEY,
            office TEXT,
            level TEXT,
            district TEXT,
            context TEXT
        );
        CREATE TABLE candidates (
            candidate_id TEXT PRIMARY KEY,
            name TEXT,
            party TEXT,
            office TEXT,
            district TEXT,
            incumbent INTEGER,
            fec_id TEXT,
            finance TEXT,
            record TEXT,
            positions TEXT,
            sources TEXT
        );
        CREATE TABLE race_candidates (
            race_id TEXT,
            candidate_id TEXT,
            PRIMARY KEY(race_id, candidate_id)
        );
        CREATE INDEX idx_races_district ON races(district);
        CREATE INDEX idx_races_level ON races(level);
        CREATE INDEX idx_cand_district ON candidates(district);
        CREATE INDEX idx_cand_name ON candidates(name);
        """
    )

    for r in races:
        cur.execute(
            "INSERT INTO races (race_id, office, level, district, context) VALUES (?,?,?,?,?)",
            (r["race_id"], r["office"], r["level"], r["district"], json.dumps(r["context"], ensure_ascii=False)),
        )
        for cid in r["candidate_ids"]:
            cur.execute(
                "INSERT INTO race_candidates (race_id, candidate_id) VALUES (?,?)",
                (r["race_id"], cid),
            )

    for cid, c in candidates.items():
        cur.execute(
            """INSERT INTO candidates
               (candidate_id, name, party, office, district, incumbent, fec_id, finance, record, positions, sources)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                cid, c["name"], c["party"], c["office"], c["district"],
                1 if c["incumbent"] else 0, c.get("fec_id"),
                json.dumps(c["finance"], ensure_ascii=False) if c.get("finance") else None,
                json.dumps(c["record"], ensure_ascii=False) if c.get("record") else None,
                json.dumps(c.get("positions", []), ensure_ascii=False),
                json.dumps(c.get("sources", []), ensure_ascii=False),
            ),
        )
    conn.commit()
    conn.close()

    # -----------------------------------------------------------------
    # summary
    # -----------------------------------------------------------------
    with_votes = sum(1 for c in candidates.values() if c.get("record", {}).get("key_votes"))
    with_finance = sum(1 for c in candidates.values() if c.get("finance"))
    print(f"races={len(races)} candidates={len(candidates)} "
          f"with_key_votes={with_votes} with_finance={with_finance}")
    print(f"unjoined report entries: "
          f"{ {k: len(v) for k, v in unjoined.items()} }")


if __name__ == "__main__":
    main()
