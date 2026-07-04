# testing.md

How this repo proves its own data is true, and proves the app serves that truth
correctly. Written against the state of the repo on 2026-07-03.

---

## 1. Philosophy

The product's one promise is **"no source, no claim"** — every fact on the
site traces to a real vote, filing, or primary document (`README.md`,
`data.md`). That promise is worthless unless it is tested twice:

- **Data truth** — does `data/tx/*.json` actually say what its cited source
  says? Enforced by the *validators* (`pipeline/validate_*.py`,
  `pipeline/clean_gold.py`) that run over the gold dataset itself, independent
  of any server.
- **Serving truth** — does the API return, unchanged, exactly what the gold
  dataset and precomputed caches contain? Enforced by the *pytest suites*
  (`tests/*.py`) that drive `app/main.py` through FastAPI's `TestClient`.

Testing here is **precompute-first** in the same way the product is: nearly
everything below runs with zero network egress and zero LLM calls, because
the demo itself is built to need neither. The few tests that do touch a live
network or a live server are marked and skip cleanly when the environment
can't support them (§6).

**Self-proving detectors.** A detector that has never been shown to fail is
not a test, it's a hope. Every non-trivial assertion helper in
`tests/test_e2e_demo.py` (unsourced bullet, stale cache drift, all-no-data
candidate, unlabeled projection) is exercised twice in a `selfproof`-marked
test: once against an injected defect (must RED / raise), once against real,
untouched data (must GREEN / pass). See §5 for two worked examples.

---

## 2. The pyramid

| Layer | File | What it proves | When to run | Runtime |
|---|---|---|---|---|
| Contracts | `tests/test_contracts.py` | Gold JSON shapes, SQLite mirrors gold JSON 1:1, insight files match their `race_id`, `/healthz` and `/api/insights` respond | pre-commit | ~2s |
| Hardening | `tests/test_hardening.py` | Input abuse (oversized/control-char addresses, SQLi-shaped race_ids, oversized bodies), one error envelope shape everywhere, no stack-trace leaks, rate limiting, security headers, geocode-cache seed fallback + a real clobber regression | pre-commit | ~4s |
| Optional-integration | `tests/test_google_civic.py` | Google Civic enrichment degrades to invisible (no key, 403, cache-hit) and normalizes correctly on the happy path — never required, never breaks `/api/ballot` | pre-commit | ~2s |
| End-to-end demo | `tests/test_e2e_demo.py` | The full voter journey (address → ballot → races → insights) across all 8 demo/golden addresses; demo-cache-matches-fresh; bullet informativeness floors; perf bounds; clean 4xx error paths; **+ the selfproof detector suite** | pre-commit, pre-demo | ~4s |
| Data validators | `pipeline/validate_data.py`, `validate_marquee_insights.py`, `validate_horizons.py`, `clean_gold.py` | Referential integrity, every finance/vote/position/bullet has a real source URL pulled from that *same* candidate's own record, district format, Postgres parity when `DATABASE_URL` is set | after any data change | seconds |
| Manual smoke | `pipeline/smoke_backend.py` | Rerunnable, human-readable PASS/FAIL walk of the same journey, one real live Census geocoder call on a cold cache | ad hoc, post-deploy | ~2-5s (network permitting) |
| Statewide breadth | `pipeline/sweep_addresses.py` | Extends the golden-8-address net to many/all TX districts at once — a ranked scorecard of where data coverage is thin, reusing `score_quality.py`'s scoring engine (see §4) | periodically, after a data change that could shift coverage | minutes (network-bound) |
| Demo readiness gate | `pipeline/demo_readiness_gate.py` | The full pre-stage contract: backend liveness, all 8 addresses live, marquee+horizons completeness, attribution truth, demo-cache freshness, the zero-LLM golden path | pre-demo, last step | ~10-30s |

Lower layers are cheap and run on every commit; the top of the pyramid is the
one gate that must pass before anyone touches a keyboard on stage.

---

## 3. One-command rituals

**Pre-commit** — the whole pytest layer, no network, no LLM:

```bash
pytest tests/ -q
```

**Pre-demo** — the full stage gate (starts the backend if it isn't already
running, never stops one it starts):

```bash
python3 pipeline/demo_readiness_gate.py
```

**After any data change** — the full regenerate-then-validate chain, in
order (each stage only consumes the previous stage's output, so a partial
rerun is always safe):

```bash
python3 pipeline/fetch_statewide.py
python3 pipeline/fetch_fec.py
python3 pipeline/fetch_votes.py
python3 pipeline/fetch_context.py
python3 pipeline/build_dataset.py
python3 pipeline/import_civicmatch_positions.py
python3 pipeline/clean_gold.py
python3 pipeline/score_quality.py
python3 pipeline/precompute_marquee_insights.py
python3 pipeline/build_insights_house.py
python3 pipeline/build_insights_tx20_38.py
python3 pipeline/precompute_horizons.py
python3 pipeline/validate_data.py
python3 pipeline/validate_insights_house.py
python3 pipeline/validate_insights_tx20_38.py
python3 pipeline/validate_marquee_insights.py
python3 pipeline/validate_horizons.py
python3 pipeline/load_postgres.py --dry-run    # sanity-check counts first
python3 pipeline/load_postgres.py              # reload Postgres, if used
pytest tests/ -q                               # confirm the API still agrees
```

**Statewide breadth** — sweep far beyond the 8 golden/precache addresses to
find coverage gaps anywhere in the state:

```bash
python3 pipeline/sweep_addresses.py
```

---

## 4. Quick address testing HOW-TO

Test any Texas address end-to-end in about 10 seconds, no frontend required.

```bash
curl -s "http://127.0.0.1:8010/api/ballot?address=1000%20Houston%20St%2C%20Laredo%2C%20TX%2078040" \
  | python3 -c "
import json, sys
d = json.load(sys.stdin)
print('districts:', d.get('districts'))
print('race count:', len(d.get('races', [])))
for r in d['races']:
    print(' ', r['race_id'], '-', len(r.get('candidates', [])), 'candidates')
"
```

What to look for:

- `districts.cd` matches `^TX-\d{2}$` — a bad match means a geocoder or
  cache-normalization bug, not a data bug.
- Race count includes every statewide race (8) **plus** that address's own
  US House/TX Senate/TX House races — a short list means the district join
  silently dropped something.
- Every race's `candidates` is a JSON **array**, never an object keyed by
  candidate_id (the historical bug `demo_readiness_gate.py` still checks for
  by name).

**Reading the sweep scorecard.** `pipeline/sweep_addresses.py` reuses
`score_quality.py`'s tier math (A/B/C/D, `demo_rank`) but runs it against a
much wider address set than the 8 golden/precache demo addresses — the goal
is to surface *which districts statewide* would embarrass the demo if
someone typed in an address live. Read it the same way you'd read
`data/tx/QUALITY.md`: sort by tier, then by score, and treat every `C`/`D`
row or every "0/8 archetypes" note as a ranked finding, worst first.

**The loop, sweep → fix → verify:**

1. `python3 pipeline/sweep_addresses.py` produces a ranked list of weak
   districts/races (thin finance, no votes, missing archetypes, mismatched
   geocode).
2. Pick the worst finding and hand it to a targeted fix agent (a fetcher
   patch, a re-research pass, a validator tightening) — never a blanket
   re-run of everything.
3. Re-run the full regen+validate chain in §3 so the fix's downstream
   effects (scoring, insights, horizons) are recomputed, not just patched
   in place.
4. `python3 pipeline/demo_readiness_gate.py` to confirm the fix didn't
   regress anything the stage gate checks.

---

## 5. Negative-case discipline

A detector is only trustworthy once someone has watched it fail. Two real
examples from `tests/test_e2e_demo.py`:

**Stale cache divergence.** `test_selfproof_stale_cache_divergence_detected`
deep-copies a real cached `data/demo_cache/*/ballot.json`, deletes one
candidate's `finance` block and appends text to their `name` — simulating a
cache captured before a later data update landed — then asserts
`_assert_ballot_cache_matches_fresh` raises `AssertionError` naming that
exact `race_id`. It then re-asserts the *untouched* copy compares clean
against itself. RED on the injected drift, GREEN on real data — proof the
comparison actually compares, rather than trivially passing.

**Unsourced bullet.** `test_selfproof_unsourced_bullet_detected` takes a real
bullet from `data/tx/insights/tx-sen-2026.json`, blanks its `source` field,
and asserts `_assert_bullet_well_formed` raises with `"source"` in the
message — then re-runs the same check on the original, unmodified bullet and
requires it to pass. This is the literal enforcement of "no source, no
claim" at the assertion-helper level, not just at data-authoring time.

(Two further examples in the same file, same pattern: an all-"no public
data" candidate list, and a `long_term` horizon bullet missing its required
`assumption`/conditional phrasing.)

---

## 6. CI notes

- Every test in `tests/test_contracts.py`, `test_hardening.py`,
  `test_google_civic.py`, and `test_e2e_demo.py` drives the app in-process
  via FastAPI's `TestClient` — no socket, no subprocess, no real database
  connection required. This means the whole suite runs **serverless**,
  identically on a laptop or in a CI runner with no services provisioned.
- Tests marked `@pytest.mark.network` (one in `test_contracts.py`, the live
  San Marcos ballot lookup) skip cleanly when `NO_NETWORK=1` is set, and
  degrade to a `pytest.skip` (not a failure) if the live Census geocoder is
  unreachable.
- `tests/test_google_civic.py`'s one live-key test
  (`test_live_smoke_if_key_present`) is `skipif`-guarded on
  `GOOGLE_CIVIC_API_KEY` actually being present in the environment — absent
  key means skip, never fail.
- Nothing in `tests/` requires `OPENROUTER_API_KEY`: every race_id exercised
  already has a precomputed `data/tx/insights/*.json` file, so the cached
  branch always wins, and `test_e2e_demo.py` additionally neutralizes the
  key at the module level as a belt-and-suspenders guarantee.
- Run everything together with:

```bash
NO_NETWORK=1 pytest tests/ -q
```
