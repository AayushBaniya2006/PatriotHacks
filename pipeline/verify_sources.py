#!/usr/bin/env python3
"""
pipeline/verify_sources.py

Source-link health checker + (optional) fixer for the gold dataset.

The product's core promise is "every claim is cited." This script is the
enforcement mechanism: it finds every distinct source URL referenced from
data/tx/candidates.json, data/tx/races.json, and data/tx/insights/*.json,
HTTP-checks each one, classifies it, and (with --fix) repairs what can be
safely and verifiably repaired -- never by deleting a claim, only by
correcting or annotating its citation.

COLLECTION
----------
A source URL is any string value found anywhere in the three JSON sources
under a dict key named "source" (singular), or any string entry inside a
list value under a dict key named "sources" (plural). This is a generic
recursive walk (not a hardcoded set of paths) so it naturally covers every
shape the schema currently uses -- candidates.json's finance.source,
record.source, record.key_votes[].source, positions[].source, top-level
sources[]; races.json's context.sources; and every insights/*.json bullet's
"source" (base/archetypes candidates[cid][] bullets and the "now"/
"long_term" horizons bullets) -- and any future field named source(s)
without needing this script to change.

CLASSIFICATION
--------------
Each distinct URL is checked HEAD-first (cheap), falling back to GET when
HEAD errors, 4xx/5xx's, or a host simply doesn't implement HEAD (405 is
common). A realistic desktop-browser User-Agent is used throughout --
deliberately different from pipeline/lib_fetch.py's DEFAULT_USER_AGENT
(which self-identifies as a bot, correct for a fetcher that harvests data).
This script instead answers "would a voter's own browser reach this page?",
so it presents as one.

  OK           -- final response is 2xx, at the URL as stored.
  REDIRECT-OK  -- final response is 2xx, but only after 1+ HTTP redirects;
                  the final URL is recorded.
  BLOCKED      -- 403/429 that persists even after retrying with a second,
                  different browser User-Agent, AND after a cross-check with
                  system `curl` (some WAFs -- confirmed empirically against
                  this exact dataset -- fingerprint at the TLS/HTTP2 client
                  level, not just the User-Agent header, so a plain curl
                  request can succeed where every httpx attempt gets 403'd;
                  when curl succeeds it settles the question, promoting the
                  result to OK/REDIRECT-OK instead). Only URLs that stay
                  blocked across ALL of that are reported "likely-live-WAF",
                  not folded into DEAD -- a WAF challenge is evidence of a
                  live server, not a dead link.
  DEAD         -- 404/410, any other definitive non-2xx/3xx status, or a
                  persistent network-level failure (timeout/connection
                  error/5xx) that survives every retry.

Retries: up to 3 attempts, but ONLY for transient outcomes (timeouts,
connection errors, 5xx) -- a definitive 200/3xx/404/410/403/429 is never
retried pointlessly. Backoff 1.5s * attempt#. Pacing: a per-host minimum
interval of 0.3s between requests, enforced even under the thread pool
(each host gets its own lock), so ~140 URLs concentrated on ~30 hosts (2/3
of them on fec.gov) never hammers one host regardless of overall
concurrency.

Known limitation: this is an HTTP-status checker, not a content checker --
a "soft 404" (200 status, page body says "not found") will read as OK. Out
of scope by design; the task's classification contract is status-code based.

OUTPUT
------
  data/tx/source_health.json -- machine-readable, every URL + classification
    + occurrences (which file/record cited it).
  data/tx/SOURCE_HEALTH.md   -- human-readable, worst-first.

FIX (--fix only; default run is read-only and safe to rerun anytime, e.g.
in CI, with zero side effects)
------------------------------
For DEAD URLs, tries -- in order, each candidate replacement independently
HTTP-verified before being accepted, NEVER fabricated:
  1. FEC candidate-page pattern: if the URL matches
     https://www.fec.gov/data/candidate/<ID>/ and the owning candidate's
     own `fec_id` field names a different ID, try that candidate's actual
     canonical FEC page.
  2. Wikipedia moved-title: ask the MediaWiki API (action=query&redirects=1)
     whether the title is a formal redirect to a different current title;
     if so, try the redirect target's URL.
  3. Mechanical www./apex and http/https variants: try toggling each; if
     exactly one variant resolves live, use it.
A verified replacement is applied EVERYWHERE that literal URL string
appears (candidates.json, races.json, every insights/*.json file) via
exact JSON-value replacement (never a blind text/regex replace), so
derived insight bullets never cite a URL that no longer matches their
candidate's own gold record (validate_marquee_insights.py /
validate_horizons.py would otherwise silently drop those bullets).

For REDIRECT-OK URLs, --canonicalize additionally rewrites the stored URL
to the final destination -- but only when the final URL's registrable
domain (eTLD, approximated as the last two labels) matches the original's,
so a same-organization www/https/path-move gets canonicalized while a
cross-domain redirect (which could indicate a sold/parked domain now
forwarding somewhere unrelated) is left alone and flagged for a human.

For DEAD URLs with no safe, verifiable replacement: the claim is NEVER
deleted. Instead, `"source_status": "unverified"` is added as a sibling key
on the smallest JSON object that owns that source (the specific position /
key_vote / finance record, or the candidate/context object itself for a
sources[] entry) in candidates.json / races.json, so the UI/insights layer
can caveat honestly later. This never changes the `source` value itself, so
existing insight bullets (matched against a candidate's own source set)
keep validating.

Every gold-data write is atomic (temp file + os.replace) and preserves each
file's original json.dumps() style (ensure_ascii / trailing newline),
auto-detected per file, so an unrelated field's formatting never churns in
the diff.

Usage:
    python3 pipeline/verify_sources.py                # check only (safe, default)
    python3 pipeline/verify_sources.py --fix           # check, fix, re-verify
    python3 pipeline/verify_sources.py --fix --canonicalize   # + rewrite REDIRECT-OK to final URL
    python3 pipeline/verify_sources.py --workers 4 --timeout 15
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

ROOT = Path(__file__).resolve().parent.parent
DATA_TX = ROOT / "data" / "tx"
CANDIDATES_PATH = DATA_TX / "candidates.json"
RACES_PATH = DATA_TX / "races.json"
INSIGHTS_DIR = DATA_TX / "insights"
HEALTH_JSON_PATH = DATA_TX / "source_health.json"
HEALTH_MD_PATH = DATA_TX / "SOURCE_HEALTH.md"

# Two distinct, realistic desktop-browser User-Agents. Intentionally NOT
# pipeline/lib_fetch.DEFAULT_USER_AGENT (a self-identifying bot string) --
# see module docstring.
PRIMARY_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
ALT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:125.0) "
    "Gecko/20100101 Firefox/125.0"
)
COMMON_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/*,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

TIMEOUT_SECONDS = 10.0
MAX_ATTEMPTS = 3  # total attempts per method, counting the first -- matches lib_fetch.py's "retries" semantics
RETRY_BACKOFF = 1.5
PACING_SECONDS = 0.3
DEFAULT_WORKERS = 8

STATUS_OK = "OK"
STATUS_REDIRECT_OK = "REDIRECT-OK"
STATUS_DEAD = "DEAD"
STATUS_BLOCKED = "BLOCKED"

TRANSIENT_EXCEPTIONS = (
    httpx.TimeoutException,
    httpx.ConnectError,
    httpx.ReadError,
    httpx.WriteError,
    httpx.RemoteProtocolError,
    httpx.PoolTimeout,
)


# ---------------------------------------------------------------------------
# Per-host polite pacing, safe under a thread pool.
# ---------------------------------------------------------------------------


class HostPacer:
    """Enforces >= min_interval seconds between successive requests to the
    same host. Each host gets its own lock (created lazily, guarded by a
    short-lived dict lock) so different hosts proceed fully in parallel
    while same-host calls -- even issued from different worker threads --
    are serialized with the pacing gap held.
    """

    def __init__(self, min_interval: float = PACING_SECONDS):
        self.min_interval = min_interval
        self._dict_lock = threading.Lock()
        self._host_locks: Dict[str, threading.Lock] = {}
        self._last_call: Dict[str, float] = {}

    def _lock_for(self, host: str) -> threading.Lock:
        with self._dict_lock:
            lock = self._host_locks.get(host)
            if lock is None:
                lock = threading.Lock()
                self._host_locks[host] = lock
            return lock

    def wait(self, host: str) -> None:
        lock = self._lock_for(host)
        with lock:
            now = time.monotonic()
            last = self._last_call.get(host)
            if last is not None:
                remaining = self.min_interval - (now - last)
                if remaining > 0:
                    time.sleep(remaining)
            self._last_call[host] = time.monotonic()


# ---------------------------------------------------------------------------
# URL collection: generic recursive walk over candidates.json / races.json /
# insights/*.json.
# ---------------------------------------------------------------------------


@dataclass
class Occurrence:
    file: str
    path: str
    candidate_id: Optional[str] = None
    race_id: Optional[str] = None

    def to_dict(self) -> dict:
        d = {"file": self.file, "path": self.path}
        if self.candidate_id:
            d["candidate_id"] = self.candidate_id
        if self.race_id:
            d["race_id"] = self.race_id
        return d


# dict keys whose value is itself a {candidate_id: ...} mapping -- descending
# into one of these attaches that candidate_id as context for everything
# beneath it (covers insights/*.json's base.candidates / archetypes.*.candidates
# / base.horizons / archetypes.*.horizons).
CANDIDATE_KEYED_CONTAINERS = {"candidates", "horizons"}


def _walk_collect(
    obj: Any,
    file_label: str,
    path: str,
    candidate_id: Optional[str],
    race_id: Optional[str],
    url_map: Dict[str, List[Occurrence]],
) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            child_path = f"{path}.{k}" if path else k
            if k == "source" and isinstance(v, str) and v.strip():
                url_map.setdefault(v, []).append(
                    Occurrence(file_label, child_path, candidate_id, race_id)
                )
            elif k == "sources" and isinstance(v, list):
                for i, u in enumerate(v):
                    if isinstance(u, str) and u.strip():
                        url_map.setdefault(u, []).append(
                            Occurrence(file_label, f"{child_path}[{i}]", candidate_id, race_id)
                        )
            elif k in CANDIDATE_KEYED_CONTAINERS and isinstance(v, dict):
                for cid, sub in v.items():
                    _walk_collect(sub, file_label, f"{child_path}.{cid}", cid, race_id, url_map)
            else:
                _walk_collect(v, file_label, child_path, candidate_id, race_id, url_map)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _walk_collect(v, file_label, f"{path}[{i}]", candidate_id, race_id, url_map)
    # scalars: nothing to do


def collect_source_urls() -> Dict[str, List[Occurrence]]:
    url_map: Dict[str, List[Occurrence]] = {}

    candidates = load_json(CANDIDATES_PATH)
    for cid, cand in candidates.items():
        _walk_collect(cand, "data/tx/candidates.json", cid, cid, None, url_map)

    races_doc = load_json(RACES_PATH)
    for r in races_doc.get("races", []):
        rid = r.get("race_id")
        _walk_collect(r, "data/tx/races.json", rid or "", None, rid, url_map)

    for fn in sorted(os.listdir(INSIGHTS_DIR)):
        if not fn.endswith(".json"):
            continue
        doc = load_json(INSIGHTS_DIR / fn)
        rid = doc.get("race_id", fn[: -len(".json")])
        _walk_collect(doc, f"data/tx/insights/{fn}", "", None, rid, url_map)

    return url_map


# ---------------------------------------------------------------------------
# JSON I/O that preserves each file's original formatting style exactly, so
# a fix only ever diffs the fields it actually touched.
# ---------------------------------------------------------------------------


def load_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _detect_style(original_text: str, obj: Any) -> Tuple[bool, bool]:
    """Returns (ensure_ascii, trailing_newline) such that re-serializing the
    UNCHANGED obj with that style reproduces original_text byte-for-byte, if
    such a combination exists among the two styles this repo's pipeline
    scripts actually use (indent=2, ensure_ascii True or False, optional
    trailing newline). Falls back to (False, original ends with newline) --
    the most content-preserving default -- if no combination matches exactly
    (e.g. the file was hand-edited); this only widens the diff for that one
    file, it never corrupts data.
    """
    for ensure_ascii in (True, False):
        s = json.dumps(obj, indent=2, ensure_ascii=ensure_ascii)
        if s == original_text:
            return ensure_ascii, False
        if s + "\n" == original_text:
            return ensure_ascii, True
    return False, original_text.endswith("\n")


def load_json_with_style(path: Path) -> Tuple[Any, str, Tuple[bool, bool]]:
    original_text = path.read_text(encoding="utf-8")
    obj = json.loads(original_text)
    style = _detect_style(original_text, obj)
    return obj, original_text, style


def dump_with_style(obj: Any, style: Tuple[bool, bool]) -> str:
    ensure_ascii, trailing_newline = style
    s = json.dumps(obj, indent=2, ensure_ascii=ensure_ascii)
    if trailing_newline:
        s += "\n"
    return s


def atomic_write_text(path: Path, text: str) -> None:
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def write_if_changed(path: Path, obj: Any, original_text: str, style: Tuple[bool, bool]) -> bool:
    new_text = dump_with_style(obj, style)
    if new_text == original_text:
        return False
    atomic_write_text(path, new_text)
    return True


# ---------------------------------------------------------------------------
# HTTP classification engine
# ---------------------------------------------------------------------------


@dataclass
class HealthResult:
    url: str
    status: str
    http_status: Optional[int] = None
    final_url: Optional[str] = None
    method_used: Optional[str] = None
    note: str = ""
    history_codes: List[int] = field(default_factory=list)
    alt_ua_used: bool = False
    elapsed_ms: Optional[int] = None

    def to_dict(self) -> dict:
        d = {
            "url": self.url,
            "status": self.status,
            "http_status": self.http_status,
            "note": self.note,
        }
        if self.final_url and self.final_url != self.url:
            d["final_url"] = self.final_url
        if self.history_codes:
            d["redirect_chain"] = self.history_codes
        if self.method_used:
            d["method_used"] = self.method_used
        if self.alt_ua_used:
            d["alt_ua_used"] = True
        if self.elapsed_ms is not None:
            d["elapsed_ms"] = self.elapsed_ms
        return d


def _do_request(url: str, method: str, ua: str, pacer: HostPacer, timeout: float) -> httpx.Response:
    host = urllib.parse.urlparse(url).netloc
    pacer.wait(host)
    headers = {"User-Agent": ua, **COMMON_HEADERS}
    return httpx.request(
        method,
        url,
        headers=headers,
        timeout=httpx.Timeout(timeout),
        follow_redirects=True,
    )


def _attempt_with_retries(
    url: str,
    method: str,
    ua: str,
    pacer: HostPacer,
    timeout: float,
    max_attempts: int = MAX_ATTEMPTS,
) -> Tuple[Optional[httpx.Response], Optional[BaseException]]:
    """Up to max_attempts attempts, retrying ONLY transient outcomes
    (network-level exceptions or a 5xx status). Any definitive status
    (2xx/3xx-followed/4xx) returns immediately on the first attempt that
    produces it -- no point retrying a real answer.
    """
    last_exc: Optional[BaseException] = None
    last_resp: Optional[httpx.Response] = None
    for attempt in range(max_attempts):
        try:
            resp = _do_request(url, method, ua, pacer, timeout)
        except TRANSIENT_EXCEPTIONS as exc:
            last_exc = exc
            if attempt < max_attempts - 1:
                time.sleep(RETRY_BACKOFF * (attempt + 1))
            continue
        except httpx.HTTPError as exc:
            # Non-transient transport failure (bad URL, redirect loop, etc.)
            # -- retrying would just reproduce the same error.
            return None, exc

        if resp.status_code >= 500:
            last_resp = resp
            if attempt < max_attempts - 1:
                time.sleep(RETRY_BACKOFF * (attempt + 1))
                continue
            return resp, None  # persistent 5xx after exhausting retries
        return resp, None  # definitive, non-5xx status -- final answer

    return last_resp, last_exc


_CURL_AVAILABLE = shutil.which("curl") is not None


def _curl_confirm(url: str, pacer: HostPacer, timeout: float) -> Optional[HealthResult]:
    """Last-resort cross-check for a URL httpx couldn't reach with either
    browser User-Agent: some WAFs (observed empirically on this dataset --
    see module docstring) fingerprint the TLS/HTTP2 client itself, and a
    plain system curl request gets a normal 200 where every httpx attempt
    is 403'd. Returns a live HealthResult only if curl confirms a clean
    (post-redirect) 2xx; returns None (leaving the httpx-based verdict
    standing) on anything else, including curl being unavailable, timing
    out, or erroring -- this is purely a confidence upgrade, never a
    downgrade, and never the ONLY check performed on a URL.
    """
    if not _CURL_AVAILABLE:
        return None
    host = urllib.parse.urlparse(url).netloc
    pacer.wait(host)
    t0 = time.monotonic()
    try:
        proc = subprocess.run(
            [
                "curl", "-s", "-L", "--max-time", str(int(timeout)),
                "-A", PRIMARY_USER_AGENT,
                "-o", os.devnull,
                "-w", "%{http_code} %{url_effective}",
                url,
            ],
            capture_output=True,
            text=True,
            timeout=timeout + 5,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    out = (proc.stdout or "").strip()
    parts = out.split(" ", 1)
    if len(parts) != 2 or not parts[0].isdigit():
        return None
    code = int(parts[0])
    final_url = parts[1] or url
    if not (200 <= code < 300):
        return None
    redirected = final_url.rstrip("/") != url.rstrip("/")
    return HealthResult(
        url=url,
        status=STATUS_REDIRECT_OK if redirected else STATUS_OK,
        http_status=code,
        final_url=final_url,
        method_used="curl-crosscheck",
        note=(
            "confirmed live via curl cross-check: httpx (Python HTTP client) was "
            "blocked with both browser User-Agents, but system curl reached this "
            "URL cleanly -- the WAF is fingerprinting the client library, not "
            "gatekeeping real visitors"
        ),
        elapsed_ms=int((time.monotonic() - t0) * 1000),
    )


def check_one(url: str, pacer: HostPacer, timeout: float = TIMEOUT_SECONDS) -> HealthResult:
    t0 = time.monotonic()

    def finalize(resp: httpx.Response, method_used: str, alt_ua: bool) -> HealthResult:
        final_url = str(resp.url)
        history_codes = [h.status_code for h in resp.history]
        redirected = len(history_codes) > 0
        status = STATUS_REDIRECT_OK if redirected else STATUS_OK
        note = "reachable" if not redirected else f"redirects to {final_url}"
        if alt_ua:
            note += " (required alternate User-Agent)"
        return HealthResult(
            url=url,
            status=status,
            http_status=resp.status_code,
            final_url=final_url,
            method_used=method_used,
            note=note,
            history_codes=history_codes,
            alt_ua_used=alt_ua,
            elapsed_ms=int((time.monotonic() - t0) * 1000),
        )

    # Phase 1: HEAD (cheap). Trusted only on a clean non-error status.
    resp, exc = _attempt_with_retries(url, "HEAD", PRIMARY_USER_AGENT, pacer, timeout)
    if resp is not None and resp.status_code < 400:
        return finalize(resp, "HEAD", alt_ua=False)

    # Phase 2: GET fallback -- HEAD errored, was refused (405 is common), or
    # a transient failure exhausted its retries.
    resp2, exc2 = _attempt_with_retries(url, "GET", PRIMARY_USER_AGENT, pacer, timeout)
    if resp2 is not None and resp2.status_code < 400:
        return finalize(resp2, "GET", alt_ua=False)

    best_resp = resp2 if resp2 is not None else resp
    best_exc = exc2 if resp2 is None else None

    if best_resp is None:
        return HealthResult(
            url=url,
            status=STATUS_DEAD,
            http_status=None,
            final_url=url,
            method_used="GET",
            note=f"persistent network error after retries: {best_exc!r}",
            elapsed_ms=int((time.monotonic() - t0) * 1000),
        )

    status_code = best_resp.status_code

    if status_code in (403, 429):
        # Phase 3: one more try with a second, different browser UA before
        # concluding this is a WAF challenge rather than a dead link.
        resp3, _exc3 = _attempt_with_retries(
            url, "GET", ALT_USER_AGENT, pacer, timeout, max_attempts=2
        )
        if resp3 is not None and resp3.status_code < 400:
            return finalize(resp3, "GET", alt_ua=True)

        curl_result = _curl_confirm(url, pacer, timeout)
        if curl_result is not None:
            return curl_result

        final_code = resp3.status_code if resp3 is not None else status_code
        final_url = str(resp3.url) if resp3 is not None else str(best_resp.url)
        return HealthResult(
            url=url,
            status=STATUS_BLOCKED,
            http_status=final_code,
            final_url=final_url,
            method_used="GET",
            note=(
                f"likely-live-WAF: HTTP {final_code} persisted with both primary and "
                f"alternate browser User-Agents (not treated as dead)"
            ),
            elapsed_ms=int((time.monotonic() - t0) * 1000),
        )

    if status_code in (404, 410):
        note = f"HTTP {status_code}"
    else:
        note = f"HTTP {status_code} (unexpected/non-success status)"

    return HealthResult(
        url=url,
        status=STATUS_DEAD,
        http_status=status_code,
        final_url=str(best_resp.url),
        method_used="GET",
        note=note,
        elapsed_ms=int((time.monotonic() - t0) * 1000),
    )


def check_all(urls: List[str], workers: int, timeout: float) -> Dict[str, HealthResult]:
    pacer = HostPacer()
    results: Dict[str, HealthResult] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(check_one, u, pacer, timeout): u for u in urls}
        done = 0
        for fut in as_completed(futures):
            u = futures[fut]
            try:
                results[u] = fut.result()
            except Exception as exc:  # noqa: BLE001 -- a checker bug must not lose the whole run
                results[u] = HealthResult(url=u, status=STATUS_DEAD, note=f"checker error: {exc!r}")
            done += 1
            if done % 20 == 0 or done == len(urls):
                print(f"  checked {done}/{len(urls)}", file=sys.stderr)
    return results


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

_STATUS_RANK = {STATUS_DEAD: 0, STATUS_BLOCKED: 1, STATUS_REDIRECT_OK: 2, STATUS_OK: 3}


def summarize(results: Dict[str, HealthResult]) -> Dict[str, int]:
    counts = {STATUS_OK: 0, STATUS_REDIRECT_OK: 0, STATUS_BLOCKED: 0, STATUS_DEAD: 0}
    for r in results.values():
        counts[r.status] = counts.get(r.status, 0) + 1
    counts["total"] = len(results)
    return counts


def write_health_json(
    results: Dict[str, HealthResult],
    url_map: Dict[str, List[Occurrence]],
    path: Path,
) -> None:
    ordered = sorted(results.values(), key=lambda r: (_STATUS_RANK[r.status], r.url))
    doc = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "summary": summarize(results),
        "results": [
            {**r.to_dict(), "occurrences": [o.to_dict() for o in url_map.get(r.url, [])]}
            for r in ordered
        ],
    }
    atomic_write_text(path, json.dumps(doc, indent=2, ensure_ascii=False) + "\n")


def write_health_md(
    results: Dict[str, HealthResult],
    url_map: Dict[str, List[Occurrence]],
    path: Path,
) -> None:
    ordered = sorted(results.values(), key=lambda r: (_STATUS_RANK[r.status], r.url))
    counts = summarize(results)
    lines = []
    lines.append("# Source Health Report")
    lines.append("")
    lines.append(f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append("")
    lines.append(
        f"**{counts['total']} distinct source URLs** — "
        f"{counts[STATUS_OK]} OK, {counts[STATUS_REDIRECT_OK]} redirect-OK, "
        f"{counts[STATUS_BLOCKED]} blocked (likely-live-WAF), {counts[STATUS_DEAD]} DEAD."
    )
    lines.append("")
    lines.append("Ranked worst-first (DEAD, then BLOCKED, then REDIRECT-OK, then OK).")
    lines.append("")
    for status in (STATUS_DEAD, STATUS_BLOCKED, STATUS_REDIRECT_OK, STATUS_OK):
        rows = [r for r in ordered if r.status == status]
        if not rows:
            continue
        lines.append(f"## {status} ({len(rows)})")
        lines.append("")
        for r in rows:
            lines.append(f"### `{r.url}`")
            code = r.http_status if r.http_status is not None else "—"
            lines.append(f"- HTTP status: {code}  ·  method: {r.method_used or '—'}  ·  {r.note}")
            if r.final_url and r.final_url != r.url:
                lines.append(f"- Final URL: `{r.final_url}`")
            occs = url_map.get(r.url, [])
            if occs:
                lines.append("- Cited from:")
                for o in occs[:12]:
                    ctx = []
                    if o.candidate_id:
                        ctx.append(f"candidate={o.candidate_id}")
                    if o.race_id:
                        ctx.append(f"race={o.race_id}")
                    ctx_str = f" ({', '.join(ctx)})" if ctx else ""
                    lines.append(f"  - `{o.file}` → `{o.path}`{ctx_str}")
                if len(occs) > 12:
                    lines.append(f"  - ...and {len(occs) - 12} more occurrence(s)")
            lines.append("")
    atomic_write_text(path, "\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# Fix helpers -- every replacement is HTTP-verified before being accepted.
# Nothing here ever invents a URL; each strategy only *constructs a
# candidate* from data already on file (a candidate's own fec_id, a
# MediaWiki-confirmed redirect target, or a mechanical scheme/host variant)
# and then checks it live exactly like everything else in this script.
# ---------------------------------------------------------------------------


def registrable_domain(netloc: str) -> str:
    """Approximate eTLD+1 (last two labels) -- good enough to distinguish
    "same organization, different subdomain/scheme" from "redirected to an
    unrelated domain" for this dataset's plain .gov/.org/.com hosts. Not a
    full public-suffix-list implementation; used only as a conservative
    canonicalization safety gate, never as a security boundary.
    """
    labels = netloc.split(":")[0].split(".")
    return ".".join(labels[-2:]) if len(labels) >= 2 else netloc


def probe_variants(url: str, pacer: HostPacer, timeout: float) -> List[Tuple[str, HealthResult]]:
    """Mechanical http/https + www./apex variants of url, each HTTP-checked.
    Returns only the variants that are OK/REDIRECT-OK (i.e. plausible fixes),
    paired with their HealthResult."""
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc
    host_variants = {("www." + host) if not host.startswith("www.") else host[4:]}
    scheme_variants = {"https"} if parsed.scheme != "https" else {"https"}
    # also try upgrading http->https on the *same* host if not already https
    variants = set()
    for scheme in ({"https", parsed.scheme} if parsed.scheme != "https" else {"https"}):
        for h in host_variants | {host}:
            if scheme == parsed.scheme and h == host:
                continue
            variants.add(urllib.parse.urlunparse((scheme, h, parsed.path, parsed.params, parsed.query, "")))

    live = []
    for v in variants:
        result = check_one(v, pacer, timeout)
        if result.status in (STATUS_OK, STATUS_REDIRECT_OK):
            live.append((v, result))
    return live


def try_fec_candidate_pattern(
    url: str, occs: List[Occurrence], candidates: Dict[str, Any], pacer: HostPacer, timeout: float
) -> Optional[Tuple[str, HealthResult, str]]:
    """If url is a fec.gov candidate-detail page and the owning candidate's
    own fec_id names a different (presumably current) ID, try that."""
    m_host = "fec.gov" in urllib.parse.urlparse(url).netloc
    if not m_host or "/candidate/" not in url:
        return None
    for o in occs:
        if not o.candidate_id:
            continue
        cand = candidates.get(o.candidate_id)
        if not cand:
            continue
        fec_id = cand.get("fec_id")
        if not fec_id or fec_id in url:
            continue
        candidate_url = f"https://www.fec.gov/data/candidate/{fec_id}/"
        result = check_one(candidate_url, pacer, timeout)
        if result.status in (STATUS_OK, STATUS_REDIRECT_OK):
            return candidate_url, result, f"fec.gov candidate-page pattern using this candidate's own fec_id ({fec_id})"
    return None


def try_wikipedia_redirect(url: str, pacer: HostPacer, timeout: float) -> Optional[Tuple[str, HealthResult, str]]:
    """Ask the MediaWiki API whether this exact title is a formal redirect
    to a different current title. Only acts on an explicit API-confirmed
    redirect target -- never a fuzzy search guess."""
    parsed = urllib.parse.urlparse(url)
    if "wikipedia.org" not in parsed.netloc or "/wiki/" not in parsed.path:
        return None
    title = urllib.parse.unquote(parsed.path.split("/wiki/", 1)[1])
    api = f"https://{parsed.netloc}/w/api.php"
    try:
        host = parsed.netloc
        pacer.wait(host)
        resp = httpx.get(
            api,
            params={"action": "query", "titles": title, "redirects": 1, "format": "json"},
            headers={"User-Agent": PRIMARY_USER_AGENT, **COMMON_HEADERS},
            timeout=httpx.Timeout(timeout),
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
    except (httpx.HTTPError, ValueError):
        return None

    redirects = data.get("query", {}).get("redirects")
    if not redirects:
        return None
    to_title = redirects[0].get("to")
    if not to_title:
        return None
    new_url = f"https://{parsed.netloc}/wiki/{urllib.parse.quote(to_title.replace(' ', '_'))}"
    if new_url == url:
        return None
    result = check_one(new_url, pacer, timeout)
    if result.status in (STATUS_OK, STATUS_REDIRECT_OK):
        return new_url, result, f"MediaWiki API confirms '{title}' redirects to '{to_title}'"
    return None


def find_dead_fix(
    url: str, occs: List[Occurrence], candidates: Dict[str, Any], pacer: HostPacer, timeout: float
) -> Optional[Tuple[str, HealthResult, str]]:
    for strategy in (
        lambda: try_fec_candidate_pattern(url, occs, candidates, pacer, timeout),
        lambda: try_wikipedia_redirect(url, pacer, timeout),
        lambda: (lambda variants: (variants[0][0], variants[0][1], "mechanical www./https variant") if len(variants) == 1 else None)(
            probe_variants(url, pacer, timeout)
        ),
    ):
        found = strategy()
        if found:
            return found
    return None


# ---------------------------------------------------------------------------
# Applying a verified fix everywhere the old URL string appears.
# ---------------------------------------------------------------------------


class GoldFiles:
    """Loads candidates.json, races.json, and every insights/*.json file
    once; tracks which ones are dirtied; writes back only the changed ones,
    atomically, each in its own auto-detected original style."""

    def __init__(self):
        self.candidates_obj, self._cand_text, self._cand_style = load_json_with_style(CANDIDATES_PATH)
        self.races_obj, self._races_text, self._races_style = load_json_with_style(RACES_PATH)
        self.insight_paths = sorted(p for p in INSIGHTS_DIR.iterdir() if p.suffix == ".json")
        self.insight_objs: Dict[Path, Any] = {}
        self.insight_texts: Dict[Path, str] = {}
        self.insight_styles: Dict[Path, Tuple[bool, bool]] = {}
        for p in self.insight_paths:
            obj, text, style = load_json_with_style(p)
            self.insight_objs[p] = obj
            self.insight_texts[p] = text
            self.insight_styles[p] = style

    def _replace_in(self, obj: Any, old: str, new: str) -> int:
        count = 0
        if isinstance(obj, dict):
            for k, v in list(obj.items()):
                if k == "source" and v == old:
                    obj[k] = new
                    count += 1
                elif k == "sources" and isinstance(v, list):
                    for i, u in enumerate(v):
                        if u == old:
                            v[i] = new
                            count += 1
                    # de-dupe while preserving order, in case new was already present
                    seen = set()
                    deduped = []
                    for u in v:
                        if u not in seen:
                            seen.add(u)
                            deduped.append(u)
                    obj[k] = deduped
                else:
                    count += self._replace_in(v, old, new)
        elif isinstance(obj, list):
            for v in obj:
                count += self._replace_in(v, old, new)
        return count

    def replace_url_everywhere(self, old: str, new: str) -> Dict[str, int]:
        """Exact JSON-value replacement of old -> new across all gold +
        derived files. Returns {file_label: replacement_count}."""
        report = {}
        n = self._replace_in(self.candidates_obj, old, new)
        if n:
            report["data/tx/candidates.json"] = n
        n = self._replace_in(self.races_obj, old, new)
        if n:
            report["data/tx/races.json"] = n
        for p in self.insight_paths:
            n = self._replace_in(self.insight_objs[p], old, new)
            if n:
                report[f"data/tx/insights/{p.name}"] = n
        return report

    def _find_owning_dicts(self, obj: Any, url: str, acc: List[dict]) -> None:
        if isinstance(obj, dict):
            if obj.get("source") == url:
                acc.append(obj)
            srcs = obj.get("sources")
            if isinstance(srcs, list) and url in srcs:
                acc.append(obj)
            for v in obj.values():
                self._find_owning_dicts(v, url, acc)
        elif isinstance(obj, list):
            for v in obj:
                self._find_owning_dicts(v, url, acc)

    def annotate_unverified(self, url: str) -> int:
        """Adds source_status: 'unverified' to every dict in candidates.json
        and races.json (gold data only -- not the derived insights/*.json)
        that directly owns this source URL. Never touches the URL itself."""
        acc: List[dict] = []
        self._find_owning_dicts(self.candidates_obj, url, acc)
        self._find_owning_dicts(self.races_obj, url, acc)
        n = 0
        for d in acc:
            if d.get("source_status") != "unverified":
                d["source_status"] = "unverified"
                n += 1
        return n

    def flush(self) -> List[str]:
        """Writes back every file whose in-memory object actually changed
        from what was loaded. Returns the list of file labels written."""
        written = []
        if write_if_changed(CANDIDATES_PATH, self.candidates_obj, self._cand_text, self._cand_style):
            written.append("data/tx/candidates.json")
        if write_if_changed(RACES_PATH, self.races_obj, self._races_text, self._races_style):
            written.append("data/tx/races.json")
        for p in self.insight_paths:
            if write_if_changed(p, self.insight_objs[p], self.insight_texts[p], self.insight_styles[p]):
                written.append(f"data/tx/insights/{p.name}")
        return written


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def run_pass(workers: int, timeout: float) -> Tuple[Dict[str, List[Occurrence]], Dict[str, HealthResult]]:
    url_map = collect_source_urls()
    urls = sorted(url_map.keys())
    print(f"Collected {len(urls)} distinct source URLs.", file=sys.stderr)
    results = check_all(urls, workers, timeout)
    return url_map, results


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fix", action="store_true", help="Apply verified fixes / unverified-annotations, then re-check.")
    parser.add_argument("--canonicalize", action="store_true", help="With --fix, also rewrite REDIRECT-OK URLs to their final destination (same-registrable-domain only).")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--timeout", type=float, default=TIMEOUT_SECONDS)
    args = parser.parse_args(argv)

    print("=== Source health: initial pass ===", file=sys.stderr)
    url_map, results = run_pass(args.workers, args.timeout)
    before_counts = summarize(results)
    print(f"BEFORE: {json.dumps(before_counts)}", file=sys.stderr)

    fix_log: List[str] = []

    if args.fix:
        gold = GoldFiles()
        dead = [r for r in results.values() if r.status == STATUS_DEAD]
        redirects = [r for r in results.values() if r.status == STATUS_REDIRECT_OK]
        pacer = HostPacer()

        for r in dead:
            occs = url_map.get(r.url, [])
            fixed = find_dead_fix(r.url, occs, gold.candidates_obj, pacer, args.timeout)
            if fixed:
                new_url, new_result, reason = fixed
                report = gold.replace_url_everywhere(r.url, new_url)
                fix_log.append(
                    f"FIXED  {r.url} -> {new_url}  ({reason}; new status {new_result.status}; "
                    f"replaced in {report})"
                )
            else:
                n = gold.annotate_unverified(r.url)
                fix_log.append(
                    f"ANNOTATED  {r.url}  (no safe verifiable replacement found; "
                    f"marked source_status=unverified on {n} record(s))"
                )

        if args.canonicalize:
            for r in redirects:
                if not r.final_url or r.final_url == r.url:
                    continue
                if registrable_domain(urllib.parse.urlparse(r.url).netloc) != registrable_domain(
                    urllib.parse.urlparse(r.final_url).netloc
                ):
                    fix_log.append(
                        f"SKIPPED-CANONICALIZE  {r.url} -> {r.final_url}  "
                        f"(cross-domain redirect; needs human review)"
                    )
                    continue
                report = gold.replace_url_everywhere(r.url, r.final_url)
                if report:
                    fix_log.append(f"CANONICALIZED  {r.url} -> {r.final_url}  (replaced in {report})")

        written = gold.flush()
        print(f"\nFiles written: {len(written)}", file=sys.stderr)
        for w in written:
            print(f"  - {w}", file=sys.stderr)
        print("\nFix log:", file=sys.stderr)
        for line in fix_log:
            print(f"  {line}", file=sys.stderr)

        if written:
            print("\n=== Source health: re-verify pass (post-fix) ===", file=sys.stderr)
            url_map, results = run_pass(args.workers, args.timeout)

    after_counts = summarize(results)
    write_health_json(results, url_map, HEALTH_JSON_PATH)
    write_health_md(results, url_map, HEALTH_MD_PATH)

    def _display_path(p: Path) -> str:
        # os.path.relpath (unlike Path.relative_to) never raises when p isn't
        # actually under ROOT -- matters for tests/tooling that repoint these
        # module-level paths at a fixture directory outside the repo.
        return os.path.relpath(p, ROOT)

    print(f"\nBEFORE: {json.dumps(before_counts)}")
    print(f"AFTER:  {json.dumps(after_counts)}")
    print(f"Wrote {_display_path(HEALTH_JSON_PATH)}")
    print(f"Wrote {_display_path(HEALTH_MD_PATH)}")
    if fix_log:
        print(f"\n{len(fix_log)} fix action(s) taken (see stderr above for detail).")

    return 0


if __name__ == "__main__":
    sys.exit(main())
