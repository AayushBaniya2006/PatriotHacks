#!/usr/bin/env python3
"""Fetch current US state executives from Wikidata SPARQL + English Wikipedia API.

Produces data/politicians/state_executives.json with:
  (a) the current governor of all 50 US states (Wikidata SPARQL, P6 head-of-government
      statements on state items with no end-date qualifier), and
  (b) the full slate of current Texas statewide executive officeholders
      (Wikidata P39 position-held queries, cross-checked / backfilled from the
      English Wikipedia MediaWiki API office-page infoboxes -- API only, no HTML
      scraping).

Every record carries mandatory source URLs. Missing facts are omitted, never invented.
"""

import json
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

USER_AGENT = (
    "PatriotHacks-CivicData/1.0 (voter-information hackathon pipeline; "
    "https://github.com/patriothacks; contact: dev@example.com)"
)
SPARQL_URL = "https://query.wikidata.org/sparql"
WD_API = "https://www.wikidata.org/w/api.php"
WP_API = "https://en.wikipedia.org/w/api.php"

OUT_PATH = Path("data/politicians/state_executives.json")

STATE_ABBR = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR",
    "California": "CA", "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE",
    "Florida": "FL", "Georgia": "GA", "Hawaii": "HI", "Idaho": "ID",
    "Illinois": "IL", "Indiana": "IN", "Iowa": "IA", "Kansas": "KS",
    "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD",
    "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS",
    "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV",
    "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY",
    "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK",
    "Oregon": "OR", "Pennsylvania": "PA", "Rhode Island": "RI", "South Carolina": "SC",
    "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX", "Utah": "UT",
    "Vermont": "VT", "Virginia": "VA", "Washington": "WA", "West Virginia": "WV",
    "Wisconsin": "WI", "Wyoming": "WY",
}

NATIONAL_PARTIES = {"Democratic Party", "Republican Party"}
NAME_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v", "jr.", "sr."}

# Texas statewide executive offices.
# wd_qid: Wikidata position item (None = no usable position item found).
# wp_page: English Wikipedia office/agency page used for cross-check + backfill.
TX_OFFICES = {
    "gov": {
        "office": "Governor of Texas",
        "wd_qid": "Q5589725",
        "wp_page": "Governor of Texas",
    },
    "ltgov": {
        "office": "Lieutenant Governor of Texas",
        "wd_qid": "Q639115",
        "wp_page": "Lieutenant Governor of Texas",
    },
    "ag": {
        "office": "Attorney General of Texas",
        "wd_qid": "Q7707525",
        "wp_page": "Texas Attorney General",
    },
    "comptroller": {
        "office": "Texas Comptroller of Public Accounts",
        "wd_qid": "Q8350359",
        "wp_page": "Texas Comptroller of Public Accounts",
    },
    "land": {
        "office": "Texas Land Commissioner",
        "wd_qid": "Q124518473",
        "wp_page": "Texas General Land Office",
    },
    "agriculture": {
        "office": "Texas Agriculture Commissioner",
        "wd_qid": "Q113045498",
        "wp_page": "Texas Department of Agriculture",
    },
    "sos": {
        "office": "Secretary of State of Texas",
        "wd_qid": "Q7444388",
        "wp_page": "Secretary of State of Texas",
    },
    # Railroad Commission: 3 members, no per-seat Wikidata position item ->
    # taken from the agency page infobox (chiefN_name fields), rrc1..rrc3.
}
RRC_PAGE = "Railroad Commission of Texas"
RRC_OFFICE = "Texas Railroad Commissioner"


# ---------------------------------------------------------------- HTTP helpers

def _get_json(url: str, params: dict) -> dict:
    qs = urllib.parse.urlencode(params)
    req = urllib.request.Request(
        f"{url}?{qs}",
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    attempts = 6
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001 - retry then re-raise
            if attempt == attempts - 1:
                raise
            # WDQS throttles to 1 req/min during outages -> honor Retry-After / wait it out.
            if isinstance(exc, urllib.error.HTTPError) and exc.code == 429:
                retry_after = exc.headers.get("Retry-After")
                wait = int(retry_after) if retry_after and retry_after.isdigit() else 65
            else:
                wait = 2 * (attempt + 1)
            print(f"  retry {attempt + 1} in {wait}s after error: {exc}", file=sys.stderr)
            time.sleep(wait)
    raise RuntimeError("unreachable")


def sparql(query: str) -> list[dict]:
    data = _get_json(SPARQL_URL, {"query": query, "format": "json"})
    return data["results"]["bindings"]


def wp_section0_wikitext(page: str) -> tuple[str, str]:
    """Return (resolved_title, wikitext of section 0) for a Wikipedia page."""
    data = _get_json(WP_API, {
        "action": "parse", "page": page, "prop": "wikitext",
        "section": 0, "redirects": 1, "format": "json",
    })
    parse = data["parse"]
    return parse["title"], parse["wikitext"]["*"]


def wd_entity_for_enwiki_title(title: str) -> dict | None:
    """Resolve an enwiki article title to its Wikidata entity (claims included)."""
    data = _get_json(WD_API, {
        "action": "wbgetentities", "sites": "enwiki", "titles": title,
        "props": "claims|labels", "redirects": "yes", "format": "json",
    })
    for ent_id, ent in data.get("entities", {}).items():
        if ent_id.startswith("Q") and "missing" not in ent:
            return ent
    return None


def wd_labels(qids: list[str]) -> dict[str, str]:
    """Batch-resolve Wikidata QIDs to English labels."""
    labels: dict[str, str] = {}
    qids = [q for q in dict.fromkeys(qids) if q]
    for i in range(0, len(qids), 50):
        batch = qids[i:i + 50]
        data = _get_json(WD_API, {
            "action": "wbgetentities", "ids": "|".join(batch),
            "props": "labels", "languages": "en", "format": "json",
        })
        for qid, ent in data.get("entities", {}).items():
            lbl = ent.get("labels", {}).get("en", {}).get("value")
            if lbl:
                labels[qid] = lbl
    return labels


# ------------------------------------------------------------- small utilities

def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return text


def politician_id(name: str, state_abbr: str, office_code: str) -> str:
    tokens = [t for t in re.split(r"\s+", name.strip()) if t]
    tokens = [t for t in tokens if t.lower().strip(".,") not in NAME_SUFFIXES]
    if len(tokens) >= 2:
        ordered = [tokens[-1]] + tokens[:-1]
    else:
        ordered = tokens
    return f"{slugify('-'.join(ordered))}-{state_abbr.lower()}-{office_code}"


def iso_date_from_wd(value: str | None) -> str | None:
    """'+2015-01-20T00:00:00Z' -> '2015-01-20'."""
    if not value:
        return None
    m = re.match(r"\+?(\d{4})-(\d{2})-(\d{2})", value)
    if not m:
        return None
    y, mo, d = m.groups()
    if mo == "00":  # year-precision value
        return y
    if d == "00":
        return f"{y}-{mo}"
    return f"{y}-{mo}-{d}"


def parse_us_date(text: str) -> str | None:
    """'January 5, 2023...' -> '2023-01-05'."""
    m = re.search(r"([A-Z][a-z]+)\s+(\d{1,2}),\s+(\d{4})", text)
    if not m:
        return None
    try:
        dt = datetime.strptime(" ".join(m.groups()), "%B %d %Y")
    except ValueError:
        return None
    return dt.strftime("%Y-%m-%d")


def strip_wikilink(raw: str) -> tuple[str, str] | None:
    """'[[Dan Patrick (politician)|Dan Patrick]]' -> ('Dan Patrick (politician)', 'Dan Patrick')."""
    m = re.search(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]", raw)
    if not m:
        txt = re.sub(r"\{\{.*?\}\}|<[^>]+>", "", raw).strip()
        return (txt, txt) if txt else None
    title = m.group(1).strip()
    display = (m.group(2) or m.group(1)).strip()
    return title, display


def infobox_field(wikitext: str, field: str) -> str | None:
    m = re.search(rf"\|\s*{re.escape(field)}\s*=\s*(.+)", wikitext)
    return m.group(1).strip() if m else None


def pick_party(labels: list[str]) -> str | None:
    labels = [l for l in dict.fromkeys(labels) if l]
    if not labels:
        return None
    for l in labels:
        if l in NATIONAL_PARTIES:
            return l
    return min(labels, key=len)


def person_party_and_start(ent: dict, office_qid: str | None) -> tuple[str | None, str | None]:
    """From a person's Wikidata entity: (party QID, start date for the given office)."""
    claims = ent.get("claims", {})
    party_qid = None
    for st in claims.get("P102", []):
        if st.get("rank") == "deprecated":
            continue
        val = st.get("mainsnak", {}).get("datavalue", {}).get("value", {})
        if isinstance(val, dict) and val.get("id"):
            party_qid = val["id"]
            if st.get("rank") == "preferred":
                break
    start = None
    if office_qid:
        for st in claims.get("P39", []):
            val = st.get("mainsnak", {}).get("datavalue", {}).get("value", {})
            if not (isinstance(val, dict) and val.get("id") == office_qid):
                continue
            quals = st.get("qualifiers", {})
            if "P582" in quals:  # ended term, not the current one
                continue
            raw = quals.get("P580", [{}])[0].get("datavalue", {}).get("value", {})
            start = iso_date_from_wd(raw.get("time") if isinstance(raw, dict) else None)
            if start:
                break
    return party_qid, start


def surname_match(a: str, b: str) -> bool:
    def surname(n: str) -> str:
        toks = [t for t in re.split(r"\s+", re.sub(r"\(.*?\)", "", n).strip()) if t]
        toks = [t for t in toks if t.lower().strip(".,") not in NAME_SUFFIXES]
        return slugify(toks[-1]) if toks else ""
    return bool(surname(a)) and surname(a) == surname(b)


# --------------------------------------------------------------- 50 governors

GOVERNORS_QUERY = """
SELECT ?state ?stateLabel ?gov ?govLabel ?party ?partyLabel ?start WHERE {
  ?state wdt:P31 wd:Q35657 .
  ?state p:P6 ?st .
  ?st ps:P6 ?gov .
  FILTER NOT EXISTS { ?st pq:P582 ?end }
  OPTIONAL { ?gov wdt:P102 ?party }
  OPTIONAL { ?st pq:P580 ?start }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en" . }
}
"""


def fetch_governors() -> tuple[list[dict], list[str]]:
    print("Fetching 50 governors from Wikidata SPARQL...")
    rows = sparql(GOVERNORS_QUERY)
    print(f"  {len(rows)} raw rows")

    # Group rows per state; within a state, group per governor statement.
    by_state: dict[str, dict] = {}
    for r in rows:
        state_label = r["stateLabel"]["value"]
        if state_label not in STATE_ABBR:
            continue  # ignore anything that isn't one of the 50 states
        gov_uri = r["gov"]["value"]
        start = iso_date_from_wd(r.get("start", {}).get("value"))
        entry = by_state.setdefault(state_label, {}).setdefault(gov_uri, {
            "name": r["govLabel"]["value"],
            "qid": gov_uri.rsplit("/", 1)[-1],
            "starts": set(),
            "parties": [],
        })
        if start:
            entry["starts"].add(start)
        p = r.get("partyLabel", {}).get("value")
        if p:
            entry["parties"].append(p)

    records, missing = [], []
    for state_label, abbr in sorted(STATE_ABBR.items()):
        cands = by_state.get(state_label)
        if not cands:
            missing.append(state_label)
            continue
        # Stale statements lack end dates; the current governor is the statement
        # with the most recent start date (statements with a start beat ones without).
        def sort_key(e: dict):
            return (bool(e["starts"]), max(e["starts"]) if e["starts"] else "")
        best = max(cands.values(), key=sort_key)
        rec = {
            "politician_id": politician_id(best["name"], abbr, "gov"),
            "name": best["name"],
            "level": "state",
            "role": "executive",
            "office": f"Governor of {state_label}",
            "state": abbr,
            "jurisdiction": abbr,
            "incumbent": True,
            "ids": {"wikidata": best["qid"]},
            "sources": [f"https://www.wikidata.org/wiki/{best['qid']}"],
        }
        party = pick_party(best["parties"])
        if party:
            rec["party"] = party
        if best["starts"]:
            rec["term"] = {"start": max(best["starts"])}
        records.append(rec)
    return records, missing


# ----------------------------------------------------------------- Texas slate

TX_P39_QUERY_TMPL = """
SELECT ?pos ?person ?personLabel ?party ?partyLabel ?start WHERE {{
  VALUES ?pos {{ {values} }}
  ?person p:P39 ?st .
  ?st ps:P39 ?pos .
  FILTER NOT EXISTS {{ ?st pq:P582 ?end }}
  FILTER NOT EXISTS {{ ?person wdt:P570 ?dod }}
  OPTIONAL {{ ?person wdt:P102 ?party }}
  OPTIONAL {{ ?st pq:P580 ?start }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en" . }}
}}
"""


def fetch_tx_wikidata() -> dict[str, dict]:
    """P39 current-holder candidates per TX office code (latest start wins)."""
    qid_to_code = {cfg["wd_qid"]: code for code, cfg in TX_OFFICES.items() if cfg["wd_qid"]}
    values = " ".join(f"wd:{q}" for q in qid_to_code)
    print("Fetching TX statewide officeholders from Wikidata SPARQL...")
    rows = sparql(TX_P39_QUERY_TMPL.format(values=values))
    print(f"  {len(rows)} raw rows")

    per_office: dict[str, dict] = {}
    grouped: dict[tuple[str, str], dict] = {}
    for r in rows:
        code = qid_to_code[r["pos"]["value"].rsplit("/", 1)[-1]]
        person_uri = r["person"]["value"]
        key = (code, person_uri)
        entry = grouped.setdefault(key, {
            "name": r["personLabel"]["value"],
            "qid": person_uri.rsplit("/", 1)[-1],
            "starts": set(),
            "parties": [],
        })
        start = iso_date_from_wd(r.get("start", {}).get("value"))
        if start:
            entry["starts"].add(start)
        p = r.get("partyLabel", {}).get("value")
        if p:
            entry["parties"].append(p)

    for (code, _), entry in grouped.items():
        cur = per_office.get(code)
        def sort_key(e):
            return (bool(e["starts"]), max(e["starts"]) if e["starts"] else "")
        if cur is None or sort_key(entry) > sort_key(cur):
            per_office[code] = entry
    return per_office


def fetch_tx_wikipedia() -> dict[str, dict]:
    """Office-page infobox incumbents for every TX office, via the MediaWiki API."""
    print("Cross-checking TX offices via English Wikipedia API...")
    out: dict[str, dict] = {}
    for code, cfg in TX_OFFICES.items():
        title, wikitext = wp_section0_wikitext(cfg["wp_page"])
        url = "https://en.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_"))
        info: dict = {"page_title": title, "page_url": url}
        raw_inc = infobox_field(wikitext, "incumbent")
        if raw_inc:
            link = strip_wikilink(raw_inc)
            if link:
                info["article"], info["name"] = link
        else:
            # Agency-style infobox (e.g. Texas Department of Agriculture):
            # take chiefN_name where chiefN_position mentions "commissioner".
            for n in range(1, 6):
                nm = infobox_field(wikitext, f"chief{n}_name")
                pos = infobox_field(wikitext, f"chief{n}_position") or ""
                if nm and "commissioner" in pos.lower():
                    link = strip_wikilink(nm)
                    if link:
                        info["article"], info["name"] = link
                        break
        since = infobox_field(wikitext, "incumbentsince")
        if since:
            d = parse_us_date(since)
            if d:
                info["since"] = d
        out[code] = info
        print(f"  {code:12s} -> {info.get('name')} (since {info.get('since')}) [{title}]")
    return out


def fetch_rrc() -> list[dict]:
    """The three sitting Railroad Commissioners, from the agency page infobox."""
    print("Fetching Railroad Commission of Texas members via Wikipedia API...")
    title, wikitext = wp_section0_wikitext(RRC_PAGE)
    url = "https://en.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_"))
    members = []
    for n in range(1, 8):
        nm = infobox_field(wikitext, f"chief{n}_name")
        pos = infobox_field(wikitext, f"chief{n}_position") or ""
        if nm and ("commissioner" in pos.lower() or "chair" in pos.lower()):
            link = strip_wikilink(nm)
            if link:
                members.append({"article": link[0], "name": link[1], "page_url": url})
    print(f"  {len(members)} commissioners: {[m['name'] for m in members]}")
    return members


def build_tx_slate() -> list[dict]:
    wd = fetch_tx_wikidata()
    wp = fetch_tx_wikipedia()
    rrc = fetch_rrc()

    party_qids_needed: list[str] = []
    staged: list[dict] = []  # (code, office, name, qid, party_label|party_qid, start, sources)

    for code, cfg in TX_OFFICES.items():
        wd_pick = wd.get(code)
        wp_pick = wp.get(code)
        wp_name = (wp_pick or {}).get("name")

        agree = bool(wd_pick and wp_name and surname_match(wd_pick["name"], wp_name))
        item = {"code": code, "office": cfg["office"], "sources": []}

        if agree:
            # Both sources agree: Wikipedia display name + date, Wikidata identity/party.
            item.update({
                "name": wp_name,
                "qid": wd_pick["qid"],
                "party_label": pick_party(wd_pick["parties"]),
                "start": wp_pick.get("since") or (max(wd_pick["starts"]) if wd_pick["starts"] else None),
            })
            item["sources"] = [
                f"https://www.wikidata.org/wiki/{wd_pick['qid']}",
                wp_pick["page_url"],
            ]
        elif wp_name:
            # Wikidata missing/stale for this office: trust the office page, then
            # resolve the person on Wikidata for QID/party/start.
            ent = wd_entity_for_enwiki_title(wp_pick["article"])
            item.update({"name": wp_name, "start": wp_pick.get("since")})
            item["sources"] = [wp_pick["page_url"]]
            if ent:
                item["qid"] = ent["id"]
                party_qid, wd_start = person_party_and_start(ent, cfg["wd_qid"])
                item["party_qid"] = party_qid
                if not item["start"]:
                    item["start"] = wd_start
                item["sources"].insert(0, f"https://www.wikidata.org/wiki/{ent['id']}")
                if party_qid:
                    party_qids_needed.append(party_qid)
        elif wd_pick:
            item.update({
                "name": wd_pick["name"],
                "qid": wd_pick["qid"],
                "party_label": pick_party(wd_pick["parties"]),
                "start": max(wd_pick["starts"]) if wd_pick["starts"] else None,
            })
            item["sources"] = [f"https://www.wikidata.org/wiki/{wd_pick['qid']}"]
        else:
            print(f"  WARNING: no holder found for TX office '{code}'", file=sys.stderr)
            continue
        staged.append(item)

    # Railroad commissioners (rrc1..rrc3 in infobox order).
    for i, m in enumerate(rrc[:3], start=1):
        item = {
            "code": f"rrc{i}", "office": RRC_OFFICE,
            "name": m["name"], "start": None, "sources": [m["page_url"]],
        }
        ent = wd_entity_for_enwiki_title(m["article"])
        if ent:
            item["qid"] = ent["id"]
            party_qid, _ = person_party_and_start(ent, None)
            item["party_qid"] = party_qid
            item["sources"].insert(0, f"https://www.wikidata.org/wiki/{ent['id']}")
            if party_qid:
                party_qids_needed.append(party_qid)
        staged.append(item)

    party_labels = wd_labels(party_qids_needed)

    records = []
    for item in staged:
        rec = {
            "politician_id": politician_id(item["name"], "TX", item["code"]),
            "name": item["name"],
            "level": "state",
            "role": "executive",
            "office": item["office"],
            "state": "TX",
            "jurisdiction": "TX",
            "incumbent": True,
            "sources": item["sources"],
        }
        party = item.get("party_label") or party_labels.get(item.get("party_qid") or "")
        if party:
            rec["party"] = party
        if item.get("start"):
            rec["term"] = {"start": item["start"]}
        if item.get("qid"):
            rec["ids"] = {"wikidata": item["qid"]}
        records.append(rec)
    return records


# -------------------------------------------------------------------- assemble

def main() -> int:
    governors, missing_states = fetch_governors()
    tx_slate = build_tx_slate()

    # Merge (the TX governor appears in both passes -> merge sources, keep one record).
    merged: dict[str, dict] = {}
    for rec in tx_slate + governors:  # TX-slate version wins (richer sources)
        pid = rec["politician_id"]
        if pid in merged:
            for s in rec["sources"]:
                if s not in merged[pid]["sources"]:
                    merged[pid]["sources"].append(s)
            for k, v in rec.items():
                merged[pid].setdefault(k, v)
        else:
            merged[pid] = rec
    politicians = sorted(merged.values(), key=lambda r: (r["state"], r["office"], r["name"]))

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "Wikidata SPARQL + English Wikipedia API",
        "politicians": politicians,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    print(f"\nWrote {OUT_PATH} ({len(politicians)} records)")

    # ---------------------------------------------------------------- verify
    print("\n=== VERIFICATION ===")
    ok = True

    govs = [r for r in politicians if r["office"].startswith("Governor of ")]
    gov_states = {r["state"] for r in govs}
    missing = sorted(set(STATE_ABBR.values()) - gov_states)
    print(f"Governors: {len(govs)} (states covered: {len(gov_states)}/50)")
    if missing or missing_states:
        ok = False
        print(f"  MISSING STATES: {missing or missing_states}")
    else:
        print("  All 50 states covered.")

    tx = [r for r in politicians if r["state"] == "TX"]
    tx_codes = {r["politician_id"].rsplit("-", 1)[-1] for r in tx}
    print(f"TX slate: {len(tx)} offices -> codes {sorted(tx_codes)}")
    if len(tx) < 10:
        ok = False
        print("  FAIL: expected >= 10 TX records (8 offices incl. 3 RRC seats)")

    ids = [r["politician_id"] for r in politicians]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        ok = False
        print(f"  DUPLICATE ids: {dupes}")
    else:
        print("No duplicate politician_ids.")

    bad = [r["politician_id"] for r in politicians
           if not all(r.get(k) for k in ("politician_id", "name", "office", "state", "sources"))]
    if bad:
        ok = False
        print(f"  RECORDS MISSING REQUIRED FIELDS: {bad}")
    else:
        print("All records have politician_id/name/office/state/sources.")

    print("\n--- Full TX slate ---")
    for r in tx:
        print(f"  {r['politician_id']:35s} {r['name']:22s} {r.get('party','?'):20s} "
              f"{r['office']} (since {r.get('term',{}).get('start','?')})")

    print("\n--- 5 sample governors ---")
    for r in [g for g in govs if g["state"] != "TX"][:5]:
        print(f"  {r['politician_id']:35s} {r['name']:22s} {r.get('party','?'):20s} "
              f"{r['office']} (since {r.get('term',{}).get('start','?')})")

    print(f"\nVERIFY: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
