"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { CivitasPanel, SourceLink } from "@/components/civitas-ui";
import { loadPrefs } from "@/lib/prefs";
import type { Motivation } from "@/app/api/motivate/route";

// Hook, information, call to action. Motivates voting, never a candidate.
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
    <CivitasPanel className="mb-8 overflow-hidden p-6">
      <div className="mb-4 flex items-center gap-3">
        <div className="h-px flex-1 bg-gold/25" />
        <span className="text-[10px] font-semibold uppercase tracking-[0.24em] text-gold">
          Stakes
        </span>
        <div className="h-px flex-1 bg-gold/25" />
      </div>
      <h2 className="font-serif text-3xl font-normal leading-tight text-white">{m.hook}</h2>

      <div className="mb-5 mt-5 space-y-3">
        {m.because.map((b, i) => (
          <div key={i} className="flex gap-3 text-sm leading-6 text-white/72">
            <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-gold" />
            <span>
              {b.text}{" "}
              {b.source && (
                <SourceLink href={b.source.url} className="text-xs">
                  {b.source.title.slice(0, 40)}
                </SourceLink>
              )}
            </span>
          </div>
        ))}
      </div>

      <div className="mb-5 grid gap-4 text-sm sm:grid-cols-2">
        <div className="border-l border-gold/35 bg-navy-dark/55 p-4">
          <div className="mb-1.5 text-xs font-semibold uppercase tracking-[0.18em] text-gold">
            If you vote
          </div>
          <p className="leading-6 text-white/72">{m.if_you_vote}</p>
        </div>
        <div className="border-l border-white/20 bg-navy-dark/55 p-4">
          <div className="mb-1.5 text-xs font-semibold uppercase tracking-[0.18em] text-white/55">
            Long term
          </div>
          <p className="leading-6 text-white/72">
            {m.long_term}{" "}
            <Link href="/future" className="text-xs font-semibold text-gold hover:text-white">
              see the full tree
            </Link>
          </p>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <a
          href="https://www.votetexas.gov/"
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center justify-center rounded-[8px] bg-red px-5 py-3 text-xs font-black uppercase tracking-[0.2em] text-white shadow-[0_12px_28px_rgba(156,42,42,0.28)] transition hover:bg-red/90"
        >
          {m.cta}
        </a>
        <span className="text-[10px] uppercase tracking-[0.14em] text-white/42">
          Official state election site for registration, dates, and polling places.
        </span>
      </div>
    </CivitasPanel>
  );
}
