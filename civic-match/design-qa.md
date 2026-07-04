# Ballot Flow Design QA

Reference: `/var/folders/_p/tdt_gb194g7bhvvyqqlqxjs80000gn/T/codex-clipboard-6fa1958b-a1c4-4838-8db7-8f65c68600ee.png`

Prototype captures generated during QA:
- Mobile found-ballot state.
- Desktop found-ballot state.
- Desktop review state.
- Desktop match state.

Checks:
- Address query advances into the post-address ballot-found state.
- Flow reaches focus, issue priorities, stance, tradeoff, dealbreaker, review, and match states.
- Review and match states preserve the dark mobile Civitas frame, gold action buttons, compact cards, and non-overlapping text.
- Match results are generated from the existing `/api/match` path after saving local preferences.
- Desktop uses a two-column layout with a persistent context rail instead of a mobile phone-width frame.
- Mobile remains a compact single-panel flow.

Remaining P3 polish:
- Long race titles still truncate in compact cards; acceptable for this pass, but a later iteration could add two-line wrapping where card height allows it.
- Candidate cards use initials instead of real headshots to avoid implying unsourced portraits.

final result: passed
