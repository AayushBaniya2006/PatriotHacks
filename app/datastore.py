"""The ONLY data-access layer for the app. Endpoints never touch files directly.

Storage contract:
  - Primary: SQLite data/tx/app.db, opened READ-ONLY. Written by the merge/data
    agent, not by us. Tables:
      races(race_id PK, office, level, district, context JSON-text)
      candidates(candidate_id PK, name, party, office, district, incumbent,
                 fec_id, finance JSON-text, record JSON-text, positions JSON-text,
                 sources JSON-text)
      race_candidates(race_id, candidate_id)
    Indexes on district/level/name (created by the writer; we don't assume).
  - Fallback: if data/tx/app.db is missing, fall back to flat JSON files
    data/tx/races.json + data/tx/candidates.json (see CLAUDE.md schema).
  - If NEITHER exists, the app must still start cleanly: every query returns
    empty results and stats()/get_ballot() surface a data_pending flag.

Insights: data/tx/insights/{race_id}.json, parsed and returned as-is, or None
if the file doesn't exist / doesn't parse.

Geocode cache: a SEPARATE sqlite file data/cache.db (address_norm PK -> cd, sd,
hd, county, matched_address, ts) so repeat addresses never hit the live
geocoder. This file is read-write (unlike app.db) and is gitignored.

Caching: ballot assembly is memoized via functools.lru_cache keyed on
(cd, sd, hd) so repeated lookups for the same district triple are free.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data" / "tx"
DB_PATH = DATA_DIR / "app.db"
RACES_JSON_PATH = DATA_DIR / "races.json"
CANDIDATES_JSON_PATH = DATA_DIR / "candidates.json"
INSIGHTS_DIR = DATA_DIR / "insights"

CACHE_DB_PATH = REPO_ROOT / "data" / "cache.db"


# ---------------------------------------------------------------------------
# Low-level storage backends
# ---------------------------------------------------------------------------


def _db_available() -> bool:
    return DB_PATH.exists()


def _json_available() -> bool:
    return RACES_JSON_PATH.exists() and CANDIDATES_JSON_PATH.exists()


def data_is_pending() -> bool:
    """True if we have neither a SQLite db nor the JSON fallback files."""
    return not _db_available() and not _json_available()


def _open_db_ro() -> Optional[sqlite3.Connection]:
    if not _db_available():
        return None
    try:
        # Read-only URI connection so we never accidentally write to a db
        # owned by the merge agent.
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error:
        return None


def _parse_json_field(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return default
    return default


def _race_row_to_dict(row: sqlite3.Row, candidate_ids: list[str]) -> dict[str, Any]:
    return {
        "race_id": row["race_id"],
        "office": row["office"],
        "level": row["level"],
        "district": row["district"],
        "context": _parse_json_field(row["context"], {}),
        "candidate_ids": candidate_ids,
    }


def _candidate_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "candidate_id": row["candidate_id"],
        "name": row["name"],
        "party": row["party"],
        "office": row["office"],
        "district": row["district"],
        "incumbent": bool(row["incumbent"]) if row["incumbent"] is not None else None,
        "fec_id": row["fec_id"],
        "finance": _parse_json_field(row["finance"], {}),
        "record": _parse_json_field(row["record"], {}),
        "positions": _parse_json_field(row["positions"], []),
        "sources": _parse_json_field(row["sources"], []),
    }


# ---------------------------------------------------------------------------
# JSON fallback loaders (mtime-aware so edits during dev are picked up)
# ---------------------------------------------------------------------------


class _JsonFileCache:
    def __init__(self, path: Path, default: Any):
        self.path = path
        self.default = default
        self._mtime: Optional[float] = None
        self._data: Any = default

    def get(self) -> Any:
        try:
            mtime = self.path.stat().st_mtime
        except FileNotFoundError:
            self._mtime = None
            self._data = self.default
            return self._data
        if mtime != self._mtime:
            try:
                with self.path.open("r", encoding="utf-8") as f:
                    self._data = json.load(f)
                self._mtime = mtime
            except (json.JSONDecodeError, OSError):
                pass  # keep last-known-good data rather than crash
        return self._data


_races_json_cache = _JsonFileCache(RACES_JSON_PATH, default={"state": "TX", "races": []})
_candidates_json_cache = _JsonFileCache(CANDIDATES_JSON_PATH, default={})


def _all_races_json() -> list[dict[str, Any]]:
    data = _races_json_cache.get()
    races = data.get("races", []) if isinstance(data, dict) else []
    return races if isinstance(races, list) else []


def _all_candidates_json() -> dict[str, Any]:
    data = _candidates_json_cache.get()
    return data if isinstance(data, dict) else {}


# ---------------------------------------------------------------------------
# Public query primitives
# ---------------------------------------------------------------------------


def _all_races() -> list[dict[str, Any]]:
    """Every race, JSON-fallback-embedded candidate_ids only (no candidate data)."""
    conn = _open_db_ro()
    if conn is not None:
        try:
            rows = conn.execute("SELECT race_id, office, level, district, context FROM races").fetchall()
            races = []
            for row in rows:
                cids = [
                    r["candidate_id"]
                    for r in conn.execute(
                        "SELECT candidate_id FROM race_candidates WHERE race_id = ?", (row["race_id"],)
                    ).fetchall()
                ]
                races.append(_race_row_to_dict(row, cids))
            return races
        except sqlite3.Error:
            pass
        finally:
            conn.close()
    return _all_races_json()


def _all_candidates() -> dict[str, Any]:
    conn = _open_db_ro()
    if conn is not None:
        try:
            rows = conn.execute(
                "SELECT candidate_id, name, party, office, district, incumbent, fec_id, "
                "finance, record, positions, sources FROM candidates"
            ).fetchall()
            return {row["candidate_id"]: _candidate_row_to_dict(row) for row in rows}
        except sqlite3.Error:
            pass
        finally:
            conn.close()
    return _all_candidates_json()


def get_race(race_id: str) -> Optional[dict[str, Any]]:
    conn = _open_db_ro()
    if conn is not None:
        try:
            row = conn.execute(
                "SELECT race_id, office, level, district, context FROM races WHERE race_id = ?",
                (race_id,),
            ).fetchone()
            if row is None:
                return None
            cids = [
                r["candidate_id"]
                for r in conn.execute(
                    "SELECT candidate_id FROM race_candidates WHERE race_id = ?", (race_id,)
                ).fetchall()
            ]
            return _race_row_to_dict(row, cids)
        except sqlite3.Error:
            return None
        finally:
            conn.close()
    for race in _all_races_json():
        if race.get("race_id") == race_id:
            return race
    return None


def get_candidate(candidate_id: str) -> Optional[dict[str, Any]]:
    conn = _open_db_ro()
    if conn is not None:
        try:
            row = conn.execute(
                "SELECT candidate_id, name, party, office, district, incumbent, fec_id, "
                "finance, record, positions, sources FROM candidates WHERE candidate_id = ?",
                (candidate_id,),
            ).fetchone()
            return _candidate_row_to_dict(row) if row is not None else None
        except sqlite3.Error:
            return None
        finally:
            conn.close()
    return _all_candidates_json().get(candidate_id)


def list_races(level: Optional[str] = None) -> list[dict[str, Any]]:
    races = _all_races()
    if level is not None:
        races = [r for r in races if r.get("level") == level]
    return races


def search_candidates(q: str) -> list[dict[str, Any]]:
    q_lower = (q or "").strip().lower()
    if not q_lower:
        return []
    candidates = _all_candidates()
    return [c for c in candidates.values() if q_lower in str(c.get("name", "")).lower()]


def _embed_candidates(race: dict[str, Any], all_candidates: dict[str, Any]) -> dict[str, Any]:
    race_out = dict(race)
    embedded: dict[str, Any] = {}
    for cid in race.get("candidate_ids", []):
        embedded[cid] = all_candidates.get(cid, {"candidate_id": cid, "data_missing": True})
    race_out["candidates"] = embedded
    return race_out


@lru_cache(maxsize=512)
def _assemble_ballot(cd: Optional[str], sd: Optional[str], hd: Optional[str]) -> tuple:
    """Memoized per (cd, sd, hd). Returns a tuple (JSON-safe) of race dicts so
    lru_cache can hash/cache the result; caller converts to a list."""
    target_districts = {d for d in (cd, sd, hd) if d}
    all_candidates = _all_candidates()
    selected = []
    for race in _all_races():
        district = race.get("district")
        if district is not None and district not in target_districts:
            continue
        selected.append(_embed_candidates(race, all_candidates))
    # tuple-of-dicts is fine for lru_cache (dicts aren't hashed, only the args are)
    return tuple(selected)


def get_ballot(cd: Optional[str] = None, sd: Optional[str] = None, hd: Optional[str] = None) -> list[dict[str, Any]]:
    """Statewide races + matching district races, candidates embedded."""
    return list(_assemble_ballot(cd, sd, hd))


def get_insights(race_id: str) -> Optional[dict[str, Any]]:
    path = INSIGHTS_DIR / f"{race_id}.json"
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def stats() -> dict[str, Any]:
    races = _all_races()
    candidates = _all_candidates()
    insights_cached = 0
    if INSIGHTS_DIR.exists():
        insights_cached = len(list(INSIGHTS_DIR.glob("*.json")))
    return {
        "data_loaded": not data_is_pending(),
        "races": len(races),
        "candidates": len(candidates),
        "insights_cached": insights_cached,
    }


# ---------------------------------------------------------------------------
# Geocode cache (data/cache.db) -- separate read-write sqlite file so repeat
# addresses never hit the live Census geocoder.
# ---------------------------------------------------------------------------


def _cache_conn() -> sqlite3.Connection:
    CACHE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(CACHE_DB_PATH), check_same_thread=False)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS geocode_cache (
            address_norm TEXT PRIMARY KEY,
            cd TEXT,
            sd TEXT,
            hd TEXT,
            county TEXT,
            matched_address TEXT,
            ts REAL
        )
        """
    )
    conn.commit()
    return conn


def _normalize_address(address: str) -> str:
    return re.sub(r"\s+", " ", address.strip().lower())


def geocode_cache_get(address: str) -> Optional[dict[str, Any]]:
    norm = _normalize_address(address)
    conn = _cache_conn()
    try:
        row = conn.execute(
            "SELECT cd, sd, hd, county, matched_address, ts FROM geocode_cache WHERE address_norm = ?",
            (norm,),
        ).fetchone()
        if row is None:
            return None
        return {
            "cd": row[0],
            "sd": row[1],
            "hd": row[2],
            "county": row[3],
            "matched_address": row[4],
            "ts": row[5],
        }
    finally:
        conn.close()


def geocode_cache_put(
    address: str,
    cd: Optional[str],
    sd: Optional[str],
    hd: Optional[str],
    county: Optional[str],
    matched_address: Optional[str],
) -> None:
    norm = _normalize_address(address)
    conn = _cache_conn()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO geocode_cache "
            "(address_norm, cd, sd, hd, county, matched_address, ts) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (norm, cd, sd, hd, county, matched_address, time.time()),
        )
        conn.commit()
    finally:
        conn.close()
