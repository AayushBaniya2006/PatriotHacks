import { NextRequest } from "next/server";
import { getPolitician } from "@/lib/db";
import { chat, FAST_MODEL } from "@/lib/llm";
import { ISSUE_MAP } from "@/lib/issues";

export const maxDuration = 120;

// POST /api/qa { politician_id, question }
// Grounded Q&A: answers ONLY from the indexed evidence base (PRD 8.5).
export async function POST(req: NextRequest) {
  const { politician_id, question } = await req.json();
  const profile = await getPolitician(politician_id);
  if (!profile) return Response.json({ error: "unknown politician" }, { status: 404 });

  const evidence = profile.stances.map((s) => ({
    issue: ISSUE_MAP[s.issue_id]?.name ?? s.issue_id,
    position: s.position_label,
    summary: s.summary,
    evidence_type: s.evidence_type,
    confidence: s.confidence,
    recency: s.recency,
    sources: s.sources.map((src) => ({
      title: src.title,
      publisher: src.publisher,
      url: src.url,
      date: src.published_at,
      primary: src.primary_source,
      quote: src.quote,
    })),
  }));

  const qualitative = (profile.qualitative ?? []).map((q) => ({
    dimension: q.id,
    score: q.score,
    summary: q.summary,
    confidence: q.confidence,
    sources: q.sources.map((src) => ({
      title: src.title,
      publisher: src.publisher,
      url: src.url,
      date: src.published_at,
      primary: src.primary_source,
    })),
  }));

  const system = `You are the Q&A layer of Civic Match, a neutral, source-grounded voter information tool.

STRICT RULES:
- Answer ONLY from the evidence base below. Never answer from memory.
- Every factual claim about the politician must reference a source from the evidence base (cite as [title — publisher]).
- If the evidence base has nothing on the question, say exactly that: "I found no source in the indexed evidence covering this." Suggest what evidence would help.
- Label inference separately from fact (e.g. "Fact: ... Inference: ...").
- Neutral language only. No persuasion, no campaign rhetoric, no telling the user how to vote.
- Keep answers short and structured.

POLITICIAN: ${profile.name} (${profile.party ?? "party unknown"}, ${profile.current_office ?? "office unknown"})
ISSUES WITH NO INDEXED EVIDENCE: ${profile.unknowns.map((u) => ISSUE_MAP[u]?.name).filter(Boolean).join(", ") || "none"}

EVIDENCE BASE — ISSUE POSITIONS:
${JSON.stringify(evidence)}

EVIDENCE BASE — RECORD QUALITY (ethics/integrity, public interest, transparency, experience):
${JSON.stringify(qualitative)}`;

  const answer = await chat(
    [
      { role: "system", content: system },
      { role: "user", content: String(question).slice(0, 2000) },
    ],
    { model: FAST_MODEL, maxTokens: 1500, timeoutMs: 90_000 }
  );

  return Response.json({ answer });
}
