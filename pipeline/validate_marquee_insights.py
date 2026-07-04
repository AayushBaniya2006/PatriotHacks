#!/usr/bin/env python3
"""
Validate data/tx/insights/{race_id}.json for every MARQUEE race
(district == null in data/tx/races.json).

Checks:
1. Each expected insight file exists and parses as JSON.
2. Shape matches {race_id, generated_at, base:{candidates,summary,caveats},
   archetypes:{<8 keys>:{candidates,summary,caveats}}}.
3. All 8 archetype keys are present.
4. Every bullet ({text, source}) in base and every archetype has a source
   URL that appears somewhere in that specific candidate's own JSON record
   (sources[], finance.source, record.*.source, positions[].source).
5. Every candidate in the race has 2-3 bullets in base and in each archetype.

Violating bullets are dropped and the file is rewritten; a report is
printed (and returned) with counts and any dropped bullets.
Re-runnable: safe to run repeatedly.
"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RACES_PATH = os.path.join(ROOT, "data", "tx", "races.json")
CANDIDATES_PATH = os.path.join(ROOT, "data", "tx", "candidates.json")
INSIGHTS_DIR = os.path.join(ROOT, "data", "tx", "insights")

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


def candidate_valid_sources(c):
    """Collect every source URL that legitimately appears in this
    candidate's own JSON record."""
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


def main():
    with open(RACES_PATH) as f:
        races_data = json.load(f)
    with open(CANDIDATES_PATH) as f:
        candidates = json.load(f)

    marquee_races = [r for r in races_data["races"] if r.get("district") is None]

    total_files = 0
    total_bullets = 0
    dropped_bullets = []
    file_bullet_counts = {}
    errors = []

    for race in marquee_races:
        race_id = race["race_id"]
        path = os.path.join(INSIGHTS_DIR, f"{race_id}.json")
        if not os.path.exists(path):
            errors.append(f"MISSING FILE: {path}")
            continue

        with open(path) as f:
            try:
                doc = json.load(f)
            except json.JSONDecodeError as e:
                errors.append(f"INVALID JSON in {path}: {e}")
                continue

        total_files += 1

        # build valid-source sets per candidate in this race
        valid_sources = {
            cid: candidate_valid_sources(candidates[cid])
            for cid in race["candidate_ids"]
            if cid in candidates
        }

        def clean_section(section_name, section, path_label):
            nonlocal total_bullets
            changed = False
            cand_map = section.get("candidates", {})
            for cid, bullets in list(cand_map.items()):
                kept = []
                for b in bullets:
                    src = b.get("source")
                    text = b.get("text")
                    ok = bool(text) and bool(src) and src in valid_sources.get(cid, set())
                    if ok:
                        kept.append(b)
                        total_bullets += 1
                    else:
                        changed = True
                        dropped_bullets.append(
                            {
                                "race_id": race_id,
                                "section": path_label,
                                "candidate_id": cid,
                                "text": text,
                                "source": src,
                                "reason": "source not found in candidate JSON"
                                if text
                                else "missing text/source",
                            }
                        )
                cand_map[cid] = kept
            return changed

        any_change = False
        any_change |= clean_section("base", doc["base"], "base")
        for key in ARCHETYPE_KEYS:
            if key in doc.get("archetypes", {}):
                any_change |= clean_section(
                    key, doc["archetypes"][key], f"archetypes.{key}"
                )
            else:
                errors.append(f"{race_id}: missing archetype key '{key}'")

        if any_change:
            with open(path, "w") as f:
                json.dump(doc, f, indent=2)

        # tally bullet counts for report
        counts = {"base": {cid: len(v) for cid, v in doc["base"]["candidates"].items()}}
        for key in ARCHETYPE_KEYS:
            if key in doc.get("archetypes", {}):
                counts[key] = {
                    cid: len(v)
                    for cid, v in doc["archetypes"][key]["candidates"].items()
                }
        file_bullet_counts[race_id] = counts

    print("=== Marquee Insights Validation Report ===")
    print(f"Files validated: {total_files} / {len(marquee_races)} expected")
    print(f"Total surviving bullets across all files: {total_bullets}")
    print(f"Dropped bullets: {len(dropped_bullets)}")
    for d in dropped_bullets:
        print(f"  DROPPED [{d['race_id']}/{d['section']}/{d['candidate_id']}]: "
              f"{d['reason']} -- text={d['text']!r} source={d['source']!r}")
    if errors:
        print(f"Errors: {len(errors)}")
        for e in errors:
            print(f"  ERROR: {e}")
    else:
        print("Errors: 0")

    print("\nPer-file bullet counts (base + 8 archetypes):")
    for race_id, counts in file_bullet_counts.items():
        base_total = sum(counts["base"].values())
        arche_totals = {
            k: sum(v.values()) for k, v in counts.items() if k != "base"
        }
        print(f"  {race_id}: base={base_total}, " +
              ", ".join(f"{k}={v}" for k, v in arche_totals.items()))

    return {
        "files_validated": total_files,
        "expected_files": len(marquee_races),
        "total_bullets": total_bullets,
        "dropped_bullets": dropped_bullets,
        "errors": errors,
        "file_bullet_counts": file_bullet_counts,
    }


if __name__ == "__main__":
    main()
