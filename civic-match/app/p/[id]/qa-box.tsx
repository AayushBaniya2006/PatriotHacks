"use client";

import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { CivitasButton, CivitasPanel } from "@/components/civitas-ui";

export default function QABox({
  politicianId,
  suggested,
}: {
  politicianId: string;
  suggested: string[];
}) {
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
    <CivitasPanel className="p-4">
      <div className="flex flex-wrap gap-2 mb-4">
        {suggested.map((s) => (
          <button
            key={s}
            onClick={() => ask(s)}
            disabled={loading}
            className="rounded-full border border-white/14 px-3 py-1.5 text-xs text-white/55 hover:border-gold/50 hover:text-gold disabled:opacity-40"
          >
            {s}
          </button>
        ))}
      </div>

      <div className="space-y-4 mb-4">
        {history.map((h, i) => (
          <div key={i}>
            <div className="mb-1.5 text-sm font-medium text-white/72">You: {h.q}</div>
            <div className="qa-answer rounded-[8px] border border-white/10 bg-navy-dark/60 p-4 text-sm text-white/72">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{h.a}</ReactMarkdown>
            </div>
          </div>
        ))}
        {loading && (
          <div className="animate-pulse text-sm text-white/45">
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
          className="flex-1 rounded-[8px] border border-white/14 bg-navy-dark px-3 py-2 text-sm text-white outline-none placeholder:text-white/32 focus:border-gold/70"
        />
        <CivitasButton disabled={loading || !q.trim()} className="px-4 py-2">
          Ask
        </CivitasButton>
      </form>
    </CivitasPanel>
  );
}
