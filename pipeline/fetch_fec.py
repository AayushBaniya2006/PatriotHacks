#!/usr/bin/env python3
"""
Fetch TX federal candidates (House + Senate, 2026 election) and their campaign
finance totals from the OpenFEC API. Writes data/tx/raw/fec.json.

Rerunnable. Uses FEC_API_KEY from .env if present, else DEMO_KEY.
Budget: bulk requests only (per_page=100, paginate as needed) — keep total
requests under ~12 since DEMO_KEY is shared/rate-limited across agents.
"""
import json
import os
import re
import sys
import time
import urllib.parse
from datetime import datetime, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PIPELINE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(REPO_ROOT, ".env")
OUT_PATH = os.path.join(REPO_ROOT, "data", "tx", "raw", "fec.json")

if PIPELINE_DIR not in sys.path:
    sys.path.insert(0, PIPELINE_DIR)
from lib_fetch import DriftError, expect_keys, get_with_retry  # noqa: E402

BASE = "https://api.open.fec.gov/v1"
ELECTION_YEAR = 2026
STATE = "TX"


def load_api_key():
    key = None
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH) as f:
            for line in f:
                line = line.strip()
                if line.startswith("FEC_API_KEY="):
                    key = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    return key or "DEMO_KEY"


API_KEY = load_api_key()
REQUEST_COUNT = 0
REQUEST_BUDGET = 12


def api_get(path, params, max_retries=3):
    """GET path with retry+backoff. Transport is pipeline/lib_fetch.get_with_retry
    (stdlib urllib, single attempt per call: retries=1, backoff=0) wrapped in the
    *same* outer budget-checked retry loop the original code used, so per-attempt
    request-budget accounting and sleep timing are unchanged. A schema-drift
    check (expect_keys) runs at the JSON parse boundary, right after the body
    is decoded."""
    global REQUEST_COUNT
    params = dict(params)
    params["api_key"] = API_KEY
    url = f"{BASE}{path}?{urllib.parse.urlencode(params)}"
    last_err = None
    for attempt in range(max_retries):
        if REQUEST_COUNT >= REQUEST_BUDGET:
            raise RuntimeError(f"Request budget of {REQUEST_BUDGET} exceeded; stopping.")
        REQUEST_COUNT += 1
        try:
            result = get_with_retry(
                url, retries=1, backoff=0, timeout=20, user_agent="patriothacks-fetch-fec/1.0"
            )
            data = json.loads(result.body.decode("utf-8"))
            expect_keys(data, f"FEC {path} response", ["results", "pagination"])
            return data
        except DriftError:
            # Schema drift is a shape problem, not a transient network problem --
            # retrying gets the same (wrong) shape again, so fail immediately and
            # loudly rather than burn the request budget re-fetching it.
            raise
        except Exception as e:
            last_err = e
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Failed GET {path} params={params}: {last_err}")


def fetch_all_pages(path, params, max_pages=3):
    """Paginate a candidates-style endpoint. Returns concatenated results list."""
    all_results = []
    page = 1
    while page <= max_pages:
        p = dict(params)
        p["page"] = page
        data = api_get(path, p)
        results = data.get("results", [])
        all_results.extend(results)
        pagination = data.get("pagination", {})
        expect_keys(pagination, f"FEC {path} pagination (page {page})", ["pages"])
        total_pages = pagination.get("pages", 1)
        if page >= total_pages:
            break
        page += 1
    return all_results


SUFFIX_RE = re.compile(r"\b(JR|SR|II|III|IV|V)\.?\b\s*$", re.IGNORECASE)


def normalize_name(name_raw):
    """'LAST, FIRST MIDDLE SUFFIX' -> 'First Middle Last' (title-cased, suffix stripped)."""
    if not name_raw:
        return name_raw
    name = name_raw.strip()
    if "," in name:
        last, _, rest = name.partition(",")
        rest = rest.strip()
        rest = SUFFIX_RE.sub("", rest).strip()
        last = last.strip()
        full = f"{rest} {last}".strip()
    else:
        full = SUFFIX_RE.sub("", name).strip()
    # Title-case each word, preserving hyphens/apostrophes reasonably
    words = full.split()
    titled = []
    for w in words:
        if "-" in w:
            titled.append("-".join(part.capitalize() for part in w.split("-")))
        elif "'" in w:
            titled.append("'".join(part.capitalize() for part in w.split("'")))
        else:
            titled.append(w.capitalize())
    return " ".join(titled)


PARTY_MAP = {
    "DEM": "Democratic",
    "REP": "Republican",
    "LIB": "Libertarian",
    "GRN": "Green",
    "GRE": "Green",  # FEC API actually codes Green Party as GRE, not GRN
}


def normalize_party(party_code):
    if not party_code:
        return party_code
    return PARTY_MAP.get(party_code.upper(), party_code)


def normalize_district(office, district_raw):
    if office != "H":
        return None
    if district_raw is None:
        return None
    try:
        num = int(str(district_raw).strip())
    except ValueError:
        return None
    if num == 0:
        return None  # at-large edge case, TX doesn't have this but guard anyway
    return f"TX-{num:02d}"


def fetch_candidates(office):
    return fetch_all_pages(
        "/candidates/",
        {
            "state": STATE,
            "office": office,
            "election_year": ELECTION_YEAR,
            "per_page": 100,
        },
        max_pages=3,
    )


def fetch_totals(office):
    return fetch_all_pages(
        "/candidates/totals/",
        {
            "state": STATE,
            "office": office,
            "election_year": ELECTION_YEAR,
            "per_page": 100,
        },
        max_pages=3,
    )


def main():
    as_of = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    candidates_by_id = {}
    counts = {"H": 0, "S": 0}
    activity_counts = {"H": 0, "S": 0}

    for office in ("H", "S"):
        cands = fetch_candidates(office)
        for c in cands:
            cid = c.get("candidate_id")
            if not cid:
                continue
            name_raw = c.get("name")
            candidates_by_id[cid] = {
                "fec_candidate_id": cid,
                "name_raw": name_raw,
                "name": normalize_name(name_raw),
                "party": normalize_party(c.get("party")),
                "office": office,
                "district": normalize_district(office, c.get("district")),
                "incumbent_challenge": c.get("incumbent_challenge_full") or c.get("incumbent_challenge"),
                "candidate_status": c.get("candidate_status"),
                "has_activity": False,
                "receipts": None,
                "disbursements": None,
                "cash_on_hand": None,
                "as_of": as_of,
                "source": f"https://www.fec.gov/data/candidate/{cid}/",
            }
        counts[office] = len(cands)

    for office in ("H", "S"):
        totals = fetch_totals(office)
        for t in totals:
            cid = t.get("candidate_id")
            if not cid:
                continue
            receipts = t.get("receipts")
            disbursements = t.get("disbursements")
            cash = t.get("last_cash_on_hand_end_period")
            if cid not in candidates_by_id:
                # totals for a candidate not present in candidates/ pull (shouldn't
                # normally happen since both filtered same way) — skip, we only
                # want candidates already collected above to keep schema consistent.
                continue
            candidates_by_id[cid]["receipts"] = receipts
            candidates_by_id[cid]["disbursements"] = disbursements
            candidates_by_id[cid]["cash_on_hand"] = cash
            if receipts is not None and receipts > 0:
                candidates_by_id[cid]["has_activity"] = True
                activity_counts[office] += 1

    candidates_list = list(candidates_by_id.values())
    candidates_list.sort(key=lambda c: (c["office"], c["district"] or "", c["name"] or ""))

    out = {"candidates": candidates_list}

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump(out, f, indent=2)

    print(f"Requests used: {REQUEST_COUNT}/{REQUEST_BUDGET}")
    print(f"House candidates: {counts['H']} (with activity: {activity_counts['H']})")
    print(f"Senate candidates: {counts['S']} (with activity: {activity_counts['S']})")
    print(f"Total candidates written: {len(candidates_list)}")
    print(f"Output: {OUT_PATH}")


if __name__ == "__main__":
    main()
