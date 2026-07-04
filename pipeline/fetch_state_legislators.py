#!/usr/bin/env python3
"""Fetch current state legislators for all states from Open States bulk CSVs.

Source: https://data.openstates.org/people/current/{xx}.csv  (free, no key)
Output: data/politicians/state_legislators/{xx}.json  per state.

stdlib only. Run: python pipeline/fetch_state_legislators.py
"""
import csv
import io
import json
import re
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

BASE_URL = "https://data.openstates.org/people/current/{xx}.csv"
OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "politicians" / "state_legislators"

STATES = {
    "al": "Alabama", "ak": "Alaska", "az": "Arizona", "ar": "Arkansas",
    "ca": "California", "co": "Colorado", "ct": "Connecticut", "de": "Delaware",
    "fl": "Florida", "ga": "Georgia", "hi": "Hawaii", "id": "Idaho",
    "il": "Illinois", "in": "Indiana", "ia": "Iowa", "ks": "Kansas",
    "ky": "Kentucky", "la": "Louisiana", "me": "Maine", "md": "Maryland",
    "ma": "Massachusetts", "mi": "Michigan", "mn": "Minnesota", "ms": "Mississippi",
    "mo": "Missouri", "mt": "Montana", "ne": "Nebraska", "nv": "Nevada",
    "nh": "New Hampshire", "nj": "New Jersey", "nm": "New Mexico", "ny": "New York",
    "nc": "North Carolina", "nd": "North Dakota", "oh": "Ohio", "ok": "Oklahoma",
    "or": "Oregon", "pa": "Pennsylvania", "ri": "Rhode Island", "sc": "South Carolina",
    "sd": "South Dakota", "tn": "Tennessee", "tx": "Texas", "ut": "Utah",
    "vt": "Vermont", "va": "Virginia", "wa": "Washington", "wv": "West Virginia",
    "wi": "Wisconsin", "wy": "Wyoming",
    "dc": "District of Columbia", "pr": "Puerto Rico",
}


def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def fetch_csv(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "PatriotHacks-civic-tool/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8-sig")


def build_record(row: dict, state_upper: str, state_name: str, csv_url: str) -> dict | None:
    if (row.get("death_date") or "").strip():
        return None

    chamber = (row.get("current_chamber") or "").strip()
    district = (row.get("current_district") or "").strip()
    prefix = "SD" if chamber == "upper" else "HD"
    title = "Senator" if chamber == "upper" else "Representative"

    family = (row.get("family_name") or "").strip()
    given = (row.get("given_name") or "").strip()
    name = (row.get("name") or "").strip()
    if family and given:
        name_slug = slugify(f"{family}-{given}")
    else:
        name_slug = slugify(name)
    pid = f"{name_slug}-{state_upper.lower()}-{prefix.lower()}{slugify(district)}"

    rec = {
        "politician_id": pid,
        "name": name,
        "party": (row.get("current_party") or "").strip(),
        "level": "state",
        "role": "legislator",
        "office": f"{state_name} State {title} ({prefix}-{district})",
        "state": state_upper,
        "district": f"{prefix}-{district}",
        "chamber": chamber,
        "jurisdiction": state_upper,
        "incumbent": True,
    }

    ids = {"openstates": (row.get("id") or "").strip()}
    wikidata = (row.get("wikidata") or "").strip()
    if wikidata:
        ids["wikidata"] = wikidata
    rec["ids"] = {k: v for k, v in ids.items() if v}

    links = [u for u in (row.get("links") or "").split(";") if u.strip()]
    contact = {
        "email": (row.get("email") or "").strip(),
        "capitol_voice": (row.get("capitol_voice") or "").strip(),
        "district_voice": (row.get("district_voice") or "").strip(),
        "website": links[0].strip() if links else "",
    }
    contact = {k: v for k, v in contact.items() if v}
    if contact:
        rec["contact"] = contact

    social = {k: (row.get(k) or "").strip() for k in ("twitter", "facebook", "youtube", "instagram")}
    social = {k: v for k, v in social.items() if v}
    if social:
        rec["social"] = social

    bio = {k: (row.get(k) or "").strip() for k in ("birth_date", "gender")}
    bio = {k: v for k, v in bio.items() if v}
    if bio:
        rec["bio"] = bio

    image = (row.get("image") or "").strip()
    if image:
        rec["image"] = image

    sources = [u.strip() for u in (row.get("sources") or "").split(";") if u.strip()]
    sources.append(csv_url)
    rec["sources"] = sources

    return rec


def process_state(xx: str, state_name: str) -> tuple[str, list[dict] | None, str | None]:
    """Returns (xx, records-or-None, error-or-None)."""
    url = BASE_URL.format(xx=xx)
    try:
        text = fetch_csv(url)
    except urllib.error.HTTPError as e:
        return xx, None, f"HTTP {e.code}"
    except Exception as e:
        return xx, None, str(e)

    state_upper = xx.upper()
    records = []
    seen: dict[str, int] = {}
    for row in csv.DictReader(io.StringIO(text)):
        rec = build_record(row, state_upper, state_name, url)
        if rec is None:
            continue
        pid = rec["politician_id"]
        if pid in seen:
            seen[pid] += 1
            rec["politician_id"] = f"{pid}-{seen[pid]}"
        else:
            seen[pid] = 1
        records.append(rec)
    return xx, records, None


def verify(files: dict[str, Path]) -> bool:
    ok = True
    total = 0
    required = ("politician_id", "name", "level", "state", "district", "chamber", "sources")
    print("\n=== VERIFICATION ===")
    for xx in sorted(files):
        data = json.loads(files[xx].read_text())
        pols = data["politicians"]
        total += len(pols)
        pids = [p["politician_id"] for p in pols]
        if len(pids) != len(set(pids)):
            print(f"  FAIL {xx}: duplicate politician_ids")
            ok = False
        for p in pols:
            missing = [f for f in required if not p.get(f)]
            if missing:
                print(f"  FAIL {xx}: {p.get('politician_id')} missing {missing}")
                ok = False
                break
        print(f"  {xx}: {len(pols)}")
    print(f"  TOTAL: {total}")
    if total < 7000:
        print(f"  FAIL: total {total} < 7000")
        ok = False
    # TX summary
    if "tx" in files:
        tx = json.loads(files["tx"].read_text())["politicians"]
        upper = sum(1 for p in tx if p["chamber"] == "upper")
        lower = sum(1 for p in tx if p["chamber"] == "lower")
        print(f"  TX: {len(tx)} total ({upper} upper / {lower} lower)")
        if not 170 <= len(tx) <= 181:
            print("  WARN: TX count outside expected ~181")
    print(f"  VERIFY: {'PASS' if ok else 'FAIL'}")
    return ok


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(timezone.utc).isoformat()
    written: dict[str, Path] = {}
    failed: list[tuple[str, str]] = []

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(process_state, xx, name): xx for xx, name in STATES.items()}
        for fut in as_completed(futures):
            xx, records, err = fut.result()
            if err:
                print(f"SKIP {xx}: {err}")
                failed.append((xx, err))
                continue
            out = {
                "generated_at": generated_at,
                "source": BASE_URL.format(xx=xx),
                "state": xx.upper(),
                "politicians": records,
            }
            path = OUT_DIR / f"{xx}.json"
            path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
            written[xx] = path
            print(f"wrote {xx}: {len(records)}")

    print(f"\nFiles written: {len(written)}  Failed states: {[f'{x} ({e})' for x, e in failed] or 'none'}")
    ok = verify(written)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
