#!/usr/bin/env python3
"""
Fetch 2024 TX election context (prior-cycle results) per US House district,
plus statewide toplines (President, US Senate), from Wikipedia.

Source strategy: Wikipedia is used as the PRIMARY source here, not a fallback.
An earlier version of this script aggregated county-level precinct CSVs from
the OpenElections openelections-data-tx GitHub repo, but that repo's 2024
general-election dataset only covers ~184 of 254 TX counties, and the
resulting statewide topline was verifiably WRONG (it showed Harris winning
Texas, when Trump won TX by ~13.7 points in the actual 2024 election --
a well-known, easily-checked fact). Since undercounting misses counties
non-uniformly, district-level aggregates built from that same partial data
cannot be trusted either, even where all 38 districts nominally had data.
Per project rule ("never invent, never show unreliable numbers as fact"),
we switched to Wikipedia's district-by-district summary table and the
Senate/President results tables, which are internally consistent, sourced
to news orgs / TX Secretary of State, and match well-known 2024 outcomes.

Pages fetched (raw wikitext, keyless, via action=raw):
- https://en.wikipedia.org/wiki/2024_United_States_House_of_Representatives_elections_in_Texas
- https://en.wikipedia.org/wiki/2024_United_States_Senate_election_in_Texas
- https://en.wikipedia.org/wiki/2024_United_States_presidential_election_in_Texas

Output: data/tx/raw/district_context.json
{
  "districts": {"TX-01": {"last_winner":..., "party":..., "margin_pct":...,
                            "total_votes":..., "source":...}, ...},
  "statewide_2024": {"president": {...}, "senate": {...}},
  "meta": {...}
}

Rerunnable: safe to re-run; re-downloads and re-parses from scratch.
"""
import json
import os
import re
import sys
import time
import urllib.request

HOUSE_PAGE = "2024_United_States_House_of_Representatives_elections_in_Texas"
SENATE_PAGE = "2024_United_States_Senate_election_in_Texas"
PRESIDENT_PAGE = "2024_United_States_presidential_election_in_Texas"

WIKI_RAW_URL = "https://en.wikipedia.org/w/index.php?title={title}&action=raw"
WIKI_HUMAN_URL = "https://en.wikipedia.org/wiki/{title}"

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "tx", "raw")
OUT_PATH = os.path.join(OUT_DIR, "district_context.json")

GENERAL_DATE = "2024-11-05"
TIMEOUT = 15

PARTY_MAP = {
    "republican": "REP",
    "democratic": "DEM",
    "libertarian": "LIB",
    "independent": "IND",
    "green": "GRN",
}


def http_get_text(url, timeout=TIMEOUT, retries=2):
    last_err = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "patriothacks-fetch-context/2.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except Exception as e:
            last_err = e
            time.sleep(0.5)
    raise last_err


def fetch_wikitext(page_title):
    return http_get_text(WIKI_RAW_URL.format(title=page_title))


def norm_party(raw):
    r = raw.lower()
    for k, v in PARTY_MAP.items():
        if k in r:
            return v
    return raw.strip().upper()[:3] if raw.strip() else None


def parse_house_districts(text):
    """Parse the 'District-by-district summary' wikitable: for each district
    row, extract Republican/Democratic/Other votes+pct and derive winner,
    margin, and total votes (recomputed as sum of the three vote columns,
    since at least one row's printed 'Total' column column is internally
    inconsistent with its own vote/pct figures -- a Wikipedia data artifact).
    Also parses each district's top infobox for the winning nominee's name.
    """
    districts = {}
    data_lines = [l for l in text.splitlines() if l.startswith("| align=left|{{ushr|TX|")]
    row_re = re.compile(
        r"\{\{ushr\|TX\|(\d+)\|District \d+\}\}\s*\|\|\s*(?:''')?([\d,]+)(?:''')?\s*\|\|\s*(?:''')?([\d.]+)%(?:''')?"
        r"\s*\|\|\s*(?:''')?([\d,]+)(?:''')?\s*\|\|\s*(?:''')?([\d.]+)%(?:''')?"
        r"\s*\|\|\s*(?:''')?([\d,]+)(?:''')?\s*\|\|\s*(?:''')?([\d.]+)%(?:''')?"
    )
    parsed_rows = {}
    for line in data_lines:
        m = row_re.search(line)
        if not m:
            continue
        dnum = int(m.group(1))
        rep_votes, rep_pct = int(m.group(2).replace(",", "")), float(m.group(3))
        dem_votes, dem_pct = int(m.group(4).replace(",", "")), float(m.group(5))
        oth_votes, oth_pct = int(m.group(6).replace(",", "")), float(m.group(7))
        parsed_rows[dnum] = {
            "REP": (rep_votes, rep_pct),
            "DEM": (dem_votes, dem_pct),
            "OTHER": (oth_votes, oth_pct),
        }

    # Winner nominee names from each district section's top infobox.
    district_headers = [(m.start(), int(m.group(1))) for m in re.finditer(r"^==District (\d+)==$", text, re.M)]
    nominees = {}
    for i, (pos, dnum) in enumerate(district_headers):
        end = district_headers[i + 1][0] if i + 1 < len(district_headers) else len(text)
        section = text[pos:end]
        m = re.search(r"nominee1\s*=\s*(.*?)\n\s*\|\s*party1\s*=\s*(.*?)\n", section)
        if m:
            nominees[dnum] = clean_candidate_name(m.group(1))

    house_source = WIKI_HUMAN_URL.format(title=HOUSE_PAGE)
    for dnum, cols in parsed_rows.items():
        ranked = sorted(cols.items(), key=lambda kv: kv[1][1], reverse=True)
        winner_party, (winner_votes, winner_pct) = ranked[0]
        runnerup_pct = ranked[1][1][1] if len(ranked) > 1 else 0.0
        total_votes = sum(v for v, _ in cols.values())
        margin_pct = round(winner_pct - runnerup_pct, 2)
        key = f"TX-{dnum:02d}"
        districts[key] = {
            "last_winner": nominees.get(dnum),
            "party": winner_party if winner_party in ("REP", "DEM") else winner_party,
            "margin_pct": margin_pct,
            "total_votes": total_votes,
            "election_date": GENERAL_DATE,
            "source": house_source,
        }
    return districts


def clean_candidate_name(raw):
    """Turn a wikitext candidate field into a plain display name.
    Handles plain wikilinks ('[[Ted Cruz]] (incumbent)'), piped wikilinks
    ('[[Target|Display]]'), and running-mate tickets
    ('{{ubl|[[Donald Trump]]|[[JD Vance]]}}' -> 'Donald Trump / JD Vance')."""
    raw = raw.strip()
    # {{ubl|...|...}} ticket: pull every wikilink inside, join with " / "
    if "{{ubl" in raw or "{{Ubl" in raw:
        names = re.findall(r"\[\[([^\]]+)\]\]", raw)
        names = [n.split("|")[-1] for n in names]
        return " / ".join(names)
    name = re.sub(r"[\[\]']", "", raw).strip()
    name = re.sub(r"\s*\(incumbent\)", "", name).strip()
    if "|" in name:
        name = name.split("|")[-1]
    return name.strip()


def parse_statewide_race(text, page_title, winner_hint_names):
    """Parse an 'Election box' style Results section for a statewide race
    (President or Senate) and return {winner, party, margin_pct, total_votes, source}.
    Picks the FIRST 'Election box winning candidate...' / total block pair that
    contains the full-state general-election numbers (largest total vote count
    on the page, to avoid matching a primary-election box)."""
    source = WIKI_HUMAN_URL.format(title=page_title)

    # Find all winning-candidate blocks and their votes/percentage/candidate name.
    # Wikipedia "Election box" templates vary in whether fields are newline-
    # or pipe-separated across different articles, so allow either as the
    # field delimiter (\n or |) rather than assuming one style.
    # Field separator: a pipe, optionally preceded by a newline+indent (the
    # "newline-style" template layout) -- covers both wikitext layouts seen
    # across TX election articles (compact `|field=val|field=val` on one
    # line, vs. one `\n |field = val` per line).
    SEP = r"(?:\n\s*)?\|\s*"
    win_re = re.compile(
        r"Election box winning candidate with party link"
        rf"{SEP}party\s*=\s*([^\n|]+?)"
        rf"{SEP}candidate\s*=\s*(.+?)"
        rf"{SEP}votes\s*=\s*([\d,]+)"
        rf"{SEP}percentage\s*=\s*([\d.]+)%",
        re.S,
    )
    runner_re = re.compile(
        r"Election box candidate with party link"
        rf"{SEP}party\s*=\s*([^\n|]+?)"
        rf"{SEP}candidate\s*=\s*(.+?)"
        rf"{SEP}votes\s*=\s*([\d,]+)"
        rf"{SEP}percentage\s*=\s*([\d.]+)%",
        re.S,
    )
    total_re = re.compile(rf"Election box total{SEP}votes\s*=\s*([\d,]+)")

    win_matches = list(win_re.finditer(text))
    tot_matches = list(total_re.finditer(text))
    if not win_matches or not tot_matches:
        return None

    # Choose the pairing with the largest total votes (the full statewide
    # general election, not a primary or a by-county subsection).
    best = None
    for wm in win_matches:
        # find nearest following total_re match after this winner block
        after = [tm for tm in tot_matches if tm.start() > wm.end()]
        if not after:
            continue
        tm = after[0]
        total_votes = int(tm.group(1).replace(",", ""))
        if best is None or total_votes > best[0]:
            best = (total_votes, wm, tm)

    if best is None:
        return None
    total_votes, wm, tm = best
    party_raw, candidate_raw, votes_raw, pct_raw = wm.groups()
    winner_name = clean_candidate_name(candidate_raw)
    winner_pct = float(pct_raw)

    # runner-up: next 'Election box candidate with party link' after wm, before tm
    segment = text[wm.end():tm.start()]
    rm = runner_re.search(segment)
    runnerup_pct = float(rm.group(4)) if rm else 0.0

    margin_pct = round(winner_pct - runnerup_pct, 2)
    return {
        "winner": winner_name,
        "party": norm_party(party_raw),
        "margin_pct": margin_pct,
        "total_votes": total_votes,
        "election_date": GENERAL_DATE,
        "source": source,
    }


def main():
    print("Fetching Wikipedia wikitext (keyless, action=raw)...", file=sys.stderr)
    errors = []

    districts = {}
    try:
        house_text = fetch_wikitext(HOUSE_PAGE)
        districts = parse_house_districts(house_text)
        print(f"Parsed {len(districts)} / 38 districts from House elections page.", file=sys.stderr)
    except Exception as e:
        errors.append({"page": HOUSE_PAGE, "error": str(e)})
        print(f"ERROR fetching/parsing house page: {e}", file=sys.stderr)

    statewide = {}
    try:
        pres_text = fetch_wikitext(PRESIDENT_PAGE)
        pres = parse_statewide_race(pres_text, PRESIDENT_PAGE, None)
        if pres:
            statewide["president"] = pres
    except Exception as e:
        errors.append({"page": PRESIDENT_PAGE, "error": str(e)})
        print(f"ERROR fetching/parsing president page: {e}", file=sys.stderr)

    try:
        sen_text = fetch_wikitext(SENATE_PAGE)
        sen = parse_statewide_race(sen_text, SENATE_PAGE, None)
        if sen:
            statewide["senate"] = sen
    except Exception as e:
        errors.append({"page": SENATE_PAGE, "error": str(e)})
        print(f"ERROR fetching/parsing senate page: {e}", file=sys.stderr)

    out = {
        "state": "TX",
        "context_election_date": GENERAL_DATE,
        "note": (
            "Prior-cycle (2024) results, provided as historical context ahead of the "
            "2026-11-03 general. Source: Wikipedia district-by-district summary table "
            "(U.S. House) and statewide Results tables (President, U.S. Senate), which "
            "cite AP/NYT/TX Secretary of State certified results."
        ),
        "districts": dict(sorted(districts.items())),
        "statewide_2024": statewide,
        "meta": {
            "source_pages": [
                WIKI_HUMAN_URL.format(title=HOUSE_PAGE),
                WIKI_HUMAN_URL.format(title=PRESIDENT_PAGE),
                WIKI_HUMAN_URL.format(title=SENATE_PAGE),
            ],
            "method": "Parsed Wikipedia raw wikitext (action=raw), no API key required.",
            "prior_source_rejected": (
                "An earlier version of this script aggregated OpenElections "
                "openelections-data-tx county CSVs (184/254 counties present). That "
                "produced an incorrect statewide presidential winner (Harris) "
                "contradicting the actual certified 2024 TX result (Trump won by "
                "~13.7 points), so it was discarded in favor of Wikipedia."
            ),
            "known_data_note": (
                "TX-20 (Castro) row in the Wikipedia summary table lists a 'Total' "
                "column value (218,720) that is inconsistent with its own Democratic "
                "votes/percentage figures (157,890 votes at 100.00%) -- likely a stale "
                "copy from the TX-18 row. We recompute total_votes as the sum of the "
                "Republican+Democratic+Other vote columns for every district rather "
                "than trusting the printed 'Total' column, to avoid propagating that error."
            ),
            "fetch_errors": errors,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        },
    }

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump(out, f, indent=2)

    print(f"Wrote {OUT_PATH}", file=sys.stderr)
    print(f"Districts covered: {len(districts)} / 38 expected", file=sys.stderr)
    if len(districts) < 38:
        missing = sorted(set(f"TX-{i:02d}" for i in range(1, 39)) - set(districts.keys()))
        print(f"Missing districts: {missing}", file=sys.stderr)
    print(f"Statewide races covered: {list(statewide.keys())}", file=sys.stderr)


if __name__ == "__main__":
    main()
