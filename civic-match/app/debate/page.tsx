"use client";

import { useEffect, useState } from "react";
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
    <div className="mx-auto max-w-3xl px-4 py-10">
      <h1 className="text-2xl font-bold mb-1">Ground-truth debate arena</h1>
      <p className="text-sm text-zinc-500 mb-6 max-w-2xl">
        Two candidate-agents, each hard-grounded in that candidate&apos;s real votes,
        platforms, and promises — no improvised positions. A judge agent scores who
        stayed truer to their actual record and flags every unsourced claim.
      </p>

      <div className="flex flex-wrap gap-2 mb-6 items-center">
        <select value={a} onChange={(e) => setA(e.target.value)}
          className="rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm">
          <option value="">Candidate A…</option>
          {politicians.map((p) => <option key={p.id} value={p.id}>{p.name} ({p.party ?? "?"})</option>)}
        </select>
        <span className="text-zinc-500 text-sm">vs</span>
        <select value={b} onChange={(e) => setB(e.target.value)}
          className="rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm">
          <option value="">Candidate B…</option>
          {politicians.map((p) => <option key={p.id} value={p.id}>{p.name} ({p.party ?? "?"})</option>)}
        </select>
        <select value={topic} onChange={(e) => setTopic(e.target.value)}
          className="rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm">
          <option value="">All issues</option>
          {issues.map((i) => <option key={i.id} value={i.id}>{i.name}</option>)}
        </select>
        <button onClick={run} disabled={!a || !b || a === b || running}
          className="rounded-lg bg-emerald-500 px-5 py-2 text-sm font-medium text-zinc-950 disabled:opacity-40">
          {running ? "Debating…" : "Start debate"}
        </button>
      </div>

      <div className="space-y-4">
        {turns.map((t, i) => (
          <div key={i} className={`max-w-[85%] ${sideOf(t.speaker) === "b" ? "ml-auto" : ""}`}>
            <div className={`text-xs mb-1 ${sideOf(t.speaker) === "b" ? "text-right text-sky-400" : "text-emerald-400"}`}>
              {t.speaker} · {t.phase}
            </div>
            <div className={`rounded-xl border p-4 text-sm whitespace-pre-wrap ${
              sideOf(t.speaker) === "b"
                ? "border-sky-500/30 bg-sky-500/5"
                : "border-emerald-500/30 bg-emerald-500/5"
            }`}>
              {t.text}
            </div>
          </div>
        ))}
        {status && <div className="text-sm text-zinc-500 animate-pulse">{status}</div>}

        {judge && (
          <div className="rounded-xl border border-amber-500/40 bg-amber-500/5 p-5">
            <h2 className="font-semibold text-amber-300 mb-3">Judge: fidelity to the record</h2>
            <div className="grid gap-3 sm:grid-cols-2 mb-3">
              {Object.entries(judge.scores).map(([name, s]) => (
                <div key={name} className="rounded-lg bg-zinc-950 p-3 text-sm">
                  <div className="flex justify-between mb-1">
                    <span className="font-medium">{name}</span>
                    <span className="font-mono text-lg">{s.groundedness}<span className="text-xs text-zinc-500">/100</span></span>
                  </div>
                  <p className="text-xs text-zinc-400 mb-2">{s.notes}</p>
                  {s.unsourced_claims.length > 0 && (
                    <ul className="text-xs text-red-300 space-y-1">
                      {s.unsourced_claims.map((c, i) => <li key={i}>⚠ {c}</li>)}
                    </ul>
                  )}
                </div>
              ))}
            </div>
            <p className="text-sm text-zinc-300">{judge.verdict}</p>
          </div>
        )}
      </div>
    </div>
  );
}
