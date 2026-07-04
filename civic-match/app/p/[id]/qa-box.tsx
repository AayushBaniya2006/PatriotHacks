"use client";

import { useState } from "react";

const SUGGESTED = [
  "Where would I likely disagree with this candidate?",
  "Which of these positions come from votes vs campaign promises?",
  "What are the weakest sources in this analysis?",
  "What is this candidate's record on ethics?",
];

export default function QABox({ politicianId }: { politicianId: string }) {
  const [q, setQ] = useState("");
  const [history, setHistory] = useState<{ q: string; a: string }[]>([]);
  const [loading, setLoading] = useState(false);

  const ask = async (question: string) => {
    if (!question.trim() || loading) return;
    setLoading(true);
    setQ("");
    try {
      const res = await fetch("/api/qa", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ politician_id: politicianId, question }),
      }).then((r) => r.json());
      setHistory((h) => [...h, { q: question, a: res.answer ?? res.error ?? "No answer." }]);
    } catch {
      setHistory((h) => [...h, { q: question, a: "Request failed — try again." }]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900/50 p-4">
      <div className="flex flex-wrap gap-2 mb-4">
        {SUGGESTED.map((s) => (
          <button
            key={s}
            onClick={() => ask(s)}
            disabled={loading}
            className="rounded-full border border-zinc-700 px-3 py-1.5 text-xs text-zinc-400 hover:border-emerald-400/50 hover:text-zinc-200 disabled:opacity-40"
          >
            {s}
          </button>
        ))}
      </div>

      <div className="space-y-4 mb-4">
        {history.map((h, i) => (
          <div key={i}>
            <div className="text-sm font-medium text-zinc-300 mb-1">You: {h.q}</div>
            <div className="whitespace-pre-wrap rounded-lg bg-zinc-950 p-3 text-sm text-zinc-300">
              {h.a}
            </div>
          </div>
        ))}
        {loading && (
          <div className="text-sm text-zinc-500 animate-pulse">
            Checking the evidence base…
          </div>
        )}
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          ask(q);
        }}
        className="flex gap-2"
      >
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Ask a question grounded in the sources above…"
          className="flex-1 rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm outline-none focus:border-emerald-400/60"
        />
        <button
          disabled={loading || !q.trim()}
          className="rounded-lg bg-emerald-500 px-4 py-2 text-sm font-medium text-zinc-950 disabled:opacity-40"
        >
          Ask
        </button>
      </form>
    </div>
  );
}
