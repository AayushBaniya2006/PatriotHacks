#!/usr/bin/env python3
"""
import_civicmatch_positions.py — reverse-bridge: import the teammate's
researched candidate stances (civic-match/data/politicians/*.json,
PoliticianProfile shape per civic-match/lib/types.ts) into OUR gold
dataset's positions[] (data/tx/candidates.json), non-destructively.

Read-only against civic-match/. Writes only data/tx/candidates.json
(atomically, temp+rename). Never overwrites or deletes an existing
positions[] entry -- only appends new ones, and is safe to re-run
(dedupes on (issue, summary, source) so reruns don't double-import).

Matching: their id is a firstname-lastname slug; ours is lastname-firstname.
We match on normalized full name (case/punctuation/whitespace-insensitive),
guarded by party (if both sides have a resolvable party bucket and they
disagree, we skip -- this is what correctly rejects the "Nathan Sheets"
(civic-match: Obama-era Treasury economist) vs "Nate Sheets" (our TX
Commissioner of Agriculture candidate) name collision: different people,
and their normalized names don't even match anyway).

Scope: attempts a match against every candidate in our gold set (not just
district == null), so any US House candidate that happens to match a
researched politician file is picked up too -- per the task, the primary
expected hits are our statewide + US Senate candidates.

For each matched candidate: take that politician's stances[], keep only
those with confidence >= 0.5 AND at least one source with a working-looking
URL, sort by confidence desc, take the top 6, and append each as
{issue, summary, source, origin: "civic-match-research", confidence} to our
candidate's positions[]. "source" is the URL of that stance's best Source:
prefer primary_source == true, tie-break by highest reliability_score.
The chosen source URL is also appended to the candidate's own sources[]
if not already present there.

Re-runnable: python3 pipeline/import_civicmatch_positions.py
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
POLITICIANS_DIR = ROOT / "civic-match" / "data" / "politicians"
CANDIDATES_PATH = ROOT / "data" / "tx" / "candidates.json"

ORIGIN = "civic-match-research"
MIN_CONFIDENCE = 0.5
MAX_STANCES_PER_CANDIDATE = 6

URL_RE = re.compile(r"^https?://[^\s]+\.[^\s]+$")

PARTY_BUCKETS = [
    ("republican", "republican"),
    ("democrat", "democratic"),
    ("libertarian", "libertarian"),
    ("green", "green"),
    ("independent", "independent"),
]


def normalize_name(name: str) -> str:
    """Lowercase, drop punctuation, collapse whitespace. Deliberately NOT
    nickname-aware (e.g. "Nate" vs "Nathan") -- exact normalized match only,
    so near-miss name collisions between different people fall through
    rather than getting silently merged."""
    if not name:
        return ""
    s = name.lower()
    s = re.sub(r"[.,'’\-]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def party_bucket(party: str | None) -> str | None:
    if not party:
        return None
    p = party.lower()
    for needle, bucket in PARTY_BUCKETS:
        if needle in p:
            return bucket
    return None


def humanize_issue(issue_id: str) -> str:
    return issue_id.replace("_", " ")


def is_working_url(url: str | None) -> bool:
    if not url or not isinstance(url, str):
        return False
    return bool(URL_RE.match(url.strip()))


def best_source_url(stance: dict) -> str | None:
    """Prefer primary_source True, then highest reliability_score, among
    sources with a working-looking URL."""
    candidates = [s for s in (stance.get("sources") or []) if is_working_url(s.get("url"))]
    if not candidates:
        return None
    candidates.sort(
        key=lambda s: (bool(s.get("primary_source")), s.get("reliability_score", 0)),
        reverse=True,
    )
    return candidates[0]["url"]


def load_politician_profiles() -> list[dict]:
    profiles = []
    for path in sorted(POLITICIANS_DIR.glob("*.json")):
        with open(path, encoding="utf-8") as f:
            profiles.append(json.load(f))
    return profiles


def match_candidate(profile: dict, candidates: dict) -> tuple[str | None, str]:
    """Return (candidate_id or None, reason)."""
    target_name = normalize_name(profile.get("name", ""))
    if not target_name:
        return None, "politician profile has no usable name"

    name_matches = [
        cid for cid, c in candidates.items() if normalize_name(c.get("name", "")) == target_name
    ]
    if not name_matches:
        return None, f"no candidate with normalized name '{target_name}'"

    their_bucket = party_bucket(profile.get("party"))
    if their_bucket is not None:
        guarded = [
            cid
            for cid in name_matches
            if party_bucket(candidates[cid].get("party")) in (None, their_bucket)
        ]
        if not guarded:
            return None, (
                f"name matched {name_matches} but party guard rejected all "
                f"(their party bucket={their_bucket!r})"
            )
        name_matches = guarded

    if len(name_matches) > 1:
        return None, f"ambiguous match among {name_matches} (party guard did not disambiguate)"

    return name_matches[0], "matched"


def select_stances(profile: dict) -> tuple[list[dict], dict]:
    """Return (selected raw stances w/ resolved source url, skip_counts)."""
    skip_counts = {"low_confidence": 0, "no_source": 0}
    eligible = []
    for stance in profile.get("stances", []) or []:
        conf = stance.get("confidence")
        if conf is None or conf < MIN_CONFIDENCE:
            skip_counts["low_confidence"] += 1
            continue
        url = best_source_url(stance)
        if not url:
            skip_counts["no_source"] += 1
            continue
        eligible.append((stance, url))

    eligible.sort(key=lambda pair: pair[0].get("confidence", 0), reverse=True)
    return eligible[:MAX_STANCES_PER_CANDIDATE], skip_counts


def import_positions(candidate: dict, profile: dict) -> tuple[int, dict]:
    """Mutates candidate in place. Returns (imported_count, skip_counts)."""
    selected, skip_counts = select_stances(profile)

    existing_keys = {
        (p.get("issue"), p.get("summary"), p.get("source"))
        for p in candidate.get("positions", []) or []
    }
    candidate.setdefault("positions", [])
    candidate.setdefault("sources", [])

    imported = 0
    for stance, url in selected:
        issue = humanize_issue(stance["issue_id"])
        summary = stance.get("summary", "")
        key = (issue, summary, url)
        if key in existing_keys:
            continue  # already imported on a previous run
        candidate["positions"].append(
            {
                "issue": issue,
                "summary": summary,
                "source": url,
                "origin": ORIGIN,
                "confidence": stance.get("confidence"),
            }
        )
        existing_keys.add(key)
        imported += 1
        if url not in candidate["sources"]:
            candidate["sources"].append(url)

    return imported, skip_counts


def main() -> None:
    with open(CANDIDATES_PATH, encoding="utf-8") as f:
        candidates = json.load(f)

    profiles = load_politician_profiles()

    total_matched = 0
    total_imported = 0
    total_skipped_stances = 0
    unmatched = []

    print("=== civic-match reverse-bridge import ===")
    for profile in profiles:
        pid = profile.get("id", "?")
        cid, reason = match_candidate(profile, candidates)
        if cid is None:
            unmatched.append((pid, reason))
            print(f"  SKIP profile '{pid}': {reason}")
            continue

        candidate = candidates[cid]
        imported, skip_counts = import_positions(candidate, profile)
        total_matched += 1
        total_imported += imported
        skipped_this = sum(skip_counts.values())
        total_skipped_stances += skipped_this

        print(
            f"  MATCH profile '{pid}' -> candidate '{cid}' ({candidate['name']}): "
            f"imported={imported}, skipped={skipped_this} "
            f"(low_confidence={skip_counts['low_confidence']}, "
            f"no_source={skip_counts['no_source']}), "
            f"positions_total_now={len(candidate['positions'])}"
        )

    print("\n=== Summary ===")
    print(f"Politician profiles read: {len(profiles)}")
    print(f"Matched to our candidates: {total_matched}")
    print(f"Unmatched profiles: {len(unmatched)}")
    for pid, reason in unmatched:
        print(f"  - {pid}: {reason}")
    print(f"Total stances imported: {total_imported}")
    print(f"Total stances skipped (confidence/source filters): {total_skipped_stances}")

    # Atomic write: temp file in same directory, then rename.
    fd, tmp_path = tempfile.mkstemp(
        dir=str(CANDIDATES_PATH.parent), prefix=".candidates.", suffix=".json.tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(candidates, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp_path, CANDIDATES_PATH)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise

    print(f"\nWrote {CANDIDATES_PATH}")


if __name__ == "__main__":
    main()
