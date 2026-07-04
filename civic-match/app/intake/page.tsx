"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { ISSUES } from "@/lib/issues";
import { savePrefs } from "@/lib/prefs";

const MAX_PICKS = 8;
const MIN_PICKS = 3;

export default function IntakePage() {
  const router = useRouter();
  const [step, setStep] = useState<"pick" | "tradeoffs">("pick");
  const [picked, setPicked] = useState<string[]>([]);
  const [positions, setPositions] = useState<Record<string, number | null>>({});
  const [idx, setIdx] = useState(0);

  const toggle = (id: string) =>
    setPicked((p) =>
      p.includes(id) ? p.filter((x) => x !== id) : p.length < MAX_PICKS ? [...p, id] : p
    );

  const currentIssue = useMemo(
    () => (step === "tradeoffs" ? ISSUES.find((i) => i.id === picked[idx]) : undefined),
    [step, picked, idx]
  );

  const answer = (scalar: number | null) => {
    const issueId = picked[idx];
    const next = { ...positions, [issueId]: scalar };
    setPositions(next);
    if (idx + 1 < picked.length) {
      setIdx(idx + 1);
    } else {
      // Rank-based weights: earlier picks weigh more.
      const weights: Record<string, number> = {};
      picked.forEach((id, i) => {
        weights[id] = (picked.length - i) / picked.length;
      });
      savePrefs({ priority_weights: weights, issue_positions: next });
      router.push("/results");
    }
  };

  if (step === "pick") {
    return (
      <div className="mx-auto max-w-3xl px-4 py-10">
        <h1 className="text-2xl font-bold mb-1">What matters most to you?</h1>
        <p className="text-zinc-400 text-sm mb-6">
          Pick {MIN_PICKS}–{MAX_PICKS} issues, most important first. Order sets the weight.
        </p>
        <div className="flex flex-wrap gap-2 mb-8">
          {ISSUES.map((issue) => {
            const pos = picked.indexOf(issue.id);
            const selected = pos !== -1;
            return (
              <button
                key={issue.id}
                onClick={() => toggle(issue.id)}
                className={`rounded-full border px-4 py-2 text-sm transition ${
                  selected
                    ? "border-emerald-400 bg-emerald-500/15 text-emerald-300"
                    : "border-zinc-700 text-zinc-300 hover:border-zinc-500"
                }`}
              >
                {selected && (
                  <span className="mr-1.5 text-xs font-semibold">#{pos + 1}</span>
                )}
                {issue.name}
              </button>
            );
          })}
        </div>
        <button
          disabled={picked.length < MIN_PICKS}
          onClick={() => setStep("tradeoffs")}
          className="rounded-lg bg-emerald-500 px-6 py-2.5 font-medium text-zinc-950 disabled:opacity-40 hover:bg-emerald-400"
        >
          Next: trade-offs ({picked.length} picked)
        </button>
      </div>
    );
  }

  if (!currentIssue) return null;

  return (
    <div className="mx-auto max-w-2xl px-4 py-10">
      <div className="mb-6">
        <div className="text-xs text-zinc-500 mb-2">
          Question {idx + 1} of {picked.length} · priority #{idx + 1}
        </div>
        <div className="h-1 rounded bg-zinc-800">
          <div
            className="h-1 rounded bg-emerald-400 transition-all"
            style={{ width: `${(idx / picked.length) * 100}%` }}
          />
        </div>
      </div>

      <h1 className="text-xl font-bold mb-1">{currentIssue.name}</h1>
      <p className="text-zinc-400 mb-6">{currentIssue.tradeoffQuestion}</p>

      <div className="space-y-3">
        {currentIssue.options.map((o) => (
          <button
            key={o.key}
            onClick={() => answer(o.scalar)}
            className="w-full rounded-xl border border-zinc-700 bg-zinc-900/50 px-5 py-4 text-left hover:border-emerald-400/60 hover:bg-zinc-900"
          >
            <span className="mr-3 font-mono text-emerald-400">{o.key}.</span>
            {o.label}
          </button>
        ))}
        <button
          onClick={() => answer(null)}
          className="w-full rounded-xl border border-dashed border-zinc-800 px-5 py-3 text-left text-sm text-zinc-500 hover:border-zinc-600"
        >
          Not sure / don&apos;t use this answer in my match score
        </button>
      </div>
    </div>
  );
}
