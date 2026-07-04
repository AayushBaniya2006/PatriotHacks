#!/usr/bin/env python3
"""
Fetch TX 2026 statewide race data (Governor, Lt Gov, AG, US Senate, Comptroller,
Land Commissioner, Agriculture Commissioner, Railroad Commissioner) from English
Wikipedia and write data/tx/raw/statewide.json.

Rerunnable, no destructive side effects. Every stored fact carries a source URL.
Uses Wikipedia's action=parse API (wikitext) — no API key required.

Extraction strategy:
  - Parse the {{Infobox election}} block for nominee/party pairs -> these are the
    post-primary GENERAL ELECTION candidates (Wikipedia convention: nomineeN/partyN
    are populated once a party's primary is decided; if a primary is unsettled the
    page omits or leaves the field blank, which we surface via context notes).
  - Cross-check against a "Third-party and independent candidates" > Declared
    section for additional general-election candidates (Libertarian, Green, etc.)
  - Pull a 1-2 sentence background for each candidate from the "===Nominee===" or
    "Declared" bullet list entries (these usually read like
    "* [[Name]], <office/bio>, <ref>").
  - Look for any explicit issue/position language ONLY inside a "Campaign" /
    "Issues" / "Platform" subsection if present; Wikipedia US statewide race pages
    rarely carry this, so positions are frequently omitted (never invented).
"""

import html
import json
import re
import sys
import time
import urllib.parse
from pathlib import Path

import requests

WIKI_API = "https://en.wikipedia.org/w/api.php"
HEADERS = {"User-Agent": "PatriotHacksBot/1.0 (contact: sww35@txstate.edu; hackathon voter-info tool)"}
OUT_PATH = Path(__file__).resolve().parent.parent / "data" / "tx" / "raw" / "statewide.json"

RACES = [
    {
        "race_id": "tx-gov-2026",
        "office": "Governor of Texas",
        "level": "state",
        "page": "2026 Texas gubernatorial election",
    },
    {
        "race_id": "tx-ltgov-2026",
        "office": "Lieutenant Governor of Texas",
        "level": "state",
        "page": "2026 Texas lieutenant gubernatorial election",
    },
    {
        "race_id": "tx-ag-2026",
        "office": "Attorney General of Texas",
        "level": "state",
        "page": "2026 Texas Attorney General election",
    },
    {
        "race_id": "tx-sen-2026",
        "office": "United States Senator from Texas",
        "level": "federal",
        "page": "2026 United States Senate election in Texas",
    },
    {
        "race_id": "tx-comptroller-2026",
        "office": "Texas Comptroller of Public Accounts",
        "level": "state",
        "page": "2026 Texas Comptroller of Public Accounts election",
    },
    {
        "race_id": "tx-landcomm-2026",
        "office": "Texas Land Commissioner",
        "level": "state",
        "page": "2026 Texas Land Commissioner election",
    },
    {
        "race_id": "tx-agcomm-2026",
        "office": "Texas Commissioner of Agriculture",
        "level": "state",
        "page": "2026 Texas Commissioner of Agriculture election",
    },
    {
        "race_id": "tx-railroad-2026",
        "office": "Railroad Commissioner of Texas",
        "level": "state",
        "page": "2026 Texas Railroad Commissioner election",
    },
]


def wiki_url(page: str) -> str:
    return "https://en.wikipedia.org/wiki/" + page.replace(" ", "_")


def fetch_wikitext(page: str) -> tuple[str, str] | None:
    """Return (wikitext, canonical_url) or None if page missing/error."""
    try:
        r = requests.get(
            WIKI_API,
            params={"action": "parse", "page": page, "format": "json", "prop": "wikitext|revid"},
            headers=HEADERS,
            timeout=15,
        )
        r.raise_for_status()
        d = r.json()
    except requests.RequestException as e:
        print(f"  ! request failed for {page}: {e}", file=sys.stderr)
        return None
    if "error" in d:
        print(f"  ! wiki error for {page}: {d['error'].get('info')}", file=sys.stderr)
        return None
    wt = d["parse"]["wikitext"]["*"]
    return wt, wiki_url(page)


def clean_wikilink_text(s: str) -> str:
    """[[Target|Display]] -> Display ; [[Target]] -> Target ; strip bold/italic/ref markup."""
    s = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]+)\]\]", r"\1", s)
    s = re.sub(r"'''?", "", s)
    s = re.sub(r"<ref\b[^>]*/>", "", s)  # self-closing <ref name="..." /> (attrs may contain '/')
    s = re.sub(r"<ref\b[^>]*>.*?</ref>", "", s, flags=re.S)
    s = re.sub(r"\{\{[^{}]*\}\}", "", s)
    s = re.sub(r"<br\s*/?>", "; ", s, flags=re.I)
    # URL-encoded punctuation sometimes leaks in from piped wikilink targets (e.g. Texas%27s)
    s = urllib.parse.unquote(s)
    s = html.unescape(s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def extract_infobox(wt: str) -> dict:
    m = re.search(r"\{\{Infobox election(.*?)\n\}\}", wt, re.S)
    if not m:
        return {}
    body = m.group(1)
    fields = {}
    for line in body.split("\n|"):
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        fields[key.strip().lstrip("|").strip()] = val.strip()
    return fields


def infobox_nominees(fields: dict) -> list[dict]:
    """Extract nomineeN/partyN (or candidateN/partyN) pairs from the infobox
    (general-election slate). Some pages use 'candidate1' before a nominee is
    formally set; treat both as equivalent for our purposes."""
    out = []
    for name_prefix in ("nominee", "candidate"):
        i = 1
        while True:
            nom_key = f"{name_prefix}{i}"
            party_key = f"party{i}"
            if nom_key not in fields:
                break
            raw_name = fields.get(nom_key, "")
            raw_party = fields.get(party_key, "")
            name = clean_wikilink_text(raw_name)
            party = clean_wikilink_text(raw_party)
            if name:
                out.append({"name": name, "party": party or None})
            i += 1
        if out:
            break  # prefer nomineeN if present; only fall back to candidateN otherwise
    return out


def find_bio_bullet(wt: str, name: str) -> str | None:
    """Find a bullet-list line introducing `name` and return a cleaned 1-2 sentence bio."""
    # Wikilink form: [[Name]] or [[Name|Display]] where Display/Name matches
    # Search bullet lines starting with '*' that mention the name as a wikilink.
    pattern = re.compile(
        r"^\*\s*\[\[[^\]]*?" + re.escape(name.split(" (")[0]) + r"[^\]]*?\]\][^\n]*",
        re.M,
    )
    m = pattern.search(wt)
    if not m:
        # fallback: plain-text mention (no wikilink, e.g. minor party candidates)
        pattern2 = re.compile(r"^\*\s*" + re.escape(name) + r"[^\n]*", re.M)
        m = pattern2.search(wt)
    if not m:
        return None
    line = clean_wikilink_text(m.group(0))
    line = line.lstrip("* ").strip()
    # Drop the leading "Name, " to keep just the descriptor, then reattach as a sentence.
    parts = line.split(",", 1)
    if len(parts) == 2:
        bio = parts[1].strip().rstrip(".")
        if bio:
            return f"{name}, {bio}."
    return line if line else None


def find_declared_thirdparty(wt: str) -> list[dict]:
    """Extract Declared candidates from a 'Third-party and independent candidates' section."""
    out = []
    m = re.search(
        r"Third-party and independent candidates ?==\s*\n(.*?)(?=\n==[^=])",
        wt,
        re.S,
    )
    if not m:
        return out
    section = m.group(1)
    decl = re.search(r"====\s*Declared\s*====\n(.*?)(?=\n====|\n===[^=]|\Z)", section, re.S)
    if not decl:
        return out
    for line in decl.group(1).split("\n"):
        line = line.strip()
        if not line.startswith("*"):
            continue
        cleaned = clean_wikilink_text(line)
        cleaned = cleaned.lstrip("* ").strip()
        if not cleaned:
            continue
        # First comma-separated token is usually "Name" or "Name (Party)"
        name_part = cleaned.split(",", 1)[0].strip()
        party_match = re.search(r"\((Libertarian|Green|Independent)[^)]*\)", name_part)
        party = party_match.group(1) if party_match else None
        if party_match:
            # strip the trailing "(Party)" annotation off the display name itself
            name_part = name_part[: party_match.start()].strip()
        out.append({"name": name_part, "party": party, "raw": cleaned})
    return out


def extract_positions(wt: str, url: str) -> list[dict]:
    """Only pull positions if the page has an explicit Issues/Platform/Campaign-issues
    subsection. Most 2026 TX statewide race pages do not have this, in which case
    an empty list is returned (never invented)."""
    positions = []
    for heading in ["Issues", "Platform", "Policy positions"]:
        m = re.search(
            rf"===+\s*{heading}\s*===+\n(.*?)(?=\n===|\n==[^=]|\Z)", wt, re.S | re.I
        )
        if m:
            text = clean_wikilink_text(m.group(1)).strip()
            if text:
                positions.append(
                    {
                        "issue": heading.lower(),
                        "summary": text[:600],
                        "source": f"{url}#{heading.replace(' ', '_')}",
                    }
                )
    return positions


def build_race(race_spec: dict) -> dict | None:
    page = race_spec["page"]
    print(f"Fetching: {page}")
    result = fetch_wikitext(page)
    if result is None:
        return {
            "race_id": race_spec["race_id"],
            "office": race_spec["office"],
            "level": race_spec["level"],
            "district": None,
            "candidates": [],
            "context": {
                "note": "Source page fetch failed or page does not exist as of run time.",
                "sources": [wiki_url(page)],
            },
        }
    wt, url = result
    fields = extract_infobox(wt)
    incumbent_raw = clean_wikilink_text(fields.get("before_election", ""))

    nominees = infobox_nominees(fields)
    thirdparty = find_declared_thirdparty(wt)

    candidates = []
    seen_names = set()
    for nom in nominees:
        name = nom["name"]
        if name in seen_names:
            continue
        seen_names.add(name)
        bio = find_bio_bullet(wt, name)
        is_incumbent = bool(incumbent_raw) and (
            incumbent_raw == name or incumbent_raw.split(" (")[0] == name.split(" (")[0]
        )
        cand = {
            "name": name,
            "party": nom["party"],
            "incumbent": is_incumbent,
            "background": bio,
            "positions": extract_positions(wt, url),
            "sources": [url],
        }
        candidates.append(cand)

    for tp in thirdparty:
        name = tp["name"]
        if not name or name in seen_names:
            continue
        seen_names.add(name)
        bio = tp["raw"] if tp["raw"] and tp["raw"] != name else None
        candidates.append(
            {
                "name": name,
                "party": tp["party"],
                "incumbent": False,
                "background": bio,
                "positions": [],
                "sources": [url],
            }
        )

    context = {"sources": [url]}
    if incumbent_raw:
        context["last_result"] = f"Incumbent prior to 2026: {incumbent_raw}"
    if not nominees:
        # Genuinely unsettled per page: record what's there verbatim (unopposed note, etc.)
        context["note"] = (
            "Infobox has no nominee/party fields populated as of fetch time — "
            "general-election nomination not yet reflected on the page."
        )

    return {
        "race_id": race_spec["race_id"],
        "office": race_spec["office"],
        "level": race_spec["level"],
        "district": None,
        "candidates": candidates,
        "context": context,
    }


def main():
    races = []
    for spec in RACES:
        race = build_race(spec)
        races.append(race)
        time.sleep(0.3)  # polite delay between Wikipedia API calls

    out = {"races": races}

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False))

    # Verify JSON parses
    json.loads(OUT_PATH.read_text())
    print(f"Wrote {OUT_PATH} ({OUT_PATH.stat().st_size} bytes)")
    for r in races:
        print(f"  {r['race_id']}: {len(r['candidates'])} candidates")


if __name__ == "__main__":
    main()
