"""The ONLY data-access layer for the app. Endpoints never touch storage directly.

Storage contract:
  - Primary: PostgreSQL, reached through a lazily-created connection pool
    (psycopg3 + psycopg_pool) built from the DATABASE_URL env var. Schema
    (races, candidates, race_candidates, insights, geocode_cache) is owned by
    pipeline/load_postgres.py -- this module only ever SELECTs/UPSERTs against
    tables that loader creates; it never runs DDL itself.
  - Fallback: if DATABASE_URL is unset, psycopg isn't installed, or the first
    connection attempt fails, we log ONCE and fall back to the flat gold JSON
    files data/tx/races.json + data/tx/candidates.json (see CLAUDE.md schema).
    That decision is cached for the life of the process -- we don't retry a
    dead database on every request. This fallback must always work: the demo
    runs on it with zero Postgres available.
  - If NEITHER Postgres nor the JSON files are available, the app must still
    start cleanly: every query returns empty results and stats()/get_ballot()
    surface a data_pending flag via data_is_pending().

Insights: Postgres `insights` table when Postgres is live, else
data/tx/insights/{race_id}.json parsed as-is. The table is keyed by
(race_id, archetype) -- one row per precomputed block ('base' plus each
voter archetype) -- rather than one row per race, so get_insights()
reassembles the rows for a race back into the same {race_id, base,
archetypes} shape the JSON file has, for app/main.py to consume unchanged.
Returns None if the race has no cached insights in whichever backend is
active. put_insight_block(race_id, archetype, payload) is the write-through
counterpart: called after a live LLM generation succeeds so the next
request for that (race_id, archetype) is served from cache. Each row/file
block carries an inputs_hash (compute_inputs_hash) -- sha256 over that
race's candidate data -- so a later bulk reload (pipeline/load_postgres.py)
can tell a still-fresh row from a stale one without an LLM call.

Geocode cache: Postgres `geocode_cache` table when live, else a JSON file
data/geocode_cache.json (read-write, gitignored). The JSON file is written
atomically (temp file + os.replace) so a crash mid-write can't corrupt it.
Optional Google Civic enrichment (voting_info/division_check, app/main.py +
app/google_civic.py) rides along in the same per-address cache entry via
geocode_cache_get_civic/geocode_cache_put_civic -- a civic_json column in
Postgres, a "civic_json" key in the JSON file. Both are additive and
backward-compatible: an existing cache entry simply lacks that key/column
and reads back as "not yet looked up" rather than erroring, and a Postgres
table that hasn't been migrated with the civic_json column degrades to the
JSON file for that call, same as every other Postgres failure here.

Caching: ballot assembly is memoized via functools.lru_cache keyed on
(cd, sd, hd) so repeated lookups for the same district triple are free.

Public primitives -- signatures are a contract with app/main.py, do not
change them: get_ballot, get_race, get_candidate, list_races,
search_candidates, get_insights, put_insight_block, compute_inputs_hash,
stats, geocode_cache_get, geocode_cache_put, geocode_cache_get_civic,
geocode_cache_put_civic, data_is_pending.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import logging
import os
import re
import tempfile
import threading
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

try:
    from psycopg.rows import dict_row
    from psycopg.types.json import Jsonb
    from psycopg_pool import ConnectionPool

    _PSYCOPG_IMPORT_ERROR: Optional[BaseException] = None
except ImportError as exc:  # psycopg not installed -- JSON-only mode
    dict_row = None  # type: ignore[assignment]
    Jsonb = None  # type: ignore[assignment]
    ConnectionPool = None  # type: ignore[assignment]
    _PSYCOPG_IMPORT_ERROR = exc

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data" / "tx"
RACES_JSON_PATH = DATA_DIR / "races.json"
CANDIDATES_JSON_PATH = DATA_DIR / "candidates.json"
INSIGHTS_DIR = DATA_DIR / "insights"

GEOCODE_CACHE_JSON_PATH = REPO_ROOT / "data" / "geocode_cache.json"


# ---------------------------------------------------------------------------
# Postgres pool -- lazy, single connection attempt, cached outcome
# ---------------------------------------------------------------------------

_pool: Optional["ConnectionPool"] = None
_pg_init_done = False
_pg_fallback_logged = False


def _log_fallback_once(message: str) -> None:
    global _pg_fallback_logged
    if not _pg_fallback_logged:
        logger.warning(message)
        _pg_fallback_logged = True


def _get_pool() -> Optional["ConnectionPool"]:
    """Return the shared Postgres connection pool, creating it on first call.

    Returns None (and logs exactly once) if DATABASE_URL is unset, psycopg
    isn't installed, or the initial connection attempt fails. That None
    result is cached for the process lifetime -- callers must treat it as
    "use the JSON fallback" and never raise.
    """
    global _pool, _pg_init_done
    if _pg_init_done:
        return _pool
    _pg_init_done = True

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        return None  # unset is the expected local/demo case -- not a warning

    if ConnectionPool is None:
        _log_fallback_once(
            f"DATABASE_URL is set but psycopg is not installed ({_PSYCOPG_IMPORT_ERROR}); "
            "falling back to JSON storage. Run: pip install -r requirements.txt"
        )
        return None

    pool: Optional["ConnectionPool"] = None
    try:
        pool = ConnectionPool(
            database_url,
            min_size=1,
            max_size=5,
            open=False,
            kwargs={"row_factory": dict_row, "autocommit": True},
        )
        pool.open(wait=True, timeout=5.0)
        with pool.connection(timeout=5.0) as conn:
            conn.execute("SELECT 1")
    except Exception as exc:  # noqa: BLE001 -- any failure means "use JSON fallback"
        _log_fallback_once(f"Could not connect to PostgreSQL ({exc}); falling back to JSON storage")
        if pool is not None:
            try:
                pool.close()
            except Exception:
                pass
        _pool = None
        return None

    _pool = pool
    logger.info("Connected to PostgreSQL for serving layer")
    return _pool


# ---------------------------------------------------------------------------
# Row -> dict helpers (Postgres, dict_row factory)
# ---------------------------------------------------------------------------


def _parse_json_field(value: Any, default: Any) -> Any:
    """Defensive normalizer: psycopg3 already deserializes JSONB columns into
    dict/list, but this guards against None/legacy-string edge cases without
    ever crashing a request."""
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


def _race_row_to_dict(row: dict[str, Any], candidate_ids: list[str]) -> dict[str, Any]:
    return {
        "race_id": row["race_id"],
        "office": row["office"],
        "level": row["level"],
        "district": row["district"],
        "context": _parse_json_field(row["context"], {}),
        "candidate_ids": candidate_ids,
    }


def _candidate_row_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "candidate_id": row["candidate_id"],
        "name": row["name"],
        "party": row["party"],
        "office": row["office"],
        "district": row["district"],
        "incumbent": row["incumbent"],
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


def _json_available() -> bool:
    return RACES_JSON_PATH.exists() and CANDIDATES_JSON_PATH.exists()


def _all_races_json() -> list[dict[str, Any]]:
    data = _races_json_cache.get()
    races = data.get("races", []) if isinstance(data, dict) else []
    return races if isinstance(races, list) else []


def _all_candidates_json() -> dict[str, Any]:
    data = _candidates_json_cache.get()
    return data if isinstance(data, dict) else {}


def data_is_pending() -> bool:
    """True if we have neither a live Postgres connection nor the JSON
    fallback files."""
    return _get_pool() is None and not _json_available()


# ---------------------------------------------------------------------------
# Public query primitives
# ---------------------------------------------------------------------------


def _all_races() -> list[dict[str, Any]]:
    """Every race, candidate_ids only (no candidate objects embedded)."""
    pool = _get_pool()
    if pool is not None:
        try:
            with pool.connection() as conn:
                race_rows = conn.execute(
                    "SELECT race_id, office, level, district, context FROM races"
                ).fetchall()
                rc_rows = conn.execute("SELECT race_id, candidate_id FROM race_candidates").fetchall()
            cids_by_race: dict[str, list[str]] = {}
            for rc in rc_rows:
                cids_by_race.setdefault(rc["race_id"], []).append(rc["candidate_id"])
            return [_race_row_to_dict(row, cids_by_race.get(row["race_id"], [])) for row in race_rows]
        except Exception as exc:  # noqa: BLE001
            logger.warning("Postgres races query failed (%s); falling back to JSON for this call", exc)
    return _all_races_json()


def _all_candidates() -> dict[str, Any]:
    pool = _get_pool()
    if pool is not None:
        try:
            with pool.connection() as conn:
                rows = conn.execute(
                    "SELECT candidate_id, name, party, office, district, incumbent, fec_id, "
                    "finance, record, positions, sources FROM candidates"
                ).fetchall()
            return {row["candidate_id"]: _candidate_row_to_dict(row) for row in rows}
        except Exception as exc:  # noqa: BLE001
            logger.warning("Postgres candidates query failed (%s); falling back to JSON for this call", exc)
    return _all_candidates_json()


def get_race(race_id: str) -> Optional[dict[str, Any]]:
    pool = _get_pool()
    if pool is not None:
        try:
            with pool.connection() as conn:
                row = conn.execute(
                    "SELECT race_id, office, level, district, context FROM races WHERE race_id = %s",
                    (race_id,),
                ).fetchone()
                if row is None:
                    return None
                cid_rows = conn.execute(
                    "SELECT candidate_id FROM race_candidates WHERE race_id = %s", (race_id,)
                ).fetchall()
            return _race_row_to_dict(row, [r["candidate_id"] for r in cid_rows])
        except Exception as exc:  # noqa: BLE001
            logger.warning("Postgres race query failed (%s); falling back to JSON for this call", exc)
    for race in _all_races_json():
        if race.get("race_id") == race_id:
            return race
    return None


def get_candidate(candidate_id: str) -> Optional[dict[str, Any]]:
    pool = _get_pool()
    if pool is not None:
        try:
            with pool.connection() as conn:
                row = conn.execute(
                    "SELECT candidate_id, name, party, office, district, incumbent, fec_id, "
                    "finance, record, positions, sources FROM candidates WHERE candidate_id = %s",
                    (candidate_id,),
                ).fetchone()
            return _candidate_row_to_dict(row) if row is not None else None
        except Exception as exc:  # noqa: BLE001
            logger.warning("Postgres candidate query failed (%s); falling back to JSON for this call", exc)
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
    """Embed full candidate objects into a race dict as an ARRAY (list), in
    candidate_ids order. This is a hard API-contract requirement: the
    frontend and schema.md both expect races[].candidates to be a list of
    candidate dicts, not an object keyed by candidate_id.

    Every embedded dict is guaranteed to carry "candidate_id" as a field
    (not just as a key the caller used to look it up): the Postgres-backed
    candidate rows already include it, but the JSON-fallback file
    (data/tx/candidates.json) is keyed by candidate_id without repeating it
    inside each value, so it's injected here. A copy is made rather than
    mutating in place, since JSON-fallback candidate dicts are shared/cached
    across calls."""
    race_out = dict(race)
    embedded: list[dict[str, Any]] = []
    for cid in race.get("candidate_ids", []):
        candidate = all_candidates.get(cid)
        if candidate is None:
            embedded.append({"candidate_id": cid, "data_missing": True})
        elif candidate.get("candidate_id") == cid:
            embedded.append(candidate)
        else:
            embedded.append({"candidate_id": cid, **candidate})
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
    """Reassemble a race's insight blocks into the same shape the JSON file
    has: {race_id, base: <payload of archetype='base'>, archetypes: {key:
    payload, ...}}. Postgres now stores one row per (race_id, archetype)
    block rather than one row per race (see pipeline/load_postgres.py's DDL
    comment), so this does one SELECT for the whole race and reassembles --
    app/main.py's _select_cached_bullets is unaware of the split and keeps
    reading cached["base"] / cached["archetypes"][archetype] exactly as
    before. Returns None if the race has no rows/file at all (not merely an
    empty one) -- same "no cached insights" contract as before.
    """
    pool = _get_pool()
    if pool is not None:
        try:
            with pool.connection() as conn:
                rows = conn.execute(
                    "SELECT archetype, payload FROM insights WHERE race_id = %s", (race_id,)
                ).fetchall()
            if rows:
                base_payload: Any = None
                archetypes_payload: dict[str, Any] = {}
                for row in rows:
                    payload = _parse_json_field(row["payload"], {})
                    if row["archetype"] == "base":
                        base_payload = payload
                    else:
                        archetypes_payload[row["archetype"]] = payload
                return {"race_id": race_id, "base": base_payload, "archetypes": archetypes_payload}
            return None
        except Exception as exc:  # noqa: BLE001
            logger.warning("Postgres insights query failed (%s); falling back to file for this call", exc)
    path = INSIGHTS_DIR / f"{race_id}.json"
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def compute_inputs_hash(race_id: str) -> str:
    """sha256 hex digest over this race's candidates' canonical JSON
    (json.dumps with sort_keys=True) -- the same algorithm
    pipeline/load_postgres.py uses (computed there directly from the
    on-disk gold JSON; here via the normal get_race/get_candidate
    primitives, Postgres if live else the JSON fallback, since this runs
    inside an already-serving process rather than a bulk loader). Used to
    hash-gate insight regeneration: unchanged candidate data means an
    unchanged hash, so a stored row/block can be recognized as still fresh.

    The "candidate_id" field is stripped from each candidate dict before
    hashing, since it's a storage-shape artifact (Postgres rows carry it
    explicitly via _candidate_row_to_dict; the raw candidates.json value
    does not) that must not perturb the hash -- keep this normalization in
    sync with pipeline/load_postgres.py's own copy of this algorithm.
    """
    race = get_race(race_id) or {}
    payload: dict[str, Any] = {}
    for cid in race.get("candidate_ids", []):
        candidate = get_candidate(cid)
        if candidate is None:
            continue
        payload[cid] = {k: v for k, v in candidate.items() if k != "candidate_id"}
    canonical = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


_insights_file_lock = threading.Lock()


def _put_insight_block_json(race_id: str, archetype: str, payload: dict[str, Any]) -> None:
    """JSON-fallback half of put_insight_block: atomically merge one block
    into data/tx/insights/{race_id}.json, creating the file if it doesn't
    exist yet. Only the targeted block ("base" or archetypes[archetype]) is
    set; everything else already in the file is preserved untouched."""
    path = INSIGHTS_DIR / f"{race_id}.json"
    with _insights_file_lock:
        doc: dict[str, Any] = {}
        if path.exists():
            try:
                with path.open("r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    doc = loaded
            except (json.JSONDecodeError, OSError):
                pass  # treat an unreadable file as absent rather than crash
        doc.setdefault("race_id", race_id)
        doc.setdefault("generated_at", datetime.date.today().isoformat())

        if archetype == "base":
            doc["base"] = payload
        else:
            archetypes = doc.get("archetypes")
            if not isinstance(archetypes, dict):
                archetypes = {}
            archetypes[archetype] = payload
            doc["archetypes"] = archetypes

        INSIGHTS_DIR.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=str(INSIGHTS_DIR), prefix=f".{path.stem}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(doc, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, path)
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise


def put_insight_block(race_id: str, archetype: str, payload: dict[str, Any]) -> None:
    """Write-through cache: persist one (race_id, archetype) insight block
    right after a live LLM generation succeeds, so the next request for the
    same (race_id, archetype) is served from cache instead of calling the
    LLM again. Postgres upsert (latest-wins, inputs_hash recomputed fresh)
    when live; otherwise an atomic merge into the JSON file. Never raises on
    a Postgres failure -- falls back to the JSON file for that call, same
    policy as every other write path in this module; callers should still
    treat this as best-effort (see app/main.py, which logs rather than
    fails the request if this itself raises)."""
    pool = _get_pool()
    if pool is not None:
        try:
            inputs_hash = compute_inputs_hash(race_id)
            with pool.connection() as conn:
                conn.execute(
                    """
                    INSERT INTO insights (race_id, archetype, payload, inputs_hash)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (race_id, archetype) DO UPDATE SET
                        payload = EXCLUDED.payload,
                        inputs_hash = EXCLUDED.inputs_hash,
                        generated_at = now()
                    """,
                    (race_id, archetype, Jsonb(payload), inputs_hash),
                )
            return
        except Exception as exc:  # noqa: BLE001
            logger.warning("Postgres insights write failed (%s); falling back to JSON file", exc)
    _put_insight_block_json(race_id, archetype, payload)


def _count_insights() -> int:
    """Count of races with cached insights (not row/block count) -- kept
    consistent between backends: Postgres now has multiple rows per race
    (one per archetype block), so this counts DISTINCT race_id to match the
    JSON fallback's "one file per race" count."""
    pool = _get_pool()
    if pool is not None:
        try:
            with pool.connection() as conn:
                row = conn.execute("SELECT COUNT(DISTINCT race_id) AS n FROM insights").fetchone()
            return int(row["n"]) if row is not None else 0
        except Exception as exc:  # noqa: BLE001
            logger.warning("Postgres insights count failed (%s); falling back to file count", exc)
    if INSIGHTS_DIR.exists():
        return len(list(INSIGHTS_DIR.glob("*.json")))
    return 0


def stats() -> dict[str, Any]:
    races = _all_races()
    candidates = _all_candidates()
    return {
        "data_loaded": not data_is_pending(),
        "races": len(races),
        "candidates": len(candidates),
        "insights_cached": _count_insights(),
    }


# ---------------------------------------------------------------------------
# Geocode cache -- Postgres geocode_cache table when live, else a JSON file
# (data/geocode_cache.json, gitignored) so repeat addresses never hit the
# live Census geocoder.
# ---------------------------------------------------------------------------

_geocode_cache_file_lock = threading.Lock()


def _normalize_address(address: str) -> str:
    return re.sub(r"\s+", " ", address.strip().lower())


def _load_geocode_cache_json() -> dict[str, Any]:
    try:
        with GEOCODE_CACHE_JSON_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except (json.JSONDecodeError, OSError):
        return {}


def _write_geocode_cache_json(data: dict[str, Any]) -> None:
    """Atomic write: write to a temp file in the same directory, then
    os.replace() so a crash mid-write never corrupts the cache file."""
    GEOCODE_CACHE_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(GEOCODE_CACHE_JSON_PATH.parent), prefix=".geocode_cache.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp_path, GEOCODE_CACHE_JSON_PATH)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def geocode_cache_get(address: str) -> Optional[dict[str, Any]]:
    norm = _normalize_address(address)
    pool = _get_pool()
    if pool is not None:
        try:
            with pool.connection() as conn:
                row = conn.execute(
                    "SELECT matched_address, cd, sd, hd, county, created_at "
                    "FROM geocode_cache WHERE address_norm = %s",
                    (norm,),
                ).fetchone()
            if row is None:
                return None
            created_at = row["created_at"]
            return {
                "cd": row["cd"],
                "sd": row["sd"],
                "hd": row["hd"],
                "county": row["county"],
                "matched_address": row["matched_address"],
                "ts": created_at.timestamp() if created_at is not None else None,
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("Postgres geocode_cache read failed (%s); falling back to JSON file", exc)
    with _geocode_cache_file_lock:
        return _load_geocode_cache_json().get(norm)


def geocode_cache_put(
    address: str,
    cd: Optional[str],
    sd: Optional[str],
    hd: Optional[str],
    county: Optional[str],
    matched_address: Optional[str],
) -> None:
    norm = _normalize_address(address)
    pool = _get_pool()
    if pool is not None:
        try:
            with pool.connection() as conn:
                conn.execute(
                    """
                    INSERT INTO geocode_cache (address_norm, matched_address, cd, sd, hd, county)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (address_norm) DO UPDATE SET
                        matched_address = EXCLUDED.matched_address,
                        cd = EXCLUDED.cd,
                        sd = EXCLUDED.sd,
                        hd = EXCLUDED.hd,
                        county = EXCLUDED.county
                    """,
                    (norm, matched_address, cd, sd, hd, county),
                )
            return
        except Exception as exc:  # noqa: BLE001
            logger.warning("Postgres geocode_cache write failed (%s); falling back to JSON file", exc)
    with _geocode_cache_file_lock:
        cache = _load_geocode_cache_json()
        cache[norm] = {
            "cd": cd,
            "sd": sd,
            "hd": hd,
            "county": county,
            "matched_address": matched_address,
            "ts": time.time(),
        }
        _write_geocode_cache_json(cache)


# ---------------------------------------------------------------------------
# Optional Google Civic enrichment cache -- rides along on the same
# per-address entry as the geocode cache above (civic_json column/key).
# Entirely additive: app/main.py only ever calls these when
# GOOGLE_CIVIC_API_KEY is set, so with no key nothing here is ever invoked
# and no cache entry ever gains a civic_json key/column.
# ---------------------------------------------------------------------------


def geocode_cache_get_civic(address: str) -> Optional[dict[str, Any]]:
    """Cached {"voting_info", "division_check"} for this normalized address,
    or None if it has never been looked up (a genuine cache miss -- the
    caller should fetch it). A known "no coverage" address is cached as
    {"voting_info": None, "division_check": None} by geocode_cache_put_civic
    and returned here as that same (non-None) dict, so it's never re-fetched
    from the Civic API.

    Postgres: if the geocode_cache table hasn't been migrated with a
    civic_json column yet, the query raises and is caught exactly like every
    other Postgres failure in this module -- falls back to the JSON file for
    this call rather than breaking the geocode cache (missing column
    handled, per the module docstring)."""
    norm = _normalize_address(address)
    pool = _get_pool()
    if pool is not None:
        try:
            with pool.connection() as conn:
                row = conn.execute(
                    "SELECT civic_json FROM geocode_cache WHERE address_norm = %s",
                    (norm,),
                ).fetchone()
            if row is None:
                return None
            return _parse_json_field(row["civic_json"], None)
        except Exception as exc:  # noqa: BLE001 -- e.g. undefined column civic_json
            logger.warning("Postgres geocode_cache civic_json read failed (%s); falling back to JSON file", exc)
    with _geocode_cache_file_lock:
        entry = _load_geocode_cache_json().get(norm)
    if not isinstance(entry, dict):
        return None
    civic = entry.get("civic_json")
    return civic if isinstance(civic, dict) else None


def geocode_cache_put_civic(address: str, civic_json: dict[str, Any]) -> None:
    """Write-through counterpart to geocode_cache_get_civic. Atomic on the
    JSON-file path (temp file + os.replace, same as every other write in
    this module) and best-effort throughout -- never raises to the caller.

    Assumes a base geocode_cache row for this address already exists:
    app/main.py always resolves and caches districts before ever calling
    this. If it doesn't (Postgres live but no such row), the UPDATE below
    simply affects zero rows rather than erroring; the JSON-file branch
    still records the civic data under this address's key either way."""
    norm = _normalize_address(address)
    pool = _get_pool()
    if pool is not None:
        try:
            with pool.connection() as conn:
                conn.execute(
                    "UPDATE geocode_cache SET civic_json = %s WHERE address_norm = %s",
                    (Jsonb(civic_json), norm),
                )
            return
        except Exception as exc:  # noqa: BLE001 -- e.g. undefined column civic_json
            logger.warning("Postgres geocode_cache civic_json write failed (%s); falling back to JSON file", exc)
    with _geocode_cache_file_lock:
        cache = _load_geocode_cache_json()
        entry = cache.get(norm)
        if not isinstance(entry, dict):
            entry = {}
        entry["civic_json"] = civic_json
        cache[norm] = entry
        _write_geocode_cache_json(cache)
