#!/usr/bin/env python3
"""
export_civic_match.py -- merge our gold TX dataset into civic-match's data.

Reads:
  data/tx/races.json
  data/tx/candidates.json
  civic-match/lib/issues.ts            (issue_id taxonomy, parsed not hand-copied)
  civic-match/data/politicians/*.json  (their existing roster, read + merged)

Writes:
  civic-match/data/politicians/<slug>.json     - merged (existing profile) or
                                                  newly created (minimal profile)
  civic-match/data/elections/texas-house.json  - all 38 U.S. House TX races
                                                  (new file; texas.json is never touched)

Matching: a candidate matches an existing civic-match profile iff
slugify(our candidate's name) -- their exact civic-match/lib/db.ts algorithm --
equals an existing politicians/<slug>.json filename. This is deliberately
literal, not fuzzy/nickname matching: e.g. our "Nate Sheets" slugifies to
"nate-sheets", which does NOT match an existing "nathan-sheets.json" even if
that turns out to be the same person under a fuller name. Misses like that
are surfaced in the printed summary rather than silently guessed at.

Merge is strictly non-destructive: for a candidate that already has a
civic-match profile, this script only (a) fills bio/party/current_office if
currently empty and (b) appends new Stance entries derived from our
key_votes/finance/sponsored_highlights/positions. It never deletes or
rewrites an existing stance, qualitative entry, source, or the
unknowns/contradictions/source_coverage_score bookkeeping the research swarm
already computed.
Appends are idempotent: stance_id/source_id are derived deterministically
from the underlying bill/finance record, so rerunning after new gold data
lands only adds what is actually new.

For a candidate with no existing profile, writes a fresh minimal
PoliticianProfile (research_status "partial") built from the same derived
stances, so their research swarm gets a head start instead of a blank page --
most useful for the 38 U.S. House races, which are not in the existing
roster yet.

If data/tx/races.json or candidates.json don't exist yet (the backend fleet
hasn't built the gold dataset), prints "SKIP: gold dataset not built yet" and
exits 0. Safe to rerun any time -- including while the gold files or the
politician roster are being actively (re)written by other agents.

Side effects are scoped to exactly two places: civic-match/data/politicians/
and civic-match/data/elections/texas-house.json. civic-match/data/elections/
texas.json and everything else in the repo is left untouched.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parent.parent
GOLD_RACES_PATH = REPO_ROOT / "data" / "tx" / "races.json"
GOLD_CANDIDATES_PATH = REPO_ROOT / "data" / "tx" / "candidates.json"

CIVIC_MATCH_ROOT = REPO_ROOT / "civic-match"
POLITICIANS_DIR = CIVIC_MATCH_ROOT / "data" / "politicians"
ISSUES_TS_PATH = CIVIC_MATCH_ROOT / "lib" / "issues.ts"
TEXAS_HOUSE_PATH = CIVIC_MATCH_ROOT / "data" / "elections" / "texas-house.json"

# Fixed per the integration contract (not wall-clock) so every Source we
# attach in a given export generation carries the same, reproducible
# retrieval date instead of drifting with whenever the script happens to run.
RETRIEVED_AT = "2026-07-03"

GOV_RELIABILITY = 0.95  # official government sources: House Clerk, FEC, Congress.gov

# The only issue axis in their 30-issue taxonomy that touches money-in-politics
# / transparency at all (see lib/issues.ts "Government Ethics & Corruption").
# Campaign-finance totals are not a policy stance, so they only ever get
# attached as a Source on an *existing* stance for this issue -- never used
# to manufacture a new Stance.
FINANCE_RELATED_ISSUE_ID = "ethics"

# Confidence tiers ("votes are facts: 0.9; inferred direction: lower"):
#   CLEAR_DIRECTION  - the vote is a fact AND its direction on the issue axis
#                       is unambiguous (a single-topic, non-procedural bill).
#   TOPIC_ONLY       - the vote is a fact and the issue is clearly implicated,
#                       but the bill is bundled/procedural enough that a
#                       directional scalar would be a guess (stays null).
#   KEYWORD_GUESS    - the issue_id itself came from a generic keyword
#                       fallback (no curated entry for this exact bill/item);
#                       scalar always null.
CONFIDENCE_CLEAR_DIRECTION = 0.9
CONFIDENCE_TOPIC_ONLY = 0.6
CONFIDENCE_KEYWORD_GUESS = 0.5


# ---------------------------------------------------------------------------
# Issue taxonomy (parsed from their TS source, not hand-copied, so this
# script can't drift out of sync with lib/issues.ts).
# ---------------------------------------------------------------------------

def load_issue_ids() -> list[str]:
    """Only IssueDef entries use an `id:` key (IssueOption entries use `key:`),
    so this regex unambiguously extracts just the 30 top-level issue ids."""
    text = ISSUES_TS_PATH.read_text(encoding="utf-8")
    ids = re.findall(r'\bid:\s*"([a-z_]+)"', text)
    if len(ids) < 10:
        raise RuntimeError(
            f"expected ~30 issue ids from {ISSUES_TS_PATH}, parsed only {len(ids)}: {ids}"
        )
    return ids


# ---------------------------------------------------------------------------
# key_votes -> issue_id mapping
#
# The gold dataset's House roll-call votes are drawn from a small, shared set
# of national bills (every TX member who held office at the time has the
# same bill recorded). As of 2026-07-03 there are exactly 8 unique bills
# across all 100 candidates, so each is hand-classified below rather than
# guessed at runtime -- far more precise than any keyword heuristic.
#
# Each entry is (issue_id, yea_scalar). yea_scalar is the position_scalar
# implied by a "Yea" vote IF this bill's direction on that issue's single
# axis is unambiguous (see lib/issues.ts axis0/axis1 for the id). `None`
# means the vote is still solid evidence the candidate engaged with that
# issue, but the bill is bundled or procedural enough (an appropriations /
# keep-the-government-open vote, a multi-title reconciliation package) that
# asserting a scalar would be a guess -- left null per "when in doubt, use
# null". A "Nay" vote mirrors the scalar (1 - yea_scalar) when one exists.
KEY_VOTE_ISSUE_MAP: dict[str, tuple[str, float | None]] = {
    # Mandatory detention for certain criminal aliens + state AG suits over
    # federal immigration-enforcement decisions -- a clean enforcement-first
    # immigration bill, not a funding/appropriations vote.
    "H R 29": ("immigration", 0.1),
    # Bars a presidential fracking moratorium without congressional approval
    # -- squarely pro-fossil-fuel-production.
    "H R 26": ("energy", 0.1),
    # Rolls back federal home-appliance/energy-efficiency mandates -- maps to
    # the climate axis ("minimal mandates" vs "clean-energy mandates"), not
    # to fossil vs. renewable *production* (that's the energy axis).
    "H R 4758": ("climate", 0.15),
    # Bars Medicaid funds from covering gender-transition procedures for
    # minors -- squarely an LGBTQ+ policy restriction, not primarily a
    # Medicare/Medicaid program-structure question.
    "H R 498": ("lgbtq", 0.1),
    # 2025 reconciliation package: extends 2017 tax cuts + new tax breaks +
    # cuts Medicaid/SNAP + boosts border/defense funding + raises the debt
    # limit, all in one vote. Tax cuts are the bill's headline/lead clause,
    # but a single bundled megabill vote is not a clean signal of a
    # standalone tax-policy direction -- scalar stays null.
    "H R 1": ("taxes", None),
    # "Republican-backed alternative" restructuring ACA premium-subsidy
    # rules -- clearly a healthcare vote, but the plain-English gloss
    # doesn't say enough about the restructuring's specifics to assert a
    # scalar confidently.
    "H R 6703": ("healthcare", None),
    # Consolidated Appropriations Act -- a must-pass, shutdown-averting
    # funding bill. Closest single axis is government spending, but
    # "keep the lights on" votes aren't a clean ideological signal.
    "H R 7148": ("debt_spending", None),
    # DHS Appropriations Act funding CBP/ICE -- implicates immigration
    # enforcement, but it's an appropriations vote (many members vote to
    # fund the government regardless of their immigration views).
    "H R 7744": ("immigration", None),
}

# Fallback for any future bill not in the curated table above (new gold data
# will bring new votes we haven't hand-classified). Deliberately coarse and
# topic-only: it never asserts a direction (position_scalar always None on
# this path), and if zero or more than one bucket's keywords fire, the
# caller skips the item rather than guessing which issue it belongs to.
ISSUE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "immigration": ("immigra", "border security", "deport", "asylum", "customs and border", " ice "),
    "energy": ("fracking", "oil and gas", "drilling", "pipeline", "natural gas production"),
    "climate": ("emissions", "energy-efficiency", "efficiency regulation", "clean-energy mandate", "carbon"),
    "healthcare": ("affordable care act", " aca ", "health insurance", "obamacare", "premium subsid"),
    "medicare_medicaid": ("medicaid", "medicare"),
    "taxes": ("tax cut", "tax break", "tax credit", "income tax", "corporate tax"),
    "debt_spending": ("appropriations act", "debt limit", "government shutdown", "federal spending", "budget reconciliation"),
    "abortion": ("abortion", "reproductive health care access"),
    "guns": ("firearm", "gun control", "background check"),
    "lgbtq": ("gender-transition", "gender transition", "transgender"),
    "education": ("public school funding", "student loan", "school choice", "voucher"),
    "defense": ("defense spending", "military spending", "armed forces appropriations"),
    "trade": ("tariff", "trade agreement"),
    "labor": ("minimum wage", "union organizing", "collective bargaining"),
    "housing": ("zoning", "affordable housing", "rent control"),
    "elections": ("voter id", "mail voting", "voting rights"),
}


def classify_topic_fallback(text: str) -> str | None:
    low = f" {text.lower()} "
    hits = {issue for issue, kws in ISSUE_KEYWORDS.items() if any(kw in low for kw in kws)}
    return hits.pop() if len(hits) == 1 else None


def _validate_issue_tables(issue_id_set: set[str]) -> None:
    """Fail fast if their taxonomy ever drops an id this script references,
    instead of silently mis-tagging stances with a dead issue_id."""
    bad = {iid for iid, _ in KEY_VOTE_ISSUE_MAP.values() if iid not in issue_id_set}
    bad |= {iid for iid in ISSUE_KEYWORDS if iid not in issue_id_set}
    if FINANCE_RELATED_ISSUE_ID not in issue_id_set:
        bad.add(FINANCE_RELATED_ISSUE_ID)
    if bad:
        raise RuntimeError(
            f"issue ids referenced by this script no longer exist in {ISSUES_TS_PATH}: {sorted(bad)}"
        )


# ---------------------------------------------------------------------------
# Small pure helpers
# ---------------------------------------------------------------------------

def slugify(name: str) -> str:
    """Exact port of civic-match/lib/db.ts slugify(), so matching is
    byte-for-byte identical to how their own code keys a saved profile."""
    s = name.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"^-+|-+$", "", s)
    return s


def parse_house_date(raw: str | None) -> str | None:
    """'7-Jan-2025' -> '2025-01-07'. Returns None (never raises) on anything
    that doesn't match -- a cosmetic published_at/recency field isn't worth
    failing the whole export over."""
    if not raw:
        return None
    try:
        return datetime.strptime(raw.strip(), "%d-%b-%Y").date().isoformat()
    except ValueError:
        return None


def normalize_party_label(raw: str | None) -> str:
    """Collapse our verbose/inconsistent party strings ('Republican Party of
    Texas', 'Democratic Party (United States)', 'IND', ...) to the short
    labels civic-match/data/elections/texas.json already uses ('Republican',
    'Democrat', ...), for a consistent ballot display. Display normalization
    only -- PoliticianProfile.party (the system-of-record field) keeps the
    verbatim source string; see merge_into_existing/create_new_profile."""
    if not raw:
        return "Unknown"
    low = raw.strip().lower()
    if "republican" in low:
        return "Republican"
    if "democrat" in low:
        return "Democrat"
    if "libertarian" in low:
        return "Libertarian"
    if "green" in low:
        return "Green"
    if low in ("ind", "independent"):
        return "Independent"
    return raw.strip()


def _bill_slug(bill: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", bill.lower())


# ---------------------------------------------------------------------------
# Stance / Source builders
# ---------------------------------------------------------------------------

def build_vote_stance(candidate_id: str, vote: dict, skip_log: list[tuple[str, str, str, str]]) -> dict | None:
    bill = (vote.get("bill") or "").strip()
    plain_english = (vote.get("plain_english") or "").strip()
    position = vote.get("position")
    source_url = vote.get("source")
    question = vote.get("question") or ""

    if not (bill and plain_english and source_url):
        skip_log.append((candidate_id, "key_vote", bill or "(unknown bill)", "missing bill/plain_english/source field"))
        return None
    if position not in ("Yea", "Nay"):
        skip_log.append((candidate_id, "key_vote", bill, f"no yea/nay position recorded ({position!r})"))
        return None

    curated = KEY_VOTE_ISSUE_MAP.get(bill)
    if curated is not None:
        issue_id, yea_scalar = curated
        confidence = CONFIDENCE_CLEAR_DIRECTION if yea_scalar is not None else CONFIDENCE_TOPIC_ONLY
    else:
        issue_id = classify_topic_fallback(f"{bill} {question} {plain_english}")
        if issue_id is None:
            skip_log.append((candidate_id, "key_vote", bill, "no clean issue_id mapping for this bill"))
            return None
        yea_scalar = None
        confidence = CONFIDENCE_KEYWORD_GUESS

    scalar = None if yea_scalar is None else (yea_scalar if position == "Yea" else round(1 - yea_scalar, 2))
    iso_date = parse_house_date(vote.get("date"))
    bill_slug = _bill_slug(bill)

    source = {
        "source_id": f"vote-{issue_id}-{bill_slug}-src",
        "type": "voting_record",
        "title": f"{bill} — {question}" if question else bill,
        "publisher": "U.S. House Clerk",
        "url": source_url,
        "retrieved_at": RETRIEVED_AT,
        "primary_source": True,
        "quote": plain_english,
        "reliability_score": GOV_RELIABILITY,
    }
    if iso_date:
        source["published_at"] = iso_date

    stance = {
        "stance_id": f"vote-{issue_id}-{bill_slug}",
        "issue_id": issue_id,
        "position_label": f"Voted {position} on {bill}",
        "position_scalar": scalar,
        "summary": plain_english,
        "evidence_type": "voting_record",
        "confidence": confidence,
        "sources": [source],
    }
    if iso_date:
        stance["recency"] = iso_date
    return stance


def build_sponsored_stance(
    candidate_id: str,
    index: int,
    headline: str,
    record_source_url: str | None,
    skip_log: list[tuple[str, str, str, str]],
) -> dict | None:
    headline = (headline or "").strip()
    if not headline:
        return None
    issue_id = classify_topic_fallback(headline)
    if issue_id is None:
        skip_log.append((candidate_id, "sponsored_bill", headline[:70], "no clean issue_id mapping"))
        return None

    source = {
        "source_id": f"sponsored-{issue_id}-{index}-src",
        "type": "sponsored_bill",
        "title": headline,
        "publisher": "U.S. Congress",
        "url": record_source_url or "https://www.congress.gov/",
        "retrieved_at": RETRIEVED_AT,
        "primary_source": bool(record_source_url),
        "quote": headline,
        "reliability_score": GOV_RELIABILITY if record_source_url else 0.6,
    }
    return {
        "stance_id": f"sponsored-{issue_id}-{index}",
        "issue_id": issue_id,
        "position_label": headline,
        "position_scalar": None,
        "summary": headline,
        "evidence_type": "sponsored_bill",
        "confidence": CONFIDENCE_KEYWORD_GUESS,
        "sources": [source],
    }


def build_finance_source(finance: dict) -> dict | None:
    """A Stance is wrong for money -- this builds a Source only, to be
    attached onto an existing/derived stance by attach_finance()."""
    url = finance.get("source")
    if not url:
        return None
    receipts = finance.get("receipts")
    disbursements = finance.get("disbursements")
    cash = finance.get("cash_on_hand")
    as_of = finance.get("as_of")

    parts = [
        f"Receipts: ${receipts:,.2f}" if isinstance(receipts, (int, float)) else "Receipts: not reported",
        f"Disbursements: ${disbursements:,.2f}" if isinstance(disbursements, (int, float)) else "Disbursements: not reported",
        f"Cash on hand: ${cash:,.2f}" if isinstance(cash, (int, float)) else "Cash on hand: not reported",
    ]
    quote = "; ".join(parts) + (f" (as of {as_of})" if as_of else "")

    source = {
        "source_id": "campaign-finance-fec-src",
        "type": "campaign_finance",
        "title": "FEC campaign finance summary",
        "publisher": "Federal Election Commission (FEC)",
        "url": url,
        "retrieved_at": RETRIEVED_AT,
        "primary_source": True,
        "quote": quote,
        "reliability_score": GOV_RELIABILITY,
    }
    if as_of:
        source["published_at"] = as_of
    return source


def derive_stances(candidate_id: str, candidate: dict, skip_log: list[tuple[str, str, str, str]]) -> list[dict]:
    """key_votes -> voting_record stances, sponsored_highlights -> sponsored_bill
    stances. Does NOT handle finance (see attach_finance) or the `positions`
    field (see derive_position_stances below, called separately from main()
    so it can dedupe against the vote/sponsored stances derived here first --
    a recorded vote is higher-fidelity evidence than a researched position on
    the same issue, so it should win rather than stack two stances on one
    issue_id)."""
    stances: list[dict] = []
    seen_ids: set[str] = set()

    record = candidate.get("record") or {}

    for vote in record.get("key_votes") or []:
        stance = build_vote_stance(candidate_id, vote, skip_log)
        if stance is None:
            continue
        if stance["stance_id"] in seen_ids:
            skip_log.append((candidate_id, "key_vote", vote.get("bill", "?"), "duplicate vote record for this bill"))
            continue
        seen_ids.add(stance["stance_id"])
        stances.append(stance)

    record_source_url = record.get("source")
    for index, headline in enumerate(record.get("sponsored_highlights") or []):
        stance = build_sponsored_stance(candidate_id, index, headline, record_source_url, skip_log)
        if stance is None:
            continue
        if stance["stance_id"] in seen_ids:
            continue
        seen_ids.add(stance["stance_id"])
        stances.append(stance)

    return stances


def attach_finance(
    candidate_id: str,
    name: str,
    finance: dict | None,
    stances: list[dict],
    finance_log: list[tuple[str, str, str]],
) -> bool:
    """Attaches a campaign_finance Source to an existing/derived stance on the
    one issue axis (ethics) that touches money-in-politics -- never creates a
    Stance for money by itself. Returns True iff a source was actually added."""
    if not finance:
        return False
    target = next((s for s in stances if s.get("issue_id") == FINANCE_RELATED_ISSUE_ID), None)
    if target is None:
        finance_log.append((candidate_id, name, "no existing/derived stance on the 'ethics' issue to attach it to"))
        return False
    source = build_finance_source(finance)
    if source is None:
        finance_log.append((candidate_id, name, "finance record has no source url"))
        return False
    existing_sources = target.setdefault("sources", [])
    if any(s.get("source_id") == source["source_id"] for s in existing_sources):
        return False  # already attached by a previous run
    existing_sources.append(source)
    return True


# ---------------------------------------------------------------------------
# Profile merge / create
# ---------------------------------------------------------------------------

@dataclass
class MergeResult:
    changed: bool
    stances_appended: int
    finance_attached: bool


def merge_into_existing(
    candidate_id: str,
    candidate: dict,
    profile: dict,
    new_stances: list[dict],
    finance_log: list[tuple[str, str, str]],
) -> MergeResult:
    """Mutates `profile` in place. Never deletes or rewrites an existing
    stance, qualitative entry, or source -- only (a) fills empty
    bio/party/current_office and (b) appends new stances/sources."""
    changed = False

    bio = candidate.get("background")
    if bio and not profile.get("bio"):
        profile["bio"] = bio
        changed = True

    party = candidate.get("party")
    if party and not profile.get("party"):
        profile["party"] = party
        changed = True

    office = candidate.get("office")
    if office and not profile.get("current_office"):
        profile["current_office"] = office
        changed = True

    stances = profile.setdefault("stances", [])
    existing_ids = {s.get("stance_id") for s in stances}
    appended = 0
    for stance in new_stances:
        if stance["stance_id"] in existing_ids:
            continue
        stances.append(stance)
        existing_ids.add(stance["stance_id"])
        appended += 1
        changed = True

    finance_attached = attach_finance(candidate_id, candidate.get("name", candidate_id), candidate.get("finance"), stances, finance_log)
    changed = changed or finance_attached

    return MergeResult(changed=changed, stances_appended=appended, finance_attached=finance_attached)


def create_new_profile(
    candidate_id: str,
    candidate: dict,
    slug: str,
    new_stances: list[dict],
    all_issue_ids: list[str],
    finance_log: list[tuple[str, str, str]],
    researched_at: str,
) -> tuple[dict, bool]:
    """Fresh minimal PoliticianProfile for a candidate with no existing
    civic-match profile: research_status 'partial', unknowns = every issue_id
    we still lack evidence for, source_coverage_score honestly low."""
    stances = list(new_stances)
    finance_attached = attach_finance(candidate_id, candidate.get("name", candidate_id), candidate.get("finance"), stances, finance_log)

    covered = {s["issue_id"] for s in stances}
    unknowns = [iid for iid in all_issue_ids if iid not in covered]

    profile: dict = {"id": slug, "name": candidate["name"]}
    if candidate.get("party"):
        profile["party"] = candidate["party"]
    if candidate.get("office"):
        profile["current_office"] = candidate["office"]
    profile["jurisdiction"] = "Texas"
    if candidate.get("background"):
        profile["bio"] = candidate["background"]
    profile["stances"] = stances
    profile["unknowns"] = unknowns
    profile["contradictions"] = []
    # Coverage = fraction of *distinct* issues with any evidence, not stance
    # count -- a candidate can have two stances on the same issue_id (e.g. two
    # different key votes both touching immigration), which must not inflate
    # this above what "unique issues we have evidence for" honestly means.
    profile["source_coverage_score"] = round(len(covered) / len(all_issue_ids), 4) if all_issue_ids else 0.0
    profile["researched_at"] = researched_at
    profile["research_status"] = "partial"
    return profile, finance_attached


# ---------------------------------------------------------------------------
# civic-match/data/elections/texas-house.json
# ---------------------------------------------------------------------------

_HOUSE_RACE_ID_RE = re.compile(r"^tx-cd\d{2}-\d{4}$")
_DISTRICT_RE = re.compile(r"^TX-(\d{2})$")


def build_texas_house_entries(
    races_data: dict,
    candidates: dict,
    skip_log: list[tuple[str, str, str, str]],
) -> list[dict]:
    election_date = races_data.get("election_date") or "2026-11-03"
    entries = []

    for race in races_data.get("races", []):
        race_id = race.get("race_id", "")
        if race.get("level") != "federal" or not _HOUSE_RACE_ID_RE.match(race_id):
            continue  # statewide races and U.S. Senate are federal-but-not-House

        district = race.get("district") or ""
        match = _DISTRICT_RE.match(district)
        if not match:
            skip_log.append((race_id, "texas_house", district or "(no district)", "district doesn't match TX-## pattern"))
            continue
        district_num = str(int(match.group(1)))

        entry_candidates = []
        for cid in race.get("candidate_ids", []):
            c = candidates.get(cid)
            if not c or not c.get("name"):
                skip_log.append((race_id, "texas_house", cid, "candidate id missing from candidates.json"))
                continue
            entry_candidates.append({"name": c["name"], "party": normalize_party_label(c.get("party"))})

        entries.append({
            "race": f"U.S. House {district}",
            "office": f"U.S. Representative, District {district_num}",
            "district": district,
            "election_date": election_date,
            "candidates": entry_candidates,
        })

    entries.sort(key=lambda e: int(e["district"].split("-")[1]))
    return entries


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------

def _load_roster() -> dict[str, tuple[Path, dict]]:
    POLITICIANS_DIR.mkdir(parents=True, exist_ok=True)
    roster: dict[str, tuple[Path, dict]] = {}
    for path in sorted(POLITICIANS_DIR.glob("*.json")):
        try:
            profile = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue  # likely being written by the research swarm right now; pick it up next run
        roster[path.stem] = (path, profile)
    return roster


def atomic_write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        # mkstemp creates the temp file 0600 (owner-only); os.replace preserves
        # that mode across the rename, which would leave the final file
        # unreadable by anyone but the current user -- unlike its untouched
        # 0644 siblings. Normalize to the standard, non-executable 0644 before
        # the rename so every file this script writes is readable the same
        # way as the rest of civic-match/data/.
        os.fchmod(fd, 0o644)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp_path, str(path))
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def verify_json_file(path: Path) -> None:
    with path.open("r", encoding="utf-8") as fh:
        json.load(fh)


# ---------------------------------------------------------------------------
# Stats + summary
# ---------------------------------------------------------------------------

@dataclass
class Stats:
    candidates_total: int = 0
    candidates_skipped_bad_name: int = 0
    candidates_skipped_slug_collision: int = 0
    profiles_matched: int = 0
    profiles_merged: int = 0
    profiles_unchanged: int = 0
    profiles_created: int = 0
    stances_appended: int = 0
    stances_from_votes: int = 0
    stances_from_sponsored: int = 0
    finance_attached: int = 0
    finance_skipped: int = 0
    items_skipped_unmappable: int = 0
    items_skipped_other: int = 0


def _print_summary(stats: Stats, skip_log: list[tuple[str, str, str, str]], finance_log: list[tuple[str, str, str]]) -> None:
    print("=== civic-match export summary ===")
    rows = [
        ("Candidates processed", stats.candidates_total),
        ("  skipped (no name)", stats.candidates_skipped_bad_name),
        ("  skipped (slug collides with another of our candidates)", stats.candidates_skipped_slug_collision),
        ("Profiles matched to existing roster", stats.profiles_matched),
        ("  merged (updated)", stats.profiles_merged),
        ("  unchanged (already up to date)", stats.profiles_unchanged),
        ("Profiles created (new, minimal)", stats.profiles_created),
        ("Stances appended", stats.stances_appended),
        ("  from key votes", stats.stances_from_votes),
        ("  from sponsored bills", stats.stances_from_sponsored),
        ("Finance sources attached", stats.finance_attached),
        ("Finance skipped (no related ethics stance)", stats.finance_skipped),
        ("Items skipped - unmappable issue", stats.items_skipped_unmappable),
        ("Items skipped - other (no direction/missing data)", stats.items_skipped_other),
    ]
    width = max(len(label) for label, _ in rows)
    for label, value in rows:
        print(f"{label.ljust(width)} : {value}")

    if skip_log:
        print("\n--- skipped items (detail) ---")
        for cid, category, detail, reason in skip_log:
            print(f"  [{category}] {cid} / {detail}: {reason}")

    if finance_log:
        print("\n--- finance present but not attached (detail) ---")
        for cid, name, reason in finance_log:
            print(f"  - {name} ({cid}): {reason}")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Merge our gold TX dataset into civic-match's PoliticianProfile JSONs "
            "and emit civic-match/data/elections/texas-house.json."
        )
    )
    parser.add_argument("--dry-run", action="store_true", help="Print planned changes; write nothing.")
    args = parser.parse_args(argv)

    if not GOLD_RACES_PATH.exists() or not GOLD_CANDIDATES_PATH.exists():
        print("SKIP: gold dataset not built yet")
        return 0

    try:
        races_data = json.loads(GOLD_RACES_PATH.read_text(encoding="utf-8"))
        candidates = json.loads(GOLD_CANDIDATES_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        # The fleet may still be mid-write on these exact files; treat a torn
        # read as "not ready yet" rather than crashing.
        print("SKIP: gold dataset not built yet")
        print(f"  (races.json/candidates.json present but not valid JSON yet: {exc})", file=sys.stderr)
        return 0

    if not isinstance(candidates, dict) or not isinstance(races_data.get("races"), list):
        print("SKIP: gold dataset not built yet")
        print("  (races.json/candidates.json present but not in the expected shape yet)", file=sys.stderr)
        return 0

    all_issue_ids = load_issue_ids()
    _validate_issue_tables(set(all_issue_ids))

    roster = _load_roster()

    stats = Stats()
    skip_log: list[tuple[str, str, str, str]] = []
    finance_log: list[tuple[str, str, str]] = []
    planned_writes: list[tuple[Path, object, str]] = []
    action_lines: list[str] = []
    researched_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    claimed_slugs: dict[str, str] = {}  # slug -> candidate_id that already claimed it this run

    for candidate_id, candidate in candidates.items():
        stats.candidates_total += 1
        name = candidate.get("name")
        if not name or not name.strip():
            stats.candidates_skipped_bad_name += 1
            skip_log.append((candidate_id, "candidate", "(no name)", "candidate record has no name"))
            continue

        slug = slugify(name)

        # Two different people in OUR OWN gold data can share a name (e.g. two
        # candidates both named "Sarah Eckhardt" in different races) and thus
        # the same slug. Writing both to the same politicians/<slug>.json
        # would silently conflate two different people's votes/finance into
        # one profile, or have the second clobber the first's freshly written
        # file. Refuse instead of guessing which one "wins".
        if slug in claimed_slugs and claimed_slugs[slug] != candidate_id:
            stats.candidates_skipped_slug_collision += 1
            skip_log.append((
                candidate_id, "candidate", slug,
                f"slug collision with candidate {claimed_slugs[slug]!r} (likely two different "
                "people sharing a name) - skipped rather than conflate their records",
            ))
            continue
        claimed_slugs[slug] = candidate_id

        new_stances = derive_stances(candidate_id, candidate, skip_log)
        stats.stances_from_votes += sum(1 for s in new_stances if s["evidence_type"] == "voting_record")
        stats.stances_from_sponsored += sum(1 for s in new_stances if s["evidence_type"] == "sponsored_bill")

        if slug in roster:
            stats.profiles_matched += 1
            path, profile = roster[slug]
            result = merge_into_existing(candidate_id, candidate, profile, new_stances, finance_log)
            stats.stances_appended += result.stances_appended
            if result.finance_attached:
                stats.finance_attached += 1
            if result.changed:
                stats.profiles_merged += 1
                planned_writes.append((path, profile, "merge"))
                suffix = ", +finance source" if result.finance_attached else ""
                action_lines.append(f"MERGE   {path.name}: +{result.stances_appended} stance(s){suffix}")
            else:
                stats.profiles_unchanged += 1
                action_lines.append(f"OK      {path.name}: already up to date, no changes")
        else:
            path = POLITICIANS_DIR / f"{slug}.json"
            profile, finance_attached = create_new_profile(
                candidate_id, candidate, slug, new_stances, all_issue_ids, finance_log, researched_at
            )
            stats.stances_appended += len(new_stances)
            if finance_attached:
                stats.finance_attached += 1
            stats.profiles_created += 1
            planned_writes.append((path, profile, "create"))
            action_lines.append(
                f"CREATE  {path.name}: minimal profile, {len(new_stances)} stance(s), "
                f"coverage {profile['source_coverage_score']:.3f}"
            )

    house_entries = build_texas_house_entries(races_data, candidates, skip_log)
    existing_house = None
    if TEXAS_HOUSE_PATH.exists():
        try:
            existing_house = json.loads(TEXAS_HOUSE_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing_house = None
    if house_entries != existing_house:
        planned_writes.append((TEXAS_HOUSE_PATH, house_entries, "elections"))
        verb = "CREATE" if existing_house is None else "UPDATE"
        total_candidates = sum(len(e["candidates"]) for e in house_entries)
        action_lines.append(f"{verb}  {TEXAS_HOUSE_PATH.name}: {len(house_entries)} districts, {total_candidates} candidate entries")
    else:
        action_lines.append(f"OK      {TEXAS_HOUSE_PATH.name}: already up to date, no changes")

    stats.finance_skipped = len(finance_log)
    for _cid, _category, _detail, reason in skip_log:
        if "mapping" in reason.lower() or "pattern" in reason.lower():
            stats.items_skipped_unmappable += 1
        else:
            stats.items_skipped_other += 1

    print("\n".join(action_lines))
    print()
    _print_summary(stats, skip_log, finance_log)

    if args.dry_run:
        print("\n(dry run -- no files were written)")
        return 0

    for path, data, _kind in planned_writes:
        atomic_write_json(path, data)

    problems = []
    for path, _data, _kind in planned_writes:
        try:
            verify_json_file(path)
        except (json.JSONDecodeError, OSError) as exc:
            problems.append(f"{path}: {exc}")

    if problems:
        print("\nERROR: re-parse verification failed for:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1

    print(f"\nWrote and verified {len(planned_writes)} file(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
