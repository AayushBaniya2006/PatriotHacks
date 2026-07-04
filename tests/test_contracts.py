from __future__ import annotations

import importlib
import json
import os
import re
import sqlite3
import sys
import warnings
from pathlib import Path
from typing import Any

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_TX = REPO_ROOT / "data" / "tx"
RACES_JSON = DATA_TX / "races.json"
CANDIDATES_JSON = DATA_TX / "candidates.json"
APP_DB = DATA_TX / "app.db"
INSIGHTS_DIR = DATA_TX / "insights"

TX_DISTRICT_RE = re.compile(r"^TX-\d{2}$")
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
URL_RE = re.compile(r"^https?://")

with warnings.catch_warnings():
    warnings.simplefilter("ignore", pytest.PytestUnknownMarkWarning)
    network = pytest.mark.network


def _require_file(path: Path) -> None:
    if not path.exists():
        pytest.skip(f"required file does not exist yet: {path.relative_to(REPO_ROOT)}")


def _load_json_file(path: Path) -> Any:
    _require_file(path)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        pytest.fail(f"{path.relative_to(REPO_ROOT)} is not valid JSON: {exc}")
    except OSError as exc:
        pytest.fail(f"{path.relative_to(REPO_ROOT)} could not be read: {exc}")


def _assert_source_url(value: Any, context: str) -> None:
    assert isinstance(value, str) and URL_RE.match(value), f"{context} must carry an http(s) source URL"


def _race_list(races_doc: Any) -> list[dict[str, Any]]:
    assert isinstance(races_doc, dict), "races.json must be a JSON object"
    races = races_doc.get("races")
    assert isinstance(races, list), "races.json must contain a races list"
    return races


def _candidate_map(candidates_doc: Any) -> dict[str, Any]:
    assert isinstance(candidates_doc, dict), "candidates.json must be keyed by candidate slug"
    return candidates_doc


def test_gold_data_contracts() -> None:
    races = _race_list(_load_json_file(RACES_JSON))
    candidates = _candidate_map(_load_json_file(CANDIDATES_JSON))

    for candidate_id, candidate in candidates.items():
        assert SLUG_RE.match(candidate_id), f"candidate key is not a slug: {candidate_id}"
        assert isinstance(candidate, dict), f"candidate {candidate_id} must be an object"

        if "finance" in candidate and candidate["finance"] is not None:
            finance = candidate["finance"]
            assert isinstance(finance, dict), f"{candidate_id}.finance must be an object"
            _assert_source_url(finance.get("source"), f"{candidate_id}.finance")

        record = candidate.get("record")
        if record is not None:
            assert isinstance(record, dict), f"{candidate_id}.record must be an object"
            key_votes = record.get("key_votes", [])
            assert isinstance(key_votes, list), f"{candidate_id}.record.key_votes must be a list"
            for idx, vote in enumerate(key_votes):
                assert isinstance(vote, dict), f"{candidate_id}.record.key_votes[{idx}] must be an object"
                _assert_source_url(vote.get("source"), f"{candidate_id}.record.key_votes[{idx}]")

        positions = candidate.get("positions", [])
        assert isinstance(positions, list), f"{candidate_id}.positions must be a list"
        for idx, position in enumerate(positions):
            assert isinstance(position, dict), f"{candidate_id}.positions[{idx}] must be an object"
            _assert_source_url(position.get("source"), f"{candidate_id}.positions[{idx}]")

    for idx, race in enumerate(races):
        assert isinstance(race, dict), f"races[{idx}] must be an object"
        for field in ("race_id", "office", "level"):
            assert race.get(field), f"races[{idx}] must have {field}"

        district = race.get("district")
        assert district is None or TX_DISTRICT_RE.match(district), (
            f"{race.get('race_id', f'races[{idx}]')}.district must be null or TX-NN"
        )

        candidate_ids = race.get("candidate_ids")
        assert isinstance(candidate_ids, list), f"{race['race_id']}.candidate_ids must be a list"
        for candidate_id in candidate_ids:
            assert candidate_id in candidates, f"{race['race_id']} references missing candidate {candidate_id}"


def test_sqlite_contract_matches_gold_json() -> None:
    _require_file(APP_DB)
    races = _race_list(_load_json_file(RACES_JSON))
    candidates = _candidate_map(_load_json_file(CANDIDATES_JSON))

    expected_columns = {
        "races": {"race_id", "office", "level", "district", "context"},
        "candidates": {
            "candidate_id",
            "name",
            "party",
            "office",
            "district",
            "incumbent",
            "fec_id",
            "finance",
            "record",
            "positions",
            "sources",
        },
        "race_candidates": {"race_id", "candidate_id"},
    }

    try:
        conn = sqlite3.connect(f"file:{APP_DB}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
    except sqlite3.Error as exc:
        pytest.fail(f"could not open data/tx/app.db read-only: {exc}")

    try:
        for table, columns in expected_columns.items():
            rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
            actual = {row["name"] for row in rows}
            assert columns <= actual, f"{table} missing columns: {sorted(columns - actual)}"

        race_count = conn.execute("SELECT COUNT(*) FROM races").fetchone()[0]
        candidate_count = conn.execute("SELECT COUNT(*) FROM candidates").fetchone()[0]
        race_candidate_count = conn.execute("SELECT COUNT(*) FROM race_candidates").fetchone()[0]

        assert race_count == len(races)
        assert candidate_count == len(candidates)
        assert race_candidate_count == sum(len(race.get("candidate_ids", [])) for race in races)

        tx35_rows = conn.execute(
            """
            SELECT c.candidate_id
            FROM races r
            JOIN race_candidates rc ON rc.race_id = r.race_id
            JOIN candidates c ON c.candidate_id = rc.candidate_id
            WHERE r.district = ?
            """,
            ("TX-35",),
        ).fetchall()
        assert tx35_rows, "TX-35 ballot join must return candidates"
    finally:
        conn.close()


def test_insight_files_contract() -> None:
    if not INSIGHTS_DIR.exists():
        pytest.skip("required directory does not exist yet: data/tx/insights")

    insight_files = sorted(INSIGHTS_DIR.glob("*.json"))
    if not insight_files:
        pytest.skip("no insight JSON files exist yet under data/tx/insights")

    for path in insight_files:
        payload = _load_json_file(path)
        assert isinstance(payload, dict), f"{path.relative_to(REPO_ROOT)} must contain a JSON object"
        assert payload.get("race_id") == path.stem, f"{path.name} race_id must match filename"

        base = payload.get("base")
        assert isinstance(base, dict), f"{path.name} must contain base object"
        candidates = base.get("candidates")
        assert isinstance(candidates, dict), f"{path.name} base.candidates must be an object"

        for candidate_id, bullets in candidates.items():
            assert isinstance(bullets, list), f"{path.name} base.candidates.{candidate_id} must be a list"
            for idx, bullet in enumerate(bullets):
                assert isinstance(bullet, dict), (
                    f"{path.name} base.candidates.{candidate_id}[{idx}] must be an object"
                )
                assert isinstance(bullet.get("text"), str) and bullet["text"].strip(), (
                    f"{path.name} base.candidates.{candidate_id}[{idx}].text must be non-empty"
                )
                _assert_source_url(
                    bullet.get("source"), f"{path.name} base.candidates.{candidate_id}[{idx}]"
                )


def _test_client() -> Any:
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))

    try:
        from fastapi.testclient import TestClient
    except (ImportError, ModuleNotFoundError) as exc:
        pytest.skip(f"FastAPI TestClient is unavailable: {exc}")

    try:
        module = importlib.import_module("app.main")
    except (ImportError, ModuleNotFoundError) as exc:
        pytest.skip(f"app.main is unavailable: {exc}")

    app = getattr(module, "app", None)
    if app is None:
        pytest.skip("app.main:app is unavailable")

    return TestClient(app)


def _first_race_id() -> str:
    if RACES_JSON.exists():
        races = _race_list(_load_json_file(RACES_JSON))
        if races:
            race_id = races[0].get("race_id")
            assert isinstance(race_id, str) and race_id.strip(), "first race must have race_id"
            return race_id

    if APP_DB.exists():
        try:
            conn = sqlite3.connect(f"file:{APP_DB}?mode=ro", uri=True)
            row = conn.execute("SELECT race_id FROM races ORDER BY race_id LIMIT 1").fetchone()
        except sqlite3.Error as exc:
            pytest.fail(f"could not read first race_id from data/tx/app.db: {exc}")
        finally:
            try:
                conn.close()
            except UnboundLocalError:
                pass
        if row is not None:
            return str(row[0])

    pytest.skip("no race_id is available yet from data/tx/races.json or data/tx/app.db")


def test_healthz() -> None:
    response = _test_client().get("/healthz")
    assert response.status_code == 200


@network
def test_ballot_for_san_marcos_address() -> None:
    if os.environ.get("NO_NETWORK") == "1":
        pytest.skip("NO_NETWORK=1")

    response = _test_client().get(
        "/api/ballot",
        params={"address": "601 University Dr, San Marcos, TX 78666"},
    )
    if response.status_code in {502, 503, 504}:
        pytest.skip(f"Census geocoder unavailable: {response.status_code} {response.text}")

    assert response.status_code == 200
    payload = response.json()
    assert TX_DISTRICT_RE.match(payload["districts"]["cd"])
    assert isinstance(payload["races"], list)


def test_insights_endpoint_returns_mode() -> None:
    race_id = _first_race_id()
    response = _test_client().post("/api/insights", json={"profile": {}, "race_id": race_id})
    assert response.status_code == 200
    assert response.json().get("mode") in {"cached", "live", "unavailable"}
