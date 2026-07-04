# Austin / Central-Texas Demo Addresses

Bulletproof, exact-matchable demo address set for the Austin / Central-Texas metro. Every address below was verified LIVE in this session against the running backend (`http://127.0.0.1:8010`): `GET /api/ballot` (>=8 races, valid `cd`), then `POST /api/insights` for that address's featured US House race with a veteran voter profile, confirming `mode: "cached"` and non-empty sourced bullets. Nothing here is assumed -- the Census geocoder only matches exact real street addresses (no ZIP/city/fuzzy matching), so an address that looks right but isn't in TIGER simply 422s (see **Dropped** below).

**21 verified addresses across 6 distinct congressional districts** (TX-10, TX-17, TX-21, TX-31, TX-35, TX-37) -- all of Travis County's core CDs plus the Williamson/Hays suburban ring. Every address returns **9 races** (8 statewide/US-Senate marquee races + 1 US House race) and 100% reliable insights (cached, sourced). All are seeded read-only in `data/tx/geocode_seed.json` (via `pipeline/build_geocode_seed.py`'s `AUSTIN_DEMO_ADDRESSES` list, or as a top-level golden/precache address for the Capitol), so every one of them resolves with **zero live-geocoder dependency** on a cold restart.

## Best single Austin demo address

> ### **1100 Congress Ave, Austin, TX 78701** -- the Texas Capitol
>
> The single most recognizable Austin address there is, and the most battle-tested address in the whole codebase: it's simultaneously one of `pipeline/precache_demo.py`'s 3 zero-dependency demo addresses, a top-level entry in `data/tx/geocode_seed.json`, and has a fully precomputed `data/demo_cache/` entry. Resolves to **TX-37 / SD-14 / HD-49 / Travis County**, 9 races, featured race `tx-cd37-2026` (tier C, score 48.0, 2 contested candidates: Rep. Lloyd Doggett vs. Lauren Pena), 5/5 sourced insight bullets for a veteran profile confirmed cached. Nothing to explain, nothing to double-check on stage -- type it and go.

## Verified set, grouped by resolved CD

### TX-37 (central/downtown Austin, Travis Co -- Rep. Lloyd Doggett vs. Lauren Pena)

8 address(es) -- all resolve to `TX-37`, featured race `tx-cd37-2026` (tier C, score 48.0, 2 candidates).

| Address | Matched (Census) | SD / HD / County | Races | Reliability |
|---|---|---|---|---|
| **Texas Capitol** -- 1100 Congress Ave, Austin, TX 78701 | 1100 CONGRESS AVE, AUSTIN, TX, 78701 | SD-14 / HD-49 / Travis County | 9 | reliable: finance+votes+insights present (5/5 sourced bullets, mode=cached) |
| **Austin City Hall** -- 301 W 2nd St, Austin, TX 78701 | 301 W 2ND ST, AUSTIN, TX, 78701 | SD-14 / HD-49 / Travis County | 9 | reliable: finance+votes+insights present (5/5 sourced bullets, mode=cached) |
| **UT Austin Main Building** -- 110 Inner Campus Dr, Austin, TX 78712 | 110 INNER CAMPUS DR, AUSTIN, TX, 78712 | SD-14 / HD-49 / Travis County | 9 | reliable: finance+votes+insights present (5/5 sourced bullets, mode=cached) |
| **Austin Central Library** -- 710 W Cesar Chavez St, Austin, TX 78701 | 710 W CESAR CHAVEZ ST, AUSTIN, TX, 78701 | SD-14 / HD-49 / Travis County | 9 | reliable: finance+votes+insights present (5/5 sourced bullets, mode=cached) |
| **Zilker Park** -- 2100 Barton Springs Rd, Austin, TX 78704 | 2100 BARTON SPRINGS RD, AUSTIN, TX, 78746 | SD-14 / HD-48 / Travis County | 9 | reliable: finance+votes+insights present (5/5 sourced bullets, mode=cached) |
| **Q2 Stadium** -- 10414 McKalla Pl, Austin, TX 78758 | 10414 MC KALLA PL, AUSTIN, TX, 78758 | SD-14 / HD-49 / Travis County | 9 | reliable: finance+votes+insights present (5/5 sourced bullets, mode=cached) |
| **The Domain** -- 11410 Century Oaks Ter, Austin, TX 78758 | 11410 CENTURY OAKS TER, AUSTIN, TX, 78758 | SD-14 / HD-50 / Travis County | 9 | reliable: finance+votes+insights present (5/5 sourced bullets, mode=cached) |
| **Long Center for the Performing Arts** -- 701 W Riverside Dr, Austin, TX 78704 | 701 W RIVERSIDE DR, AUSTIN, TX, 78704 | SD-14 / HD-51 / Travis County | 9 | reliable: finance+votes+insights present (5/5 sourced bullets, mode=cached) |

### TX-10 (NW Austin / Williamson Co suburbs -- Rep. Michael McCaul vs. Sarah Eckhardt)

4 address(es) -- all resolve to `TX-10`, featured race `tx-cd10-2026` (tier C, score 48.0, 2 candidates).

| Address | Matched (Census) | SD / HD / County | Races | Reliability |
|---|---|---|---|---|
| **Cedar Park City Hall** -- 450 Cypress Creek Rd, Cedar Park, TX 78613 | 450 CYPRESS CREEK RD, CEDAR PARK, TX, 78613 | SD-24 / HD-20 / Williamson County | 9 | reliable: finance+votes+insights present (6/6 sourced bullets, mode=cached) |
| **Lakeway City Hall** -- 1102 Lohmans Crossing Rd, Lakeway, TX 78734 | 1102 LOHMANS CROSSING RD, LAKEWAY, TX, 78734 | SD-25 / HD-19 / Travis County | 9 | reliable: finance+votes+insights present (6/6 sourced bullets, mode=cached) |
| **Pflugerville (E Pecan St)** -- 201 E Pecan St, Pflugerville, TX 78660 | 201 E PECAN ST, PFLUGERVILLE, TX, 78660 | SD-14 / HD-50 / Travis County | 9 | reliable: finance+votes+insights present (6/6 sourced bullets, mode=cached) |
| **Pflugerville (E Main St)** -- 100 E Main St, Pflugerville, TX 78660 | 100 E MAIN ST, PFLUGERVILLE, TX, 78660 | SD-14 / HD-46 / Travis County | 9 | reliable: finance+votes+insights present (6/6 sourced bullets, mode=cached) |

### TX-17 (Round Rock / Williamson Co -- Rep. Pete Sessions vs. James Mitchell)

1 address(es) -- all resolve to `TX-17`, featured race `tx-cd17-2026` (tier C, score 48.0, 2 candidates).

| Address | Matched (Census) | SD / HD / County | Races | Reliability |
|---|---|---|---|---|
| **Round Rock City Hall** -- 221 E Main St, Round Rock, TX 78664 | 221 E MAIN AVE, ROUND ROCK, TX, 78664 | SD-5 / HD-136 / Williamson County | 9 | reliable: finance+votes+insights present (6/6 sourced bullets, mode=cached) |

### TX-21 (Hays Co / Hill Country -- Rep. Chip Roy vs. Kristin Hook)

2 address(es) -- all resolve to `TX-21`, featured race `tx-cd21-2026` (tier C, score 48.0, 2 candidates).

| Address | Matched (Census) | SD / HD / County | Races | Reliability |
|---|---|---|---|---|
| **Kyle City Hall** -- 100 W Center St, Kyle, TX 78640 | 100 W CENTER ST, KYLE, TX, 78640 | SD-21 / HD-45 / Hays County | 9 | reliable: finance+votes+insights present (5/5 sourced bullets, mode=cached) |
| **Dripping Springs Ranch Park** -- 511 Sportsplex Dr, Dripping Springs, TX 78620 | 511 SPORTSPLEX TRL, DRIPPING SPRINGS, TX, 78620 | SD-25 / HD-73 / Hays County | 9 | reliable: finance+votes+insights present (5/5 sourced bullets, mode=cached) |

### TX-31 (Georgetown / Williamson Co -- Rep. John Carter vs. Gregory Stoker)

2 address(es) -- all resolve to `TX-31`, featured race `tx-cd31-2026` (tier C, score 43.0, 2 candidates).

| Address | Matched (Census) | SD / HD / County | Races | Reliability |
|---|---|---|---|---|
| **Georgetown (Williamson Co Courthouse)** -- 710 S Main St, Georgetown, TX 78626 | 710 S MAIN ST, GEORGETOWN, TX, 78626 | SD-5 / HD-20 / Williamson County | 9 | reliable: finance+votes+insights present (4/4 sourced bullets, mode=cached) |
| **Georgetown (Martin Luther King Jr St)** -- 808 Martin Luther King Jr St, Georgetown, TX 78626 | 808 MARTIN LUTHER KING ST, GEORGETOWN, TX, 78626 | SD-5 / HD-20 / Williamson County | 9 | reliable: finance+votes+insights present (4/4 sourced bullets, mode=cached) |

### TX-35 (San Marcos / Austin-San Antonio corridor -- 3-way: Carlos De La Cruz, Johnny Garcia, Greg Casar)

4 address(es) -- all resolve to `TX-35`, featured race `tx-cd35-2026` (tier C, score 41.2, 3 candidates).

| Address | Matched (Census) | SD / HD / County | Races | Reliability |
|---|---|---|---|---|
| **Huston-Tillotson University** -- 900 Chicon St, Austin, TX 78702 | 900 CHICON ST, AUSTIN, TX, 78702 | SD-14 / HD-46 / Travis County | 9 | reliable: finance+votes+insights present (6/6 sourced bullets, mode=cached) |
| **Austin-Bergstrom Intl Airport** -- 3600 Presidential Blvd, Austin, TX 78719 | 3600 PRESIDENTIAL BLVD, AUSTIN, TX, 78719 | SD-21 / HD-51 / Travis County | 9 | reliable: finance+votes+insights present (6/6 sourced bullets, mode=cached) |
| **Manor City Hall** -- 105 E Eggleston St, Manor, TX 78653 | 105 E EGGLESTON ST, MANOR, TX, 78653 | SD-14 / HD-46 / Travis County | 9 | reliable: finance+votes+insights present (6/6 sourced bullets, mode=cached) |
| **San Marcos (E Hopkins St)** -- 630 E Hopkins St, San Marcos, TX 78666 | 630 E HOPKINS ST, SAN MARCOS, TX, 78666 | SD-21 / HD-45 / Hays County | 9 | reliable: finance+votes+insights present (6/6 sourced bullets, mode=cached) |

## Dropped -- verified NOT to resolve

| Address tried | Result | Why kept out |
|---|---|---|
| `9201 Circuit of the Americas Blvd, Austin, TX 78617` | HTTP 422 (both as `Austin, TX` and `Del Valle, TX`) | The Census geocoder has no exact TIGER street-segment match for Circuit of the Americas Blvd -- a real address, but evidently not one the geocoder's reference file resolves. Per the exact-match rule, an address that *sounds* right but doesn't resolve is never seeded. Not present in `geocode_seed.json` or `AUSTIN_DEMO_ADDRESSES`. |

## Methodology / reproduction

- Live verification pass run against `http://127.0.0.1:8010` with 0.8s pacing between calls: `GET /api/ballot?address=...` then, for the resolved CD's US House race, `POST /api/insights {"profile": {"veteran": true, ...}, "race_id": "tx-cd##-2026"}`.
- Kept only responses with HTTP 200, `races >= 8`, and a non-null `districts.cd`. Reliability additionally requires `mode == "cached"` and at least one non-empty, sourced insight bullet.
- `positions[]` is empty on these US House candidates in the underlying gold dataset by design (free-text position summaries are only hand-researched for statewide/marquee candidates -- see `pipeline/eval_dataset.py`); `finance` and `record.key_votes` (FEC + congress.gov, both sourced) are present for the incumbent in every district above, and `/api/insights` is what supplies researched, sourced bullets for the down-ballot race -- confirmed present for all 21 addresses, which is what "reliable" means in the table above.
- All 21 addresses are seeded in `data/tx/geocode_seed.json` (read-only warm layer consulted by `app/datastore.py` ahead of the live Census geocoder). 20 of them live in `pipeline/build_geocode_seed.py`'s `AUSTIN_DEMO_ADDRESSES` list; the Capitol is already a top-level precache/golden address there, so it isn't duplicated into that list.
- Regenerate/re-verify any time: `python3 pipeline/build_geocode_seed.py` (add `--force` to re-resolve live instead of reusing the runtime cache).

