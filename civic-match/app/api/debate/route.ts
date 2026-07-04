import { NextRequest } from "next/server";
import crypto from "crypto";
import { promises as fs } from "fs";
import path from "path";
import { chat, extractJSON, FAST_MODEL } from "@/lib/llm";
import { getPolitician } from "@/lib/db";
import { getIssueMap } from "@/lib/config";
import type { PoliticianProfile } from "@/lib/types";

export const maxDuration = 300;

const CACHE_DIR = path.join(process.cwd(), "data", "debates");

interface DebateEvent {
  type: "turn" | "judge" | "status" | "error" | "complete";
  speaker?: string;
  phase?: string;
  text?: string;
  judge?: JudgeVerdict;
  message?: string;
}

interface JudgeVerdict {
  scores: Record<
    string,
    { groundedness: number; unsourced_claims: string[]; notes: string }
  >;
  verdict: string; // who stayed truer to their actual record, and why
}

function evidencePack(p: PoliticianProfile, topicIssues: string[]) {
  const ISSUE_MAP = getIssueMap();
  const stances = p.stances
    .filter((s) => topicIssues.length === 0 || topicIssues.includes(s.issue_id))
    .map((s) => ({
      issue: ISSUE_MAP[s.issue_id]?.name ?? s.issue_id,
      position: s.position_label,
      summary: s.summary,
      evidence_type: s.evidence_type,
      sources: s.sources.slice(0, 2).map((src) => `${src.title} (${src.publisher})`),
    }));
  const promises = (p.promise_record ?? []).map((r) => ({
    promise: r.promise,
    action: r.action,
    verdict: r.verdict,
  }));
  return { name: p.name, party: p.party, office: p.current_office, stances, promises };
}

function candidateSystem(pack: ReturnType<typeof evidencePack>, topic: string) {
  return `You are a debate agent playing U.S. politician ${pack.name} (${pack.party ?? "?"}) in a moderated debate on: ${topic}.

HARD RULES — you are graded on fidelity to the real record:
- Argue ONLY from the evidence pack below (real positions, votes, promises). Cite as [source name] after each claim.
- If your record is silent on a point, say so — do not improvise positions.
- Stay in character but factual: represent their actual documented views, including uncomfortable parts of the record (broken promises may be raised by your opponent).
- Max 110 words per turn. Plain, direct debate style. No slogans, no attacks on groups, no fabricated statistics.

EVIDENCE PACK:
${JSON.stringify(pack)}`;
}

// POST /api/debate { a, b, topic_issue? } → SSE stream of DebateEvent
export async function POST(req: NextRequest) {
  const { a, b, topic_issue } = await req.json();
  const [pa, pb] = await Promise.all([getPolitician(a), getPolitician(b)]);
  if (!pa || !pb) return Response.json({ error: "unknown politician" }, { status: 404 });

  const ISSUE_MAP = getIssueMap();
  const topicIssues = topic_issue && ISSUE_MAP[topic_issue] ? [topic_issue] : [];
  const topic = topic_issue && ISSUE_MAP[topic_issue]
    ? ISSUE_MAP[topic_issue].name
    : "the issues facing voters in this election";

  const hash = crypto.createHash("sha1").update(`${a}|${b}|${topic_issue ?? "all"}|${pa.researched_at}|${pb.researched_at}`).digest("hex").slice(0, 16);
  const cacheFile = path.join(CACHE_DIR, `${hash}.json`);

  const encoder = new TextEncoder();
  const stream = new ReadableStream({
    async start(controller) {
      const send = (e: DebateEvent) =>
        controller.enqueue(encoder.encode(`data: ${JSON.stringify(e)}\n\n`));
      try {
        // Cached debate: replay instantly (latency-first)
        try {
          const cached: DebateEvent[] = JSON.parse(await fs.readFile(cacheFile, "utf-8"));
          for (const e of cached) send(e);
          send({ type: "complete", message: "cached" });
          controller.close();
          return;
        } catch { /* miss */ }

        const events: DebateEvent[] = [];
        const packA = evidencePack(pa, topicIssues);
        const packB = evidencePack(pb, topicIssues);
        const sysA = candidateSystem(packA, topic);
        const sysB = candidateSystem(packB, topic);
        const transcript: { speaker: string; phase: string; text: string }[] = [];

        const phases: { phase: string; prompt: (opp: string) => string }[] = [
          { phase: "opening", prompt: () => `Give your opening statement on ${topic}. Ground every claim in your evidence pack with [source] citations.` },
          { phase: "rebuttal", prompt: (opp) => `Your opponent said:\n"${opp}"\nRebut using ONLY your evidence pack — you may point out where their stated record contradicts their claims. Cite [source] for everything.` },
          { phase: "closing", prompt: () => `Give a short closing statement on ${topic}. Only evidence-pack claims, cited.` },
        ];

        for (const { phase, prompt } of phases) {
          for (const [name, sys, profile] of [
            [pa.name, sysA, pa],
            [pb.name, sysB, pb],
          ] as const) {
            send({ type: "status", message: `${name} — ${phase}...` });
            const oppLast = [...transcript].reverse().find((t) => t.speaker !== name)?.text ?? "";
            const text = await chat(
              [
                { role: "system", content: sys },
                { role: "user", content: prompt(oppLast) },
              ],
              { model: FAST_MODEL, maxTokens: 400, timeoutMs: 90_000 }
            );
            transcript.push({ speaker: name, phase, text });
            const ev: DebateEvent = { type: "turn", speaker: name, phase, text };
            events.push(ev);
            send(ev);
            void profile;
          }
        }

        // Judge agent: fidelity to the real record, penalize unsourced claims
        send({ type: "status", message: "Judge reviewing transcript against ground truth..." });
        const judgeOut = await chat(
          [
            {
              role: "user",
              content: `You are a neutral debate judge for a ground-truth voter tool. Score each debater ONLY on fidelity to their real documented record — not rhetoric, not who you agree with.

EVIDENCE PACKS (ground truth):
${pa.name}: ${JSON.stringify(packA)}
${pb.name}: ${JSON.stringify(packB)}

TRANSCRIPT:
${JSON.stringify(transcript)}

For each debater: groundedness 0-100 (every claim traceable to their pack = 100; deduct ~15 per unsourced or contradicted claim), list the specific unsourced/contradicted claims, and one sentence of notes. Then a verdict: who stayed truer to their actual record and why.

Return ONLY JSON: {"scores": {"${pa.name}": {"groundedness": 0-100, "unsourced_claims": ["..."], "notes": "..."}, "${pb.name}": {...}}, "verdict": "..."}`,
            },
          ],
          { model: FAST_MODEL, maxTokens: 1200, timeoutMs: 90_000 }
        );
        let judge: JudgeVerdict;
        try {
          judge = extractJSON<JudgeVerdict>(judgeOut);
        } catch {
          judge = { scores: {}, verdict: "Judge output unavailable." };
        }
        const jev: DebateEvent = { type: "judge", judge };
        events.push(jev);
        send(jev);

        await fs.mkdir(CACHE_DIR, { recursive: true });
        await fs.writeFile(cacheFile, JSON.stringify(events));
        send({ type: "complete", message: "done" });
      } catch (err) {
        send({ type: "error", message: err instanceof Error ? err.message : "debate failed" });
      }
      controller.close();
    },
  });

  return new Response(stream, {
    headers: { "Content-Type": "text/event-stream", "Cache-Control": "no-cache" },
  });
}
