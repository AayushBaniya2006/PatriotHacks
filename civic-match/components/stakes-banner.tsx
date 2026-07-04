"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { CivitasPanel, SourceLink } from "@/components/civitas-ui";
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
    <CivitasPanel className="mb-8 p-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.22em] text-gold">
            Participation record
          </p>
          <h2 className="font-serif text-2xl font-normal leading-tight text-white">
            These decisions happen with or without you.
          </h2>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-white/62">
            Every office on this ballot will be filled either way — the only variable
            is who decides. Here is the ground truth on how close it gets, and what
            the winners will control.
          </p>
        </div>
        <button
          onClick={() => setOpen(!open)}
          className="shrink-0 rounded-[8px] border border-gold/45 px-3 py-2 text-xs font-semibold uppercase tracking-[0.16em] text-gold hover:bg-gold/10"
        >
          {open ? "Hide" : "What happens if I don't vote?"}
        </button>
      </div>

      {open && (
        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          <div>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-[0.18em] text-white/45">
              How close it actually gets
            </h3>
            <ul className="space-y-2 text-sm">
              {margins.map((s) => (
                <li key={s.race} className="leading-6 text-white/70">
                  <span className="text-white/42">{s.race}:</span> {s.last_margin!.summary}{" "}
                  <SourceLink href={s.last_margin!.source.url} className="text-xs">
                    {s.last_margin!.source.publisher ?? "source"}
                  </SourceLink>
                  {s.turnout && (
                    <span className="block text-xs text-white/42">
                      {s.turnout.summary}{" "}
                      <SourceLink href={s.turnout.source.url}>source</SourceLink>
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </div>
          <div>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-[0.18em] text-white/45">
              Decided anyway — by whoever wins
            </h3>
            <ul className="space-y-2 text-sm">
              {decided.slice(0, 6).map((d, i) => (
                <li key={i} className="leading-6 text-white/70">
                  {d.text}{" "}
                  <SourceLink href={d.source.url} className="text-xs">source</SourceLink>
                </li>
              ))}
            </ul>
            <Link href="/future" className="mt-3 inline-block text-xs font-semibold uppercase tracking-[0.16em] text-gold hover:text-white">
              See the full consequence tree
            </Link>
          </div>
        </div>
      )}
    </CivitasPanel>
  );
}
