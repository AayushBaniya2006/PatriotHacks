#!/usr/bin/env python3
"""
clean_gold.py -- idempotent, atomic, logged cleaning pass over the gold TX
dataset (data/tx/candidates.json + data/tx/races.json).

This is a CLEANER, not a validator: it never invents data and never deletes
a race or a candidate. Anything it cannot safely auto-fix is left exactly as
the source spelled/reported it and is instead logged so a human can review.

Cleaning passes (see each function's docstring for exact rules):

  1. Name display canonicalization (`name` field only):
       - Mc-casing:  "Mccaul"   -> "McCaul"
       - O'-casing:  "O'brien"  -> "O'Brien"
       - Roman-numeral suffix casing: "Iii" -> "III" (last name-token only,
         closed set {II,III,IV,VI,VII,VIII,IX,X} -- bare "I"/"V" are never
         auto-touched, too easily confused with a middle initial)
       - Collapse doubled/multiple whitespace
       - Mac-casing ("Macdonald" vs "MacDonald") is DETECTED but never
         auto-applied -- genuinely ambiguous (real surnames go both ways),
         so it is only ever logged as a skip for human review.
       - `name_raw` is set to the original string the first time `name`
         changes, and is NEVER overwritten again once present -- it is the
         permanent record of exactly what the source spelled.
  2. Party canonicalization: maps known raw values (registrar-legalese like
     "Republican Party of Texas", "Democratic Party (United States)",
     "Democrat", "IND", ...) onto the exact 6-value canonical set
     {Democratic, Republican, Libertarian, Green, Independent, Write-in}.
     Anything not recognized is left completely untouched and logged as
     "unknown, kept verbatim".
  3. Money sanity (candidates[].finance):
       - negative receipts/disbursements/cash_on_hand -> the value is moved
         into finance.flags[] (never silently dropped) and the field itself
         is nulled (never left as a misleading negative number).
       - disbursements > 3x receipts -> finance.flags[] gets the string
         'spend_exceeds_receipts_check_basis' (this is legitimate under a
         per_report_period reporting basis -- we annotate, we do not hide
         or "fix" it).
       - finance.as_of must parse as ISO (YYYY-MM-DD) and be <= 2026-07-04;
         otherwise finance.flags[] gets 'as_of_not_iso_format' or
         'as_of_future_date'. The value itself is left untouched (flag,
         don't guess a replacement date).
       - a finance object whose own `source` is blank/whitespace is dropped
         entirely (not just the source field) -- an unsourced finance
         record fails this project's "no source, no claim" invariant and a
         partially-null finance block would be worse than none at all.
  4. Source hygiene:
       - empty-string/whitespace entries in candidates[].sources[] and
         races[].context.sources[] are removed (logged).
       - positions[]/record.key_votes[] entries whose own `source` is
         blank/whitespace are dropped entirely (same "no source, no claim"
         rule as #3's finance case -- a positionless-of-source claim is not
         data, it is a liability).
       - exact-duplicate entries (full value equality) in positions[],
         record.key_votes[], sources[], and context.sources[] are deduped,
         keeping the first occurrence.
  5. Referential integrity (report only -- never auto-deletes a race or a
     candidate):
       - every race.candidate_ids entry must resolve to a candidates.json
         key -- a break here is treated as a fatal finding (non-zero exit)
         because it means the ballot API would silently omit a candidate.
       - candidates.json entries never referenced by any race are logged as
         informational (not fatal -- an unused researched candidate is not
         a data bug).
  6. Coverage matrix: emits data/tx/coverage_report.json, one entry per
     race: parties present, a one-sided flag (only one distinct party on
     the ballot), and counts of candidates with finance / voting record /
     positions, plus precomputed-insight archetype coverage (0-8).

Usage:
    python3 pipeline/clean_gold.py --dry-run   # preview only, writes nothing
    python3 pipeline/clean_gold.py             # apply + atomic write + report

Idempotent: every transform above is a no-op on already-clean input (running
this twice in a row produces zero further changes on the second run).
Atomic: each output file is written to a temp file in the same directory and
then os.replace()'d over the original, so a crash mid-write never corrupts
candidates.json, races.json, or coverage_report.json.

Exit code: 0 on a clean run (flags/skips are annotations, not failures).
1 only if a genuine unresolvable referential-integrity break is found (a
race.candidate_ids entry with no matching candidate) or a fatal I/O/JSON
read error occurs.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / "tx"
RACES_PATH = DATA_DIR / "races.json"
CANDIDATES_PATH = DATA_DIR / "candidates.json"
COVERAGE_REPORT_PATH = DATA_DIR / "coverage_report.json"
INSIGHTS_DIR = DATA_DIR / "insights"

# Matches CLAUDE.md's locked-decisions date / finance.as_of convention seen
# throughout data/tx/candidates.json (e.g. "as_of": "2026-07-04").
AS_OF_CUTOFF = date(2026, 7, 4)
FINANCE_SPEND_RATIO = 3.0

# Kept in sync with pipeline/score_quality.py's ARCHETYPES list.
ARCHETYPES = [
    "renter_young_worker",
    "homeowner_parent",
    "small_business_owner",
    "healthcare_aca_or_uninsured",
    "medicare_retiree",
    "veteran",
    "student",
    "rural_agriculture",
]

CANONICAL_PARTIES = {"Democratic", "Republican", "Libertarian", "Green", "Independent", "Write-in"}

# Lowercased-raw -> canonical. Extend this table (never guess) if a new raw
# spelling shows up in a future pipeline run.
PARTY_CANON_MAP = {
    "democratic": "Democratic",
    "democrat": "Democratic",
    "democratic party": "Democratic",
    "democratic party (united states)": "Democratic",
    "texas democratic party": "Democratic",
    "dem": "Democratic",
    "republican": "Republican",
    "republican party": "Republican",
    "republican party (united states)": "Republican",
    "republican party of texas": "Republican",
    "gop": "Republican",
    "rep": "Republican",
    "libertarian": "Libertarian",
    "libertarian party": "Libertarian",
    "lp": "Libertarian",
    "green": "Green",
    "green party": "Green",
    "gp": "Green",
    "independent": "Independent",
    "ind": "Independent",
    "unaffiliated": "Independent",
    "no party affiliation": "Independent",
    "npa": "Independent",
    "write-in": "Write-in",
    "write in": "Write-in",
    "writein": "Write-in",
}

# Roman-numeral suffix casing fixes -- closed set, deliberately excludes bare
# "i" / "v" (too easily confused with a middle initial like "John V. Smith").
ROMAN_NUMERAL_FIX = {
    "ii": "II",
    "iii": "III",
    "iv": "IV",
    "vi": "VI",
    "vii": "VII",
    "viii": "VIII",
    "ix": "IX",
    "x": "X",
}

MC_RE = re.compile(r"\bMc([a-z])")
OSUFFIX_RE = re.compile(r"\bO'([a-z])")
MAC_RE = re.compile(r"\bMac[a-z]{2,}")  # detect-only; never auto-applied
MULTI_SPACE_RE = re.compile(r" {2,}")


# ---------------------------------------------------------------------------
# Atomic JSON write (matches pipeline/score_quality.py's convention)
# ---------------------------------------------------------------------------


def atomic_write_json(path: Path, data: Any) -> None:
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.stem}.", suffix=".json.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


# ---------------------------------------------------------------------------
# 1. Name display canonicalization
# ---------------------------------------------------------------------------


def _fix_trailing_roman_numeral(name: str) -> tuple[str, bool]:
    tokens = name.split(" ")
    if not tokens:
        return name, False
    last = tokens[-1]
    trailing_period = last.endswith(".")
    bare = last[:-1] if trailing_period else last
    key = bare.lower()
    if key in ("i", "v"):  # too ambiguous with an initial -- never auto-touch
        return name, False
    canon = ROMAN_NUMERAL_FIX.get(key)
    if canon and bare != canon:
        tokens[-1] = canon + ("." if trailing_period else "")
        return " ".join(tokens), True
    return name, False


def clean_name(cid: str, c: dict[str, Any], log: dict[str, Any]) -> None:
    name = c.get("name")
    if not isinstance(name, str) or not name:
        return
    original = name
    working = MULTI_SPACE_RE.sub(" ", name).strip()
    working = MC_RE.sub(lambda m: "Mc" + m.group(1).upper(), working)
    working = OSUFFIX_RE.sub(lambda m: "O'" + m.group(1).upper(), working)
    working, _ = _fix_trailing_roman_numeral(working)

    if working != original:
        if "name_raw" not in c:
            c["name_raw"] = original
        c["name"] = working
        log["names_renamed"].append({"candidate_id": cid, "before": original, "after": working})

    # Mac-casing: detect only. Never guess whether the source meant
    # "Macdonald" or "MacDonald" -- log for a human to check against the
    # cited source instead of silently picking one.
    if MAC_RE.search(working):
        log["names_skipped_ambiguous"].append(
            {
                "candidate_id": cid,
                "name": working,
                "reason": "Mac-prefix casing is ambiguous (e.g. Mackenzie vs MacKenzie) -- "
                "left exactly as the cited source spells it",
            }
        )


# ---------------------------------------------------------------------------
# 2. Party canonicalization
# ---------------------------------------------------------------------------


def clean_party(cid: str, c: dict[str, Any], log: dict[str, Any]) -> None:
    party = c.get("party")
    if not isinstance(party, str) or not party.strip():
        return
    if party in CANONICAL_PARTIES:
        return
    canon = PARTY_CANON_MAP.get(party.strip().lower())
    if canon:
        log["party_remapped"].append({"candidate_id": cid, "before": party, "after": canon})
        c["party"] = canon
    else:
        log["party_unknown_kept"].append({"candidate_id": cid, "party": party})


# ---------------------------------------------------------------------------
# 3. Money sanity
# ---------------------------------------------------------------------------


def clean_finance(cid: str, c: dict[str, Any], log: dict[str, Any]) -> None:
    finance = c.get("finance")
    if not isinstance(finance, dict):
        return

    # A finance record with no source is not a citable fact -- drop the
    # whole block rather than leave a partially-null, unsourced object
    # around (mirrors "omit, don't invent": no finance is honest; finance
    # with receipts but no source is not).
    source = finance.get("source")
    if not isinstance(source, str) or not source.strip():
        log["finance_removed_no_source"].append({"candidate_id": cid, "finance": finance})
        del c["finance"]
        return

    flags = finance.get("flags")
    if not isinstance(flags, list):
        flags = []

    def add_flag(flag: Any) -> None:
        if flag not in flags:
            flags.append(flag)

    for field in ("receipts", "disbursements", "cash_on_hand"):
        v = finance.get(field)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v < 0:
            add_flag({"flag": "negative_amount_nulled", "field": field, "original_value": v})
            finance[field] = None
            log["finance_negative_nulled"].append({"candidate_id": cid, "field": field, "original_value": v})

    receipts = finance.get("receipts")
    disbursements = finance.get("disbursements")
    if (
        isinstance(receipts, (int, float))
        and not isinstance(receipts, bool)
        and isinstance(disbursements, (int, float))
        and not isinstance(disbursements, bool)
        and receipts >= 0
        and disbursements > FINANCE_SPEND_RATIO * receipts
        and disbursements > 0
    ):
        before = list(flags)
        add_flag("spend_exceeds_receipts_check_basis")
        if flags != before:
            ratio = (disbursements / receipts) if receipts > 0 else float("inf")
            log["finance_spend_exceeds_flagged"].append(
                {"candidate_id": cid, "receipts": receipts, "disbursements": disbursements, "ratio": ratio}
            )

    as_of = finance.get("as_of")
    if as_of is not None:
        try:
            parsed = datetime.strptime(as_of, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            before = list(flags)
            add_flag("as_of_not_iso_format")
            if flags != before:
                log["finance_asof_flagged"].append({"candidate_id": cid, "as_of": as_of, "reason": "not_iso_format"})
        else:
            if parsed > AS_OF_CUTOFF:
                before = list(flags)
                add_flag("as_of_future_date")
                if flags != before:
                    log["finance_asof_flagged"].append({"candidate_id": cid, "as_of": as_of, "reason": "future_date"})

    if flags:
        finance["flags"] = flags


# ---------------------------------------------------------------------------
# 4. Source hygiene
# ---------------------------------------------------------------------------


def clean_url_list(urls: list[Any]) -> tuple[list[Any], int, int]:
    """Returns (new_list, n_removed_empty, n_removed_dupe)."""
    step1 = []
    n_empty = 0
    for u in urls:
        if isinstance(u, str) and u.strip():
            step1.append(u)
        else:
            n_empty += 1
    step2: list[Any] = []
    seen: set[Any] = set()
    n_dupe = 0
    for u in step1:
        if u in seen:
            n_dupe += 1
            continue
        seen.add(u)
        step2.append(u)
    return step2, n_empty, n_dupe


def clean_object_list_with_source(items: list[Any]) -> tuple[list[Any], int, int, list[Any]]:
    """positions[] or record.key_votes[]. Returns
    (new_list, n_removed_missing_source, n_removed_dupe, removed_items)."""
    step1 = []
    n_missing = 0
    removed_items: list[Any] = []
    for item in items:
        src = item.get("source") if isinstance(item, dict) else None
        if isinstance(src, str) and src.strip():
            step1.append(item)
        else:
            n_missing += 1
            removed_items.append(item)
    step2: list[Any] = []
    seen: set[str] = set()
    n_dupe = 0
    for item in step1:
        key = json.dumps(item, sort_keys=True, default=str)
        if key in seen:
            n_dupe += 1
            continue
        seen.add(key)
        step2.append(item)
    return step2, n_missing, n_dupe, removed_items


def clean_candidate_lists(cid: str, c: dict[str, Any], log: dict[str, Any]) -> None:
    sources = c.get("sources")
    if isinstance(sources, list):
        new_sources, n_empty, n_dupe = clean_url_list(sources)
        log["sources_empty_removed"] += n_empty
        log["sources_dupe_removed"] += n_dupe
        if new_sources != sources:
            c["sources"] = new_sources

    positions = c.get("positions")
    if isinstance(positions, list):
        new_positions, n_missing, n_dupe, removed = clean_object_list_with_source(positions)
        log["positions_empty_source_removed"] += n_missing
        log["positions_dupe_removed"] += n_dupe
        if n_missing:
            log["positions_removed_detail"].append({"candidate_id": cid, "removed": removed})
        if new_positions != positions:
            c["positions"] = new_positions

    record = c.get("record")
    if isinstance(record, dict):
        key_votes = record.get("key_votes")
        if isinstance(key_votes, list):
            new_key_votes, n_missing, n_dupe, removed = clean_object_list_with_source(key_votes)
            log["key_votes_empty_source_removed"] += n_missing
            log["key_votes_dupe_removed"] += n_dupe
            if n_missing:
                log["key_votes_removed_detail"].append({"candidate_id": cid, "removed": removed})
            if new_key_votes != key_votes:
                record["key_votes"] = new_key_votes


def clean_race_context_sources(r: dict[str, Any], log: dict[str, Any]) -> None:
    context = r.get("context")
    if not isinstance(context, dict):
        return
    sources = context.get("sources")
    if isinstance(sources, list):
        new_sources, n_empty, n_dupe = clean_url_list(sources)
        log["context_sources_empty_removed"] += n_empty
        log["context_sources_dupe_removed"] += n_dupe
        if new_sources != sources:
            context["sources"] = new_sources


# ---------------------------------------------------------------------------
# 5. Referential integrity (report only)
# ---------------------------------------------------------------------------


def check_referential_integrity(
    races: list[dict[str, Any]], candidates: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[str]]:
    orphan_refs = []
    for r in races:
        for cid in r.get("candidate_ids", []):
            if cid not in candidates:
                orphan_refs.append({"race_id": r["race_id"], "missing_candidate_id": cid})
    referenced: set[str] = set()
    for r in races:
        referenced.update(r.get("candidate_ids", []))
    orphan_candidates = sorted(set(candidates.keys()) - referenced)
    return orphan_refs, orphan_candidates


# ---------------------------------------------------------------------------
# 6. Coverage matrix
# ---------------------------------------------------------------------------


def _insights_coverage_for(race_id: str) -> tuple[int, bool]:
    """(archetype count 0-8 with real candidate bullets, base block present)."""
    path = INSIGHTS_DIR / f"{race_id}.json"
    if not path.exists():
        return 0, False
    try:
        with open(path, "r", encoding="utf-8") as f:
            doc = json.load(f)
    except (json.JSONDecodeError, OSError):
        return 0, False
    archetypes = doc.get("archetypes") or {}
    count = sum(
        1
        for a in ARCHETYPES
        if isinstance(archetypes.get(a), dict) and archetypes[a].get("candidates")
    )
    base = doc.get("base")
    base_present = isinstance(base, dict) and bool(base.get("candidates"))
    return count, base_present


def build_coverage_report(races: list[dict[str, Any]], candidates: dict[str, Any]) -> dict[str, Any]:
    per_race = []
    for r in races:
        cids = [cid for cid in r.get("candidate_ids", []) if cid in candidates]
        parties = sorted({candidates[cid].get("party") for cid in cids if candidates[cid].get("party")})
        finance_count = sum(1 for cid in cids if candidates[cid].get("finance"))
        votes_count = sum(1 for cid in cids if ((candidates[cid].get("record") or {}).get("key_votes")))
        positions_count = sum(1 for cid in cids if candidates[cid].get("positions"))
        archetypes_covered, base_present = _insights_coverage_for(r["race_id"])
        per_race.append(
            {
                "race_id": r["race_id"],
                "office": r.get("office"),
                "level": r.get("level"),
                "district": r.get("district"),
                "candidate_count": len(cids),
                "parties_present": parties,
                "one_sided": len(parties) <= 1,
                "candidates_with_finance": finance_count,
                "candidates_with_votes": votes_count,
                "candidates_with_positions": positions_count,
                "insights_base_present": base_present,
                "insights_archetypes_covered": archetypes_covered,
            }
        )
    return {
        "generated_by": "pipeline/clean_gold.py",
        "race_count": len(races),
        "one_sided_race_count": sum(1 for x in per_race if x["one_sided"]),
        "races": per_race,
    }


# ---------------------------------------------------------------------------
# Report printing
# ---------------------------------------------------------------------------


def _new_log() -> dict[str, Any]:
    return {
        "names_renamed": [],
        "names_skipped_ambiguous": [],
        "party_remapped": [],
        "party_unknown_kept": [],
        "finance_negative_nulled": [],
        "finance_spend_exceeds_flagged": [],
        "finance_asof_flagged": [],
        "finance_removed_no_source": [],
        "sources_empty_removed": 0,
        "sources_dupe_removed": 0,
        "positions_empty_source_removed": 0,
        "positions_dupe_removed": 0,
        "positions_removed_detail": [],
        "key_votes_empty_source_removed": 0,
        "key_votes_dupe_removed": 0,
        "key_votes_removed_detail": [],
        "context_sources_empty_removed": 0,
        "context_sources_dupe_removed": 0,
    }


def print_report(log: dict[str, Any], orphan_refs: list[Any], orphan_candidates: list[str], coverage: dict[str, Any], dry_run: bool) -> None:
    mode = "DRY-RUN (no files written)" if dry_run else "REAL (files written)"
    print(f"=== clean_gold.py report [{mode}] ===")

    print("\n-- Name canonicalization --")
    print(f"  renamed: {len(log['names_renamed'])}")
    for x in log["names_renamed"]:
        print(f"    {x['candidate_id']}: {x['before']!r} -> {x['after']!r}")
    print(f"  skipped (ambiguous Mac-casing, left as source spells it): {len(log['names_skipped_ambiguous'])}")
    for x in log["names_skipped_ambiguous"]:
        print(f"    {x['candidate_id']}: {x['name']!r}")

    print("\n-- Party canonicalization --")
    print(f"  remapped: {len(log['party_remapped'])}")
    for x in log["party_remapped"]:
        print(f"    {x['candidate_id']}: {x['before']!r} -> {x['after']!r}")
    print(f"  unknown (kept verbatim): {len(log['party_unknown_kept'])}")
    for x in log["party_unknown_kept"]:
        print(f"    {x['candidate_id']}: {x['party']!r}")

    print("\n-- Money sanity --")
    print(f"  negative amounts moved to flags + nulled: {len(log['finance_negative_nulled'])}")
    for x in log["finance_negative_nulled"]:
        print(f"    {x['candidate_id']}.{x['field']}: {x['original_value']}")
    print(f"  spend > {FINANCE_SPEND_RATIO}x receipts flagged: {len(log['finance_spend_exceeds_flagged'])}")
    for x in log["finance_spend_exceeds_flagged"]:
        print(f"    {x['candidate_id']}: receipts={x['receipts']} disbursements={x['disbursements']} ratio={x['ratio']:.2f}")
    print(f"  as_of flagged: {len(log['finance_asof_flagged'])}")
    for x in log["finance_asof_flagged"]:
        print(f"    {x['candidate_id']}: as_of={x['as_of']!r} ({x['reason']})")
    print(f"  finance removed (missing source): {len(log['finance_removed_no_source'])}")
    for x in log["finance_removed_no_source"]:
        print(f"    {x['candidate_id']}")

    print("\n-- Source hygiene --")
    print(f"  candidate sources[] empty removed: {log['sources_empty_removed']}")
    print(f"  candidate sources[] duplicates removed: {log['sources_dupe_removed']}")
    print(f"  positions[] entries removed (missing source): {log['positions_empty_source_removed']}")
    print(f"  positions[] duplicates removed: {log['positions_dupe_removed']}")
    print(f"  key_votes[] entries removed (missing source): {log['key_votes_empty_source_removed']}")
    print(f"  key_votes[] duplicates removed: {log['key_votes_dupe_removed']}")
    print(f"  race context.sources[] empty removed: {log['context_sources_empty_removed']}")
    print(f"  race context.sources[] duplicates removed: {log['context_sources_dupe_removed']}")

    print("\n-- Referential integrity --")
    print(f"  BROKEN race->candidate references (reported, NOT auto-fixed): {len(orphan_refs)}")
    for x in orphan_refs:
        print(f"    {x['race_id']} -> missing candidate '{x['missing_candidate_id']}'")
    print(f"  orphan candidates (not referenced by any race, informational only): {len(orphan_candidates)}")
    for cid in orphan_candidates:
        print(f"    {cid}")

    print("\n-- Coverage matrix --")
    print(f"  races: {coverage['race_count']}, one-sided: {coverage['one_sided_race_count']}")
    print(f"  {'written' if not dry_run else 'would write'} {COVERAGE_REPORT_PATH.relative_to(ROOT)}")

    verdict = "REFERENTIAL_INTEGRITY_BROKEN" if orphan_refs else ("DRY_RUN_OK" if dry_run else "CLEANED")
    print(f"\nVERDICT: {verdict}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="Preview cleaning actions; write nothing.")
    args = parser.parse_args(argv)

    try:
        with open(CANDIDATES_PATH, "r", encoding="utf-8") as f:
            candidates: dict[str, Any] = json.load(f)
        with open(RACES_PATH, "r", encoding="utf-8") as f:
            races_doc: dict[str, Any] = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"FATAL: could not read gold JSON: {exc}", file=sys.stderr)
        return 1

    races = races_doc.get("races", [])
    candidates_before = json.dumps(candidates, sort_keys=True, default=str)
    races_before = json.dumps(races_doc, sort_keys=True, default=str)

    log = _new_log()

    for cid, c in candidates.items():
        if not isinstance(c, dict):
            continue
        clean_name(cid, c, log)
        clean_party(cid, c, log)
        clean_finance(cid, c, log)
        clean_candidate_lists(cid, c, log)

    for r in races:
        clean_race_context_sources(r, log)

    orphan_refs, orphan_candidates = check_referential_integrity(races, candidates)
    coverage = build_coverage_report(races, candidates)

    print_report(log, orphan_refs, orphan_candidates, coverage, dry_run=args.dry_run)

    if args.dry_run:
        return 1 if orphan_refs else 0

    candidates_after = json.dumps(candidates, sort_keys=True, default=str)
    races_after = json.dumps(races_doc, sort_keys=True, default=str)

    if candidates_after != candidates_before:
        atomic_write_json(CANDIDATES_PATH, candidates)
        print(f"wrote {CANDIDATES_PATH.relative_to(ROOT)}")
    else:
        print(f"no changes -- {CANDIDATES_PATH.relative_to(ROOT)} left untouched")

    if races_after != races_before:
        atomic_write_json(RACES_PATH, races_doc)
        print(f"wrote {RACES_PATH.relative_to(ROOT)}")
    else:
        print(f"no changes -- {RACES_PATH.relative_to(ROOT)} left untouched")

    atomic_write_json(COVERAGE_REPORT_PATH, coverage)
    print(f"wrote {COVERAGE_REPORT_PATH.relative_to(ROOT)}")

    return 1 if orphan_refs else 0


if __name__ == "__main__":
    sys.exit(main())
