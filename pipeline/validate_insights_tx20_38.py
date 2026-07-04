#!/usr/bin/env python3
"""
Validate data/tx/insights/{race_id}.json for TX-20..TX-38:
1. Every insight file parses as JSON.
2. Every bullet's source URL appears somewhere in that race's candidate JSON
   (sources / finance.source / record.key_votes[].source / positions[].source).
Drops (and reports) any bullet whose source cannot be verified, rewriting
the file without the violating bullet.
"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data", "tx")
INSIGHTS_DIR = os.path.join(DATA_DIR, "insights")


def load_json(path):
    with open(path) as f:
        return json.load(f)


def collect_valid_sources(cand):
    srcs = set()
    for s in cand.get("sources") or []:
        srcs.add(s)
    fin = cand.get("finance")
    if fin and fin.get("source"):
        srcs.add(fin["source"])
    rec = cand.get("record")
    if rec:
        if rec.get("source"):
            srcs.add(rec["source"])
        for v in rec.get("key_votes") or []:
            if v.get("source"):
                srcs.add(v["source"])
    for p in cand.get("positions") or []:
        if p.get("source"):
            srcs.add(p["source"])
    return srcs


def main():
    races = load_json(os.path.join(DATA_DIR, "races.json"))["races"]
    candidates = load_json(os.path.join(DATA_DIR, "candidates.json"))

    target_races = {}
    for r in races:
        d = r.get("district")
        if d and str(d).startswith("TX-"):
            num = int(d.split("-")[1])
            if 20 <= num <= 38:
                target_races[r["race_id"]] = r

    total_files = 0
    total_bullets = 0
    dropped = []
    file_reports = []

    for race_id, race in sorted(target_races.items()):
        path = os.path.join(INSIGHTS_DIR, f"{race_id}.json")
        if not os.path.exists(path):
            file_reports.append({"race_id": race_id, "error": "missing file"})
            continue

        try:
            data = load_json(path)
        except json.JSONDecodeError as e:
            file_reports.append({"race_id": race_id, "error": f"JSON parse error: {e}"})
            continue

        total_files += 1
        valid_sources_by_cand = {
            cid: collect_valid_sources(candidates[cid])
            for cid in race["candidate_ids"] if cid in candidates
        }

        changed = False
        kept = 0

        def clean_bucket(cand_map):
            nonlocal changed, kept
            for cid, bullets in list(cand_map.items()):
                valid_srcs = valid_sources_by_cand.get(cid, set())
                kept_bullets = []
                for b in bullets:
                    if b.get("source") in valid_srcs:
                        kept_bullets.append(b)
                        kept += 1
                    else:
                        changed = True
                        dropped.append({
                            "race_id": race_id,
                            "candidate_id": cid,
                            "text": b.get("text"),
                            "source": b.get("source"),
                        })
                if kept_bullets:
                    cand_map[cid] = kept_bullets
                else:
                    del cand_map[cid]

        clean_bucket(data["base"]["candidates"])
        if "archetypes" in data:
            for arch in data["archetypes"].values():
                clean_bucket(arch["candidates"])

        if changed:
            with open(path, "w") as f:
                json.dump(data, f, indent=2)

        total_bullets += kept
        file_reports.append({"race_id": race_id, "bullets_kept": kept, "changed": changed})

    print(json.dumps({
        "files_validated": total_files,
        "total_bullets_kept": total_bullets,
        "dropped_bullets": dropped,
        "file_reports": file_reports,
    }, indent=2))


if __name__ == "__main__":
    main()
