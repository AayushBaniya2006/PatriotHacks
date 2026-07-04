# Civic Match

**A neutral, source-grounded candidate alignment engine.**

Tell it what you care about. It compares your stated priorities against candidates'
voting records, platforms, and public statements — researched live by a **Kimi agent
swarm** — and returns an explainable alignment score, a qualitative explanation,
and a source for every single claim.

> Do not optimize for persuasion. Optimize for informed, source-backed comparison.

---

## System architecture

```mermaid
flowchart TB
    subgraph CLIENT["Frontend (Next.js)"]
        LANDING["Landing page<br/>Nov 2026 Texas election<br/>(auto-discovered races)"]
        INTAKE["User info intake<br/>priority selection +<br/>trade-off questions"]
        RESULTS["Results dashboard<br/>quantitative score +<br/>qualitative explanation"]
        PRESENT["Presentation page<br/>politician info · policies ·<br/>sources · grounded Q&A"]
    end

    subgraph STAGING["Agent staging (minimize context)"]
        ORCH["Orchestrator<br/>splits 30-issue taxonomy into<br/>4 clusters + 1 profile task<br/>each agent sees ONLY its slice"]
    end

    subgraph SWARM["Kimi swarm — parallel research agents (kimi-k2 + web search)"]
        A1["Economy agent<br/>econ · taxes · jobs · housing<br/>energy · trade · infra ..."]
        A2["Society agent<br/>healthcare · education ·<br/>abortion · labor · civil rights ..."]
        A3["Security agent<br/>immigration · crime · guns ·<br/>defense · foreign policy ..."]
        A4["Governance agent<br/>elections · ethics · AI ·<br/>privacy · judiciary ..."]
        A5["Profile agent<br/>bio · party · office ·<br/>jurisdiction · website"]
    end

    subgraph ENDPOINTS["Data endpoints (via web search)"]
        E1["Roll-call votes /<br/>legislative records"]
        E2["Official campaign<br/>& office sites"]
        E3["Debate transcripts /<br/>public statements"]
        E4["Campaign finance /<br/>news / questionnaires"]
    end

    subgraph OUTPUT["Output report + double checks"]
        VAL["Programmatic validator<br/>NO SOURCE → NO CLAIM<br/>URL check · scalar clamp ·<br/>dedupe by confidence"]
        VER["Verifier agent (kimi-k2)<br/>double-checks axis placement ·<br/>flags contradictions"]
    end

    subgraph DB["db of politicians (cached, latency-first)"]
        PROFILES[("data/politicians/*.json<br/>stances · sources · quotes ·<br/>confidence · unknowns ·<br/>contradictions")]
        ELECTIONS[("data/elections/*.json<br/>auto-discovered races<br/>+ candidates")]
    end

    subgraph SCORING["Scoring engine (pure computation, ~ms)"]
        SCORE["Match score =<br/>Σ weight × alignment × confidence<br/>× recency × source quality"]
        QUAL["Qualitative layer<br/>agreements · conflicts ·<br/>caveats · confidence label"]
    end

    LANDING --> INTAKE
    INTAKE -->|"politician not cached"| ORCH
    ORCH --> A1 & A2 & A3 & A4 & A5
    A1 & A2 & A3 & A4 --> E1 & E2 & E3 & E4
    A1 & A2 & A3 & A4 & A5 --> VAL
    VAL --> VER
    VER --> PROFILES
    INTAKE -->|"politician cached (fast path)"| PROFILES
    ELECTIONS --> LANDING
    PROFILES --> SCORE
    SCORE --> QUAL
    QUAL --> RESULTS
    PROFILES --> PRESENT
    RESULTS --> PRESENT
```

## Research pipeline (per candidate)

```mermaid
sequenceDiagram
    participant U as User / Seed script
    participant O as Orchestrator
    participant S as Kimi swarm (5 agents, parallel)
    participant W as Web (primary sources)
    participant V as Validator + Verifier agent
    participant D as db of politicians

    U->>O: research "Candidate X"
    O->>D: cached?
    alt cache hit (fast path)
        D-->>U: profile in ~ms
    else cache miss
        O->>S: fan out — each agent gets ONLY its issue cluster
        par economy ∥ society ∥ security ∥ governance ∥ profile
            S->>W: web search: votes, platforms, statements
            W-->>S: evidence + URLs + quotes
        end
        S-->>V: raw stances (JSON)
        V->>V: drop claims without real source URLs
        V->>V: verify scalar vs. stated position (double check)
        V->>V: detect contradictions (promise vs. vote)
        V->>D: save structured profile
        D-->>U: SSE progress events → complete
    end
```

## Scoring: quantitative + qualitative

Every match returns **both**:

| Layer | What it is | How |
|---|---|---|
| Quantitative | `score` 0–100 + per-issue point decomposition | `Σ(weight × alignment × evidence_confidence × recency × source_quality)`, normalized to max achievable |
| Confidence | High / Medium / Low, shown separately from alignment | how much of the user's weighted priorities are covered by real evidence |
| Qualitative | short neutral explanation: top agreements, top conflicts, main caveat, missing evidence | generated from the scored breakdown, grounded only in indexed sources |

Key rules (from the PRD):

- **No source, no claim** — the validator drops any stance without a verifiable URL.
- **Unknowns are first-class** — missing evidence lowers *confidence*, never inflates *alignment*.
- **Conflicts are always shown** — "strongest match" still lists where you disagree.
- **Facts vs. inference are labeled** — the Q&A layer answers only from the indexed evidence base.

## The 30-issue taxonomy

User intake uses **trade-off questions**, not "do you care about X":
each of the 30 issues (economy, inflation, taxes, … judicial appointments) defines a
shared scalar axis (0.0 ↔ 1.0). The user's answer and the candidate's evidenced
position land on the *same axis*, so alignment is a simple, auditable distance.

## Latency-first design

1. **Pre-warm everything**: `npm run seed` auto-discovers the November Texas
   election, then swarm-researches every candidate into the JSON DB.
2. **Cache hit = no LLM call**: match scoring is pure arithmetic over cached
   profiles (<5 ms). The swarm only runs for uncached politicians.
3. **Parallel fan-out**: 5 agents per candidate, 2 candidates concurrently;
   each agent gets a minimal context slice (its cluster only).
4. **SSE streaming**: live research progress streams to the UI so users see
   agents working instead of a spinner.

## Running it

```bash
cp ../.env.example .env.local   # set OPENROUTER_API_KEY
npm install

# Pre-warm: auto-query the November election (Texas first) + research all candidates
npm run seed

npm run dev                     # http://localhost:3000
```

Other states: `npm run seed:state -- virginia`

## API

| Route | Method | Purpose |
|---|---|---|
| `/api/election?state=texas` | GET | cached races (fast path) |
| `/api/election` | POST | force live discovery agent |
| `/api/research` | POST | SSE stream: run the Kimi swarm for one politician |
| `/api/politicians` | GET | list cached profiles |
| `/api/match` | POST | score prefs vs. cached profiles (pure computation) |
| `/api/qa` | POST | grounded Q&A — answers only from indexed evidence |

## Models

| Role | Model | Why |
|---|---|---|
| Research agents (×4 clusters + profile) | `moonshotai/kimi-k2-0905:online` | web search, long context, cheap parallel fan-out |
| Verifier / output agent | `moonshotai/kimi-k2-0905` | fast double-check, no search needed |
| Grounded Q&A | `moonshotai/kimi-k2-0905` | answers restricted to evidence base |

Override with `RESEARCH_MODEL` / `FAST_MODEL` env vars.

## Trust & safety posture

- Neutral language everywhere; the product never says "vote for X".
- User preferences are explicit and local — never inferred, never sold.
- Judicial races and voting logistics deliberately out of scope for generation;
  logistics should link to official election authorities only.
- Every scored claim opens a source drawer: URL, publisher, date, quote,
  primary vs. secondary, and why it was classified that way.
