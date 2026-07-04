# Claude Code Prompt: Demo-Winning Civic Match Depth

You are working in `/home/abheekp/vulcan/PatriotHacks`.

Do not push or commit unless explicitly instructed. Preserve all existing user/team changes. Inspect the current worktree before editing and stage only files you intentionally change.

## Mission

Make Civic Match feel deeper, more trustworthy, and easier to demo without adding distracting breadth.

Winning lane:

> A normal voter enters an address, sees a real ballot, reviews one race, gets a neutral source-backed insight, sees how the claim is known, and leaves with a voting plan.

This is not a persuasion app. It is a ballot evidence app: real address, real ballot, real candidate records, every claim cited.

## What Better Means

A judge should believe a normal voter can use Civic Match in two minutes and trust it more than a generic chatbot.

Optimize for this exact path:

> Enter address -> Your ballot -> Featured race -> Source-backed insight -> How we know -> You're ballot-ready -> Make plan

The best demo is narrow and undeniable:

- one golden address
- one clear ballot
- one featured race
- one cited personalized insight
- one visible missing-data caveat
- one voting-plan ending

Do not show every capability unless asked. The core flow must be understandable without narration.

## Non-Negotiables

- Neutral, voter-facing language only.
- No factual insight renders as authoritative without a source.
- Missing data must be shown as a trust signal, not hidden.
- The demo path must not depend on a new live API key or live LLM call.
- Do not build a map, chatbot, social counter, or broad new feature.
- Prefer one excellent golden race over shallow polish across the whole app.
- Do not say the app recommends who to vote for. Say it helps voters review public evidence.

## Repo Hygiene Requirements

Before adding more UI polish, make the repository safe to work from.

Current distinction:

- **Merge conflicts** are files Git marks as unmerged, usually with conflict markers like `<<<<<<<`, `=======`, and `>>>>>>>`. These must be resolved before normal commits, builds, or reviews.
- **Dirty worktree changes** are modified or untracked files that are not necessarily conflicts. They can be valid work, generated output, or accidental churn, but they still need an explicit keep/discard decision before pushing.

Required checks:

```bash
git status -sb
git diff --name-only --diff-filter=U
rg -n "^(<<<<<<<|=======|>>>>>>>)" .
```

Acceptance:

- `git diff --name-only --diff-filter=U` prints nothing.
- No conflict markers exist in tracked source/docs.
- Every modified/untracked file is classified as one of:
  - keep and commit
  - generated but intentional
  - ignore/local-only
  - discard only with explicit approval
- Do not stage broad paths. Stage exact files only.
- Do not commit `local-only/` competitive analysis.
- Do not push unless explicitly asked.

Known hygiene risks to resolve before final judging:

- Demo cache JSON churn can be valid if refreshed, but it should be intentional and explained.
- New frontend/test files must be wired into the app or kept out of the final commit.
- If the branch is behind remote, pull/rebase only after confirming no teammate work will be overwritten.
- A passing backend gate does not prove frontend UX polish is wired; verify both.

Demo artifact source of truth:

- Demo-critical audited artifacts must be versioned or reproducibly generated from a checked-in seed.
- Scratch analysis, competitive notes, and temporary audit work should stay ignored.
- If an ignored working copy produces final demo data, promote only the minimal reviewed artifact into the repo and document how a fresh checkout receives it.
- Seed/import code must not overwrite an audit or data refresh that is already in progress.
- Fresh-checkout reproducibility matters as much as local demo success.

Minimum validation before calling the repo demo-ready:

```bash
python3 -m pytest tests/test_e2e_demo.py -q
python3 pipeline/demo_readiness_gate.py --base-url http://127.0.0.1:8010
cd civic-match && npm run lint
```

## Demo UX Requirements

### Staged Progress

Use short status labels so the app feels deliberate and reliable:

- `Finding your ballot`
- `Loading public records`
- `Checking sources`
- `Ready`

Do not use fake progress to hide failures. If a stage fails, show the specific missing dependency or missing data.

### Plain Trust Labels

Keep internal data tiers if useful, but user-facing labels should be:

- `Strong public record`
- `Good public record`
- `Partial public record`
- `Thin public record`

### Intentional Caveats

Show at least one caveat deliberately in the golden demo, for example:

- `No roll-call voting record found for this candidate.`
- `No public finance record found in our current dataset.`

Frame this as the product refusing to guess. Generic AI would often fill the gap; Civic Match should not.

### End With Action

After the featured insight, show a simple `Make a voting plan` ending:

- Election Day or early voting
- time window
- client-side `.ics` reminder if feasible
- official VoteTexas.gov link

Do not claim a polling place unless that location is verified.

## Competitor-Inspired Threat Model

Do not mention competitor names in code, docs, issues, or UI.

Observed patterns to beat:

- The easiest voter-flow competitor has a strong completion loop: progress, reviewed races, plan, reminder.
- The most rigorous research competitor makes citation integrity obvious and acts on selected evidence before asking AI to synthesize.
- The strongest visual-demo competitor uses polished artifacts, audit rationale, and fail-closed compliance framing.
- The strongest demo-hygiene pattern keeps completed audit artifacts in a clear source of truth instead of relying on ignored local temp data.
- The strongest trust UX uses plain verdict/confidence labels instead of abstract data codes.
- The strongest demo-hardening competitor validates cached demo payloads before the presenter is on stage.
- The strongest workflow competitor uses one-question-at-a-time clarification and visible step/status affordances.

Our response:

- Keep the voter journey simpler than the UX competitor.
- Make sources more visible than the research competitor.
- Make trust/compliance more explicit than the visual-demo competitor.
- Make final demo artifacts reproducible from a fresh checkout.
- Make the golden demo more reliable than every live-key path.
- Make the story sharper than analytics-heavy competitors: real ballot, public evidence, sourced insight, concrete voter action.

## Use Subagents

If subagents are available, run these in parallel with disjoint ownership. Each subagent must inspect first, preserve unrelated changes, and report changed files.

### Subagent 1: Demo Reliability and API Health

Ownership:

- Backend health and golden demo checks.
- Demo-readiness script or health endpoint.
- Source validation for cached/precomputed insights.

Tasks:

- Confirm the golden address path works without a live LLM.
- Confirm backend health exposes enough readiness state for demo confidence.
- Verify golden address returns the expected ballot/race.
- Verify the golden insight is cached/precomputed.
- Verify every factual insight bullet has a source or is downgraded to a caveat.
- Add or update one quick demo check if an appropriate script already exists.

Acceptance:

- One command can validate the golden path before the demo.
- Failures are explicit: missing backend, missing race, uncached insight, source-less factual bullet.

### Subagent 2: Ballot Completion UX

Ownership:

- Results/ballot frontend components.
- Local reviewed state.
- Completion progress UI.

Tasks:

- Fix visible polish issues, including duplicated quality text if still present.
- Add reviewed state for ballot races.
- Mark a race reviewed when the user opens the personalized insight.
- Persist reviewed races in `localStorage`, keyed by stable address/election/district data.
- Show a simple readiness bar:
  - `Reviewed 0 of N races`
  - progress bar
  - completed state: `You're ballot-ready`

Acceptance:

- A judge can tell what remains to review without presenter explanation.
- Refreshing the page preserves reviewed state for the same matched ballot.

### Subagent 3: Evidence Depth and Trust Labels

Ownership:

- Source display.
- Data confidence labels.
- `How we know` copy and caveats.

Tasks:

- Keep existing internal A-D tiers, but render plain-English labels:
  - A: `Strong public record`
  - B: `Good public record`
  - C: `Partial public record`
  - D: `Thin public record`
- Add a concise `How we know` section on race cards or the insight panel.
- Include:
  - finance source type
  - vote source type
  - candidate/source list coverage
  - missing data caveat
  - last checked/generated value if available
- Explain personalization neutrally:
  - `Personalized because you selected veteran`
  - `Personalized because healthcare was marked important`

Acceptance:

- At least one golden race shows candidates, money or caveat, votes or caveat, source links, personalized insight, and missing-data caveat.
- No raw `A/B/C/D` tier is the primary user-facing trust language.

### Subagent 4: Polished Demo Ending and Smoke Test

Ownership:

- Final demo flow polish.
- Optional voting-plan card.
- Browser smoke test if existing test setup supports it.

Tasks:

- Make one primary race card/insight panel visually crisp enough to stand alone in screenshots.
- Add a simple voting-plan card if time allows:
  - Election Day or early voting
  - time window
  - client-side `.ics` reminder
  - official VoteTexas.gov link
- Do not claim a polling place unless verified.
- Add or update one smoke check for:
  - intake
  - results
  - `Your ballot`
  - visible source link
  - visible insight panel

Acceptance:

- The demo has a clear ending after the insight.
- The smoke check covers the exact golden path, not a generic homepage.

## Implementation Order

1. Inspect current changes and avoid overwriting teammate work.
2. Stabilize golden demo health and source validation.
3. Add readiness progress and reviewed state.
4. Add trust labels and `How we know`.
5. Polish one golden race path.
6. Add voting-plan/reminder only if the core path is already stable.
7. Run the smallest meaningful validation commands and report results.

## Required Final Report

Return:

- Files changed.
- What is now demoable.
- Exact validation commands run and results.
- Any remaining risks before presenting.
- The one recommended golden demo path.
