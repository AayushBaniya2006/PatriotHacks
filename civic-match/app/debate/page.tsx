"use client";

import { useEffect, useState } from "react";
import { CivitasButton, CivitasPage, CivitasPanel, StatusPill } from "@/components/civitas-ui";
import type { IssueDef } from "@/lib/issues";

interface Turn { speaker: string; phase: string; text: string }
interface Judge {
  scores: Record<string, { groundedness: number; unsourced_claims: string[]; notes: string }>;
  verdict: string;
}
interface Summary { id: string; name: string; party?: string }

export default function DebatePage() {
  const [politicians, setPoliticians] = useState<Summary[]>([]);
  const [issues, setIssues] = useState<IssueDef[]>([]);
  const [a, setA] = useState("");
  const [b, setB] = useState("");
  const [topic, setTopic] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [judge, setJudge] = useState<Judge | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [running, setRunning] = useState(false);

  useEffect(() => {
    fetch("/api/politicians").then((r) => r.json()).then(setPoliticians);
    fetch("/api/config").then((r) => r.json()).then((c) => setIssues(c.issues));
  }, []);

  const run = async () => {
    if (!a || !b || a === b || running) return;
    setRunning(true);
    setTurns([]);
    setJudge(null);
    setStatus("Grounding both agents in their real records…");
    const res = await fetch("/api/debate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ a, b, topic_issue: topic || undefined }),
    });
    const reader = res.body!.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const parts = buf.split("\n\n");
      buf = parts.pop()!;
      for (const p of parts) {
        if (!p.startsWith("data: ")) continue;
        const e = JSON.parse(p.slice(6));
        if (e.type === "status") setStatus(e.message);
        if (e.type === "turn") { setTurns((t) => [...t, e]); setStatus(null); }
        if (e.type === "judge") setJudge(e.judge);
        if (e.type === "error") setStatus(`Error: ${e.message}`);
        if (e.type === "complete") setStatus(null);
      }
    }
    setRunning(false);
  };

  const nameOf = (id: string) => politicians.find((p) => p.id === id)?.name ?? id;
  const sideOf = (speaker: string) => (speaker === nameOf(a) ? "a" : "b");

  return (
    <CivitasPage
      eyebrow="Record hearing"
      title="Ground-truth debate arena"
      description={
        <>
        Two candidate-agents, each hard-grounded in that candidate&apos;s real votes,
        platforms, and promises — no improvised positions. A judge agent scores who
        stayed truer to their actual record and flags every unsourced claim.
        </>
      }
    >

      <div className="mb-6 grid min-w-0 gap-3 sm:grid-cols-2 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,220px)_auto] lg:items-end">
        <label className="grid min-w-0 gap-1.5 text-xs font-semibold uppercase tracking-[0.16em] text-white/50">
          Candidate A
          <select value={a} onChange={(e) => setA(e.target.value)}
            className="min-w-0 rounded-[8px] border border-white/14 bg-navy-dark px-3 py-2 text-sm normal-case tracking-normal text-white outline-none focus:border-gold/70">
            <option value="">Choose candidate A…</option>
            {politicians.map((p) => <option key={p.id} value={p.id}>{p.name} ({p.party ?? "?"})</option>)}
          </select>
        </label>
        <label className="grid min-w-0 gap-1.5 text-xs font-semibold uppercase tracking-[0.16em] text-white/50">
          Candidate B
          <select value={b} onChange={(e) => setB(e.target.value)}
            className="min-w-0 rounded-[8px] border border-white/14 bg-navy-dark px-3 py-2 text-sm normal-case tracking-normal text-white outline-none focus:border-gold/70">
            <option value="">Choose candidate B…</option>
            {politicians.map((p) => <option key={p.id} value={p.id}>{p.name} ({p.party ?? "?"})</option>)}
          </select>
        </label>
        <label className="grid min-w-0 gap-1.5 text-xs font-semibold uppercase tracking-[0.16em] text-white/50">
          Issue
          <select value={topic} onChange={(e) => setTopic(e.target.value)}
            className="min-w-0 rounded-[8px] border border-white/14 bg-navy-dark px-3 py-2 text-sm normal-case tracking-normal text-white outline-none focus:border-gold/70">
            <option value="">All issues</option>
            {issues.map((i) => <option key={i.id} value={i.id}>{i.name}</option>)}
          </select>
        </label>
        <CivitasButton onClick={run} disabled={!a || !b || a === b || running} className="h-[42px]">
          {running ? "Debating…" : "Start debate"}
        </CivitasButton>
      </div>

      <div className="space-y-4">
        {turns.map((t, i) => (
          <div key={i} className={`max-w-[88%] ${sideOf(t.speaker) === "b" ? "ml-auto" : ""}`}>
            <div className={`mb-1 text-xs font-semibold uppercase tracking-[0.16em] ${sideOf(t.speaker) === "b" ? "text-right text-cream/70" : "text-gold"}`}>
              {t.speaker} · {t.phase}
            </div>
            <div className={`whitespace-pre-wrap rounded-[10px] border p-4 text-sm leading-6 ${
              sideOf(t.speaker) === "b"
                ? "border-cream/20 bg-cream/5 text-white/72"
                : "border-gold/30 bg-gold/10 text-white/72"
            }`}>
              {t.text}
            </div>
          </div>
        ))}
        {status && <div role="status" aria-live="polite" className="animate-pulse text-sm text-white/45">{status}</div>}

        {judge && (
          <CivitasPanel className="p-5">
            <h2 className="mb-3 font-serif text-2xl font-normal text-white">Judge: fidelity to the record</h2>
            <div className="mb-3 grid gap-3 sm:grid-cols-2">
              {Object.entries(judge.scores).map(([name, s]) => (
                <div key={name} className="rounded-[8px] border border-white/10 bg-navy-dark/60 p-3 text-sm">
                  <div className="flex justify-between mb-1">
                    <span className="font-medium text-white/78">{name}</span>
                    <span className="font-mono text-lg text-gold">{s.groundedness}<span className="text-xs text-white/38">/100</span></span>
                  </div>
                  <p className="mb-2 text-xs leading-5 text-white/50">{s.notes}</p>
                  {s.unsourced_claims.length > 0 && (
                    <ul className="space-y-1 text-xs text-red-100">
                      {s.unsourced_claims.map((c, i) => <li key={i}><StatusPill tone="red">Unsourced</StatusPill> {c}</li>)}
                    </ul>
                  )}
                </div>
              ))}
            </div>
            <p className="text-sm leading-6 text-white/72">{judge.verdict}</p>
          </CivitasPanel>
        )}
      </div>
    </CivitasPage>
  );
}
