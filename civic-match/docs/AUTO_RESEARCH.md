# Auto-Research Feature

## Overview
When a candidate has insufficient data (< 8 sourced positions), the system now provides a **one-click auto-research** button that triggers the agent swarm to find and verify government-backed information.

## How It Works

### 1. Insufficient Data Detection
The system automatically detects when a candidate profile lacks sufficient data for meaningful scoring:
- Less than 8 sourced positions
- Missing qualitative dimensions
- Coverage tier is "minimal"

### 2. User-Triggered Research
When insufficient data is detected, users see:
- **"Research Now"** button in the collapsed card view
- **"Auto-Research via Agent Swarm (Uses Government Data)"** button in the expanded detail view
- Clear messaging: "Limited data — research pending"

### 3. Research Agent Swarm
Clicking the button triggers the full research pipeline:

```
User clicks → POST /api/research → Agent swarm launches → Real-time progress updates
```

**Agents deployed**:
1. **Profile agent** - Basic facts (name, party, office, bio)
2. **4 Issue cluster agents** (parallel) - Research positions on 30 issues across 4 thematic clusters
3. **Qualitative agent** - Record quality dimensions (integrity, transparency, experience, public interest)
4. **Promise-record agent** - Campaign promises vs actual voting record
5. **Finance agent** - FEC campaign finance data, top donors, correlations

### 4. Data Sources (Government-Backed)
All research is grounded in verifiable, government-backed sources:

**Primary sources**:
- **FEC (Federal Election Commission)** - Campaign finance, receipts, disbursements, donors
- **Congress.gov API** - Bill sponsorships, legislative text, committee assignments
- **House Clerk Roll-Call XML** - Voting records with bill numbers, dates, positions
- **Official campaign websites** - Candidate platforms (when available)
- **Government transcripts** - Debate transcripts, official statements

**Secondary sources** (must cite primary evidence):
- News reports (only when citing primary government data)
- Nonpartisan research organizations

### 5. Real-Time Progress Updates
The UI shows live progress via Server-Sent Events (SSE):
```
Starting research swarm...
→ Running profile agent...
→ Running cluster: Economy & Labor (7 issues)
→ Running qualitative agent...
→ Verifying sources...
→ ✓ Research complete! Reloading...
```

### 6. Auto-Reload
Once research completes, the page automatically reloads to show:
- New sourced positions
- Updated OVR score (if now above threshold)
- Qualitative dimensions
- All evidence with citations

## API Endpoints

### Check Research Status
```
GET /api/check-research/:id
```

**Response**:
```json
{
  "needs_research": true,
  "current_stances": 3,
  "current_qualitative": 0,
  "coverage_tier": "minimal",
  "researched_at": "2026-07-03T12:00:00.000Z"
}
```

### Trigger Research
```
POST /api/research
Body: { "name": "politician-id-or-name", "force": false }
```

**Response**: SSE stream of `ResearchEvent`
```json
{"type":"status","message":"Running profile agent...","progress":0.1}
{"type":"agent_start","agent":"cluster-economy","message":"Researching 7 issues..."}
{"type":"agent_done","agent":"cluster-economy","message":"Found 5 positions"}
{"type":"complete","message":"done","progress":1,"profile_id":"jane-doe"}
```

## Quality Guarantees

### 1. No Source, No Claim
Every position MUST have:
- At least one cited source with a real URL
- Evidence type (voting_record, sponsored_bill, official_platform, etc.)
- Confidence score (0.0-1.0) based on evidence quality

### 2. Neutral Language
All research uses neutral, factual language:
- ✅ "Voted for H.R. 1234 (Infrastructure Investment Act)"
- ❌ "Supports Biden's infrastructure boondoggle"

### 3. Honest Gaps
When evidence doesn't exist, the system:
- Omits the issue (doesn't guess)
- Shows "insufficient data" state
- Never fabricates positions

### 4. Verifier Guard
A separate verifier agent double-checks:
- All sources are accessible
- Quotes match source content
- Evidence types are accurate
- Confidence scores are justified

## Performance

**Typical research time**: 90-180 seconds
- Profile agent: ~10s
- 4 cluster agents (parallel): ~60-90s
- Qualitative + Promise + Finance agents: ~30-45s
- Verification: ~15-20s

**Cost**: ~$0.50-1.50 per candidate (OpenRouter API)

## Testing

To test the auto-research feature:

1. Find a candidate with insufficient data:
   ```bash
   npm run seed  # This will identify candidates needing research
   ```

2. Navigate to `/results` after completing intake

3. Look for candidates showing "Limited data — research pending"

4. Click "Research Now" button

5. Watch real-time progress

6. Verify updated profile after reload

## Example Flow

```
User: [Completes 30-issue intake + voter profile]
  ↓
System: Loads ballot, scores all candidates
  ↓
UI: Shows "Jane Doe - Limited data — research pending"
  ↓
User: [Clicks "Research Now"]
  ↓
Agent Swarm: 
  - Searches FEC for campaign finance data
  - Fetches voting record from House Clerk
  - Scrapes official campaign website
  - Cross-references bills on Congress.gov
  - Verifies all sources are accessible
  ↓
UI: "✓ Research complete! Reloading..."
  ↓
Results: Jane Doe now shows OVR 84, 19 sourced positions, 4 qualitative dimensions
```

## Future Enhancements

- **Background research**: Auto-research all candidates in a race proactively
- **Incremental updates**: Update profiles when new votes/bills are recorded
- **Notification**: Email user when research completes (for slow connections)
- **Batch research**: "Research all" button for entire ballot
