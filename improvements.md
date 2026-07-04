# Claude Code Prompt: Demo-Winning Civic Match Depth

You are working in `/home/abheekp/vulcan/PatriotHacks`.

Do not push or commit unless explicitly instructed. Preserve all existing user/team changes. Inspect the current worktree before editing and stage only files you intentionally change.

## Mission

Make Civic Match feel deeper, more trustworthy, and easier to demo without adding distracting breadth.

Winning lane:

> A normal voter enters an address, sees a real ballot, reviews one race, gets a neutral source-backed insight, sees how the claim is known, and leaves with a voting plan.

This is not a persuasion app. It is a ballot evidence app: real address, real ballot, real candidate records, every claim cited.

## Non-Negotiables

- Neutral, voter-facing language only.
- No factual insight renders as authoritative without a source.
- Missing data must be shown as a trust signal, not hidden.
- The demo path must not depend on a new live API key or live LLM call.
- Do not build a map, chatbot, social counter, or broad new feature.
- Prefer one excellent golden race over shallow polish across the whole app.

## Competitor-Inspired Threat Model

Do not mention competitor names in code, docs, issues, or UI.

Observed patterns to beat:

- The easiest voter-flow competitor has a strong completion loop: progress, reviewed races, plan, reminder.
- The most rigorous research competitor makes citation integrity obvious and acts on selected evidence before asking AI to synthesize.
- The strongest visual-demo competitor uses polished artifacts, audit rationale, and fail-closed compliance framing.
- The strongest trust UX uses plain verdict/confidence labels instead of abstract data codes.
- The strongest demo-hardening competitor validates cached demo payloads before the presenter is on stage.
- The strongest workflow competitor uses one-question-at-a-time clarification and visible step/status affordances.

Our response:

- Keep the voter journey simpler than the UX competitor.
- Make sources more visible than the research competitor.
- Make trust/compliance more explicit than the visual-demo competitor.
- Make the golden demo more reliable than every live-key path.

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
