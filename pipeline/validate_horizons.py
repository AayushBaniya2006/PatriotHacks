#!/usr/bin/env python3
"""
Validate CONSEQUENCE HORIZONS content written by
pipeline/precompute_horizons.py, for the 8 marquee races (district ==
null in data/tx/races.json) plus tx-cd28-2026 and tx-cd34-2026.

Checks, for every horizons bullet in every base/archetype block of every
target race's data/tx/insights/{race_id}.json:
  1. Parses: the bullet is a dict carrying the fields its list requires
     -- "now" needs {text, source, basis}; "long_term" needs {text,
     source, basis, assumption} -- every one a non-empty string.
  2. "source" is a URL that actually appears somewhere in that specific
     candidate's own JSON record (sources[], finance.source,
     record.source, record.key_votes[].source, positions[].source) --
     never fabricated, never borrowed from another candidate.
  3. Every "long_term" bullet has a non-empty "assumption" AND opens
     with explicit conditional phrasing ("if ...").

Also checks structural coverage: every target race file exists, parses,
and has a "horizons" key on its "base" block and on each of the 8
"archetypes" blocks.

Violating bullets are DROPPED (not just flagged) and the file is
rewritten atomically; a report is printed with pass/drop counts.
Re-runnable: a clean file changes nothing on a repeat run.

Run:
    python3 pipeline/validate_horizons.py
"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RACES_PATH = os.path.join(ROOT, "data", "tx", "races.json")
CANDIDATES_PATH = os.path.join(ROOT, "data", "tx", "candidates.json")
INSIGHTS_DIR = os.path.join(ROOT, "data", "tx", "insights")

TARGET_EXTRA_RACE_IDS = {"tx-cd28-2026", "tx-cd34-2026"}

ARCHETYPE_KEYS = [
    "renter_young_worker",
    "homeowner_parent",
    "small_business_owner",
    "healthcare_aca_or_uninsured",
    "medicare_retiree",
    "veteran",
    "student",
    "rural_agriculture",
]


def load_json(path):
    with open(path) as f:
        return json.load(f)


def atomic_write_json(path, obj):
    tmp_path = path + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(obj, f, indent=2)
        f.write("\n")
    os.replace(tmp_path, path)


def candidate_valid_sources(c):
    """Every source URL that legitimately appears in this candidate's own
    JSON record (same universe as pipeline/validate_marquee_insights.py's
    candidate_valid_sources)."""
    urls = set()
    for u in c.get("sources", []) or []:
        urls.add(u)
    fin = c.get("finance")
    if fin and fin.get("source"):
        urls.add(fin["source"])
    rec = c.get("record")
    if rec:
        if rec.get("source"):
            urls.add(rec["source"])
        for kv in rec.get("key_votes", []) or []:
            if kv.get("source"):
                urls.add(kv["source"])
    for p in c.get("positions", []) or []:
        if p.get("source"):
            urls.add(p["source"])
    return urls


def _nonempty_str(v):
    return isinstance(v, str) and bool(v.strip())


def _is_conditional(text):
    return _nonempty_str(text) and text.strip().lower().startswith("if ")


def _drop_reason_now(b, valid_sources):
    if not isinstance(b, dict):
        return "not an object"
    if not _nonempty_str(b.get("text")):
        return "missing/empty text"
    if not _nonempty_str(b.get("source")):
        return "missing/empty source"
    if not _nonempty_str(b.get("basis")):
        return "missing/empty basis"
    if b["source"] not in valid_sources:
        return "source not found in candidate JSON"
    return None


def _drop_reason_long_term(b, valid_sources):
    reason = _drop_reason_now(b, valid_sources)
    if reason:
        return reason
    if not _nonempty_str(b.get("assumption")):
        return "missing/empty assumption"
    if not _is_conditional(b.get("text")):
        return "long_term bullet is not conditionally phrased (must open with 'If ...')"
    return None


def clean_list(items, valid_sources, reason_fn, race_id, section, cid, list_name, dropped):
    kept = []
    for b in items if isinstance(items, list) else []:
        reason = reason_fn(b, valid_sources)
        if reason is None:
            kept.append(b)
        else:
            dropped.append(
                {
                    "race_id": race_id,
                    "section": section,
                    "candidate_id": cid,
                    "list": list_name,
                    "text": b.get("text") if isinstance(b, dict) else b,
                    "reason": reason,
                }
            )
    return kept


def validate_block(block, valid_sources_by_cid, race_id, section, dropped, stats):
    """Mutates block['horizons'] in place (dropping bad bullets); returns
    True if anything changed."""
    horizons = block.get("horizons")
    if not isinstance(horizons, dict):
        return False
    changed = False
    for cid, h in list(horizons.items()):
        if not isinstance(h, dict):
            continue
        valid_sources = valid_sources_by_cid.get(cid, set())
        now_before = h.get("now") if isinstance(h.get("now"), list) else []
        lt_before = h.get("long_term") if isinstance(h.get("long_term"), list) else []

        now_after = clean_list(
            now_before, valid_sources, _drop_reason_now, race_id, section, cid, "now", dropped
        )
        lt_after = clean_list(
            lt_before, valid_sources, _drop_reason_long_term, race_id, section, cid, "long_term", dropped
        )

        stats["now_total"] += len(now_before)
        stats["now_kept"] += len(now_after)
        stats["long_term_total"] += len(lt_before)
        stats["long_term_kept"] += len(lt_after)

        if now_after != now_before or lt_after != lt_before:
            changed = True
            h["now"] = now_after
            h["long_term"] = lt_after
    return changed


def main():
    races_data = load_json(RACES_PATH)
    candidates = load_json(CANDIDATES_PATH)

    target_races = [
        r
        for r in races_data["races"]
        if r.get("district") is None or r["race_id"] in TARGET_EXTRA_RACE_IDS
    ]

    dropped = []
    stats = {"now_total": 0, "now_kept": 0, "long_term_total": 0, "long_term_kept": 0}
    errors = []
    files_validated = 0
    per_file_report = {}

    for race in target_races:
        race_id = race["race_id"]
        path = os.path.join(INSIGHTS_DIR, f"{race_id}.json")
        if not os.path.exists(path):
            errors.append(f"MISSING FILE: {path}")
            continue
        try:
            doc = load_json(path)
        except json.JSONDecodeError as e:
            errors.append(f"INVALID JSON in {path}: {e}")
            continue

        valid_sources_by_cid = {
            cid: candidate_valid_sources(candidates[cid])
            for cid in race.get("candidate_ids", [])
            if cid in candidates
        }

        any_change = False

        base = doc.get("base")
        if not isinstance(base, dict):
            errors.append(f"{race_id}: missing 'base' block")
            base = {}
        elif "horizons" not in base:
            errors.append(f"{race_id}: base block missing 'horizons'")
        else:
            any_change |= validate_block(base, valid_sources_by_cid, race_id, "base", dropped, stats)

        archetypes = doc.get("archetypes")
        file_archetype_counts = {}
        if not isinstance(archetypes, dict):
            errors.append(f"{race_id}: missing 'archetypes' block")
            archetypes = {}
        for key in ARCHETYPE_KEYS:
            block = archetypes.get(key)
            if not isinstance(block, dict):
                errors.append(f"{race_id}: missing archetype block '{key}'")
                continue
            if "horizons" not in block:
                errors.append(f"{race_id}: archetypes.{key} missing 'horizons'")
                continue
            any_change |= validate_block(
                block, valid_sources_by_cid, race_id, f"archetypes.{key}", dropped, stats
            )
            h = block["horizons"]
            file_archetype_counts[key] = {
                "now": sum(len(v.get("now", [])) for v in h.values() if isinstance(v, dict)),
                "long_term": sum(len(v.get("long_term", [])) for v in h.values() if isinstance(v, dict)),
            }

        if any_change:
            atomic_write_json(path, doc)

        files_validated += 1
        base_h = base.get("horizons", {}) if isinstance(base, dict) else {}
        per_file_report[race_id] = {
            "base": {
                "now": sum(len(v.get("now", [])) for v in base_h.values() if isinstance(v, dict)),
                "long_term": sum(len(v.get("long_term", [])) for v in base_h.values() if isinstance(v, dict)),
            },
            "archetypes": file_archetype_counts,
        }

    print("=== Consequence Horizons Validation Report ===")
    print(f"Files validated: {files_validated} / {len(target_races)} expected")
    print(f"'now' bullets: {stats['now_kept']} kept / {stats['now_total']} checked")
    print(f"'long_term' bullets: {stats['long_term_kept']} kept / {stats['long_term_total']} checked")
    print(f"Dropped bullets: {len(dropped)}")
    for d in dropped:
        print(
            f"  DROPPED [{d['race_id']}/{d['section']}/{d['candidate_id']}/{d['list']}]: "
            f"{d['reason']} -- text={d['text']!r}"
        )
    if errors:
        print(f"Errors: {len(errors)}")
        for e in errors:
            print(f"  ERROR: {e}")
    else:
        print("Errors: 0")

    print("\nPer-file horizons bullet counts:")
    for race_id, counts in per_file_report.items():
        arch_now = sum(v["now"] for v in counts["archetypes"].values())
        arch_lt = sum(v["long_term"] for v in counts["archetypes"].values())
        print(
            f"  {race_id}: base(now={counts['base']['now']}, long_term={counts['base']['long_term']}), "
            f"archetypes(now={arch_now}, long_term={arch_lt})"
        )

    return {
        "files_validated": files_validated,
        "expected_files": len(target_races),
        "now_kept": stats["now_kept"],
        "now_total": stats["now_total"],
        "long_term_kept": stats["long_term_kept"],
        "long_term_total": stats["long_term_total"],
        "dropped": dropped,
        "errors": errors,
        "per_file_report": per_file_report,
    }


if __name__ == "__main__":
    main()
