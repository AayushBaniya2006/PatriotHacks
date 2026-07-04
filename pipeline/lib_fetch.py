#!/usr/bin/env python3
"""
pipeline/lib_fetch.py

Small, shared fetch-robustness kit for the pipeline/fetch_*.py scripts:

  - get_with_retry(url, ...): retrying HTTP GET/HEAD over stdlib urllib,
    matching the dependency profile pipeline/fetch_fec.py already uses (no
    new third-party dependency for the retry path itself).
  - retry_call(fn, ...): the transport-agnostic retry/backoff engine behind
    get_with_retry, exposed directly so a fetcher whose transport is NOT a
    plain single-shot urllib GET (e.g. pipeline/fetch_tec_finance.py's HTTP
    Range requests, which need a `requests.Session` for connection reuse and
    a `Range` header) can still get the same retry/backoff semantics without
    reimplementing byte-range fetching in urllib.
  - expect_keys(payload, path_desc, required_keys) / DriftError: a loud
    schema-drift guard. Call it right at the boundary where an upstream
    payload gets parsed into fields our pipeline depends on. If upstream
    silently renamed or dropped a key, we want a crash naming the missing
    key(s) and the source -- never a fetcher that quietly writes incomplete
    or garbled data because a `.get(...)` returned None everywhere.
  - RateBudget: a per-host minimum-interval helper so a fetcher (or a shared
    kit-level default) can avoid hammering one host across many calls.

Kept stdlib-only (urllib, time) so importing this module never adds a new
dependency to a fetcher that doesn't already have one.
"""
from __future__ import annotations

import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, TypeVar

DEFAULT_USER_AGENT = "PatriotHacksBot/1.0 (contact: sww35@txstate.edu; hackathon voter-info tool)"

T = TypeVar("T")


class DriftError(RuntimeError):
    """Raised when an upstream payload is missing key(s) our pipeline relies on.

    This is intentionally a hard failure (raised exception), not a logged
    warning: a changed upstream shape must stop the fetcher before it writes
    silently-incomplete data downstream.
    """


class FetchError(RuntimeError):
    """Raised when get_with_retry / retry_call exhausts all attempts."""


@dataclass
class FetchResult:
    """Return value of get_with_retry: a fully-read, connection-closed response."""

    status: int
    headers: Any  # http.client.HTTPMessage; supports .get(name), iteration, etc.
    body: bytes
    url: str  # final URL (after any redirects urllib followed)


# ---------------------------------------------------------------------------
# Generic retry/backoff engine
# ---------------------------------------------------------------------------


def retry_call(
    fn: Callable[[], T],
    *,
    retries: int = 3,
    backoff: float = 1.5,
    sleep_fn: Callable[[float], None] = time.sleep,
    exceptions: tuple = (Exception,),
    on_error: Optional[Callable[[int, Exception], None]] = None,
) -> T:
    """Call fn() up to `retries` times total, sleeping `backoff * (attempt+1)`
    seconds after each failed attempt (including the last, matching the
    original fetch_fec.py retry loop this generalizes). Raises FetchError
    wrapping the last exception once attempts are exhausted.

    `retries` counts total attempts (not "retries after the first"), matching
    the `max_retries` semantics fetch_fec.py already used pre-retrofit.
    """
    if retries < 1:
        raise ValueError("retries must be >= 1")
    last_err: Optional[Exception] = None
    for attempt in range(retries):
        try:
            return fn()
        except exceptions as e:  # noqa: BLE001 - broad by design, caller can narrow via `exceptions`
            last_err = e
            if on_error is not None:
                on_error(attempt, e)
            sleep_fn(backoff * (attempt + 1))
    raise FetchError(f"Exhausted {retries} attempt(s): {last_err!r}") from last_err


# ---------------------------------------------------------------------------
# stdlib-urllib GET/HEAD with retry
# ---------------------------------------------------------------------------


def get_with_retry(
    url: str,
    *,
    retries: int = 3,
    backoff: float = 1.5,
    timeout: float = 20.0,
    headers: Optional[Mapping[str, str]] = None,
    method: str = "GET",
    user_agent: str = DEFAULT_USER_AGENT,
    min_interval: float = 0.0,
    rate_budget: Optional["RateBudget"] = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> FetchResult:
    """GET (or HEAD) `url` with retry+backoff, using stdlib urllib only.

    A polite default User-Agent is sent unless overridden. If `min_interval`
    (or an explicit `rate_budget`) is given, calls to the same host are
    throttled to at most one per `min_interval` seconds.
    """
    req_headers = {"User-Agent": user_agent}
    if headers:
        req_headers.update(headers)

    budget = rate_budget
    if budget is None and min_interval:
        budget = RateBudget(min_interval=min_interval)
    host = urllib.parse.urlparse(url).netloc

    def _do() -> FetchResult:
        if budget is not None:
            budget.wait(host)
        req = urllib.request.Request(url, headers=req_headers, method=method)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            return FetchResult(status=resp.status, headers=resp.headers, body=body, url=resp.geturl())

    return retry_call(_do, retries=retries, backoff=backoff, sleep_fn=sleep_fn)


# ---------------------------------------------------------------------------
# Schema-drift guard
# ---------------------------------------------------------------------------


def expect_keys(payload: Any, path_desc: str, required_keys: Iterable[str]) -> None:
    """Raise DriftError if any of required_keys is absent from payload.

    `payload` only needs to support `key in payload`: a parsed-JSON dict
    (checks its keys) and a plain list/tuple/set of column names (e.g. a
    csv.DictReader.fieldnames list) both work, so the same call covers a
    JSON API response body and a CSV header.

    `path_desc` should name both the shape being checked and where it came
    from (e.g. "FEC /candidates/ page 1" or "TEC cover.csv header") so the
    raised error is immediately actionable.
    """
    missing = [k for k in required_keys if k not in payload]
    if missing:
        raise DriftError(
            f"Schema drift detected in {path_desc}: missing required key(s) {missing!r}. "
            f"Upstream shape changed -- refusing to proceed rather than silently "
            f"produce incomplete/garbage data."
        )


# ---------------------------------------------------------------------------
# Per-host rate budget
# ---------------------------------------------------------------------------


class RateBudget:
    """Enforces a minimum interval between successive calls to the same host.

    Call `wait(host)` immediately before issuing a request to that host; it
    sleeps just long enough (if at all) so that no two calls to the same
    host happen closer together than `min_interval` seconds. `min_interval`
    of 0 (the default) makes `wait` a no-op timestamp bookkeeping call --
    safe to leave wired in everywhere without changing timing behavior until
    a caller actually opts into throttling.
    """

    def __init__(self, min_interval: float = 0.0, sleep_fn: Callable[[float], None] = time.sleep):
        self.min_interval = min_interval
        self.sleep_fn = sleep_fn
        self._last_call: Dict[str, float] = {}

    def wait(self, host: str) -> None:
        now = time.monotonic()
        if self.min_interval > 0:
            last = self._last_call.get(host)
            if last is not None:
                remaining = self.min_interval - (now - last)
                if remaining > 0:
                    self.sleep_fn(remaining)
        self._last_call[host] = time.monotonic()
