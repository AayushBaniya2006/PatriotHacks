from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx


DEFAULT_BASE_URL = "http://127.0.0.1:8000"
ADDRESSES = [
    "601 University Dr, San Marcos, TX 78666",
    "1100 Congress Ave, Austin, TX 78701",
    "901 Bagby St, Houston, TX 77002",
]
REQUEST_TIMEOUT = httpx.Timeout(15.0, connect=5.0)
HEALTH_TIMEOUT_SECONDS = 30.0

REPO_ROOT = Path(__file__).resolve().parents[1]
CACHE_ROOT = REPO_ROOT / "data" / "demo_cache"

HOMEOWNER_PARENT_PROFILE = {
    "occupation": "public school teacher",
    "age_bracket": "35-44",
    "income_bracket": "75000-100000",
    "homeowner": True,
    "renter": False,
    "kids_public_school": True,
    "health_coverage": "employer",
    "veteran": False,
    "small_business_owner": False,
    "student": False,
}


@dataclass
class ResponseResult:
    ok: bool
    payload: Any
    status_code: int | None = None
    error: str | None = None


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "item"


def _response_payload(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return {
            "status_code": response.status_code,
            "content_type": response.headers.get("content-type"),
            "body": response.text,
        }


def _save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _request_json(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    save_path: Path,
    **kwargs: Any,
) -> ResponseResult:
    try:
        response = client.request(method, url, **kwargs)
    except httpx.HTTPError as exc:
        payload = {"error": str(exc), "method": method, "url": str(client.base_url.join(url))}
        _save_json(save_path, payload)
        return ResponseResult(ok=False, payload=payload, error=str(exc))

    payload = _response_payload(response)
    _save_json(save_path, payload)

    if response.is_error:
        return ResponseResult(
            ok=False,
            payload=payload,
            status_code=response.status_code,
            error=f"HTTP {response.status_code}",
        )
    return ResponseResult(ok=True, payload=payload, status_code=response.status_code)


def _healthz_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/healthz"


def _server_is_healthy(base_url: str) -> bool:
    try:
        response = httpx.get(_healthz_url(base_url), timeout=httpx.Timeout(2.0, connect=1.0))
    except httpx.HTTPError:
        return False
    return response.status_code == 200


def _uvicorn_command(base_url: str) -> list[str]:
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", ""}:
        raise RuntimeError("--serve only supports http base URLs")
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 8000
    return [sys.executable, "-m", "uvicorn", "app.main:app", "--host", host, "--port", str(port)]


def _start_server_if_needed(base_url: str) -> subprocess.Popen[bytes] | None:
    if _server_is_healthy(base_url):
        return None

    command = _uvicorn_command(base_url)
    print(f"Starting local server: {' '.join(command)}", file=sys.stderr)
    process = subprocess.Popen(command, cwd=REPO_ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    deadline = time.monotonic() + HEALTH_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(
                "uvicorn exited before /healthz became ready; run the command manually for logs: "
                + " ".join(command)
            )
        if _server_is_healthy(base_url):
            return process
        time.sleep(0.5)

    _stop_server(process)
    raise RuntimeError(f"server did not answer {_healthz_url(base_url)} within {HEALTH_TIMEOUT_SECONDS:.0f}s")


def _stop_server(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _race_id_from_ballot_race(race: Any) -> str | None:
    if not isinstance(race, dict):
        return None
    race_id = race.get("race_id") or race.get("id")
    return race_id if isinstance(race_id, str) and race_id else None


def _process_address(client: httpx.Client, address: str) -> bool:
    address_dir = CACHE_ROOT / _slug(address)
    print(f"Precaching {address}", file=sys.stderr)

    ballot = _request_json(
        client,
        "GET",
        "/api/ballot",
        params={"address": address},
        save_path=address_dir / "ballot.json",
    )
    if not ballot.ok:
        print(f"  ballot failed for {address}: {ballot.error}", file=sys.stderr)
        return False

    if not isinstance(ballot.payload, dict):
        print(f"  ballot response was not a JSON object for {address}", file=sys.stderr)
        return False

    races = ballot.payload.get("races")
    if not isinstance(races, list) or not races:
        print(f"  ballot returned no races for {address}", file=sys.stderr)
        return False

    insight_successes = 0
    insight_attempts = 0
    for index, race in enumerate(races, start=1):
        race_id = _race_id_from_ballot_race(race)
        if race_id is None:
            print(f"  skipping race #{index}: missing race_id/id", file=sys.stderr)
            continue

        insight_attempts += 1
        result = _request_json(
            client,
            "POST",
            "/api/insights",
            json={"profile": HOMEOWNER_PARENT_PROFILE, "race_id": race_id},
            save_path=address_dir / f"insights_{_slug(race_id)}.json",
        )
        if result.ok:
            insight_successes += 1
        else:
            print(f"  insights failed for {race_id}: {result.error}", file=sys.stderr)

    if insight_attempts == 0:
        print(f"  no insight calls could be attempted for {address}", file=sys.stderr)
        return False
    if insight_successes == 0:
        print(f"  all insight calls failed for {address}", file=sys.stderr)
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Warm demo ballot and insight responses into data/demo_cache.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help=f"API base URL, default {DEFAULT_BASE_URL}")
    parser.add_argument(
        "--serve",
        action="store_true",
        help="Start uvicorn app.main:app if the base URL is not already healthy.",
    )
    args = parser.parse_args(argv)

    base_url = args.base_url.rstrip("/")
    server_process: subprocess.Popen[bytes] | None = None
    failures: list[str] = []

    try:
        if args.serve:
            server_process = _start_server_if_needed(base_url)

        with httpx.Client(base_url=base_url, timeout=REQUEST_TIMEOUT) as client:
            for address in ADDRESSES:
                if not _process_address(client, address):
                    failures.append(address)
    except KeyboardInterrupt:
        print("Interrupted; stopping local server if this script started it.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"Fatal error: {exc}", file=sys.stderr)
        return 1
    finally:
        _stop_server(server_process)

    if failures:
        print("Addresses that failed completely:", file=sys.stderr)
        for address in failures:
            print(f"  - {address}", file=sys.stderr)
        return 1

    print(f"Demo cache written under {CACHE_ROOT.relative_to(REPO_ROOT)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
