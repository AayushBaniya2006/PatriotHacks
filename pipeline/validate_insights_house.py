#!/usr/bin/env python3
"""
Validate data/tx/insights/{race_id}.json for TX-01..TX-19 US House races.

Checks:
- each file parses as JSON
- every bullet's source URL appears somewhere in that race's candidates.json
  (in sources[], finance.source, record.source, record.key_votes[].source, positions[].source)
Drops (and reports) any bullet whose source cannot be traced, then rewrites the file.
"""
import json
import os
import re

REPO = "/home/abheekp/vulcan/PatriotHacks"
CANDIDATES_PATH = os.path.join(REPO, "data/tx/candidates.json")
INSIGHTS_DIR = os.path.join(REPO, "data/tx/insights")


def allowed_sources_for_candidate(cand):
    urls = set()
    for s in cand.get("sources") or []:
        urls.add(s)
    fin = cand.get("finance")
    if fin and fin.get("source"):
        urls.add(fin["source"])
    record = cand.get("record")
    if record:
        if record.get("source"):
            urls.add(record["source"])
        for v in record.get("key_votes") or []:
            if v.get("source"):
                urls.add(v["source"])
    for p in cand.get("positions") or []:
        if p.get("source"):
            urls.add(p["source"])
    return urls


def main():
    with open(CANDIDATES_PATH) as f:
        candidates = json.load(f)

    files = sorted(
        fn for fn in os.listdir(INSIGHTS_DIR)
        if re.match(r"tx-cd(0[1-9]|1[0-9])-2026\.json$", fn)
    )

    total_files = 0
    total_bullets = 0
    total_dropped = 0
    dropped_report = []
    parse_errors = []

    for fn in files:
        path = os.path.join(INSIGHTS_DIR, fn)
        try:
            with open(path) as f:
                doc = json.load(f)
        except Exception as e:
            parse_errors.append((fn, str(e)))
            continue
        total_files += 1
        changed = False

        def clean_candidates_block(cands_block):
            nonlocal total_bullets, total_dropped, changed
            for cid, bullets in list(cands_block.items()):
                cand = candidates.get(cid, {})
                allowed = allowed_sources_for_candidate(cand)
                kept = []
                for b in bullets:
                    total_bullets += 1
                    src = b.get("source")
                    if src in allowed:
                        kept.append(b)
                    else:
                        total_dropped += 1
                        dropped_report.append({
                            "file": fn, "candidate_id": cid,
                            "text": b.get("text"), "source": src,
                        })
                        changed = True
                cands_block[cid] = kept

        clean_candidates_block(doc.get("base", {}).get("candidates", {}))
        for arch_key, arch_val in (doc.get("archetypes") or {}).items():
            clean_candidates_block(arch_val.get("candidates", {}))

        if changed:
            with open(path, "w") as f:
                json.dump(doc, f, indent=2)

    print(f"Files validated: {total_files}")
    print(f"Total bullets checked: {total_bullets}")
    print(f"Bullets dropped (untraceable source): {total_dropped}")
    if dropped_report:
        print("\nDropped bullets:")
        for d in dropped_report:
            print(f"  [{d['file']}] {d['candidate_id']}: {d['text']!r} (source={d['source']})")
    if parse_errors:
        print("\nPARSE ERRORS:")
        for fn, err in parse_errors:
            print(f"  {fn}: {err}")

    # final re-check: reload and confirm all parse + counts per file
    per_file_counts = {}
    for fn in files:
        path = os.path.join(INSIGHTS_DIR, fn)
        with open(path) as f:
            doc = json.load(f)
        n = sum(len(v) for v in doc.get("base", {}).get("candidates", {}).values())
        for arch in (doc.get("archetypes") or {}).values():
            n += sum(len(v) for v in arch.get("candidates", {}).values())
        per_file_counts[fn] = n

    print("\nPer-file bullet counts (base + archetypes):")
    for fn, n in per_file_counts.items():
        print(f"  {fn}: {n}")

    if parse_errors or total_files != len(files):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
