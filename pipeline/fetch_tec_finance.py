#!/usr/bin/env python3
"""
fetch_tec_finance.py

Fills the campaign-finance gap for TX STATEWIDE candidates (district == null
in data/tx/candidates.json) using the Texas Ethics Commission's (TEC) bulk
campaign-finance CSV export -- WITHOUT downloading the ~1.02GB archive.

SOURCE (verified live 2026-07-03 via HEAD: HTTP 200, content-type
application/zip, content-length 1,022,628,632 bytes, accept-ranges: bytes):
    https://dv2dphbeckkgm.cloudfront.net/TEC_CF_CSV.zip
also reachable via https://prd.tecprd.ethicsefile.com/public/cf/public/TEC_CF_CSV.zip
(301 -> the CloudFront URL above). The originally-documented
https://www.ethics.state.tx.us/data/search/cf/TEC_CF_CSV.zip 404s as of this
writing -- kept first in TEC_ZIP_URLS in case TEC restores the redirect.
Schema doc: https://www.ethics.state.tx.us/data/search/cf/CFS-ReadMe.txt

METHOD (no full download): HTTPRangeFile below is a minimal seekable
file-like object backed by HTTP Range requests, handed directly to stdlib
zipfile.ZipFile. zipfile reads only the central directory (near the end of
the archive) to find each member's offset/size, then we issue exactly one
additional ranged GET per target member covering just its compressed byte
span (primed into the object's cache so zipfile's own decompression read
loop costs zero further requests). Verified live: extracted cover.csv
(412,423 data rows) + cand.csv (253,183 data rows) -- about 34MB of ranged
GETs total across 6 HTTP requests in ~3s, instead of downloading the full
1.02GB archive.

We fetch both cover.csv and cand.csv per the original task spec, but only
cover.csv (CoverSheet1Data / record type CVR1 -- one row per filed report,
carrying filerIdent, filerName, totalContribAmount, totalExpendAmount,
contribsMaintainedAmount, periodEndDt, electionDt, seek/hold office) is
actually used for matching. cand.csv (CandidateData / record type CAND) is
fetched-but-unused: on inspection its rows are candidates who BENEFITED from
a THIRD PARTY's direct campaign expenditure, not a filer's own committee
totals -- structurally irrelevant to "this candidate's own receipts/
disbursements/cash on hand". Noted here rather than silently dropped.

MATCHING: normalizes TEC filerNameLast/filerNameFirst (uppercase, strip
accents/punctuation, take the first whitespace-token of each -- this drops
suffix tokens TEC sometimes appends to the last name, e.g. "Hinojosa Jr." ->
"HINOJOSA", and middle names/initials TEC appends to the first name, e.g.
"Vikki A." -> "VIKKI") and compares against each target candidate's `name`
field (first token = first name, last token = last name -- does not handle
hyphenated surnames or suffixes in candidates.json; none of the current 22
statewide targets need it, flagged here for future maintainers). A small,
well-known nickname table (Pat/Patrick, Mike/Michael, ...) is applied
automatically in both directions.

A candidate/officeholder-shaped filerTypeCd is required: COH, JCOH, or SCC
(the last is TEC's code for a filer whose CTA later converted to a plain COH
candidate committee -- several of our targets, e.g. Dixon and French, show
this exact SCC -> COH transition over their filing history; PAC and
party-committee codes GPAC/MPAC/SPAC/CEC/PTYCORP/JSPC/LEG/DCE/SPK/ASIFSPAC/
SCPC are excluded). A filer must be the UNIQUE such filer under the
(normalized last, normalized/nickname first) key. If more than one filer
qualifies, we narrow to whichever has a report with electionDt in 2026 (the
task's specified tie-break); if that still leaves 0 or >1, or if 0 qualify
in the first place, the candidate is logged as AMBIGUOUS or NO MATCH and
skipped entirely -- never guessed.

Two candidates required a documented MANUAL_OVERRIDE because their TEC-filed
first name is neither identical nor a standard nickname of their public
first name (Gina/Regina Hinojosa, Mayes/"David M." Middleton). Each override
below carries the full evidence trail used to resolve it (matching
office-held district + office-sought transition timing + financial-scale
corroboration, all found in that filer's own report history) and is flagged
distinctly (as "override", not "auto") in the run log and in the written
finance block's internal bookkeeping is identical to an auto-match -- the
distinction only matters for this script's transparency, not the schema.

For each resolved candidate we take the report row with the MOST RECENT
periodEndDt (ties broken by receivedDt; rows with infoOnlyFlag=='Y'
[superseded by a later filing] are excluded whenever a non-superseded
alternative exists) and write:
    finance = {
      "receipts": totalContribAmount, "disbursements": totalExpendAmount,
      "cash_on_hand": contribsMaintainedAmount, "as_of": periodEndDt (ISO),
      "source": "https://www.ethics.state.tx.us/search/cf/",
      "filer_id": filerIdent, "basis": "per_report_period",
    }

totalContribAmount/totalExpendAmount/contribsMaintainedAmount are BigDecimal
fields using TEC's documented "Blank When Zero" (BWZ) convention (see the
Legend at the bottom of CFS-ReadMe.txt: "BWZ indicates 'Blank When Zero'") --
a blank CSV value is parsed as 0.0, not treated as missing/null. Verified
against Abbott's own Jan/Feb-2026 pre-election reports, which show a blank
totalContribAmount alongside a populated, non-zero totalExpendAmount and
noActivityFlag=='N' -- i.e. genuinely zero itemized contributions that
period, not an unfilled field.

CAVEAT that must be reflected honestly downstream: TEC cover-sheet totals
are PER REPORT PERIOD (e.g. a ~40-day pre-election window), not full-cycle
aggregates -- hence "basis": "per_report_period" on every finance block this
script writes. Downstream insight text must not describe these numbers as
"raised this cycle" the way a cycle-to-date FEC total would be.

Only ever ADDS a finance{} block to a candidate that doesn't already have
one -- never touches Paxton/Talarico's existing FEC-sourced finance blocks
(those are federal US Senate candidates, out of scope here; they're simply
skipped by the same "already has finance" filter). Idempotent: once every
resolvable target candidate has a finance block, a rerun fetches nothing and
exits immediately. Writes data/tx/candidates.json atomically (temp file +
os.replace), matching the convention in pipeline/score_quality.py and
pipeline/import_civicmatch_positions.py.

Rerun: python3 pipeline/fetch_tec_finance.py
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import sys
import tempfile
import unicodedata
import zipfile
from pathlib import Path
from typing import Any, Optional

import requests

ROOT = Path(__file__).resolve().parent.parent
PIPELINE_DIR = Path(__file__).resolve().parent
if str(PIPELINE_DIR) not in sys.path:
    sys.path.insert(0, str(PIPELINE_DIR))
from lib_fetch import expect_keys, retry_call  # noqa: E402

CANDIDATES_PATH = ROOT / "data" / "tx" / "candidates.json"

# Tried in order; first one that responds 200 with Accept-Ranges: bytes wins.
TEC_ZIP_URLS = [
    "https://www.ethics.state.tx.us/data/search/cf/TEC_CF_CSV.zip",
    "https://prd.tecprd.ethicsefile.com/public/cf/public/TEC_CF_CSV.zip",
    "https://dv2dphbeckkgm.cloudfront.net/TEC_CF_CSV.zip",
]
# Fixed citation URL per task spec (the human-navigable TEC filer search page,
# not the bulk-zip URL, which is not a stable thing to cite per-candidate).
FINANCE_SOURCE_URL = "https://www.ethics.state.tx.us/search/cf/"

MEMBERS_TO_FETCH = ["cover.csv", "cand.csv"]  # cand.csv fetched-but-unused, see module docstring
REQUEST_TIMEOUT = 30
TAIL_WINDOW = 2 * 1024 * 1024  # 2MB tail read to find EOCD + central directory in one shot

# Every cover.csv column this script actually reads (see build_filer_index,
# build_fid_index, most_recent_row, resolve_candidate, and the finance-block
# assembly in main). Checked against the live header at the parse boundary
# (load_cover_rows) via lib_fetch.expect_keys -- if TEC ever renames one of
# these, we want a loud DriftError naming it, not a filer index silently
# built from a column that always comes back empty/missing.
REQUIRED_COVER_COLUMNS = [
    "filerIdent",
    "filerName",
    "filerNameFirst",
    "filerNameLast",
    "filerTypeCd",
    "filerSeekOfficeCd",
    "periodEndDt",
    "receivedDt",
    "electionDt",
    "infoOnlyFlag",
    "totalContribAmount",
    "totalExpendAmount",
    "contribsMaintainedAmount",
]

# Candidate/officeholder-shaped filer types; excludes PAC & party-committee codes.
ALLOWED_FILER_TYPES = {"COH", "JCOH", "SCC"}

# Small, well-known nickname table used only for automatic first-name matching.
# Each key maps to the set of formal first names it is standard shorthand for.
NICKNAMES: dict[str, set[str]] = {
    "PAT": {"PATRICK", "PATRICIA"},
    "MIKE": {"MICHAEL"},
    "NATE": {"NATHAN", "NATHANIEL"},
    "TOM": {"THOMAS"},
    "DON": {"DONALD"},
    "JENN": {"JENNIFER"},
    "JEN": {"JENNIFER"},
    "BEN": {"BENJAMIN"},
    "BOB": {"ROBERT"},
    "BILL": {"WILLIAM"},
    "DICK": {"RICHARD"},
    "JIM": {"JAMES"},
    "DAVE": {"DAVID"},
    "DAN": {"DANIEL"},
    "GREG": {"GREGORY"},
    "STEVE": {"STEVEN", "STEPHEN"},
    "JOE": {"JOSEPH"},
    "CHRIS": {"CHRISTOPHER"},
    "MATT": {"MATTHEW"},
}

# Documented exceptions: TEC-filed first name is neither identical to nor a
# standard nickname of the candidate's public first name. See module
# docstring section "MANUAL_OVERRIDE" for the shared rationale shape; each
# entry's "evidence" is the specific corroboration found in that filer's own
# cover.csv report history (district match + office-sought transition timing
# + financial-scale consistency) -- never a bare name guess.
MANUAL_OVERRIDES = {
    "hinojosa-gina": {
        "filer_id": "00080440",
        "evidence": (
            "TEC filerName='Hinojosa, Regina (Ms.)' ('Gina' is a common nickname for the "
            "legal first name 'Regina', not in our automatic nickname table). Verified via "
            "filerIdent 00080440's full report history: (1) filerHoldOfficeDistrict=49 "
            "matches our sourced bio 'state representative from the 49th district' exactly "
            "across every report since 2016; (2) filerSeekOfficeCd transitions from STATEREP "
            "to GOVERNOR starting with the report period ending 2025-12-31 -- exactly when a "
            "2026 gubernatorial campaign would be expected to launch; (3) totalContribAmount "
            "jumps from $4,366 (last STATEREP-period report, 2025-06-30) to $1,038,189 (first "
            "GOVERNOR-period report) and stays in that range through the most recent report. "
            "No other Hinojosa filer in cover.csv has seekOffice=GOVERNOR."
        ),
    },
    "middleton-mayes": {
        "filer_id": "00081727",
        "evidence": (
            "TEC filerName='Middleton II, David M. (Mr.)' -- our candidate 'Mayes Middleton' "
            "appears to go publicly by his middle name ('M.' = Mayes), not caught by "
            "first-name/nickname matching since 'David' != 'Mayes'. Verified via filerIdent "
            "00081727's full report history: (1) filerHoldOfficeDistrict=11 matches our "
            "sourced bio 'state senator from the 11th district' exactly; (2) filerSeekOfficeCd "
            "transitions STATEREP(d23) -> STATESEN(d11) -> ATTYGEN starting with the report "
            "period ending 2025-06-30, matching his known State-Rep -> State-Senate -> "
            "AG-candidate career path and our target office 'Attorney General of Texas' "
            "exactly; (3) totalContribAmount jumps from ~$267,527 (last STATESEN-period "
            "report, 2024) to $11,819,527+ (first ATTYGEN-period report), consistent with a "
            "well-funded statewide AG campaign. No other Middleton filer has seekOffice=ATTYGEN."
        ),
    },
}


# ---------------------------------------------------------------------------
# Seekable-over-HTTP-Range file object
# ---------------------------------------------------------------------------


class HTTPRangeFile(io.RawIOBase):
    """A read-only, seekable file-like object backed by HTTP Range requests.

    Good enough for zipfile.ZipFile: implements seek/tell/readinto with a
    single-window read-ahead cache so zipfile's small, scattered reads while
    parsing the central directory collapse into one HTTP request per
    distinct region of the file actually touched (see `prime` for how member
    extraction pins the cache to exactly the bytes needed, avoiding zipfile's
    default small-chunk read loop from spraying requests during decompress).
    """

    def __init__(self, url: str, session: requests.Session, size: int, timeout: int = REQUEST_TIMEOUT):
        self.url = url
        self.session = session
        self.size = size
        self.timeout = timeout
        self.pos = 0
        self._buf_start = 0
        self._buf = b""
        self.request_count = 0
        self.bytes_fetched = 0

    def seekable(self) -> bool:
        return True

    def readable(self) -> bool:
        return True

    def seek(self, offset: int, whence: int = 0) -> int:
        if whence == 0:
            self.pos = offset
        elif whence == 1:
            self.pos += offset
        elif whence == 2:
            self.pos = self.size + offset
        else:
            raise ValueError(f"bad whence {whence}")
        return self.pos

    def tell(self) -> int:
        return self.pos

    def _fetch_range(self, start: int, end: int) -> bytes:
        end = min(end, self.size - 1)
        headers = {"Range": f"bytes={start}-{end}"}

        def _do() -> bytes:
            resp = self.session.get(self.url, headers=headers, timeout=self.timeout)
            resp.raise_for_status()
            if resp.status_code != 206:
                raise RuntimeError(f"expected 206 Partial Content, got {resp.status_code} for {self.url}")
            return resp.content

        # Transport: same requests.Session (needed for the Range header +
        # connection reuse the whole HTTPRangeFile design depends on) but the
        # retry/backoff loop itself now comes from pipeline/lib_fetch.py so a
        # transient blip on one ranged GET doesn't kill the whole run.
        content = retry_call(_do, retries=3, backoff=1.5)
        self.request_count += 1
        self.bytes_fetched += len(content)
        return content

    def prime(self, start: int, data: bytes) -> None:
        """Pre-populate the cache with an exact byte range fetched separately."""
        self._buf_start = start
        self._buf = data

    def readinto(self, b) -> int:
        n = len(b)
        if n == 0 or self.pos >= self.size:
            return 0
        if self._buf_start <= self.pos and self.pos + n <= self._buf_start + len(self._buf):
            off = self.pos - self._buf_start
            chunk = self._buf[off : off + n]
        else:
            fetch_len = max(n, TAIL_WINDOW)
            data = self._fetch_range(self.pos, self.pos + fetch_len - 1)
            self._buf_start = self.pos
            self._buf = data
            chunk = data[:n]
        b[: len(chunk)] = chunk
        self.pos += len(chunk)
        return len(chunk)


def open_tec_zip() -> tuple[zipfile.ZipFile, HTTPRangeFile, str]:
    """Locate a working TEC bulk-zip URL and return an open ZipFile over it
    without downloading the archive body."""
    session = requests.Session()
    last_err: Optional[Exception] = None
    for url in TEC_ZIP_URLS:
        try:
            head = session.head(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
            if head.status_code != 200:
                last_err = RuntimeError(f"{url} -> HTTP {head.status_code}")
                continue
            if head.headers.get("Accept-Ranges", "").lower() != "bytes":
                last_err = RuntimeError(f"{url} does not advertise Accept-Ranges: bytes")
                continue
            size = int(head.headers["Content-Length"])
            rf = HTTPRangeFile(head.url, session, size)
            tail_start = max(0, size - TAIL_WINDOW)
            tail_data = rf._fetch_range(tail_start, size - 1)
            rf.prime(tail_start, tail_data)
            zf = zipfile.ZipFile(rf)
            return zf, rf, head.url
        except Exception as exc:  # noqa: BLE001 - we deliberately try the next URL
            last_err = exc
            continue
    raise RuntimeError(
        f"Could not open the TEC bulk zip from any of {TEC_ZIP_URLS!r}. "
        f"Per the task spec, the full-archive fallback download only applies if member "
        f"extraction is flaky after ~10min of retrying; all {len(TEC_ZIP_URLS)} known URLs "
        f"failed outright instead, which is a different failure mode -- stopping here rather "
        f"than silently downloading ~1.02GB. Last error: {last_err!r}"
    )


def extract_member_text(zf: zipfile.ZipFile, rf: HTTPRangeFile, name: str) -> io.TextIOWrapper:
    """Range-fetch exactly one zip member's compressed span, prime the cache
    with it, and return a streaming decoded text handle (decompression still
    happens lazily as the caller iterates -- nothing is materialized here)."""
    info = zf.getinfo(name)
    start = info.header_offset
    end = info.header_offset + info.compress_size + 2048  # local-header slack
    data = rf._fetch_range(start, end)
    rf.prime(start, data)
    raw = zf.open(name)
    return io.TextIOWrapper(raw, encoding="utf-8", newline="")


# ---------------------------------------------------------------------------
# Name normalization + matching
# ---------------------------------------------------------------------------


def normalize_name(s: Optional[str]) -> str:
    s = s or ""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip().upper()
    return s


def first_token(s: Optional[str]) -> str:
    norm = normalize_name(s)
    return norm.split(" ")[0] if norm else ""


def last_name_token(s: Optional[str]) -> str:
    """First token of the normalized last-name field, dropping any suffix
    TEC appended directly onto the surname (e.g. 'Hinojosa Jr.' -> 'HINOJOSA',
    'Collier II' -> 'COLLIER')."""
    norm = normalize_name(s)
    tok = norm.split(" ")[0] if norm else ""
    return tok


def names_match(candidate_first: str, filer_first_field: str) -> bool:
    filer_tok = first_token(filer_first_field)
    cand_tok = normalize_name(candidate_first).split(" ")[0] if candidate_first else ""
    if not cand_tok or not filer_tok:
        return False
    if cand_tok == filer_tok:
        return True
    if filer_tok in NICKNAMES.get(cand_tok, set()):
        return True
    if cand_tok in NICKNAMES.get(filer_tok, set()):
        return True
    return False


def split_candidate_name(full_name: str) -> tuple[str, str]:
    tokens = full_name.split()
    if not tokens:
        return "", ""
    return tokens[0], tokens[-1]


# ---------------------------------------------------------------------------
# cover.csv indexing + per-filer most-recent-report selection
# ---------------------------------------------------------------------------


def load_cover_rows(
    text_handle: io.TextIOWrapper,
    required_keys: Optional[list[str]] = None,
    path_desc: str = "csv",
) -> list[dict]:
    reader = csv.DictReader(text_handle)
    if required_keys is not None:
        expect_keys(reader.fieldnames or [], f"TEC {path_desc} header", required_keys)
    return list(reader)


def build_filer_index(rows: list[dict]) -> dict[str, dict[str, dict]]:
    """last_name_token -> filerIdent -> {"firsts": set(), "types": set(), "rows": [...]}"""
    index: dict[str, dict[str, dict]] = {}
    for row in rows:
        last_tok = last_name_token(row.get("filerNameLast"))
        if not last_tok:
            continue
        fid = row.get("filerIdent", "").strip()
        if not fid:
            continue
        bucket = index.setdefault(last_tok, {})
        entry = bucket.setdefault(fid, {"firsts": set(), "types": set(), "rows": []})
        entry["firsts"].add(first_token(row.get("filerNameFirst")))
        entry["types"].add((row.get("filerTypeCd") or "").strip())
        entry["rows"].append(row)
    return index


def build_fid_index(rows: list[dict]) -> dict[str, list[dict]]:
    by_fid: dict[str, list[dict]] = {}
    for row in rows:
        fid = row.get("filerIdent", "").strip()
        if fid:
            by_fid.setdefault(fid, []).append(row)
    return by_fid


def most_recent_row(rows: list[dict]) -> dict:
    non_superseded = [r for r in rows if (r.get("infoOnlyFlag") or "").strip().upper() != "Y"]
    pool = non_superseded if non_superseded else rows
    return max(pool, key=lambda r: ((r.get("periodEndDt") or ""), (r.get("receivedDt") or "")))


def parse_amount(raw: Optional[str]) -> float:
    """BigDecimal field using TEC's 'Blank When Zero' convention (see
    CFS-ReadMe.txt Legend) -- blank means 0.0, not missing."""
    raw = (raw or "").strip()
    if not raw:
        return 0.0
    return round(float(raw), 2)


def iso_date(yyyymmdd: Optional[str]) -> Optional[str]:
    s = (yyyymmdd or "").strip()
    if len(s) != 8 or not s.isdigit():
        return None
    return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"


def resolve_candidate(
    candidate_id: str,
    cand: dict,
    last_index: dict[str, dict[str, dict]],
    fid_index: dict[str, list[dict]],
    log: list[str],
) -> Optional[dict]:
    if candidate_id in MANUAL_OVERRIDES:
        override = MANUAL_OVERRIDES[candidate_id]
        fid = override["filer_id"]
        rows = fid_index.get(fid)
        if not rows:
            log.append(f"OVERRIDE-FAILED {candidate_id}: filer_id {fid} not found in cover.csv this run")
            return None
        log.append(f"OVERRIDE {candidate_id} -> filerIdent {fid}. Evidence: {override['evidence']}")
        return {"filer_id": fid, "row": most_recent_row(rows)}

    first, last = split_candidate_name(cand["name"])
    last_tok = last_name_token(last)
    bucket = last_index.get(last_tok, {})

    qualifying = [
        fid
        for fid, entry in bucket.items()
        if (entry["types"] & ALLOWED_FILER_TYPES) and any(names_match(first, f) for f in entry["firsts"])
    ]

    if len(qualifying) > 1:
        # Task-specified tie-break: prefer a filer with a report electionDt in 2026.
        narrowed = [
            fid
            for fid in qualifying
            if any((r.get("electionDt") or "").startswith("2026") for r in bucket[fid]["rows"])
        ]
        if len(narrowed) == 1:
            qualifying = narrowed
            log.append(
                f"TIE-BREAK {candidate_id} ({cand['name']}): {len(qualifying)} candidate/officeholder "
                f"filers matched '{first} {last}', narrowed to 1 via electionDt-in-2026"
            )

    if len(qualifying) == 0:
        log.append(f"NO MATCH {candidate_id} ({cand['name']}, {cand.get('office')}): no COH/JCOH/SCC filer named '{first} {last}' found in cover.csv")
        return None
    if len(qualifying) > 1:
        detail = ", ".join(f"{fid}:{sorted(bucket[fid]['firsts'])}" for fid in qualifying)
        log.append(
            f"AMBIGUOUS {candidate_id} ({cand['name']}, {cand.get('office')}): {len(qualifying)} filers "
            f"qualify under last name '{last_tok}' matching first name '{first}' -- {detail} -- skipped, no guess made"
        )
        return None

    fid = qualifying[0]
    row = most_recent_row(bucket[fid]["rows"])
    log.append(
        f"MATCHED {candidate_id} ({cand['name']}, {cand.get('office')}) -> filerIdent {fid} "
        f"(filerName='{row.get('filerName')}', filerTypeCd seen={sorted(bucket[fid]['types'])}, "
        f"most-recent periodEndDt={row.get('periodEndDt')}, seekOffice={row.get('filerSeekOfficeCd')})"
    )
    return {"filer_id": fid, "row": row}


# ---------------------------------------------------------------------------
# Atomic JSON write (matches pipeline/score_quality.py convention)
# ---------------------------------------------------------------------------


def atomic_write_json(path: Path, data: Any) -> None:
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.stem}.", suffix=".json.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    with open(CANDIDATES_PATH, encoding="utf-8") as f:
        candidates = json.load(f)

    targets = {
        cid: c for cid, c in candidates.items() if c.get("district") is None and not c.get("finance")
    }

    print(f"Statewide candidates needing finance: {len(targets)}")
    if not targets:
        print("Nothing to do -- every statewide (district==null) candidate already has a finance block.")
        return 0
    for cid in targets:
        print(f"  - {cid}: {targets[cid]['name']} ({targets[cid].get('office')})")

    print("\nOpening TEC bulk zip via HTTP range requests (no full download)...")
    zf, rf, resolved_url = open_tec_zip()
    print(f"  resolved URL: {resolved_url}")
    print(f"  archive size: {rf.size:,} bytes ({rf.size/1e9:.3f} GB)")
    names = zf.namelist()
    print(f"  central directory parsed: {len(names)} members, {rf.request_count} HTTP requests so far")

    cover_rows: list[dict] = []
    for member in MEMBERS_TO_FETCH:
        match = next((n for n in names if n.lower().endswith(member)), None)
        if not match:
            print(f"  WARNING: no member matching '{member}' found in archive namelist -- skipping")
            continue
        text = extract_member_text(zf, rf, match)
        required = REQUIRED_COVER_COLUMNS if member == "cover.csv" else None
        rows = load_cover_rows(text, required_keys=required, path_desc=match)
        print(f"  extracted {match}: {len(rows)} data rows ({rf.request_count} total HTTP requests, "
              f"{rf.bytes_fetched/1e6:.1f}MB fetched so far)")
        if member == "cover.csv":
            cover_rows = rows

    print(f"\nTotal: {rf.request_count} HTTP requests, {rf.bytes_fetched/1e6:.1f}MB fetched "
          f"(vs {rf.size/1e6:.1f}MB full archive)")

    last_index = build_filer_index(cover_rows)
    fid_index = build_fid_index(cover_rows)

    log: list[str] = []
    updated = 0
    for cid, cand in targets.items():
        result = resolve_candidate(cid, cand, last_index, fid_index, log)
        if result is None:
            continue
        row = result["row"]
        finance = {
            "receipts": parse_amount(row.get("totalContribAmount")),
            "disbursements": parse_amount(row.get("totalExpendAmount")),
            "cash_on_hand": parse_amount(row.get("contribsMaintainedAmount")),
            "as_of": iso_date(row.get("periodEndDt")),
            "source": FINANCE_SOURCE_URL,
            "filer_id": result["filer_id"],
            "basis": "per_report_period",
        }
        candidates[cid]["finance"] = finance
        updated += 1

    print("\n=== Match log ===")
    for line in log:
        print(line)

    matched = sum(1 for l in log if l.startswith("MATCHED") or l.startswith("OVERRIDE "))
    ambiguous = sum(1 for l in log if l.startswith("AMBIGUOUS"))
    no_match = sum(1 for l in log if l.startswith("NO MATCH"))
    print(f"\nSummary: {matched} matched, {ambiguous} ambiguous, {no_match} no-match, out of {len(targets)} targets")

    if updated == 0:
        print("\nNo candidates resolved -- candidates.json left untouched.")
        return 0

    atomic_write_json(CANDIDATES_PATH, candidates)
    print(f"\nWrote {updated} new finance block(s) to {CANDIDATES_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
