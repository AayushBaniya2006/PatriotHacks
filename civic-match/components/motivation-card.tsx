"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { loadPrefs } from "@/lib/prefs";
import type { Motivation } from "@/app/api/motivate/route";

// Hook → information → call to action. Motivates voting, never a candidate.
export default function MotivationCard() {
  const [m, setM] = useState<Motivation | null>(null);

  useEffect(() => {
    const prefs = loadPrefs();
    if (!prefs) return;
    fetch("/api/motivate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prefs }),
    })
      .then((r) => r.json())
      .then((d) => setM(d.motivation ?? null))
      .catch(() => {});
  }, []);

  if (!m) return null;

  return (
    <div className="rounded-2xl border border-emerald-500/30 bg-gradient-to-br from-emerald-500/10 to-transparent p-6 mb-8">
      <h2 className="text-2xl font-bold tracking-tight mb-4">{m.hook}</h2>

      <div className="space-y-2 mb-5">
        {m.because.map((b, i) => (
          <div key={i} className="flex gap-2 text-sm text-zinc-300">
            <span className="text-emerald-400 font-bold shrink-0">→</span>
            <span>
              {b.text}{" "}
              {b.source && (
                <a href={b.source.url} target="_blank" className="text-emerald-400 text-xs hover:underline">
                  [{b.source.title.slice(0, 40)}] ↗
                </a>
              )}
            </span>
          </div>
        ))}
      </div>

      <div className="grid gap-4 sm:grid-cols-2 mb-5 text-sm">
        <div className="rounded-xl bg-zinc-950/60 p-4">
          <div className="text-xs uppercase tracking-wider text-emerald-400 mb-1.5">
            If you vote
          </div>
          <p className="text-zinc-300">{m.if_you_vote}</p>
        </div>
        <div className="rounded-xl bg-zinc-950/60 p-4">
          <div className="text-xs uppercase tracking-wider text-sky-400 mb-1.5">
            Long term
          </div>
          <p className="text-zinc-300">
            {m.long_term}{" "}
            <Link href="/future" className="text-emerald-400 text-xs hover:underline">
              see the full tree →
            </Link>
          </p>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <a
          href="https://www.votetexas.gov/"
          target="_blank"
          className="rounded-lg bg-emerald-500 px-5 py-2.5 text-sm font-semibold text-zinc-950 hover:bg-emerald-400"
        >
          {m.cta}
        </a>
        <span className="text-[10px] text-zinc-600">
          Official state election site (VoteTexas.gov) — registration, dates, polling places.
        </span>
      </div>
    </div>
  );
}
