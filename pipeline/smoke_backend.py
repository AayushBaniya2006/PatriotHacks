"""Rerunnable smoke test for the FastAPI backend.

Uses FastAPI's TestClient (sync, wraps httpx) so we can exercise the app
in-process. Prints PASS/FAIL per assertion and exits nonzero if anything
failed.

Checks:
  1. GET /healthz -> 200, sane shape.
  2. GET / -> 200 serving HTML (tolerates 404 if the frontend agent hasn't
     written app/static/index.html yet -- that's a timing gap, not a bug here).
  3. GET /api/ballot for a real San Marcos address -- LIVE call to the Census
     geocoder on the first hit; districts.cd must match ^TX-\\d{2}$.
  4. A second identical call must be served from data/cache.db (no live
     geocoder round trip) -- verified by checking the cache row exists and
     the response is unchanged.
  5. POST /api/insights -> mode is one of {cached, live, unavailable}.

Run:
    python3 pipeline/smoke_backend.py
"""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from app import datastore  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}" + (f" -- {detail}" if detail and not condition else ""))
    if not condition:
        failures.append(label)


def main() -> int:
    # 1. GET /healthz
    resp = client.get("/healthz")
    check("GET /healthz returns 200", resp.status_code == 200, f"status={resp.status_code}")
    if resp.status_code == 200:
        body = resp.json()
        check("healthz has status='ok'", body.get("status") == "ok", f"body={body}")
        check("healthz has data_loaded key", "data_loaded" in body, f"body={body}")
        check("healthz has races/candidates/insights_cached counts", {"races", "candidates", "insights_cached"} <= set(body.keys()), f"body={body}")
        print(f"       healthz={body}")

    # 2. GET / serves HTML (may 404 if the frontend agent hasn't written it yet).
    resp = client.get("/")
    if resp.status_code == 404:
        print("[SKIP] GET / -- app/static/index.html not written yet (frontend agent pending)")
    else:
        check("GET / returns 200", resp.status_code == 200, f"status={resp.status_code}")
        check(
            "GET / content-type is html",
            "text/html" in resp.headers.get("content-type", ""),
            f"content-type={resp.headers.get('content-type')}",
        )

    # 3. GET /api/ballot with a real San Marcos address -- live geocoder call.
    address = "601 University Dr, San Marcos, TX 78666"
    try:
        resp = client.get("/api/ballot", params={"address": address})
        check(
            "GET /api/ballot status is 200",
            resp.status_code == 200,
            f"status={resp.status_code} body={resp.text[:300]}",
        )
        if resp.status_code == 200:
            body = resp.json()
            districts = body.get("districts", {})
            check("ballot response has 'districts'", "districts" in body)
            check("ballot response has 'races' list", isinstance(body.get("races"), list))
            cd = districts.get("cd") or ""
            check(
                "districts.cd matches ^TX-\\d{2}$",
                bool(re.match(r"^TX-\d{2}$", cd)),
                f"districts={districts}",
            )
            print(f"       matched_address={body.get('matched_address')!r} districts={districts}")
            if body.get("warning"):
                print(f"       warning={body['warning']!r} (expected until data/tx/*.json or app.db are populated)")

            # 4. Verify the address landed in data/cache.db, and a second call
            #    is served from cache (same result, and the cache row's ts
            #    does not advance because we don't re-write on a cache hit).
            cached_row = datastore.geocode_cache_get(address)
            check("address_norm cached in data/cache.db after first lookup", cached_row is not None)
            if cached_row is not None:
                ts_before = cached_row["ts"]
                time.sleep(0.05)
                resp2 = client.get("/api/ballot", params={"address": address})
                check("second GET /api/ballot (cache hit) returns 200", resp2.status_code == 200)
                if resp2.status_code == 200:
                    body2 = resp2.json()
                    check(
                        "cached response districts match first response",
                        body2.get("districts") == districts,
                        f"first={districts} second={body2.get('districts')}",
                    )
                cached_row_after = datastore.geocode_cache_get(address)
                check(
                    "cache row unchanged (ts not re-written) on cache-hit path",
                    cached_row_after is not None and cached_row_after["ts"] == ts_before,
                    f"ts_before={ts_before} ts_after={cached_row_after and cached_row_after['ts']}",
                )
    except Exception as exc:  # pragma: no cover - network flakiness path
        check("GET /api/ballot completed without exception", False, f"{type(exc).__name__}: {exc}")

    # 5. POST /api/insights -> mode in {cached, live, unavailable}.
    resp = client.post("/api/insights", json={"profile": {}, "race_id": "tx-gov-2026"})
    check(
        "POST /api/insights returns 200",
        resp.status_code == 200,
        f"status={resp.status_code} body={resp.text[:300]}",
    )
    if resp.status_code == 200:
        body = resp.json()
        mode = body.get("mode")
        check(
            "insights mode in {cached, live, unavailable}",
            mode in ("cached", "live", "unavailable"),
            f"body={body}",
        )
        print(f"       insights mode={mode!r}")

    print()
    if failures:
        print(f"{len(failures)} check(s) FAILED: {failures}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
