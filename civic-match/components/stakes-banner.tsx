"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import type { RaceStakes } from "@/app/api/stakes/route";

// "Here's what happens whether or not you vote" — nonpartisan, ground-truth-backed.
export default function StakesBanner() {
  const [stakes, setStakes] = useState<RaceStakes[]>([]);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    fetch("/api/stakes")
      .then((r) => r.json())
      .then((d) => setStakes(d.stakes ?? []))
      .catch(() => {});
  }, []);

  if (stakes.length === 0) return null;

  const margins = stakes.filter((s) => s.last_margin);
  const decided = stakes.flatMap((s) =>
    (s.decided_anyway ?? []).map((d) => ({ ...d, race: s.race }))
  );

  return (
    <div className="rounded-xl border border-amber-500/30 bg-amber-500/5 p-5 mb-8">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="font-semibold text-amber-300 mb-1">
            These decisions happen with or without you.
          </h2>
          <p className="text-sm text-zinc-400 max-w-2xl">
            Every office on this ballot will be filled either way — the only variable
            is who decides. Here is the ground truth on how close it gets, and what
            the winners will control.
          </p>
        </div>
        <button
          onClick={() => setOpen(!open)}
          className="shrink-0 rounded-lg border border-amber-500/40 px-3 py-1.5 text-xs text-amber-300 hover:bg-amber-500/10"
        >
          {open ? "Hide" : "What happens if I don't vote?"}
        </button>
      </div>

      {open && (
        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          <div>
            <h3 className="text-xs uppercase tracking-wider text-zinc-500 mb-2">
              How close it actually gets
            </h3>
            <ul className="space-y-2 text-sm">
              {margins.map((s) => (
                <li key={s.race} className="text-zinc-300">
                  <span className="text-zinc-500">{s.race}:</span> {s.last_margin!.summary}{" "}
                  <a href={s.last_margin!.source.url} target="_blank" className="text-emerald-400 text-xs hover:underline">
                    [{s.last_margin!.source.publisher ?? "source"}] ↗
                  </a>
                  {s.turnout && (
                    <span className="block text-xs text-zinc-500">
                      {s.turnout.summary}{" "}
                      <a href={s.turnout.source.url} target="_blank" className="text-emerald-400 hover:underline">
                        ↗
                      </a>
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </div>
          <div>
            <h3 className="text-xs uppercase tracking-wider text-zinc-500 mb-2">
              Decided anyway — by whoever wins
            </h3>
            <ul className="space-y-2 text-sm">
              {decided.slice(0, 6).map((d, i) => (
                <li key={i} className="text-zinc-300">
                  {d.text}{" "}
                  <a href={d.source.url} target="_blank" className="text-emerald-400 text-xs hover:underline">
                    ↗
                  </a>
                </li>
              ))}
            </ul>
            <Link href="/future" className="mt-3 inline-block text-xs text-emerald-400 hover:underline">
              See the full down-the-line consequence tree →
            </Link>
          </div>
        </div>
      )}
    </div>
  );
}
