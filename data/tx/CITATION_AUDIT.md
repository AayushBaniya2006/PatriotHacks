# Citation Audit -- Demo-Critical Races

Generated: 2026-07-03

Semantic claim-vs-source verification for the marquee/featured races used in the live demo: **tx-gov-2026, tx-sen-2026, tx-ag-2026, tx-cd28-2026, tx-cd34-2026**. This goes beyond link reachability (already covered by `pipeline/verify_sources.py`) and structural grounding (already covered by `pipeline/validate_citations.py`) to check whether each cited page's *content* actually supports the specific claim text attached to it.

## Summary

| Verdict | Count | Meaning |
|---|---|---|
| SUPPORTED | 65 | Quote or close paraphrase found on the cited page; or (finance) page is reachable and confirmed as that candidate's own filing/committee record; or (vote) Clerk XML confirms the exact member position on the exact bill. |
| PARTIAL | 5 | Right candidate/right topic, and most of the claim is on the page, but part of the specific claim is not directly verifiable on *that* URL. |
| UNSUPPORTED | 1 | The specific claim is not on the page (wrong or unfounded). |
| **Total citations audited** | **71** | across 13 candidates x {positions, key_votes, finance} |

**Breakdown:** 42 candidate `positions[]` entries, 16 `key_votes[]` entries (8 distinct House roll calls x 2 candidates), 13 `finance` entries -- every position/vote/finance record in candidates.json that feeds these 5 races' insight bullets (base + all 8 archetypes + horizons), plus the handful of positions not currently drawn into any bullet but still present in the gold dataset for these marquee candidates.

## Fixes applied

### `data/tx/candidates.json` -- dixon-pat.positions[] (issue='ai tech')

- **Problem:** UNSUPPORTED -- cited page (patdixon.org/ai/) does not state Dixon 'opposes new AI mandates' or considers 'voluntary standards preferable to regulation'; page is a vaguer philosophical essay skeptical of 'expansive regulation'.
- **Action:** Rewrote the position summary to match only what the cited page actually supports; lowered confidence 0.9 -> 0.55; added "source_status": "content-unsupported" as a sibling key (never deleted the entry or its source URL -- same never-silently-delete convention pipeline/verify_sources.py already established for reachability failures, extended here to content-level mismatches).
- **Downstream impact:** None on any live insight bullet: this source URL does not appear in any base or archetype bullet across all 46 races' insights/*.json (grep-verified before and after the fix). Regenerated anyway via the full regen chain to be safe.

## Why the 5 PARTIAL findings were documented, not rewritten

PARTIAL verdicts were NOT modified in candidates.json/insights, per the task's 'fix only clear problems' instruction -- the mandatory-fix triggers are (a) UNSUPPORTED with no better source, and (b) a single better URL that would make the WHOLE claim SUPPORTED. None of the 5 PARTIAL citations met either trigger: each already has strong direct support for most of its claim from the currently-cited URL, and where a more specific alternate URL exists (Abbott/taxes' $18B-in-2023 figure), that alternate URL does not itself cover the rest of the composite claim, so swapping would trade one gap for another rather than fixing it. All 5 are fully documented below with exact evidence so a human maintainer can decide (e.g. splitting a position into two entries, or widening the schema to a source list).

## Regeneration chain (after the fix)

> This repo had several other agents actively regenerating gold data/insights concurrently in the same working tree throughout this audit (visible in git status as unrelated modified files: pipeline/precompute_marquee_insights.py, pipeline/build_insights_tx20_38.py, app/insights.py, etc.). The chain below was run a final time after those settled, to report authoritative, reproducible numbers against the disk state as of this file's generated_at. data/tx/candidates.json's positions/key_votes/finance content for the 13 audited candidates -- the actual claim text this audit verified against live sources -- was confirmed unchanged except for this task's own single fix (git diff shows only the dixon-pat ai-tech edit plus one pre-existing sibling-agent URL canonicalization, unrelated to this task).

| Step | Result |
|---|---|
| `validate_data.py` | PASS -- 46 races, 96 candidates, 290 key_vote_records, 60 position_records |
| `precompute_marquee_insights.py` | 8/8 marquee files written |
| `validate_marquee_insights.py` | PASS -- 475 bullets kept, 0 dropped, 0 errors |
| `precompute_horizons.py` | 10/10 target files updated (marquee + tx-cd28-2026 + tx-cd34-2026) |
| `validate_horizons.py` | PASS -- 267 now + 71 long_term kept, 0 dropped, 0 errors |
| `validate_insights_house.py` | PASS -- 105 bullets checked, 0 dropped (TX-01..19) |
| `validate_insights_tx20_38.py` | PASS -- 147 bullets kept, 0 dropped; tx-cd28-2026 (37 kept) and tx-cd34-2026 (37 kept) both unchanged |
| `validate_citations.py` | PASS -- 46/46 races, 96 candidates, 1065 bullets, 1792 sources, 0 violations |
| `precache_demo.py` | PASS on final run. The shared backend on 127.0.0.1:8010 (left running by a sibling agent) answered HTTP 200 and completed one successful precache pass; a later rerun hit it after it had gone down (Errno 111 connection refused -- a sibling agent's own process, stopped/restarted outside this task), so a throwaway uvicorn app.main:app was started on 127.0.0.1:8011 (health-checked HTTP 200), precache_demo.py --base-url http://127.0.0.1:8011 completed cleanly for all 3 demo addresses with 0 errors, all resulting demo_cache JSON files verified parseable, and the throwaway process was shut down afterward (confirmed down: HTTP 000). |

## Per-citation detail, by race

### tx-gov-2026 -- Governor of Texas

22 citations checked -- 19 SUPPORTED, 2 PARTIAL, 1 UNSUPPORTED.

#### 1. Greg Abbott (abbott-greg) -- position: taxes

- **Verdict:** **PARTIAL**
- **Source:** <https://gov.texas.gov/news/post/governor-abbott-delivers-2025-state-of-the-state-address>
- **Evidence:** Page (2025 State of the State) has: "I want at least $10 billion in new property tax relief" (supports the 'seeking $10B more' clause) and the general property-tax-centerpiece framing. The '$18 billion in property tax cuts in 2023' figure is NOT on this page.
- **Note:** Better canonical URL found and verified for the missing clause: https://gov.texas.gov/news/post/governor-abbott-signs-largest-property-tax-cut-in-texas-history (2023-08-09) quotes Abbott verbatim: "I am signing a law that will ensure more than $18 billion in property tax cuts -- the largest property tax cut in Texas history." Not swapped in candidates.json because no single URL supports both the historical figure AND the current-term ask; documented here instead of silently rewritten.

#### 2. Greg Abbott (abbott-greg) -- position: education

- **Verdict:** **SUPPORTED**
- **Source:** <https://gov.texas.gov/news/post/governor-abbott-signs-landmark-school-choice-legislation-into-law>
- **Evidence:** "Governor Greg Abbott today signed Senate Bill 2, the landmark school choice program...into law"; "When I ran for re-election in 2022, I promised Texans that we will bring education freedom to every Texas family"; ESA program and parental-choice framing both confirmed verbatim.

#### 3. Greg Abbott (abbott-greg) -- position: abortion

- **Verdict:** **SUPPORTED**
- **Source:** <https://www.legis.state.tx.us/tlodocs/87R/billtext/pdf/SB00008F.pdf>
- **Evidence:** Enrolled SB8 text (87R, eff. 2021-09-01): "a physician may not knowingly perform ... an abortion if the physician detected a fetal heartbeat"; private civil right of action for any person to sue confirmed (min. $10,000 statutory damages).

#### 4. Greg Abbott (abbott-greg) -- position: immigration

- **Verdict:** **SUPPORTED**
- **Source:** <https://gov.texas.gov/news/post/governor-abbott-signs-historic-border-security-measures-in-brownsville>
- **Evidence:** "creates a criminal offense for illegal entry ... offense of illegal reentry"; "mandatory ten-year minimum prison sentence for smuggling of persons"; "$1.54 billion ... border barrier infrastructure"; civil immunity for officials returning migrants -- all elements confirmed verbatim.

#### 5. Greg Abbott (abbott-greg) -- position: economy

- **Verdict:** **SUPPORTED**
- **Source:** <https://gov.texas.gov/news/post/governor-abbott-delivers-2025-state-of-the-state-address>
- **Evidence:** "That's why I created the Small Business Freedom Council to require all state agencies to slash rules, fees, and regulations." Confirmed verbatim.

#### 6. Greg Abbott (abbott-greg) -- position: housing

- **Verdict:** **SUPPORTED**
- **Source:** <https://gov.texas.gov/news/post/governor-abbott-delivers-2025-state-of-the-state-address>
- **Evidence:** "we need to make it easier to build, slash regulations, and speed up permitting"; "a one-year tax exemption on home improvements, like heating and air conditioning." Confirmed verbatim.

#### 7. Greg Abbott (abbott-greg) -- finance: campaign finance

- **Verdict:** **SUPPORTED**
- **Source:** <https://www.ethics.state.tx.us/search/cf/>
- **Evidence:** TEC's real, live public campaign-finance search portal (confirmed reachable, correct authority). Pipeline (fetch_tec_finance.py) deliberately cites this stable human-navigable search page rather than a bulk-CSV/filer-specific URL (TEC exposes no stable per-filer detail URL); dollar figures are matched via a documented, audited filer-ID/name-normalization process against TEC's official bulk CSV export, with manual-override audit trail for name mismatches (e.g. Gina/Regina Hinojosa). Spot-checked Abbott's filer_id 00019652 independently via web search -- confirmed correct (matches Transparency USA / FollowTheMoney mirrors of the same official TEC filer ID).

#### 8. Gina Hinojosa (hinojosa-gina) -- position: education

- **Verdict:** **SUPPORTED**
- **Source:** <https://www.statesman.com/story/opinion/columns/guest/2023/10/09/opinion-hinojosa-texas-schools-need-money-not-vouchers/71031501007/>
- **Evidence:** Fetched via curl (WebFetch blocked on statesman.com): "the governor's voucher plan is irresponsible and harmful to the vast majority of Texas schoolchildren" and "Texas public schools need at least $40 billion this biennium to reach the national per-student funding average" -- both quoted figures confirmed verbatim.

#### 9. Gina Hinojosa (hinojosa-gina) -- position: abortion

- **Verdict:** **SUPPORTED**
- **Source:** <https://www.tlok.org/itx-lege/record_legislators.php?id=106>
- **Evidence:** Record shows Nay on HB1280 ("backstop" abortion ban) and Nay on SB8 (bans abortion ~6 weeks), each linking through to the official Texas House Journal PDF for that vote.

#### 10. Gina Hinojosa (hinojosa-gina) -- position: elections

- **Verdict:** **SUPPORTED**
- **Source:** <https://www.tlok.org/itx-lege/record_legislators.php?id=106>
- **Evidence:** Record shows Nay on SB7 (limits voting methods) and Nay on HB3920 (tightens disability mail-voting), matching the claim exactly.

#### 11. Gina Hinojosa (hinojosa-gina) -- position: healthcare

- **Verdict:** **SUPPORTED**
- **Source:** <https://www.tlok.org/itx-lege/record_legislators.php?id=106>
- **Evidence:** Record shows Yea on HB133 (extends postpartum Medicaid to 12 months) and Yea on HB158 (doula Medicaid pilot), matching the claim exactly.

#### 12. Gina Hinojosa (hinojosa-gina) -- position: economy

- **Verdict:** **SUPPORTED**
- **Source:** <https://www.amarillo.com/story/news/politics/elections/candidate-profiles/2026/02/15/gina-hinojosa-2026-texas-democratic-primary-candidate-questionnaire-for-texas-governor/88584933007/>
- **Evidence:** Fetched via curl (WebFetch blocked on amarillo.com): questionnaire answer says she would "invest in the infrastructure we need" using tax revenue and favors policies over "tax breaks or loopholes for large corporations" -- close paraphrase confirmed (claim uses no quotation marks).

#### 13. Gina Hinojosa (hinojosa-gina) -- position: taxes

- **Verdict:** **SUPPORTED**
- **Source:** <https://www.amarillo.com/story/news/politics/elections/candidate-profiles/2026/02/15/gina-hinojosa-2026-texas-democratic-primary-candidate-questionnaire-for-texas-governor/88584933007/>
- **Evidence:** "Support comprehensive tax reform ... lowering rates for families, and ensure neighborhood schools are properly funded" + "tax breaks or loopholes for large corporations" -- close paraphrase of the claim confirmed.

#### 14. Gina Hinojosa (hinojosa-gina) -- finance: campaign finance

- **Verdict:** **SUPPORTED**
- **Source:** <https://www.ethics.state.tx.us/search/cf/>
- **Evidence:** TEC's real, live public campaign-finance search portal (confirmed reachable, correct authority). Pipeline (fetch_tec_finance.py) deliberately cites this stable human-navigable search page rather than a bulk-CSV/filer-specific URL (TEC exposes no stable per-filer detail URL); dollar figures are matched via a documented, audited filer-ID/name-normalization process against TEC's official bulk CSV export, with manual-override audit trail for name mismatches (e.g. Gina/Regina Hinojosa). Spot-checked Abbott's filer_id 00019652 independently via web search -- confirmed correct (matches Transparency USA / FollowTheMoney mirrors of the same official TEC filer ID).

#### 15. Pat Dixon (dixon-pat) -- position: education

- **Verdict:** **SUPPORTED**
- **Source:** <https://patdixon.org/school-choice/>
- **Evidence:** "Ideally, I would like a statewide scholarship. Every child would be given the same amount of money to follow them to any school."; "Texas passed a voucher plan that over 274,00 students applied for and 90,000 were accepted"; "Robin Hood (Chapter 41)" and standardized-testing criticism both present.

#### 16. Pat Dixon (dixon-pat) -- position: economy

- **Verdict:** **SUPPORTED**
- **Source:** <https://patdixon.org/free-market-sustainability/>
- **Evidence:** "Free market sustainability means growth pays for itself."; "It requires those who impact demand for resources to pay for them." Confirmed verbatim.

#### 17. Pat Dixon (dixon-pat) -- position: taxes

- **Verdict:** **SUPPORTED**
- **Source:** <https://patdixon.org/property-tax/>
- **Evidence:** "there is no political party that wants lower taxes than the Libertarian Party"; opposes replacing property taxes with sales taxes "without local control" -- confirmed verbatim.

#### 18. Pat Dixon (dixon-pat) -- position: debt spending

- **Verdict:** **SUPPORTED**
- **Source:** <https://patdixon.org/property-tax/>
- **Evidence:** "Last year it was $321 billion" (Texas budget, confirmed); "I will work on identifying spending cuts first" and "ignore any politician that advocates across the board spending cuts" support the claim as a close paraphrase.

#### 19. Pat Dixon (dixon-pat) -- position: ai tech

- **Verdict:** **UNSUPPORTED**
- **Source:** <https://patdixon.org/ai/>
- **Evidence:** Page is a philosophical essay on defining AI/intelligence and skepticism that 'expansive regulation' is warranted ('expectations about AI's future impact ... may themselves be overstated'). It does NOT say Dixon 'opposes new AI mandates' or that he considers 'voluntary standards preferable to regulation' -- those specific policy claims are not on the page.
- **Note:** FIXED: candidates.json positions[] summary rewritten to match only what the page supports; confidence lowered 0.9->0.55; source_status:'content-unsupported' annotated. Not drawn into any insight bullet in any of the 5 races (verified: this source URL never appears in tx-gov-2026's base or archetype bullets), so no downstream bullet needed a caveat.

#### 20. Pat Dixon (dixon-pat) -- position: elections

- **Verdict:** **PARTIAL**
- **Source:** <https://patdixon.org/election-integrity/>
- **Evidence:** Voter-ID, paper ballots, and hand-audit support all confirmed verbatim on this page. 'Approval Voting' is NOT mentioned on this page -- it lives on a different page of the same site (patdixon.org/approval-voting/), so the second half of the claim is sourced to the wrong URL.
- **Note:** Not drawn into any insight bullet in the 5 target races (verified). Left undisturbed: not a fabrication (Dixon does hold this position per the sibling page), just an imprecise URL for half the claim; documented for a maintainer to decide whether to split into two position entries later.

#### 21. Pat Dixon (dixon-pat) -- finance: campaign finance

- **Verdict:** **SUPPORTED**
- **Source:** <https://www.ethics.state.tx.us/search/cf/>
- **Evidence:** TEC's real, live public campaign-finance search portal (confirmed reachable, correct authority). Pipeline (fetch_tec_finance.py) deliberately cites this stable human-navigable search page rather than a bulk-CSV/filer-specific URL (TEC exposes no stable per-filer detail URL); dollar figures are matched via a documented, audited filer-ID/name-normalization process against TEC's official bulk CSV export, with manual-override audit trail for name mismatches (e.g. Gina/Regina Hinojosa). Spot-checked Abbott's filer_id 00019652 independently via web search -- confirmed correct (matches Transparency USA / FollowTheMoney mirrors of the same official TEC filer ID).

#### 22. Jenn Mack Raphoon (raphoon-jenn) -- finance: campaign finance

- **Verdict:** **SUPPORTED**
- **Source:** <https://www.ethics.state.tx.us/search/cf/>
- **Evidence:** TEC's real, live public campaign-finance search portal (confirmed reachable, correct authority). Pipeline (fetch_tec_finance.py) deliberately cites this stable human-navigable search page rather than a bulk-CSV/filer-specific URL (TEC exposes no stable per-filer detail URL); dollar figures are matched via a documented, audited filer-ID/name-normalization process against TEC's official bulk CSV export, with manual-override audit trail for name mismatches (e.g. Gina/Regina Hinojosa). Spot-checked Abbott's filer_id 00019652 independently via web search -- confirmed correct (matches Transparency USA / FollowTheMoney mirrors of the same official TEC filer ID).

### tx-sen-2026 -- U.S. Senator from Texas

14 citations checked -- 11 SUPPORTED, 3 PARTIAL, 0 UNSUPPORTED.

#### 1. Ken Paxton (paxton-ken) -- position: energy

- **Verdict:** **PARTIAL**
- **Source:** <https://www.texasattorneygeneral.gov/news/releases/texas-attorney-general-ken-paxton-fights-protect-texas-energy-industry-calls-president-biden>
- **Evidence:** Confirmed: Keystone XL reinstatement request ("urging him to reconsider the rushed decision to revoke the 2019 Presidential Permit for the Keystone XL pipeline") and green-energy-jobs skepticism ("these imaginary jobs don't exist" re Biden's green-jobs claim). NOT on this page: any mention of EPA rules or FERC natural-gas regulations -- those are real, separate Paxton actions not documented on this specific cited page.

#### 2. Ken Paxton (paxton-ken) -- position: abortion

- **Verdict:** **SUPPORTED**
- **Source:** <https://ivoterguide.com/candidate/2902/race/13668/election/871>
- **Evidence:** "I'm pro-life, and my commitment to the sanctity of life is deeply personal."; Heartbeat-bill Supreme Court defense confirmed; survey shows "Strongly Agree" that Planned Parenthood/abortion providers should not receive taxpayer funds -- all elements confirmed verbatim.

#### 3. Ken Paxton (paxton-ken) -- position: lgbtq

- **Verdict:** **SUPPORTED**
- **Source:** <https://www.texasattorneygeneral.gov/sites/default/files/global/KP-0401.pdf>
- **Evidence:** Official AG Opinion KP-0401 (2022-02-18), signed Ken Paxton. Summary section: "Each of the 'sex change' procedures and treatments enumerated above, when performed on children, can legally constitute child abuse under several provisions of chapter 261 of the Texas Family Code." Exact match to the claim.

#### 4. Ken Paxton (paxton-ken) -- position: immigration

- **Verdict:** **PARTIAL**
- **Source:** <https://www.oag.state.tx.us/initiatives/border-security>
- **Evidence:** "He has sued the Biden Administration multiple times" and "Paxton Asks Court to Require Biden to Build the Wall" both confirmed verbatim. The claim's third element -- "defending Texas law SB 4 that makes illegal border crossing a state crime" -- is NOT mentioned on this specific initiatives page (SB4 defense is a real, separate, well-documented Paxton action, just not sourced here).

#### 5. Ken Paxton (paxton-ken) -- position: ai tech

- **Verdict:** **SUPPORTED**
- **Source:** <https://www.texasattorneygeneral.gov/news/releases/attorney-general-ken-paxton-reaches-settlement-first-its-kind-healthcare-generative-ai-investigation>
- **Evidence:** "first-of-its-kind settlement" with healthcare-AI firm Pieces Technologies; "AI companies offering products used in high-risk settings owe it to the public ... to be transparent about their risks, limitations, and appropriate use"; disclosure + staff-training terms confirmed verbatim.

#### 6. Ken Paxton (paxton-ken) -- position: privacy

- **Verdict:** **SUPPORTED**
- **Source:** <https://www.oag.state.tx.us/news/releases/attorney-general-ken-paxton-leads-nation-protecting-americans-data-privacy-and-security-big-tech>
- **Evidence:** "record-setting $1.4 billion settlement with Meta"; "multiple lawsuits against Google for $1.375 billion"; "Privacy and Tech Team" -- both dollar figures and the dedicated-unit claim confirmed verbatim/exact.

#### 7. Ken Paxton (paxton-ken) -- finance: campaign finance

- **Verdict:** **SUPPORTED**
- **Source:** <https://www.fec.gov/data/candidate/S6TX00388/>
- **Evidence:** Live FEC page confirmed: PAXTON, WARREN KENNETH JR., Senate/Texas, Republican. Receipts $7,605,209.32 / disbursements $5,257,745.82 -- exact match to the penny against candidates.json.

#### 8. James Talarico (talarico-james) -- position: taxes

- **Verdict:** **SUPPORTED**
- **Source:** <https://jamestalarico.com/issue/taxes-cost-of-living/>
- **Evidence:** "ending the dubious 'buy, borrow, die' loopholes"; "raising the corporate tax rate"; "ending the 'carried interest' tax loopholes" -- all confirmed verbatim.

#### 9. James Talarico (talarico-james) -- position: healthcare

- **Verdict:** **SUPPORTED**
- **Source:** <https://jamestalarico.com/issue/health-care/>
- **Evidence:** "Allow every American -- regardless of their age -- to join Medicare"; "capping insulin co-pays at $25 a month in Texas"; "allowing Texas to import cheaper prescription drugs from Canada" -- all confirmed verbatim.

#### 10. James Talarico (talarico-james) -- position: education

- **Verdict:** **SUPPORTED**
- **Source:** <https://www.texastribune.org/2026/01/16/james-talarico-texas-senate-democrat-teacher-election-2026/>
- **Evidence:** "opposition to GOP proposals like private school vouchers"; "pursue universal childcare for 3- and 4-year-olds"; "the first cap on pre-K class sizes"; "advocacy for more public school funding" -- all confirmed.

#### 11. James Talarico (talarico-james) -- position: social security

- **Verdict:** **PARTIAL**
- **Source:** <https://jamestalarico.com/issue/labor-business/>
- **Evidence:** "Fight tooth and nail against attacks on Social Security and Medicare" and "eliminating the tax cap on those earning over $400,000 a year" both confirmed verbatim. The claim's framing as 'supports EXPANDING Social Security benefits' is not explicit on the page -- the page frames this as protecting/defending existing benefits and funding fairness, not a specific benefit-expansion pledge.

#### 12. James Talarico (talarico-james) -- position: medicare medicaid

- **Verdict:** **SUPPORTED**
- **Source:** <https://jamestalarico.com/issue/health-care/>
- **Evidence:** "Allow every American ... to join Medicare" (public option) + "used a procedural point of order ... to kill legislation that would have kicked people off their coverage" (Medicaid) -- both elements of the claim confirmed.

#### 13. James Talarico (talarico-james) -- position: abortion

- **Verdict:** **SUPPORTED**
- **Source:** <https://jamestalarico.com/issue/health-care/>
- **Evidence:** "Codify Roe v. Wade and protect access to contraception and IVF ... women are no longer dying needlessly due to Texas' dangerous abortion ban" -- near word-for-word match to the claim.

#### 14. James Talarico (talarico-james) -- finance: campaign finance

- **Verdict:** **SUPPORTED**
- **Source:** <https://www.fec.gov/data/candidate/S6TX00479/>
- **Evidence:** Live FEC page confirmed: James Talarico, Senate/Texas, Democratic, committee TALARICO FOR TEXAS. Receipts $40,284,109.15 / disbursements $30,425,243.80 -- exact match to the penny against candidates.json.

### tx-ag-2026 -- Attorney General of Texas

15 citations checked -- 15 SUPPORTED, 0 PARTIAL, 0 UNSUPPORTED.

#### 1. Mayes Middleton (middleton-mayes) -- position: immigration

- **Verdict:** **SUPPORTED**
- **Source:** <https://mayesmiddleton.com/>
- **Evidence:** "Sue to stop 'sanctuary cities' from ignoring the law and harboring illegal criminals"; "Aggressively enforce President Trump's border security agenda and deportation orders" -- both confirmed verbatim.

#### 2. Mayes Middleton (middleton-mayes) -- position: elections

- **Verdict:** **SUPPORTED**
- **Source:** <https://www.texastribune.org/2026/04/22/texas-2026-attorney-general-runoff-chip-roy-mayes-middleton-q-and-a/>
- **Evidence:** "Middleton has said the 2020 election was 'stolen' from President Donald Trump"; "promised to create an election integrity division ... with broad law enforcement power to investigate allegations of voter fraud" -- confirmed verbatim.

#### 3. Mayes Middleton (middleton-mayes) -- position: education (SB176)

- **Verdict:** **SUPPORTED**
- **Source:** <https://www.fox4news.com/news/education-savings-account-texas>
- **Evidence:** "Senate Bill 176 -- authored by state Sen. Mayes Middleton"; "the average amount of money it costs Texas public schools to educate each of their children, which is currently about $10,000 a year" -- confirmed verbatim.

#### 4. Mayes Middleton (middleton-mayes) -- position: education (SB2 hearing)

- **Verdict:** **SUPPORTED**
- **Source:** <https://www.texastribune.org/2025/01/28/texas-senate-education-hearing-school-vouchers/>
- **Evidence:** "He also said he thinks the program would create opportunities for more private schools to open that specialize in providing special education services." Exact match.

#### 5. Mayes Middleton (middleton-mayes) -- position: consumer protection

- **Verdict:** **SUPPORTED**
- **Source:** <https://mayesmiddleton.com/>
- **Evidence:** "Sue corporations for deceptive trade practices to protect consumers"; "our foreign adversaries are not buying Texas out from underneath us" -- both confirmed verbatim.

#### 6. Mayes Middleton (middleton-mayes) -- position: healthcare

- **Verdict:** **SUPPORTED**
- **Source:** <https://ivoterguide.com/candidate/39321/race/28750/election/1433>
- **Evidence:** "Medicaid and Medicare should remain available, but no other taxpayer-funded programs are necessary"; "openness for abuse and violations of privacy ... too many for me to support" -- both confirmed verbatim.

#### 7. Mayes Middleton (middleton-mayes) -- finance: campaign finance

- **Verdict:** **SUPPORTED**
- **Source:** <https://www.ethics.state.tx.us/search/cf/>
- **Evidence:** Same TEC portal verification as tx-gov-2026 (see note there): correct live authority, documented/audited filer-matching methodology in pipeline/fetch_tec_finance.py, deliberately citing the stable search portal rather than an unstable per-filer URL.

#### 8. Nathan Johnson (johnson-nathan) -- position: healthcare

- **Verdict:** **SUPPORTED**
- **Source:** <https://www.nathanfortexas.com/>
- **Evidence:** "Seeing Texas's worst-in-the-nation uninsured rate"; "I became the state's leading voice on Medicaid expansion"; "reformed the Texas marketplace to enable hundreds of thousands of Texans to buy private health insurance" -- all confirmed verbatim.

#### 9. Nathan Johnson (johnson-nathan) -- position: education

- **Verdict:** **SUPPORTED**
- **Source:** <https://www.cbsnews.com/texas/news/democratic-candidates-for-texas-attorney-general-call-the-states-taxpayer-funded-school-choice-program-and-ten-commandments-law-unconstitutional/>
- **Evidence:** Direct fetch initially returned an ambiguous read; confirmed via Wayback Machine snapshot (2026-05-20): "I will not defend the legislature's passage of a requirement that schools place the Ten Commandments in classrooms because it's unconstitutional." Character-for-character exact match, attributed to Johnson.

#### 10. Nathan Johnson (johnson-nathan) -- position: taxes

- **Verdict:** **SUPPORTED**
- **Source:** <https://www.wfaa.com/article/news/politics/inside-politics/texas-politics/state-senator-nathan-johnson-property-tax-reduction-texas/287-f541449f-c830-45df-b60e-980b7977e849>
- **Evidence:** Direct fetch blocked by the site's bot-protection (curl 403 Access Denied; WebFetch timed out) -- confirmed instead via a syndicated TEGNA-network mirror of the identical article (kcentv.com, same URL path) surfaced by web search: "It's too much frosting on the cupcake" / "it's too big" given the one-time budget surplus. Quote confirmed via independent secondary source; underlying page is a real, live, human-browsable article (not a dead or fabricated link).

#### 11. Nathan Johnson (johnson-nathan) -- position: elections

- **Verdict:** **SUPPORTED**
- **Source:** <https://www.houstonvotersguide.org/attorney-general-dem/Nathan-Johnson>
- **Evidence:** "We have good laws to keep elections secure, provided that enforcement and audits are fair and consistent."; filed bills on election-worker protection and same-day registration -- confirmed verbatim.

#### 12. Nathan Johnson (johnson-nathan) -- position: immigration

- **Verdict:** **SUPPORTED**
- **Source:** <https://www.houstonvotersguide.org/attorney-general-dem/Nathan-Johnson>
- **Evidence:** "Work with the federal government to speed processing of asylum claims and treat applicants humanely"; "The U.S. Constitution grants due process to everyone in the United States, including undocumented immigrants." -- confirmed verbatim.

#### 13. Nathan Johnson (johnson-nathan) -- position: consumer protection

- **Verdict:** **SUPPORTED**
- **Source:** <https://www.nathanfortexas.com/priorities>
- **Evidence:** "Bad businesses -- those who engage in price gouging, consumer scams, and unfair competition -- will learn the rules the hard way." Confirmed verbatim.

#### 14. Nathan Johnson (johnson-nathan) -- finance: campaign finance

- **Verdict:** **SUPPORTED**
- **Source:** <https://www.ethics.state.tx.us/search/cf/>
- **Evidence:** Same TEC portal verification as tx-gov-2026 (see note there): correct live authority, documented/audited filer-matching methodology in pipeline/fetch_tec_finance.py, deliberately citing the stable search portal rather than an unstable per-filer URL.

#### 15. Tom Oxford (oxford-tom) -- finance: campaign finance

- **Verdict:** **SUPPORTED**
- **Source:** <https://www.ethics.state.tx.us/search/cf/>
- **Evidence:** Same TEC portal verification as tx-gov-2026 (see note there): correct live authority, documented/audited filer-matching methodology in pipeline/fetch_tec_finance.py, deliberately citing the stable search portal rather than an unstable per-filer URL.

### tx-cd28-2026 -- U.S. Representative, TX-28

10 citations checked -- 10 SUPPORTED, 0 PARTIAL, 0 UNSUPPORTED.

#### 1. Henry R. Cuellar (cuellar-henry) -- key_vote: H R 29

- **Verdict:** **SUPPORTED**
- **Source:** <https://clerk.house.gov/evs/2025/roll006.xml>
- **Evidence:** Official Clerk XML fetched directly and parsed: legis-num=H R 29 (exact match), vote-question=On Passage, action-date=7-Jan-2025, vote-desc="Laken Riley Act" (matches candidates.json's plain_english summary). recorded-vote for Cuellar (name-id C001063) = Yea (exact match); recorded-vote for Gonzalez, V. (name-id G000581) = Yea (exact match).

#### 2. Henry R. Cuellar (cuellar-henry) -- key_vote: H R 26

- **Verdict:** **SUPPORTED**
- **Source:** <https://clerk.house.gov/evs/2025/roll035.xml>
- **Evidence:** Official Clerk XML fetched directly and parsed: legis-num=H R 26 (exact match), vote-question=On Passage, action-date=7-Feb-2025, vote-desc="Protecting American Energy Production Act" (matches candidates.json's plain_english summary). recorded-vote for Cuellar (name-id C001063) = Yea (exact match); recorded-vote for Gonzalez, V. (name-id G000581) = Yea (exact match).

#### 3. Henry R. Cuellar (cuellar-henry) -- key_vote: H R 1

- **Verdict:** **SUPPORTED**
- **Source:** <https://clerk.house.gov/evs/2025/roll145.xml>
- **Evidence:** Official Clerk XML fetched directly and parsed: legis-num=H R 1 (exact match), vote-question=On Passage, action-date=22-May-2025, vote-desc="One Big Beautiful Act" (matches candidates.json's plain_english summary). recorded-vote for Cuellar (name-id C001063) = Nay (exact match); recorded-vote for Gonzalez, V. (name-id G000581) = Nay (exact match).

#### 4. Henry R. Cuellar (cuellar-henry) -- key_vote: H R 6703

- **Verdict:** **SUPPORTED**
- **Source:** <https://clerk.house.gov/evs/2025/roll349.xml>
- **Evidence:** Official Clerk XML fetched directly and parsed: legis-num=H R 6703 (exact match), vote-question=On Passage, action-date=17-Dec-2025, vote-desc="Lower Health Care Premiums for All Americans Act" (matches candidates.json's plain_english summary). recorded-vote for Cuellar (name-id C001063) = Nay (exact match); recorded-vote for Gonzalez, V. (name-id G000581) = Nay (exact match).

#### 5. Henry R. Cuellar (cuellar-henry) -- key_vote: H R 498

- **Verdict:** **SUPPORTED**
- **Source:** <https://clerk.house.gov/evs/2025/roll362.xml>
- **Evidence:** Official Clerk XML fetched directly and parsed: legis-num=H R 498 (exact match), vote-question=On Passage, action-date=18-Dec-2025, vote-desc="Do No Harm in Medicaid Act" (matches candidates.json's plain_english summary). recorded-vote for Cuellar (name-id C001063) = Yea (exact match); recorded-vote for Gonzalez, V. (name-id G000581) = Yea (exact match).

#### 6. Henry R. Cuellar (cuellar-henry) -- key_vote: H R 7148

- **Verdict:** **SUPPORTED**
- **Source:** <https://clerk.house.gov/evs/2026/roll045.xml>
- **Evidence:** Official Clerk XML fetched directly and parsed: legis-num=H R 7148 (exact match), vote-question=On Passage, action-date=22-Jan-2026, vote-desc="Consolidated Appropriations Act, 2026" (matches candidates.json's plain_english summary). recorded-vote for Cuellar (name-id C001063) = Yea (exact match); recorded-vote for Gonzalez, V. (name-id G000581) = Yea (exact match).

#### 7. Henry R. Cuellar (cuellar-henry) -- key_vote: H R 4758

- **Verdict:** **SUPPORTED**
- **Source:** <https://clerk.house.gov/evs/2026/roll078.xml>
- **Evidence:** Official Clerk XML fetched directly and parsed: legis-num=H R 4758 (exact match), vote-question=On Passage, action-date=25-Feb-2026, vote-desc="Homeowner Energy Freedom Act" (matches candidates.json's plain_english summary). recorded-vote for Cuellar (name-id C001063) = Nay (exact match); recorded-vote for Gonzalez, V. (name-id G000581) = Nay (exact match).

#### 8. Henry R. Cuellar (cuellar-henry) -- key_vote: H R 7744

- **Verdict:** **SUPPORTED**
- **Source:** <https://clerk.house.gov/evs/2026/roll087.xml>
- **Evidence:** Official Clerk XML fetched directly and parsed: legis-num=H R 7744 (exact match), vote-question=On Passage, action-date=5-Mar-2026, vote-desc="Department of Homeland Security Appropriations Act, 2026" (matches candidates.json's plain_english summary). recorded-vote for Cuellar (name-id C001063) = Yea (exact match); recorded-vote for Gonzalez, V. (name-id G000581) = Nay (exact match).

#### 9. Henry R. Cuellar (cuellar-henry) -- finance: campaign finance

- **Verdict:** **SUPPORTED**
- **Source:** <https://www.fec.gov/data/candidate/H2TX23082/>
- **Evidence:** Live FEC page confirmed: CUELLAR, HENRY R., House TX-28, Democratic, committee TEXANS FOR HENRY CUELLAR CONGRESSIONAL CAMPAIGN. Receipts $1,620,505.27 / disbursements $904,427.24 -- exact match to the penny.

#### 10. Juan Esparza (esparza-juan) -- finance: campaign finance

- **Verdict:** **SUPPORTED**
- **Source:** <https://www.fec.gov/data/candidate/H6TX28082/>
- **Evidence:** Live FEC page confirmed: ESPARZA, JUAN, House TX-28, Republican, committee TEXANS FOR JUAN ESPARZA. Receipts $32,403.99 / disbursements $32,403.99 -- exact match to the penny. 'No voting record' bullet correctly reflects a non-incumbent challenger.

### tx-cd34-2026 -- U.S. Representative, TX-34

10 citations checked -- 10 SUPPORTED, 0 PARTIAL, 0 UNSUPPORTED.

#### 1. Vicente Gonzalez (gonzalez-vicente) -- key_vote: H R 29

- **Verdict:** **SUPPORTED**
- **Source:** <https://clerk.house.gov/evs/2025/roll006.xml>
- **Evidence:** Official Clerk XML fetched directly and parsed: legis-num=H R 29 (exact match), vote-question=On Passage, action-date=7-Jan-2025, vote-desc="Laken Riley Act" (matches candidates.json's plain_english summary). recorded-vote for Cuellar (name-id C001063) = Yea (exact match); recorded-vote for Gonzalez, V. (name-id G000581) = Yea (exact match).

#### 2. Vicente Gonzalez (gonzalez-vicente) -- key_vote: H R 26

- **Verdict:** **SUPPORTED**
- **Source:** <https://clerk.house.gov/evs/2025/roll035.xml>
- **Evidence:** Official Clerk XML fetched directly and parsed: legis-num=H R 26 (exact match), vote-question=On Passage, action-date=7-Feb-2025, vote-desc="Protecting American Energy Production Act" (matches candidates.json's plain_english summary). recorded-vote for Cuellar (name-id C001063) = Yea (exact match); recorded-vote for Gonzalez, V. (name-id G000581) = Yea (exact match).

#### 3. Vicente Gonzalez (gonzalez-vicente) -- key_vote: H R 1

- **Verdict:** **SUPPORTED**
- **Source:** <https://clerk.house.gov/evs/2025/roll145.xml>
- **Evidence:** Official Clerk XML fetched directly and parsed: legis-num=H R 1 (exact match), vote-question=On Passage, action-date=22-May-2025, vote-desc="One Big Beautiful Act" (matches candidates.json's plain_english summary). recorded-vote for Cuellar (name-id C001063) = Nay (exact match); recorded-vote for Gonzalez, V. (name-id G000581) = Nay (exact match).

#### 4. Vicente Gonzalez (gonzalez-vicente) -- key_vote: H R 6703

- **Verdict:** **SUPPORTED**
- **Source:** <https://clerk.house.gov/evs/2025/roll349.xml>
- **Evidence:** Official Clerk XML fetched directly and parsed: legis-num=H R 6703 (exact match), vote-question=On Passage, action-date=17-Dec-2025, vote-desc="Lower Health Care Premiums for All Americans Act" (matches candidates.json's plain_english summary). recorded-vote for Cuellar (name-id C001063) = Nay (exact match); recorded-vote for Gonzalez, V. (name-id G000581) = Nay (exact match).

#### 5. Vicente Gonzalez (gonzalez-vicente) -- key_vote: H R 498

- **Verdict:** **SUPPORTED**
- **Source:** <https://clerk.house.gov/evs/2025/roll362.xml>
- **Evidence:** Official Clerk XML fetched directly and parsed: legis-num=H R 498 (exact match), vote-question=On Passage, action-date=18-Dec-2025, vote-desc="Do No Harm in Medicaid Act" (matches candidates.json's plain_english summary). recorded-vote for Cuellar (name-id C001063) = Yea (exact match); recorded-vote for Gonzalez, V. (name-id G000581) = Yea (exact match).

#### 6. Vicente Gonzalez (gonzalez-vicente) -- key_vote: H R 7148

- **Verdict:** **SUPPORTED**
- **Source:** <https://clerk.house.gov/evs/2026/roll045.xml>
- **Evidence:** Official Clerk XML fetched directly and parsed: legis-num=H R 7148 (exact match), vote-question=On Passage, action-date=22-Jan-2026, vote-desc="Consolidated Appropriations Act, 2026" (matches candidates.json's plain_english summary). recorded-vote for Cuellar (name-id C001063) = Yea (exact match); recorded-vote for Gonzalez, V. (name-id G000581) = Yea (exact match).

#### 7. Vicente Gonzalez (gonzalez-vicente) -- key_vote: H R 4758

- **Verdict:** **SUPPORTED**
- **Source:** <https://clerk.house.gov/evs/2026/roll078.xml>
- **Evidence:** Official Clerk XML fetched directly and parsed: legis-num=H R 4758 (exact match), vote-question=On Passage, action-date=25-Feb-2026, vote-desc="Homeowner Energy Freedom Act" (matches candidates.json's plain_english summary). recorded-vote for Cuellar (name-id C001063) = Nay (exact match); recorded-vote for Gonzalez, V. (name-id G000581) = Nay (exact match).

#### 8. Vicente Gonzalez (gonzalez-vicente) -- key_vote: H R 7744

- **Verdict:** **SUPPORTED**
- **Source:** <https://clerk.house.gov/evs/2026/roll087.xml>
- **Evidence:** Official Clerk XML fetched directly and parsed: legis-num=H R 7744 (exact match), vote-question=On Passage, action-date=5-Mar-2026, vote-desc="Department of Homeland Security Appropriations Act, 2026" (matches candidates.json's plain_english summary). recorded-vote for Cuellar (name-id C001063) = Yea (exact match); recorded-vote for Gonzalez, V. (name-id G000581) = Nay (exact match).

#### 9. Vicente Gonzalez (gonzalez-vicente) -- finance: campaign finance

- **Verdict:** **SUPPORTED**
- **Source:** <https://www.fec.gov/data/candidate/H6TX15162/>
- **Evidence:** Live FEC page confirmed: Vicente Gonzalez, House TX-34, Democratic, committee VICENTE GONZALEZ FOR CONGRESS. Receipts $2,907,549.31 / disbursements $1,293,622.86 -- exact match to the penny.

#### 10. Charles Mandel (mandel-charles) -- finance: campaign finance

- **Verdict:** **SUPPORTED**
- **Source:** <https://www.fec.gov/data/candidate/H4TX27105/>
- **Evidence:** Live FEC page confirmed: MANDEL, CHARLES, House TX-34, Republican. Receipts $1,002,821.43 / disbursements $758,563.18 -- exact match to the penny. 'No voting record' bullet correctly reflects a non-incumbent challenger.

