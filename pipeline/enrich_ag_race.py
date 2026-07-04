#!/usr/bin/env python3
"""
enrich_ag_race.py -- SOURCED enrichment for tx-ag-2026 (Attorney General of
Texas: Mayes Middleton, Nathan Johnson, Tom Oxford), identified as our
weakest marquee race: zero positions[], zero record.key_votes, zero finance
prior to the concurrent TEC-finance-agent pass that filled finance only.

This script closes the positions[] gap with hand-researched, cited stances,
plus a modest sourced expansion of each candidate's one-line `background`.

Research method (2026-07-03, via WebSearch + WebFetch): each candidate's own
campaign site, their official Texas Senate member page, Wikipedia, and news
coverage (Texas Tribune, CBS News Texas, WFAA, fox4news, teachthevote.atpe.org,
League of Women Voters of Houston voter guide, iVoterGuide questionnaire,
San Antonio Report). Every position below is a claim EXPLICITLY made in its
cited source -- quoted or closely paraphrased, never invented, never
stretched to a topic the source didn't address.

Tom Oxford (Libertarian) genuinely has thin coverage: Vote-USA, TransparencyUSA,
the Libertarian Party of Texas candidates page, an Amarillo Pioneer convention
recap, and a San Antonio Report bio profile were all checked and none carries
a stated AG-relevant policy position from him -- so POSITIONS["oxford-tom"] is
intentionally empty. That is the honest finding, not a gap in this script.

One citation (johnson-nathan / taxes, wfaa.com) was read via two independent
WebSearch tool syntheses after two direct WebFetch attempts to that URL each
timed out; its content (an attributed, quoted statement) was consistent
across both search attempts. Flagged with a slightly lower confidence (0.65)
to reflect that one extra layer of indirection versus a direct page fetch.

Shape per CLAUDE.md's positions contract: {issue, summary, source}, plus the
same optional origin/confidence fields already used by
pipeline/import_civicmatch_positions.py's civic-match-research imports.

Idempotent / append-only / dedup-guarded: re-running is a no-op the second
time. Positions dedup on the (issue, summary, source) triple, matching
pipeline/import_civicmatch_positions.py's convention exactly. Background
text is only overwritten if it still equals the known pre-enrichment stub
(never clobbers a value this script didn't itself write, and never clobbers
a value some other process wrote later).
Atomic write: temp file in the same directory, then os.replace().

Run:
    python3 pipeline/enrich_ag_race.py
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CANDIDATES_PATH = ROOT / "data" / "tx" / "candidates.json"

ORIGIN = "web-research"

# ---------------------------------------------------------------------------
# Researched positions, embedded as a literal for auditability + rerunning.
# Every summary is a neutral, closely-paraphrased-or-quoted statement of what
# THAT candidate has said/done, per the cited source, read 2026-07-03.
# ---------------------------------------------------------------------------
POSITIONS: dict[str, list[dict]] = {
    "middleton-mayes": [
        {
            "issue": "immigration",
            "summary": (
                "Middleton's attorney general campaign platform pledges to sue to stop "
                "so-called 'sanctuary cities' from 'ignoring the law and harboring illegal "
                "criminals' and to 'aggressively enforce President Trump's border security "
                "agenda and deportation orders.'"
            ),
            "source": "https://mayesmiddleton.com/",
            "origin": ORIGIN,
            "confidence": 0.9,
        },
        {
            "issue": "elections",
            "summary": (
                "Middleton has said the 2020 presidential election was 'stolen' from Donald "
                "Trump and has pledged to create an 'election integrity division' within the "
                "attorney general's office with 'broad law enforcement power to investigate "
                "allegations of voter fraud,' pointing to his role passing legislation letting "
                "the AG pursue election-fraud cases independently."
            ),
            "source": "https://www.texastribune.org/2026/04/22/texas-2026-attorney-general-runoff-chip-roy-mayes-middleton-q-and-a/",
            "origin": ORIGIN,
            "confidence": 0.85,
        },
        {
            "issue": "education",
            "summary": (
                "State Sen. Mayes Middleton authored Senate Bill 176 (2023), which would "
                "create education savings accounts letting participating families receive "
                "'the average amount of money it costs Texas public schools to educate each "
                "of their children' -- about $10,000 a year -- to spend on private-school "
                "tuition, online schooling, tutoring, or higher-education costs."
            ),
            "source": "https://www.fox4news.com/news/education-savings-account-texas",
            "origin": ORIGIN,
            "confidence": 0.8,
        },
        {
            "issue": "education",
            "summary": (
                "In a January 2025 Senate committee hearing on Senate Bill 2 (education "
                "savings accounts), Middleton spoke in support of the program and said he "
                "expects it to 'create opportunities for more private schools to open that "
                "specialize in providing special education services.'"
            ),
            "source": "https://www.texastribune.org/2025/01/28/texas-senate-education-hearing-school-vouchers/",
            "origin": ORIGIN,
            "confidence": 0.85,
        },
        {
            "issue": "consumer protection",
            "summary": (
                "Middleton's campaign platform lists suing 'corporations for deceptive trade "
                "practices to protect consumers' among his stated attorney-general priorities, "
                "alongside fighting to prevent 'foreign adversaries' from acquiring Texas assets."
            ),
            "source": "https://mayesmiddleton.com/",
            "origin": ORIGIN,
            "confidence": 0.8,
        },
        {
            "issue": "healthcare",
            "summary": (
                "In a candidate questionnaire, Middleton selected the position that "
                "'Medicaid and Medicare should remain available, but no other taxpayer-funded "
                "[healthcare] programs are necessary,' and said he opposes government medical "
                "databases over concerns about 'abuse and violations of privacy.'"
            ),
            "source": "https://ivoterguide.com/candidate/39321/race/28750/election/1433",
            "origin": ORIGIN,
            "confidence": 0.7,
        },
    ],
    "johnson-nathan": [
        {
            "issue": "healthcare",
            "summary": (
                "Johnson's campaign site says that after seeing Texas's 'worst-in-the-nation "
                "uninsured rate,' he 'became the state's leading voice on Medicaid expansion' "
                "in the state Senate, and describes his work reforming 'the Texas marketplace "
                "to enable hundreds of thousands of Texans to buy private health insurance.'"
            ),
            "source": "https://www.nathanfortexas.com/",
            "origin": ORIGIN,
            "confidence": 0.8,
        },
        {
            "issue": "education",
            "summary": (
                "Johnson has said he would not defend Texas's law requiring the Ten "
                "Commandments be displayed in public school classrooms if elected attorney "
                "general, calling it unconstitutional: 'I will not defend the legislature's "
                "passage of a requirement that schools place the Ten Commandments in "
                "classrooms because it's unconstitutional.'"
            ),
            "source": "https://www.cbsnews.com/texas/news/democratic-candidates-for-texas-attorney-general-call-the-states-taxpayer-funded-school-choice-program-and-ten-commandments-law-unconstitutional/",
            "origin": ORIGIN,
            "confidence": 0.9,
        },
        {
            "issue": "taxes",
            "summary": (
                "On the Legislature's property-tax-cut package, Johnson said it had 'too "
                "much frosting on the cupcake' and was 'too big' given it relied on a "
                "one-time budget surplus, but that faced with an up-or-down vote he "
                "supported it: 'It's either property tax reduction, or no property tax "
                "reduction. And in principle, I support the whole thing.'"
            ),
            "source": "https://www.wfaa.com/article/news/politics/inside-politics/texas-politics/state-senator-nathan-johnson-property-tax-reduction-texas/287-f541449f-c830-45df-b60e-980b7977e849",
            "origin": ORIGIN,
            "confidence": 0.65,
        },
        {
            "issue": "elections",
            "summary": (
                "In a League of Women Voters of Houston questionnaire, Johnson said 'we "
                "have good laws to keep elections secure, provided that enforcement and "
                "audits are fair and consistent,' and noted he has filed Senate legislation "
                "to protect election workers from harassment, enable same-day voter "
                "registration, and move redistricting to an independent commission."
            ),
            "source": "https://www.houstonvotersguide.org/attorney-general-dem/Nathan-Johnson",
            "origin": ORIGIN,
            "confidence": 0.85,
        },
        {
            "issue": "immigration",
            "summary": (
                "In the same questionnaire, Johnson said he would have the attorney "
                "general's office work with federal authorities to 'speed processing of "
                "asylum claims and treat applicants humanely,' stated that 'the U.S. "
                "Constitution grants due process to everyone in the United States, "
                "including undocumented immigrants,' and proposed revising Texas's 287(g) "
                "immigration-enforcement agreements and expanding guest-worker programs."
            ),
            "source": "https://www.houstonvotersguide.org/attorney-general-dem/Nathan-Johnson",
            "origin": ORIGIN,
            "confidence": 0.85,
        },
        {
            "issue": "consumer protection",
            "summary": (
                "Johnson's campaign platform pledges to 'protect consumers and make life "
                "more affordable' by enforcing existing consumer-protection laws against "
                "businesses engaged in 'price gouging, consumer scams, and unfair "
                "competition.'"
            ),
            "source": "https://www.nathanfortexas.com/priorities",
            "origin": ORIGIN,
            "confidence": 0.8,
        },
    ],
    # Thin coverage confirmed across 6+ independently checked sources
    # (Vote-USA, TransparencyUSA, Libertarian Party of Texas candidates page,
    # an Amarillo Pioneer convention recap, a San Antonio Report bio profile,
    # and the Wikipedia race page) -- none carries a stated AG-relevant issue
    # position from Oxford himself. Honest zero, not padded.
    "oxford-tom": [],
}

# Enriched background text, applied ONLY if the candidate's current
# background still equals the known pre-enrichment stub -- idempotent,
# never clobbers a value this script didn't itself write.
BACKGROUND_UPDATES: dict[str, dict] = {
    "middleton-mayes": {
        "old": "Mayes Middleton, state senator from the 11th district (2023–present).",
        "new": (
            "Mayes Middleton is a Republican state senator representing Senate District 11 "
            "(elected 2022, serving since January 2023) who previously served two terms in "
            "the Texas House (2019-2023) chairing the Texas House Freedom Caucus; he is "
            "president of Middleton Oil Company, an independent oil and gas firm, and is the "
            "Republican nominee for Texas Attorney General in 2026."
        ),
        "sources": [
            "https://en.wikipedia.org/wiki/Mayes_Middleton",
            "https://senate.texas.gov/member.php?d=11",
        ],
    },
    "johnson-nathan": {
        "old": "Nathan Johnson, state senator from the 16th district (2019–present).",
        "new": (
            "Nathan Johnson is a Democratic state senator representing Senate District 16 "
            "in Dallas County (since January 2019) and a business litigator at Thompson "
            "Coburn LLP; he is the Democratic nominee for Texas Attorney General in 2026 "
            "after winning a May 2026 primary runoff."
        ),
        "sources": [
            "https://en.wikipedia.org/wiki/Nathan_M._Johnson",
            "https://senate.texas.gov/member.php?d=16",
        ],
    },
    "oxford-tom": {
        "old": "Tom Oxford (Libertarian), attorney and perennial candidate",
        "new": (
            "Tom Oxford is a Beaumont, Texas attorney who has practiced personal injury and "
            "immigration law with the Waldman Smallwood firm; running as the Libertarian "
            "Party's nominee, he previously ran unsuccessfully for the Texas Supreme Court, "
            "Place 3, in 2022."
        ),
        "sources": [
            "https://sanantonioreport.org/profile/thomas-oxford/",
        ],
    },
}


def dedup_key(p: dict) -> tuple:
    return (p.get("issue"), p.get("summary"), p.get("source"))


def apply_positions(candidates: dict) -> dict:
    report = {}
    for cid, new_positions in POSITIONS.items():
        c = candidates.get(cid)
        if c is None:
            report[cid] = {"error": "candidate not found in candidates.json"}
            continue
        c.setdefault("positions", [])
        c.setdefault("sources", [])
        existing_keys = {dedup_key(p) for p in c["positions"]}
        added = 0
        skipped_dupe = 0
        for p in new_positions:
            key = dedup_key(p)
            if key in existing_keys:
                skipped_dupe += 1
                continue
            c["positions"].append(dict(p))
            existing_keys.add(key)
            added += 1
            src = p.get("source")
            if src and src not in c["sources"]:
                c["sources"].append(src)
        report[cid] = {
            "added": added,
            "skipped_dupe_on_rerun": skipped_dupe,
            "total_positions_now": len(c["positions"]),
        }
    return report


def apply_background(candidates: dict) -> dict:
    report = {}
    for cid, upd in BACKGROUND_UPDATES.items():
        c = candidates.get(cid)
        if c is None:
            report[cid] = "SKIPPED (candidate not found)"
            continue
        current = c.get("background")
        if current == upd["old"]:
            c["background"] = upd["new"]
            c.setdefault("sources", [])
            for src in upd["sources"]:
                if src not in c["sources"]:
                    c["sources"].append(src)
            report[cid] = "updated"
        elif current == upd["new"]:
            report[cid] = "already up to date (no-op)"
        else:
            report[cid] = f"SKIPPED -- background changed since baseline: {current!r}"
    return report


def main() -> None:
    with open(CANDIDATES_PATH, encoding="utf-8") as f:
        candidates = json.load(f)

    print("=== tx-ag-2026 SOURCED enrichment ===")
    pos_report = apply_positions(candidates)
    for cid, r in pos_report.items():
        print(f"  positions[{cid}]: {r}")

    print()
    bg_report = apply_background(candidates)
    for cid, r in bg_report.items():
        print(f"  background[{cid}]: {r}")

    total_added = sum(r.get("added", 0) for r in pos_report.values() if isinstance(r, dict))
    print(f"\nTotal new positions added this run: {total_added}")
    if not POSITIONS.get("oxford-tom"):
        print(
            "NOTE: oxford-tom has 0 researched positions on file -- confirmed thin "
            "coverage across multiple independent sources, reported honestly rather "
            "than padded (see module docstring)."
        )

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
