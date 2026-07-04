# DEMO_PLAYBOOK.md

3-minute demo script: product walkthrough + 15s engineering beat. Written against the
state of the repo on 2026-07-03 — re-verify the "current status" callouts below if you
run this more than a day later, since the frontend is under active development.

---

## (a) Pre-demo setup checklist

Run these in order, in two terminals. Times are what to expect on this box.

**Terminal 1 — data backend (FastAPI), port 8010:**

```bash
cd /home/abheekp/vulcan/PatriotHacks
python3 -m uvicorn app.main:app --port 8010
```

**Terminal 2 — product frontend (Next.js), port 3000:**

```bash
cd civic-match
npm run dev
```

**`civic-match/.env.local`** — set:

```
DATA_BACKEND_URL=http://localhost:8010
```

`DATA_BACKEND_URL` is the single canonical var — both `lib/dataBackend.ts` and
`app/api/ballot/route.ts` read it (the route also accepts a legacy
`BALLOT_BACKEND_URL` alias if `DATA_BACKEND_URL` is unset, but there's no need
to set both). Restart `npm run dev` after editing `.env.local` — Next.js only
reads it at process start.

**Verify before anyone touches the keyboard on stage:**

```bash
curl -s http://127.0.0.1:8010/healthz
```

Expect: `{"status":"ok","data_loaded":true,"races":46,"candidates":96,"insights_cached":46}`.
If `data_loaded` is `false`, the JSON fallback didn't load — check the backend's stdout for
a startup error before going further; do not proceed to the DB pivot story on stage.

Then load `http://localhost:3000` in the browser once, just to trigger Next's first-request
compile (avoids a 3-5s stall live on the intake→results transition).

**Have a second browser tab pinned to** `http://127.0.0.1:8010/api/ballot?address=1000%20Houston%20St%2C%20Laredo%2C%20TX%2078040`
— if anything on the frontend looks wrong live, this tab proves the backend data is fine
and the bug is frontend-side, not "our data is broken."

Run `python3 pipeline/demo_readiness_gate.py` last, right before going on stage — it starts
the backend if needed, live-checks the ballot API for all 8 precache+golden addresses,
verifies marquee insight/horizons completeness, scans for finance-source misattribution, and
confirms the demo cache isn't stale; it exits non-zero and prints exactly what's wrong if
anything fails.

---

## (b) The script, minute by minute

### 0:00–0:20 — Open, landing page

Load `http://localhost:3000/`. Say the one-liner: *"Every claim on this site traces to a
real source — a roll-call vote, an FEC filing, a primary document. No source, no claim."*
Point at the stakes banner and the auto-discovered race list, then click **Get matched**
(`/intake`).

### 0:20–1:00 — Intake: address + profile flags that flip the archetype

On `/intake`:

1. Street address field → type the golden TX-28 address:
   **`1000 Houston St, Laredo, TX 78040`**
   This is a real, publicly geocodable building (Laredo City Hall) verified against the
   Census geocoder's `119th Congressional Districts` layer at pipeline build time — it
   resolves to **CD TX-28 / SD-21 / HD-42, Webb County**, a genuinely competitive,
   tier-B-scored race (Cuellar vs. Esparza, 2024 margin 5.6 pts) — see
   `data/tx/QUALITY.md` "Golden demo districts."
   *Backup if this address ever fails to resolve live:* **`1100 E Monroe St,
   Brownsville, TX 78520`** → CD TX-34 / SD-27 / HD-38, Cameron County (Gonzalez vs.
   Mandel, 2024 margin 2.6 pts — the single best-scoring House district in the set).
2. Occupation / age / income — fill in anything plausible (doesn't affect the demo).
3. Situation flags — click **Veteran**. This is the archetype-flipping moment: the
   precomputed insight the app serves later is keyed off this flag (deterministic
   precedence in the backend: veteran beats every other archetype except nothing —
   it's first in line). Narrate: *"That single toggle changes which of our 8
   pre-written, source-grounded reads gets served — no LLM call happens for this."*
4. Pick 3+ issues, set trade-offs/importance (fast — doesn't need narration), submit →
   routes to `/results`.

### 1:00–1:45 — Results: match scores + "Your ballot"

`/results` shows two things stacked:

- The 2K-style match cards (60-99 OVERALL) for the *researched, cached statewide*
  candidates — this is civic-match's own scoring engine, pure arithmetic, no LLM call
  on a cache hit.
- Scroll to **"Your ballot"** — this is the section sourced live from our FastAPI
  backend (`GET /api/ballot`) for the Laredo address. Point out: it's grouped Federal →
  Statewide, and the TX-28 U.S. House race is right there next to the statewide
  Governor/Senate/AG races the same address is on the hook for.

### 1:45–2:30 — Open the TX-28 candidate comparison

On the TX-28 card (Henry R. Cuellar, D, incumbent vs. Juan Esparza, R):

- Point at **money raised** on each candidate column — Cuellar $1.62M raised / $904K
  spent, Esparza $32K/$32K — each with a **source chip** linking straight to the FEC
  filing.
- Point at **key votes** — up to 3 real House-Clerk roll-call records per candidate
  (e.g. Cuellar's Nay on H.R. 1, 22-May-2025), each in plain English with its own
  **source chip** to the Clerk's roll-call XML.
- Point at the **data-confidence chip** next to the candidate name (and the one on the
  race card itself) — a neutral A-D tier signal for "how much do we actually know
  here," never a knock on the candidate; hovering shows exactly what's missing.

### 2:30–2:45 — "What this means for you" (personalized, precomputed)

Click **"What this means for you"** on the TX-28 card. This calls
`/api/voter-insights` → our backend's `/api/insights`, which for this profile+race
combination is served **entirely from a cache file** (`mode: "cached"`,
`archetype_used: "veteran"`) — zero LLM calls. Narrate the two bullets it shows
(finance + "no public data on veteran-specific votes/positions" stated honestly where
the record doesn't cover it — never papered over). **If the response for this
race/profile also carries a `horizons` block** (a `now` vs. `long_term` split — direct
restatement of the current record vs. explicitly-labeled, assumption-flagged
projections, each still individually sourced), point at it as the newest layer: *"Right
now" is what the record says today; "down the road" is a labeled projection, never
presented as fact.* **Confirmed populated for this exact demo combo** —
`data/tx/insights/tx-cd28-2026.json` carries `horizons` under both `base` and
the `veteran` archetype, so this beat works out of the box. Re-confirm right
before stage anyway (cache files do get regenerated):

```bash
curl -s -X POST http://127.0.0.1:8010/api/insights \
  -H "Content-Type: application/json" \
  -d '{"profile":{"veteran":true},"race_id":"tx-cd28-2026"}' | python3 -c "import json,sys;print('horizons' in json.load(sys.stdin))"
```

If that ever prints `False` (stale cache, reverted data), drop the horizons
sentence and instead pivot to `/future` (same nav bar, "Down the line") and
open the **U.S. Senate** scenario tree (Paxton vs. Talarico) — same address's
statewide ballot, same "labeled projection with sources" idea, already fully
built and populated for all 4 statewide races.

### 2:45–3:00 — Close: the engineering beat (15s)

*"Under all of that: 46 races, 96 candidates, 290 individual roll-call vote records,
pulled from official APIs — Census, FEC, Congress.gov, the House Clerk. It's all
precomputed and quality-scored ahead of time, so the whole demo you just watched ran
with zero LLM calls. It's Postgres-ready — JSON fallback right now, same code path
flips to Postgres the moment `DATABASE_URL` is set."*

---

## (c) Failure fallbacks

**Geocoder (Census) is down or slow:** any address that has been looked up once during
rehearsal is cached in `data/geocode_cache.json` and resolves instantly without a live
call on retry — this is automatic, not a manual step. Addresses already warmed for this
purpose (see part 2 below): `601 University Dr, San Marcos, TX 78666`,
`1100 Congress Ave, Austin, TX 78701`, `901 Bagby St, Houston, TX 77002`. Warm the two
golden addresses (Laredo, Brownsville) the same way before going on stage by simply
loading them once in rehearsal.

**Backend (port 8010) is down or unreachable:** `civic-match/app/api/ballot/route.ts`
catches the failed fetch automatically and returns `{mode: "statewide_fallback", warning:
"District resolver unavailable — showing statewide races for your state only.", races: [...]}`
using civic-match's own in-repo cached statewide election data — the "Your ballot" section
still renders, just without district narrowing. No manual intervention needed; just
narrate the warning banner honestly if it appears.

**Wifi/network is fully dead (nothing loads, backend and geocoder both unreachable):**
fall back to narrating from the static response dumps in `data/demo_cache/<address-slug>/`
(one `ballot.json` + one `insights_<race>.json` per cached address) — open them directly
in a text editor or `python3 -m json.tool` in a terminal and read off the same finance /
vote / source data by hand. These are reference dumps only; the running app does not read
them at request time, so this is a manual last resort, not an automatic fallback.

---

## (d) Two items to flag to the teammate before the demo — not resolved here

1. **`nate-sheets.json` vs `nathan-sheets.json` duplicate/near-duplicate in
   `civic-match/data/politicians/`.** Our backend's gold dataset has one Nate Sheets
   (Republican, Texas Commissioner of Agriculture race, D-tier / thin data — beekeeper,
   small business owner, `candidates.json` key `sheets-nate`). civic-match's politician
   DB has *two* files: `nate-sheets.json` (Republican Party of Texas, 0 sourced stances —
   looks like the same Ag Commissioner candidate, unresearched) and `nathan-sheets.json`
   (6 sourced stances, tagged as running for **Texas Attorney General** — a different
   office entirely). Unclear whether this is the swarm researching the same real person
   under two name spellings and putting him on the wrong race, or two distinct real
   candidates who happen to share a surname. Needs the teammate's call before this race
   comes up live — do not touch it as part of this pass.
2. **The "Promise vs. record" scorecard feature exists but is dark.** It's fully built
   and renders on `/p/[id]` (`p.promise_record`, sourced "said X / did Y" pairs with
   receipts) whenever a candidate profile has that field populated — but there is no nav
   link, landing-page mention, or call-out anywhere pointing at it. If you want it in the
   demo, you have to know to click into a specific researched candidate's page and scroll
   to it; otherwise it will never come up. Worth a 10-second mention or a nav link before
   the demo if it's meant to be a headline feature.

---

## Reference: exact request/response shapes used above

`GET /api/ballot?address=1000 Houston St, Laredo, TX 78040` → `districts: {cd: "TX-28",
sd: "SD-21", hd: "HD-42", county: "Webb County"}`, races include `tx-cd28-2026`
(candidates `cuellar-henry`, `esparza-juan`) plus every statewide race
(`tx-gov-2026`, `tx-sen-2026`, `tx-ltgov-2026`, `tx-ag-2026`, `tx-comptroller-2026`,
`tx-landcomm-2026`, `tx-railroad-2026`, `tx-agcomm-2026`).

`GET /api/ballot?address=1100 E Monroe St, Brownsville, TX 78520` → `districts: {cd:
"TX-34", sd: "SD-27", hd: "HD-38", county: "Cameron County"}`, races include
`tx-cd34-2026` (candidates `mandel-charles`, `gonzalez-vicente`) plus the same statewide
set.
