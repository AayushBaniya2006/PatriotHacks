#!/usr/bin/env python3
"""Fetch current Texas municipal officials (mayors of ~25 largest cities +
city council members for the big 5) into data/politicians/tx_municipal.json.

Sources (APIs only, per repo policy — no raw-HTML scraping):
  1. Wikidata SPARQL: city P6 (head of government) statements with no end
     date -> current mayor, with P580 start-time qualifier and optional
     P102 party (usually absent; TX municipal races are nonpartisan).
  2. English Wikipedia MediaWiki API (action=query, prop=revisions,
     rvslots=main): wikitext of "<City> City Council" pages, parsed
     conservatively for member tables. If a page's tables don't yield
     clean name+district rows, the council for that city is SKIPPED and
     noted. Sparse-but-honest beats invented.

Run:  python3 pipeline/fetch_tx_municipal.py
"""

import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = ROOT / "data" / "politicians" / "tx_municipal.json"

USER_AGENT = (
    "PatriotHacks-VoterInfoTool/1.0 (civic hackathon data pipeline; "
    "contact: github.com/AayushBaniya2006) python-urllib"
)

# Top 25 TX cities by population + San Marcos (demo golden address).
TARGET_CITIES = [
    "Houston", "San Antonio", "Dallas", "Austin", "Fort Worth",
    "El Paso", "Arlington", "Corpus Christi", "Plano", "Lubbock",
    "Laredo", "Irving", "Garland", "Frisco", "McKinney",
    "Amarillo", "Grand Prairie", "Brownsville", "Denton", "Mesquite",
    "Killeen", "McAllen", "Waco", "Carrollton", "Round Rock",
    "San Marcos",
]

BIG5 = ["Houston", "San Antonio", "Dallas", "Austin", "Fort Worth"]

COUNCIL_PAGES = {
    "Houston": "Houston City Council",
    "San Antonio": "San Antonio City Council",
    "Dallas": "Dallas City Council",
    "Austin": "Austin City Council",
    "Fort Worth": "Fort Worth City Council",
}

SPARQL_ENDPOINT = "https://query.wikidata.org/sparql"
WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"

NAME_SUFFIXES = {"jr", "jr.", "sr", "sr.", "ii", "iii", "iv", "v"}


# ---------------------------------------------------------------- helpers

def http_get_json(url: str, params: dict, retries: int = 3,
                  backoff_429: int = 70) -> dict:
    qs = urllib.parse.urlencode(params)
    req = urllib.request.Request(
        f"{url}?{qs}",
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    last_err = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code == 429 and attempt < retries - 1:
                print(f"  429 rate-limited; sleeping {backoff_429}s ...")
                time.sleep(backoff_429)
            else:
                time.sleep(2 * (attempt + 1))
        except Exception as e:  # noqa: BLE001 - retry then surface
            last_err = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"GET {url} failed after {retries} tries: {last_err}")


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return text


def name_slug(full_name: str) -> str:
    """slugify(lastname-firstname[-middles]) per repo convention."""
    tokens = [t for t in re.split(r"\s+", full_name.strip()) if t]
    # drop parentheticals/nicknames like "(Trey)" or quoted nicknames
    tokens = [t for t in tokens if not (t.startswith("(") or t.startswith('"'))]
    while tokens and tokens[-1].lower().strip(",") in NAME_SUFFIXES:
        tokens.pop()
    if not tokens:
        return slugify(full_name)
    if len(tokens) == 1:
        return slugify(tokens[0])
    last, rest = tokens[-1], tokens[:-1]
    return slugify(f"{last}-{'-'.join(rest)}")


# ---------------------------------------------------------------- wikidata

SPARQL_QUERY_TEMPLATE = """
SELECT DISTINCT ?city ?cityLabel ?mayor ?mayorLabel ?partyLabel ?start ?rank WHERE {
  VALUES ?cityName { %s }
  ?city rdfs:label ?cityName .
  ?city wdt:P31 ?type .
  VALUES ?type { wd:Q1093829 wd:Q515 wd:Q62049 wd:Q21518270 }
  ?city wdt:P131+ wd:Q1439 .
  ?city p:P6 ?st .
  ?st ps:P6 ?mayor .
  ?st wikibase:rank ?rank .
  FILTER(?rank != wikibase:DeprecatedRank)
  FILTER NOT EXISTS { ?st pq:P582 ?end }
  OPTIONAL { ?st pq:P580 ?start }
  OPTIONAL { ?mayor wdt:P102 ?party }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}
"""


def fetch_mayors() -> dict:
    """Return {city_name: record_dict} for current mayors.

    Primary: one Wikidata SPARQL query. Fallback (WDQS outage / 429):
    Wikipedia pageprops -> city QIDs, then Wikidata wbgetentities for the
    P6 claims. Both paths read the same P6 statements.
    """
    try:
        return fetch_mayors_sparql()
    except RuntimeError as e:
        print(f"  SPARQL path failed ({e}); falling back to Wikidata entity API")
        return fetch_mayors_entity_api()


def fetch_mayors_sparql() -> dict:
    values = " ".join(f'"{c}"@en' for c in TARGET_CITIES)
    query = SPARQL_QUERY_TEMPLATE % values
    data = http_get_json(SPARQL_ENDPOINT, {"query": query, "format": "json"},
                         retries=2)
    rows = data["results"]["bindings"]

    # group candidate statements per city
    by_city: dict[str, list[dict]] = {}
    for row in rows:
        city = row["cityLabel"]["value"]
        if city not in TARGET_CITIES:
            continue
        by_city.setdefault(city, []).append(row)

    mayors: dict[str, dict] = {}
    for city, candidates in by_city.items():
        # prefer PreferredRank, then latest start date
        def sort_key(r):
            preferred = r["rank"]["value"].endswith("PreferredRank")
            start = r.get("start", {}).get("value", "")
            return (preferred, start)

        best = sorted(candidates, key=sort_key)[-1]
        mayor_qid = best["mayor"]["value"].rsplit("/", 1)[-1]
        name = best["mayorLabel"]["value"]
        if re.fullmatch(r"Q\d+", name):
            print(f"  WARN {city}: mayor entity {mayor_qid} has no English label, skipping")
            continue
        party = best.get("partyLabel", {}).get("value")
        start = best.get("start", {}).get("value")
        mayors[city] = build_mayor_record(city, name, mayor_qid, party,
                                          normalize_wd_date(start))
    return mayors


def normalize_wd_date(raw: str | None) -> str | None:
    """Trim Wikidata timestamps to their real precision: '2022-05-00' -> '2022-05'."""
    if not raw:
        return None
    d = raw.lstrip("+")[:10]
    while d.endswith("-00"):
        d = d[:-3]
    return d or None


def build_mayor_record(city: str, name: str, qid: str,
                       party: str | None, start: str | None) -> dict:
    rec = {
        "politician_id": f"{name_slug(name)}-tx-mayor-{slugify(city)}",
        "name": name,
        "level": "municipal",
        "role": "executive",
        "office": f"Mayor of {city}",
        "state": "TX",
        "jurisdiction": f"{city}, TX",
        "incumbent": True,
        "ids": {"wikidata": qid},
        "sources": [f"https://www.wikidata.org/wiki/{qid}"],
    }
    if party and not re.fullmatch(r"Q\d+", party):
        # mayors are usually nonpartisan; only include a real party label
        if party.lower() not in {"independent politician", "nonpartisanism"}:
            rec["party"] = party
    if start:
        rec["term"] = {"start": start}
    return rec


# ---- fallback path: Wikipedia pageprops -> Wikidata wbgetentities --------

WIKIDATA_API = "https://www.wikidata.org/w/api.php"


def resolve_city_qids() -> dict:
    """{city_name: QID} via en.wikipedia pageprops (wikibase_item)."""
    titles = {f"{c}, Texas": c for c in TARGET_CITIES}
    data = http_get_json(WIKIPEDIA_API, {
        "action": "query", "prop": "pageprops", "ppprop": "wikibase_item",
        "titles": "|".join(titles), "redirects": "1",
        "format": "json", "formatversion": "2",
    })
    q = data.get("query", {})
    # map requested title -> final title through normalization + redirects
    final = {t: t for t in titles}
    for step in ("normalized", "redirects"):
        moves = {m["from"]: m["to"] for m in q.get(step, [])}
        final = {req: moves.get(cur, cur) for req, cur in final.items()}
    by_title = {p["title"]: p for p in q.get("pages", [])}
    out = {}
    for req_title, city in titles.items():
        page = by_title.get(final[req_title])
        qid = (page or {}).get("pageprops", {}).get("wikibase_item")
        if qid:
            out[city] = qid
        else:
            print(f"  WARN {city}: could not resolve Wikidata QID via Wikipedia")
    return out


def wbgetentities(ids: list[str], props: str) -> dict:
    entities = {}
    for i in range(0, len(ids), 50):
        chunk = ids[i:i + 50]
        data = http_get_json(WIKIDATA_API, {
            "action": "wbgetentities", "ids": "|".join(chunk),
            "props": props, "languages": "en", "format": "json",
        })
        entities.update(data.get("entities", {}))
        time.sleep(0.5)
    return entities


def _qualifier_time(stmt: dict, prop: str) -> str | None:
    for qual in stmt.get("qualifiers", {}).get(prop, []):
        t = qual.get("datavalue", {}).get("value", {}).get("time")
        if t:
            return normalize_wd_date(t)
    return None


def current_p6_statement(entity: dict) -> dict | None:
    stmts = entity.get("claims", {}).get("P6", [])
    live = []
    for st in stmts:
        if st.get("rank") == "deprecated":
            continue
        if "P582" in st.get("qualifiers", {}):
            continue  # ended term
        if st.get("mainsnak", {}).get("snaktype") != "value":
            continue
        live.append(st)
    if not live:
        return None
    return sorted(live, key=lambda s: (s.get("rank") == "preferred",
                                       _qualifier_time(s, "P580") or ""))[-1]


def fetch_mayors_entity_api() -> dict:
    city_qids = resolve_city_qids()
    city_entities = wbgetentities(list(city_qids.values()), "claims")

    picks = {}  # city -> (mayor_qid, start)
    for city, cqid in city_qids.items():
        st = current_p6_statement(city_entities.get(cqid, {}))
        if not st:
            continue
        mayor_qid = st["mainsnak"]["datavalue"]["value"]["id"]
        picks[city] = (mayor_qid, _qualifier_time(st, "P580"))

    mayor_qids = sorted({q for q, _ in picks.values()})
    mayor_entities = wbgetentities(mayor_qids, "labels|claims")

    # collect party QIDs (truthy-ish: skip deprecated/ended)
    party_of = {}
    for qid, ent in mayor_entities.items():
        for st in ent.get("claims", {}).get("P102", []):
            if st.get("rank") == "deprecated" or "P582" in st.get("qualifiers", {}):
                continue
            if st.get("mainsnak", {}).get("snaktype") == "value":
                party_of[qid] = st["mainsnak"]["datavalue"]["value"]["id"]
                break
    party_labels = {}
    if party_of:
        for pqid, ent in wbgetentities(sorted(set(party_of.values())),
                                       "labels").items():
            party_labels[pqid] = ent.get("labels", {}).get("en", {}).get("value")

    mayors = {}
    for city, (mayor_qid, start) in picks.items():
        name = (mayor_entities.get(mayor_qid, {})
                .get("labels", {}).get("en", {}).get("value"))
        if not name:
            print(f"  WARN {city}: mayor entity {mayor_qid} has no English label, skipping")
            continue
        party = party_labels.get(party_of.get(mayor_qid))
        mayors[city] = build_mayor_record(city, name, mayor_qid, party, start)
    return mayors


# ------------------------------------------------------------- wikipedia

def fetch_wikitext(title: str) -> tuple[str, str] | None:
    """Return (canonical_title, wikitext) or None."""
    data = http_get_json(WIKIPEDIA_API, {
        "action": "query", "prop": "revisions", "rvslots": "main",
        "rvprop": "content", "format": "json", "formatversion": "2",
        "redirects": "1", "titles": title,
    })
    pages = data.get("query", {}).get("pages", [])
    if not pages or pages[0].get("missing"):
        return None
    page = pages[0]
    try:
        return page["title"], page["revisions"][0]["slots"]["main"]["content"]
    except (KeyError, IndexError):
        return None


REF_RE = re.compile(r"<ref[^>/]*/>|<ref[^>]*>.*?</ref>", re.DOTALL)
COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
TAG_RE = re.compile(r"<[^>]+>")


def clean_cell(cell: str) -> str:
    s = REF_RE.sub("", cell)
    s = COMMENT_RE.sub("", s)
    # {{sortname|First|Last|...}} -> First Last
    s = re.sub(
        r"\{\{\s*sortname\s*\|([^|{}]+)\|([^|{}]+)(?:\|[^{}]*)?\}\}",
        r"\1 \2", s, flags=re.IGNORECASE)
    # drop any other templates
    while "{{" in s:
        new = re.sub(r"\{\{[^{}]*\}\}", "", s)
        if new == s:
            break
        s = new
    # [[target|text]] -> text ; [[target]] -> target
    s = re.sub(r"\[\[(?:[^\[\]|]*\|)?([^\[\]|]+)\]\]", r"\1", s)
    s = TAG_RE.sub(" ", s)
    s = s.replace("'''", "").replace("''", "")
    # drop leading style attrs like: style="..." |
    if "|" in s and ("=" in s.split("|", 1)[0]):
        s = s.split("|", 1)[1]
    return re.sub(r"\s+", " ", s).strip(" \u2020\u2021*").strip()


def extract_tables(wikitext: str) -> list[str]:
    """Return raw contents of top-level {| ... |} tables (nested kept inline)."""
    tables, depth, start = [], 0, None
    i = 0
    while i < len(wikitext) - 1:
        two = wikitext[i:i + 2]
        if two == "{|":
            if depth == 0:
                start = i
            depth += 1
            i += 2
            continue
        if two == "|}" and depth > 0:
            depth -= 1
            if depth == 0 and start is not None:
                tables.append(wikitext[start:i + 2])
                start = None
            i += 2
            continue
        i += 1
    return tables


def table_rows(table: str) -> list[list[str]]:
    """Split a wikitext table into rows of raw cells."""
    body = table.strip()
    body = body[2:] if body.startswith("{|") else body
    body = body[:-2] if body.endswith("|}") else body
    rows_raw = re.split(r"\n\s*\|-[^\n]*", body)
    rows = []
    for raw in rows_raw:
        cells = []
        for line in raw.split("\n"):
            line = line.strip()
            if not line or line.startswith("|+"):
                continue
            if line.startswith("!"):
                parts = re.split(r"\s*!!\s*", line[1:])
                cells.extend(parts)
            elif line.startswith("|"):
                parts = re.split(r"\s*\|\|\s*", line[1:])
                cells.extend(parts)
            elif cells:
                cells[-1] += " " + line  # continuation of previous cell
        if cells:
            rows.append(cells)
    return rows


DISTRICT_HEADERS = ("district", "place", "position", "seat", "ward")
NAME_HEADERS = ("member", "name", "council member", "councilmember",
                "incumbent", "representative")
NAME_OK_RE = re.compile(
    r"^[^\W\d_][\w.'\u2019\-]*(?: [\w.'\u2019\-()\"]+){1,4}$", re.UNICODE)
BAD_NAME_WORDS = {"vacant", "tbd", "district", "mayor", "president", "election",
                  "party", "term", "notes", "residence"}


def parse_council_members(wikitext: str) -> list[dict]:
    """Conservative extraction of (name, district) rows from member tables."""
    members: list[dict] = []
    seen = set()
    for table in extract_tables(wikitext):
        rows = table_rows(table)
        if len(rows) < 3:
            continue
        header = [clean_cell(c).lower() for c in rows[0]]
        d_idx = n_idx = None
        for i, h in enumerate(header):
            if d_idx is None and any(h.startswith(k) for k in DISTRICT_HEADERS):
                d_idx = i
            if n_idx is None and any(k in h for k in NAME_HEADERS):
                n_idx = i
        if d_idx is None or n_idx is None or d_idx == n_idx:
            continue
        d_word = header[d_idx].split()[0].title() if header[d_idx] else "District"
        for row in rows[1:]:
            if len(row) <= max(d_idx, n_idx):
                continue
            district = clean_cell(row[d_idx])
            name = clean_cell(row[n_idx])
            # strip parenthetical/quoted nicknames for validation
            plain = re.sub(r"\s*[(\"][^)\"]*[)\"]", "", name).strip()
            if not plain or not district:
                continue
            low = plain.lower()
            if any(w in low for w in BAD_NAME_WORDS):
                continue
            if "mayor" in district.lower():
                continue  # mayor listed inside council table; captured separately
            if not NAME_OK_RE.match(plain) or re.search(r"\d", plain) \
                    or not plain[0].isupper():
                continue
            # normalize district label
            if re.fullmatch(r"[0-9]+|[A-Z]", district):
                district = f"{d_word} {district}"
            district = re.sub(r"\s+", " ", district).strip()
            if len(district) > 40:
                continue
            key = (plain.lower(), district.lower())
            if key in seen:
                continue
            seen.add(key)
            members.append({"name": name, "district": district})
    return members


def fetch_councils(mayors: dict) -> tuple[list[dict], dict, list[str]]:
    records, counts, skipped = [], {}, []
    for city in BIG5:
        title = COUNCIL_PAGES[city]
        got = fetch_wikitext(title)
        time.sleep(0.5)
        if not got:
            skipped.append(f"{city} (page '{title}' not found)")
            continue
        canonical, wikitext = got
        members = parse_council_members(wikitext)
        if len(members) < 5:
            skipped.append(
                f"{city} (only {len(members)} clean rows parsed from '{canonical}' — "
                "table not reliably extractable)")
            continue
        page_url = "https://en.wikipedia.org/wiki/" + canonical.replace(" ", "_")
        mayor_name = mayors.get(city, {}).get("name", "").lower()
        kept = 0
        for m in members:
            if mayor_name and m["name"].lower() == mayor_name:
                continue  # mayor already recorded as executive
            rec = {
                "politician_id": (
                    f"{name_slug(m['name'])}-tx-council-{slugify(city)}-"
                    f"{slugify(m['district'])}"),
                "name": m["name"],
                "level": "municipal",
                "role": "legislator",
                "office": f"{city} City Council, {m['district']}",
                "state": "TX",
                "district": m["district"],
                "jurisdiction": f"{city}, TX",
                "incumbent": True,
                "sources": [page_url],
            }
            records.append(rec)
            kept += 1
        counts[city] = kept
    return records, counts, skipped


# ------------------------------------------------------------------ main

def main() -> int:
    print("== Fetching mayors from Wikidata SPARQL ==")
    mayors = fetch_mayors()

    print("\n== Fetching big-5 council pages from Wikipedia API ==")
    council_records, council_counts, council_skipped = fetch_councils(mayors)

    politicians = [mayors[c] for c in TARGET_CITIES if c in mayors]
    politicians += council_records

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "Wikidata SPARQL + English Wikipedia API",
        "politicians": politicians,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")

    # ---------------- verification ----------------
    print("\n== VERIFICATION ==")
    ok = True

    missing = [c for c in TARGET_CITIES if c not in mayors]
    print(f"Mayors found: {len(mayors)}/{len(TARGET_CITIES)}")
    for city, rec in ((c, mayors[c]) for c in TARGET_CITIES if c in mayors):
        term = rec.get("term", {}).get("start", "start unknown")
        party = rec.get("party", "no party listed")
        print(f"  {city:15s} {rec['name']:30s} ({term}; {party}) {rec['ids']['wikidata']}")
    for city in missing:
        print(f"  MISSING mayor: {city} — no current (un-ended) P6 statement "
              "matched on Wikidata for a city entity with that label in Texas")
    if len(mayors) < 20:
        print("FAIL: fewer than 20 mayors")
        ok = False

    print("\nCouncil counts:")
    for city in BIG5:
        if city in council_counts:
            print(f"  {city:15s} {council_counts[city]} members")
    for s in council_skipped:
        print(f"  SKIPPED council: {s}")

    required = ("politician_id", "name", "office", "jurisdiction", "sources")
    ids_seen = set()
    for rec in politicians:
        for field in required:
            if not rec.get(field):
                print(f"FAIL: record missing {field}: {rec}")
                ok = False
        if rec["politician_id"] in ids_seen:
            print(f"FAIL: duplicate politician_id {rec['politician_id']}")
            ok = False
        ids_seen.add(rec["politician_id"])

    print(f"\nTotal records: {len(politicians)} "
          f"({len(mayors)} mayors + {len(council_records)} council members)")
    print(f"Wrote {OUT_PATH.relative_to(ROOT)}")
    print("VERIFICATION:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
