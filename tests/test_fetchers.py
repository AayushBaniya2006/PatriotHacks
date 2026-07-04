"""tests/test_fetchers.py

Recorded-fixture tests for pipeline/lib_fetch.py and the two fetchers
retrofitted to use it (pipeline/fetch_fec.py, pipeline/fetch_tec_finance.py).

No live network anywhere in this file. Every fixture below is a small,
trimmed sample shaped like -- and, where possible, numerically identical to
-- real values already recorded in this repo:
  - FEC fixtures reconstruct the raw OpenFEC /candidates/ and
    /candidates/totals/ response shape from the real name_raw/receipts/
    disbursements/cash_on_hand values already stored for candidate_id
    H6TX01337 in data/tx/raw/fec.json.
  - TEC fixtures reconstruct the raw cover.csv row shape from the real,
    already-recorded finance blocks in data/tx/candidates.json for
    abbott-greg (auto-match path) and hinojosa-gina (the fetcher's actual,
    documented MANUAL_OVERRIDES entry) -- filer_id and every dollar amount
    below are the real recorded values. (TEC's raw cover.csv itself is never
    persisted to data/tx/raw/ -- fetch_tec_finance.py deliberately avoids
    downloading/caching the ~1GB bulk archive -- so this is the closest
    "real shape" available; the alternative, downloading the live archive
    just to build a test fixture, would defeat that design.)

Run:
    pytest tests/test_fetchers.py -q
"""
from __future__ import annotations

import csv
import importlib.util
import io
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from types import ModuleType

import pytest
import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
PIPELINE_DIR = REPO_ROOT / "pipeline"
if str(PIPELINE_DIR) not in sys.path:
    sys.path.insert(0, str(PIPELINE_DIR))

import lib_fetch  # noqa: E402

FETCH_FEC_PATH = PIPELINE_DIR / "fetch_fec.py"
FETCH_TEC_PATH = PIPELINE_DIR / "fetch_tec_finance.py"


def _load_module(mod_name: str, path: Path) -> ModuleType:
    """Load a sibling pipeline script as a fresh module instance by file path.

    Mirrors tests/test_e2e_demo.py's _load_module: pipeline/ has no
    __init__.py so plain `import pipeline.x` isn't available. Loading a
    fresh instance per test also sidesteps any cross-test module-level
    global-state bleed (e.g. fetch_fec.py's REQUEST_COUNT counter).
    """
    spec = importlib.util.spec_from_file_location(mod_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Fixtures: trimmed/reshaped real data
# ---------------------------------------------------------------------------

# Reshaped from data/tx/raw/fec.json's real "ALEXANDER, DAX CORNELL" record
# (name_raw, receipts, disbursements, cash_on_hand are the real recorded
# values) into the raw OpenFEC API response shape fetch_fec.py's api_get
# actually parses (results + pagination envelope).
FEC_CANDIDATES_PAGE_H = {
    "results": [
        {
            "candidate_id": "H6TX01337",
            "name": "ALEXANDER, DAX CORNELL",
            "party": "DEM",
            "office": "H",
            "district": "01",
            "incumbent_challenge_full": "Challenger",
            "candidate_status": "C",
        }
    ],
    "pagination": {"page": 1, "pages": 1, "per_page": 100, "count": 1},
}

FEC_TOTALS_PAGE_H = {
    "results": [
        {
            "candidate_id": "H6TX01337",
            "receipts": 12466.68,
            "disbursements": 10893.2,
            "last_cash_on_hand_end_period": None,
        }
    ],
    "pagination": {"page": 1, "pages": 1, "per_page": 100, "count": 1},
}

FEC_EMPTY_PAGE = {"results": [], "pagination": {"page": 1, "pages": 1, "per_page": 100, "count": 0}}

# Reshaped from data/tx/candidates.json's real TEC-sourced finance blocks:
# abbott-greg (filer_id 00019652, auto-match path) and hinojosa-gina
# (filer_id 00080440, the module's real MANUAL_OVERRIDES entry). Plus two
# synthetic COH filers ("Smith, John A"/"Smith, John B") to exercise the
# ambiguous-match path, which no real committed candidate happens to hit.
TEC_COVER_ROWS = [
    {
        "filerIdent": "00019652",
        "filerName": "Abbott, Greg (Mr.)",
        "filerNameFirst": "Greg",
        "filerNameLast": "Abbott",
        "filerTypeCd": "COH",
        "filerSeekOfficeCd": "GOVERNOR",
        "periodEndDt": "20260221",
        "receivedDt": "20260225",
        "electionDt": "20261103",
        "infoOnlyFlag": "N",
        "totalContribAmount": "",  # BWZ: blank == 0.0 (real recorded value)
        "totalExpendAmount": "42592.76",
        "contribsMaintainedAmount": "569675.55",
    },
    {
        "filerIdent": "00080440",
        "filerName": "Hinojosa, Regina (Ms.)",
        "filerNameFirst": "Regina",
        "filerNameLast": "Hinojosa",
        "filerTypeCd": "COH",
        "filerSeekOfficeCd": "GOVERNOR",
        "periodEndDt": "20260221",
        "receivedDt": "20260225",
        "electionDt": "20261103",
        "infoOnlyFlag": "N",
        "totalContribAmount": "951069.37",
        "totalExpendAmount": "673404.86",
        "contribsMaintainedAmount": "617635.11",
    },
    {
        "filerIdent": "00090001",
        "filerName": "Smith, John A",
        "filerNameFirst": "John A",
        "filerNameLast": "Smith",
        "filerTypeCd": "COH",
        "filerSeekOfficeCd": "STATEREP",
        "periodEndDt": "20250630",
        "receivedDt": "20250701",
        "electionDt": "20241105",
        "infoOnlyFlag": "N",
        "totalContribAmount": "500.00",
        "totalExpendAmount": "100.00",
        "contribsMaintainedAmount": "400.00",
    },
    {
        "filerIdent": "00090002",
        "filerName": "Smith, John B",
        "filerNameFirst": "John B",
        "filerNameLast": "Smith",
        "filerTypeCd": "COH",
        "filerSeekOfficeCd": "STATESEN",
        "periodEndDt": "20250630",
        "receivedDt": "20250701",
        "electionDt": "20241105",
        "infoOnlyFlag": "N",
        "totalContribAmount": "700.00",
        "totalExpendAmount": "200.00",
        "contribsMaintainedAmount": "500.00",
    },
]


def _csv_handle(rows, fieldnames) -> io.StringIO:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    buf.seek(0)
    return buf


# ---------------------------------------------------------------------------
# expect_keys / DriftError
# ---------------------------------------------------------------------------


class TestExpectKeys:
    def test_dict_missing_key_raises_drift_error(self):
        payload = {"results": []}  # "pagination" silently dropped by upstream
        with pytest.raises(lib_fetch.DriftError) as exc:
            lib_fetch.expect_keys(payload, "fixture endpoint", ["results", "pagination"])
        assert "pagination" in str(exc.value)
        assert "fixture endpoint" in str(exc.value)

    def test_list_missing_key_raises_drift_error(self):
        # csv.DictReader.fieldnames-shaped input: a bare list of column names.
        fieldnames = ["filerIdent", "filerName"]
        with pytest.raises(lib_fetch.DriftError) as exc:
            lib_fetch.expect_keys(fieldnames, "TEC cover.csv header", ["filerIdent", "totalContribAmount"])
        assert "totalContribAmount" in str(exc.value)

    def test_present_keys_do_not_raise(self):
        payload = {"results": [], "pagination": {"pages": 1}}
        lib_fetch.expect_keys(payload, "fixture endpoint", ["results", "pagination"])  # no raise


# ---------------------------------------------------------------------------
# retry_call (transport-agnostic retry engine)
# ---------------------------------------------------------------------------


class TestRetryCall:
    def test_succeeds_after_transient_failures(self):
        calls = {"n": 0}

        def flaky():
            calls["n"] += 1
            if calls["n"] < 3:
                raise ConnectionError("simulated blip")
            return "ok"

        result = lib_fetch.retry_call(flaky, retries=5, backoff=1.5, sleep_fn=lambda s: None)
        assert result == "ok"
        assert calls["n"] == 3

    def test_exhausts_and_raises_fetch_error(self):
        calls = {"n": 0}

        def always_fails():
            calls["n"] += 1
            raise ValueError("boom")

        with pytest.raises(lib_fetch.FetchError) as exc:
            lib_fetch.retry_call(always_fails, retries=3, backoff=1.5, sleep_fn=lambda s: None)
        assert calls["n"] == 3
        assert "boom" in str(exc.value)

    def test_retries_must_be_positive(self):
        with pytest.raises(ValueError):
            lib_fetch.retry_call(lambda: "unreachable", retries=0)


# ---------------------------------------------------------------------------
# get_with_retry (stdlib urllib transport)
# ---------------------------------------------------------------------------


class _FakeHTTPResponse:
    def __init__(self, body: bytes, status: int = 200, url: str = "http://example.test/ok"):
        self._body = body
        self.status = status
        self.headers = {}
        self._url = url

    def read(self):
        return self._body

    def geturl(self):
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class TestGetWithRetry:
    def test_success_returns_fetch_result(self, monkeypatch):
        def fake_urlopen(req, timeout=None):
            return _FakeHTTPResponse(b'{"ok": true}')

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        result = lib_fetch.get_with_retry("http://example.test/ok", sleep_fn=lambda s: None)
        assert result.status == 200
        assert json.loads(result.body) == {"ok": True}

    def test_happy_path_never_sleeps(self, monkeypatch):
        def fake_urlopen(req, timeout=None):
            return _FakeHTTPResponse(b"{}")

        sleeps = []
        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        lib_fetch.get_with_retry("http://example.test/ok", sleep_fn=sleeps.append)
        assert sleeps == []

    def test_retries_then_raises_fetch_error(self, monkeypatch):
        calls = {"n": 0}

        def fake_urlopen(req, timeout=None):
            calls["n"] += 1
            raise urllib.error.URLError("simulated network blip")

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        with pytest.raises(lib_fetch.FetchError):
            lib_fetch.get_with_retry("http://example.test/flaky", retries=3, sleep_fn=lambda s: None)
        assert calls["n"] == 3


# ---------------------------------------------------------------------------
# RateBudget
# ---------------------------------------------------------------------------


class TestRateBudget:
    def test_default_min_interval_zero_never_sleeps(self):
        sleeps = []
        budget = lib_fetch.RateBudget(min_interval=0.0, sleep_fn=sleeps.append)
        budget.wait("host-a")
        budget.wait("host-a")
        assert sleeps == []

    def test_enforces_min_interval_per_host(self, monkeypatch):
        fake_now = {"t": 0.0}
        monkeypatch.setattr(lib_fetch.time, "monotonic", lambda: fake_now["t"])
        sleeps = []
        budget = lib_fetch.RateBudget(min_interval=2.0, sleep_fn=sleeps.append)

        budget.wait("host-a")  # first call for this host: no wait
        assert sleeps == []

        fake_now["t"] = 0.5  # only 0.5s elapsed, need to wait 1.5s more
        budget.wait("host-a")
        assert sleeps == [1.5]

        fake_now["t"] = 10.0  # well past the interval now
        budget.wait("host-a")
        assert sleeps == [1.5]  # no extra sleep needed

        budget.wait("host-b")  # a different host is never throttled by host-a
        assert sleeps == [1.5]


# ---------------------------------------------------------------------------
# fetch_fec.py retrofit
# ---------------------------------------------------------------------------


def _fec_dispatcher():
    """Fake get_with_retry: routes on (path, office) markers found in the
    request URL, matching FEC-most-specific-first so a totals:// URL (which
    contains the plain candidates path as a substring) isn't misrouted."""
    routes = [
        (("/candidates/totals/", "office=H"), FEC_TOTALS_PAGE_H),
        (("/candidates/totals/", "office=S"), FEC_EMPTY_PAGE),
        (("/candidates/", "office=H"), FEC_CANDIDATES_PAGE_H),
        (("/candidates/", "office=S"), FEC_EMPTY_PAGE),
    ]

    def _fake(url, **kwargs):
        for markers, payload in routes:
            if all(m in url for m in markers):
                return lib_fetch.FetchResult(
                    status=200, headers={}, body=json.dumps(payload).encode("utf-8"), url=url
                )
        raise AssertionError(f"no fixture route registered for URL: {url}")

    return _fake


class TestFetchFecRetrofit:
    def test_fetch_candidates_handles_fixture(self, monkeypatch):
        mod = _load_module("fetch_fec_candidates", FETCH_FEC_PATH)
        monkeypatch.setattr(mod, "get_with_retry", _fec_dispatcher())
        results = mod.fetch_candidates("H")
        assert len(results) == 1
        assert results[0]["candidate_id"] == "H6TX01337"
        assert results[0]["name"] == "ALEXANDER, DAX CORNELL"

    def test_main_writes_normalized_candidate_from_fixtures(self, monkeypatch, tmp_path):
        mod = _load_module("fetch_fec_main", FETCH_FEC_PATH)
        monkeypatch.setattr(mod, "get_with_retry", _fec_dispatcher())
        out_path = tmp_path / "fec.json"
        monkeypatch.setattr(mod, "OUT_PATH", str(out_path))

        mod.main()

        assert mod.REQUEST_COUNT == 4  # candidates(H,S) + totals(H,S), one page each
        written = json.loads(out_path.read_text())
        candidates = written["candidates"]
        assert len(candidates) == 1
        c = candidates[0]
        assert c["fec_candidate_id"] == "H6TX01337"
        assert c["name"] == "Dax Cornell Alexander"
        assert c["party"] == "Democratic"
        assert c["district"] == "TX-01"
        assert c["receipts"] == 12466.68
        assert c["disbursements"] == 10893.2
        assert c["cash_on_hand"] is None
        assert c["has_activity"] is True

    @pytest.mark.parametrize("dropped_key", ["results", "pagination"])
    def test_schema_drift_on_removed_key_raises_immediately(self, monkeypatch, dropped_key):
        mod = _load_module(f"fetch_fec_drift_{dropped_key}", FETCH_FEC_PATH)
        bad_payload = {k: v for k, v in FEC_CANDIDATES_PAGE_H.items() if k != dropped_key}

        def _fake(url, **kwargs):
            return lib_fetch.FetchResult(
                status=200, headers={}, body=json.dumps(bad_payload).encode("utf-8"), url=url
            )

        monkeypatch.setattr(mod, "get_with_retry", _fake)
        with pytest.raises(lib_fetch.DriftError) as exc:
            mod.fetch_candidates("H")
        assert dropped_key in str(exc.value)
        # Drift must be raised immediately, not silently retried away burning
        # the request budget -- exactly one attempt should have been made.
        assert mod.REQUEST_COUNT == 1


# ---------------------------------------------------------------------------
# fetch_tec_finance.py retrofit
# ---------------------------------------------------------------------------


class TestFetchTecFinanceLoadCoverRows:
    def test_valid_fixture_is_accepted(self):
        mod = _load_module("fetch_tec_load_ok", FETCH_TEC_PATH)
        handle = _csv_handle(TEC_COVER_ROWS, mod.REQUIRED_COVER_COLUMNS)
        rows = mod.load_cover_rows(handle, required_keys=mod.REQUIRED_COVER_COLUMNS, path_desc="cover.csv")
        assert len(rows) == len(TEC_COVER_ROWS)
        assert rows[0]["filerIdent"] == "00019652"

    def test_removed_required_column_raises_drift_error(self):
        mod = _load_module("fetch_tec_load_drift", FETCH_TEC_PATH)
        trimmed_fieldnames = [c for c in mod.REQUIRED_COVER_COLUMNS if c != "totalContribAmount"]
        trimmed_rows = [{k: v for k, v in row.items() if k != "totalContribAmount"} for row in TEC_COVER_ROWS]
        handle = _csv_handle(trimmed_rows, trimmed_fieldnames)
        with pytest.raises(lib_fetch.DriftError) as exc:
            mod.load_cover_rows(handle, required_keys=mod.REQUIRED_COVER_COLUMNS, path_desc="cover.csv")
        assert "totalContribAmount" in str(exc.value)
        assert "cover.csv" in str(exc.value)


class TestFetchTecFinanceResolveCandidate:
    def _indexes(self, mod):
        return mod.build_filer_index(TEC_COVER_ROWS), mod.build_fid_index(TEC_COVER_ROWS)

    def test_auto_match(self):
        mod = _load_module("fetch_tec_auto_match", FETCH_TEC_PATH)
        last_index, fid_index = self._indexes(mod)
        log = []
        result = mod.resolve_candidate(
            "abbott-greg", {"name": "Greg Abbott", "office": "Governor of Texas"}, last_index, fid_index, log
        )
        assert result is not None
        assert result["filer_id"] == "00019652"
        assert mod.parse_amount(result["row"]["totalExpendAmount"]) == 42592.76
        assert any(line.startswith("MATCHED abbott-greg") for line in log)

    def test_manual_override(self):
        mod = _load_module("fetch_tec_override", FETCH_TEC_PATH)
        last_index, fid_index = self._indexes(mod)
        log = []
        result = mod.resolve_candidate(
            "hinojosa-gina", {"name": "Gina Hinojosa", "office": "Governor of Texas"}, last_index, fid_index, log
        )
        assert result is not None
        assert result["filer_id"] == "00080440"
        assert mod.parse_amount(result["row"]["totalContribAmount"]) == 951069.37
        assert any(line.startswith("OVERRIDE hinojosa-gina") for line in log)

    def test_ambiguous_match_is_skipped(self):
        mod = _load_module("fetch_tec_ambiguous", FETCH_TEC_PATH)
        last_index, fid_index = self._indexes(mod)
        log = []
        result = mod.resolve_candidate(
            "smith-john", {"name": "John Smith", "office": "Attorney General of Texas"}, last_index, fid_index, log
        )
        assert result is None
        assert any(line.startswith("AMBIGUOUS smith-john") for line in log)

    def test_no_match_is_skipped(self):
        mod = _load_module("fetch_tec_no_match", FETCH_TEC_PATH)
        last_index, fid_index = self._indexes(mod)
        log = []
        result = mod.resolve_candidate(
            "nobody-real", {"name": "Nobody Realname", "office": "Whatever"}, last_index, fid_index, log
        )
        assert result is None
        assert any(line.startswith("NO MATCH nobody-real") for line in log)


class TestFetchTecFinanceAmountsAndDates:
    def test_parse_amount_blank_when_zero_convention(self):
        mod = _load_module("fetch_tec_amounts", FETCH_TEC_PATH)
        assert mod.parse_amount("") == 0.0
        assert mod.parse_amount(None) == 0.0
        assert mod.parse_amount("42592.76") == 42592.76

    def test_iso_date(self):
        mod = _load_module("fetch_tec_dates", FETCH_TEC_PATH)
        assert mod.iso_date("20260221") == "2026-02-21"
        assert mod.iso_date("") is None
        assert mod.iso_date(None) is None


# ---------------------------------------------------------------------------
# fetch_tec_finance.py: HTTPRangeFile._fetch_range retry retrofit
# ---------------------------------------------------------------------------


class _FakeRangeResponse:
    def __init__(self, status_code: int = 206, content: bytes = b"payload-bytes"):
        self.status_code = status_code
        self.content = content

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"status {self.status_code}")


class _FlakySession:
    """Fails `fail_times` calls with a connection error, then succeeds."""

    def __init__(self, fail_times: int, content: bytes = b"payload-bytes"):
        self.fail_times = fail_times
        self.calls = 0
        self.content = content

    def get(self, url, headers=None, timeout=None):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise requests.exceptions.ConnectionError("simulated flaky network")
        return _FakeRangeResponse(content=self.content)


def _fast_retry_call(fn, *, retries=3, backoff=1.5, **kwargs):
    """Same retry_call, but with sleep_fn forced to a no-op so retry tests
    against the real backoff (1.5s, 3s, ...) don't slow down the suite."""
    return lib_fetch.retry_call(fn, retries=retries, backoff=backoff, sleep_fn=lambda s: None, **kwargs)


class TestFetchRangeRetryRetrofit:
    def test_retries_then_succeeds(self, monkeypatch):
        mod = _load_module("fetch_tec_range_ok", FETCH_TEC_PATH)
        monkeypatch.setattr(mod, "retry_call", _fast_retry_call)
        session = _FlakySession(fail_times=1)
        rf = mod.HTTPRangeFile("http://example.test/TEC_CF_CSV.zip", session, size=1000)

        data = rf._fetch_range(0, 9)

        assert data == b"payload-bytes"
        assert session.calls == 2  # one failure, one success
        assert rf.request_count == 1  # one logical range request, regardless of retries

    def test_exhausts_retries_and_raises(self, monkeypatch):
        mod = _load_module("fetch_tec_range_fail", FETCH_TEC_PATH)
        monkeypatch.setattr(mod, "retry_call", _fast_retry_call)
        session = _FlakySession(fail_times=999)
        rf = mod.HTTPRangeFile("http://example.test/TEC_CF_CSV.zip", session, size=1000)

        with pytest.raises(lib_fetch.FetchError):
            rf._fetch_range(0, 9)

        assert session.calls == 3  # default retries=3
        assert rf.request_count == 0  # never counted -- it never succeeded


# ---------------------------------------------------------------------------
# Idempotent no-op rerun: covered live (not fixture-based) in the task's own
# verification step -- `python3 pipeline/fetch_tec_finance.py` against the
# real, already-fully-populated data/tx/candidates.json reports "Nothing to
# do" and performs no network fetch. Kept out of this fixture-only suite
# since it depends on real repo data state rather than an embedded fixture.
# ---------------------------------------------------------------------------
