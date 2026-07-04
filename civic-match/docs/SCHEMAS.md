# Civic Match — Data Schemas

Single source of truth: `civic-match/lib/types.ts` (TypeScript contracts). This doc
mirrors it for teammates + integrations (FastAPI backend exporter, seed scripts).
Slug convention everywhere: `firstname-lastname` via `lib/db.ts slugify()`.

## Storage layout (file DB)

```
civic-match/data/
├── politicians/{slug}.json      # PoliticianProfile (the core record)
├── elections/{state}.json       # DiscoveredRace[] (auto-discovered ballot)
├── config/issues.json           # IssueDef[] — 30-issue taxonomy
├── config/ui.json               # UIConfig — all frontend content/options
├── explanations/{hash}.json     # cached QualitativeExplanation, keyed by prefs-hash
└── scenarios/{race-slug}.json   # ScenarioTree (future-possibilities tree, WIP)
```

## PoliticianProfile — `data/politicians/{slug}.json`

```jsonc
{
  "id": "greg-abbott",                  // slug, firstname-lastname
  "name": "Greg Abbott",                // ballot display name
  "party": "Republican",
  "current_office": "Governor of Texas",
  "jurisdiction": "Texas",
  "bio": "2 neutral sentences",
  "campaign_website": "https://...",
  "stances": [ /* Stance[] — see below */ ],
  "qualitative": [ /* QualitativeDimension[] — see below */ ],
  "promise_record": [ /* PromiseRecord[] — see below */ ],
  "unknowns": ["privacy", "..."],       // issue_ids with NO reliable evidence
  "contradictions": [
    { "issue_id": "taxes", "description": "neutral sentence", "sources": [] }
  ],
  "source_coverage_score": 0.63,        // covered issues / 30
  "researched_at": "2026-07-03T...Z",
  "research_status": "complete"         // complete | partial | failed
}
```

### Stance (one per issue, max 30)

```jsonc
{
  "stance_id": "housing_1751...",
  "issue_id": "housing",               // must exist in config/issues.json
  "position_label": "short neutral label",
  "position_scalar": 0.35,             // 0..1 on the issue axis, null = unclear
  "summary": "1-2 neutral sentences",
  "evidence_type": "voting_record",    // voting_record | sponsored_bill | official_platform | public_statement | debate_transcript | interview | campaign_finance | news_report | questionnaire | other
  "confidence": 0.85,                  // 0..1
  "recency": "2025-06-01",
  "sources": [ /* Source[] — at least 1, else stance is dropped */ ]
}
```

### Source (attached to every claim — no source, no claim)

```jsonc
{
  "source_id": "housing_src_0",
  "type": "voting_record",             // same enum as evidence_type
  "title": "HB 2127 signature",
  "publisher": "Texas Legislature Online",
  "url": "https://...",                // REQUIRED, must be real http(s)
  "published_at": "2023-06-14",
  "retrieved_at": "2026-07-03T...Z",
  "primary_source": true,
  "quote": "short exact quote (optional)",
  "reliability_score": 0.95            // 0.95 primary / 0.7 secondary
}
```

### QualitativeDimension (character record, independent of user positions)

```jsonc
{
  "id": "integrity",                   // integrity | public_interest | transparency | experience
  "score": 0.10,                       // 0..1, higher = better
  "summary": "2 neutral sentences citing specific evidence",
  "confidence": 0.9,
  "sources": [ /* Source[] — required */ ]
}
```

### PromiseRecord (accountability watchdog: promise vs. record)

```jsonc
{
  "promise": "what they promised, plain English",
  "promised_at": "2022-01-15",
  "promise_source": { /* Source */ },
  "action": "what they actually did",
  "action_at": "2023-06-14",
  "action_sources": [ /* Source[] — receipts, required unless untested */ ],
  "verdict": "broken",                 // kept | broken | partial | untested
  "explanation": "one neutral reconciling sentence",
  "confidence": 0.8
}
```

## IssueDef — `data/config/issues.json` (30 entries)

```jsonc
{
  "id": "housing",
  "name": "Housing",
  "cluster": "economy",                // economy | society | security | governance
  "voterQuestion": "How can housing become more affordable?",
  "tradeoffQuestion": "Which housing approach is closest to your view?",
  "axis0": "meaning of scalar 0.0",    // shared axis: user AND candidate land on it
  "axis1": "meaning of scalar 1.0",
  "options": [
    { "key": "A", "label": "...", "scalar": 0 },
    { "key": "B", "label": "...", "scalar": 0.5 },
    { "key": "C", "label": "...", "scalar": 1 }
  ]
}
```

## UserPreferences (client-side only — localStorage `civicmatch_prefs`)

```jsonc
{
  "zip": "78666",
  "profile": {                          // ALL optional, explicitly user-stated
    "name": "Sam",
    "occupation": "nurse",
    "age_bracket": "25-34",             // 18-24 | 25-34 | 35-49 | 50-64 | 65+
    "income_bracket": "30-60k",         // <30k | 30-60k | 60-100k | 100-200k | 200k+
    "flags": {
      "homeowner": true, "renter": true, "kids_in_public_school": true,
      "veteran": true, "small_business_owner": true, "student": true,
      "healthcare": "aca"               // employer | aca | medicare | uninsured
    }
  },
  "priority_weights": { "housing": 1.0 },   // issue_id -> weight (rank × importance mult)
  "issue_positions": { "housing": 0.5 }     // issue_id -> 0..1 scalar or null (= don't use)
}
```

## MatchResult (returned by POST /api/match — computed, never stored)

```jsonc
{
  "politician_id": "greg-abbott",
  "politician_name": "Greg Abbott",
  "party": "Republican",
  "score": 42,                         // quantitative issue alignment 0-100
  "confidence": "High",                // High | Medium | Low (evidence coverage)
  "confidence_value": 0.72,
  "overall": 79,                       // 2K-style 60-99
  "overall_tier": "Solid match",
  "overall_components": {              // overall = 60 + 39×(0.6·quant + 0.4·qual − penalty)
    "alignment_component": 10,
    "qualitative_component": 12,
    "conflict_penalty": 2
  },
  "qualitative_composite": 0.74,       // confidence-weighted mean of dimensions, null if none
  "qualitative": [ { "id": "integrity", "label": "...", "score": 0.7, "summary": "...", "confidence": 0.9 } ],
  "breakdown": [ /* IssueScoreBreakdown[] — every weighted issue */ ],
  "top_agreements": [ /* subset, status=match */ ],
  "top_conflicts": [ /* subset, status=conflict */ ],
  "unknown_issues": [ /* subset, status=unknown */ ]
}
```

### IssueScoreBreakdown

```jsonc
{
  "issue_id": "housing", "issue_name": "Housing",
  "user_position": 0.5, "candidate_position": 0.2,
  "candidate_label": "supports deregulation to boost supply",
  "alignment": 0.7,                    // 1 − |user − candidate|, null if unknown
  "weight": 0.31,                      // normalized user weight
  "evidence_confidence": 0.85, "source_quality": 0.9, "recency_adjustment": 0.92,
  "points": 0.16, "max_points": 0.22,
  "status": "match"                    // match(≥0.7) | partial(≥0.4) | conflict | unknown
}
```

## DiscoveredRace — `data/elections/{state}.json`

```jsonc
{
  "race": "Texas Governor",
  "office": "Governor",
  "election_date": "2026-11-03",
  "candidates": [ { "name": "Greg Abbott", "party": "Republican" } ]
}
```

## ScenarioTree — `data/scenarios/{race-slug}.json` (in progress)

Future-possibilities tree: root = the race, first level = "candidate X wins",
deeper levels = consequences, leaf nodes = long-term possibilities.

```jsonc
{
  "race": "Texas Attorney General",
  "built_at": "2026-07-03T...Z",
  "root": {
    "id": "root",
    "label": "Nov 3 2026: Texas AG race decided",
    "timeframe": "2026-11",
    "kind": "fact",                     // fact | inference
    "likelihood": "high",               // high | medium | low (inference only)
    "description": "...",
    "issue_ids": ["ethics"],            // for personalization highlighting
    "affected_groups": ["renter", "small_business_owner"],  // matches VoterProfile flags
    "sources": [ { "title": "...", "url": "https://...", "publisher": "..." } ],
    "children": [ /* ScenarioNode[] — recursively down to leaves */ ]
  }
}
```

## API surface (all JSON)

| Route | Method | Body / query | Returns |
|---|---|---|---|
| `/api/config` | GET | — | `{ issues: IssueDef[], ui: UIConfig }` |
| `/api/election` | GET | `?state=texas` | `{ state, races: DiscoveredRace[], cached }` |
| `/api/election` | POST | `{ state }` | force live discovery |
| `/api/politicians` | GET | — | profile summaries |
| `/api/research` | POST | `{ name, force? }` | SSE `ResearchEvent` stream |
| `/api/match` | POST | `{ prefs: UserPreferences, politician_ids: string[] }` | `{ results: MatchResult[] }` |
| `/api/explain` | POST | `{ politician_id, prefs }` | `{ explanation, match, cached }` |
| `/api/qa` | POST | `{ politician_id, question }` | `{ answer }` (grounded, markdown) |

Planned (in progress): `/api/ballot` (address → races via FastAPI backend),
`/api/scenario?race=` (ScenarioTree).

## Invariants

1. **No source, no claim** — validators drop anything without a real URL.
2. Missing evidence → `unknowns`, lowers confidence, never inflates alignment.
3. All user data is explicit, local, request-scoped; never stored server-side.
4. `fact` vs `inference` labeled on every generated claim; predictions carry likelihood.
