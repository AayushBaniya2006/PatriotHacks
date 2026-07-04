"use client";

import { useState } from "react";
import Link from "next/link";
import { slugify } from "@/lib/db-client";

interface BallotRace {
  race?: string;
  office?: string;
  election_date?: string;
  candidates?: { name: string; party?: string }[];
}

export default function BallotPage() {
  const [address, setAddress] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<{
    mode?: string;
    warning?: string;
    matched_address?: string;
    districts?: Record<string, string>;
    races: BallotRace[];
  } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const lookup = async () => {
    if (!address.trim() || loading) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/ballot?address=${encodeURIComponent(address)}`);
      const data = await res.json();
      if (!res.ok) setError(data.error ?? data.detail ?? "Address could not be matched.");
      else setResult({ ...data, races: data.races ?? [] });
    } catch {
      setError("Lookup failed — try again.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="mx-auto max-w-3xl px-4 py-10">
      <h1 className="text-2xl font-bold mb-1">Your actual ballot</h1>
      <p className="text-sm text-zinc-500 mb-6">
        Enter your address — we resolve your districts and show the races you will
        actually vote on, down-ballot included. Your address is used for the lookup
        only and never stored.
      </p>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          lookup();
        }}
        className="flex gap-2 mb-8"
      >
        <input
          value={address}
          onChange={(e) => setAddress(e.target.value)}
          placeholder="1600 Congress Ave, Austin, TX"
          className="flex-1 rounded-lg border border-zinc-700 bg-zinc-950 px-4 py-2.5 text-sm outline-none focus:border-emerald-400/60"
        />
        <button
          disabled={loading || !address.trim()}
          className="rounded-lg bg-emerald-500 px-5 py-2.5 text-sm font-medium text-zinc-950 disabled:opacity-40"
        >
          {loading ? "Resolving…" : "Find my ballot"}
        </button>
      </form>

      {error && (
        <p className="rounded-lg border border-red-500/40 bg-red-500/10 p-3 text-sm text-red-300 mb-6">{error}</p>
      )}

      {result && (
        <>
          {result.matched_address && (
            <p className="text-xs text-zinc-500 mb-1">Matched: {result.matched_address}</p>
          )}
          {result.districts && (
            <p className="text-xs text-zinc-500 mb-3">
              Districts:{" "}
              {Object.entries(result.districts)
                .filter(([, v]) => v)
                .map(([k, v]) => `${k.toUpperCase()} ${v}`)
                .join(" · ")}
            </p>
          )}
          {result.warning && (
            <p className="rounded-lg border border-yellow-500/30 bg-yellow-500/5 p-3 text-xs text-yellow-300 mb-4">
              {result.warning}
            </p>
          )}
          <div className="space-y-4">
            {result.races.map((r, i) => (
              <div key={i} className="rounded-xl border border-zinc-800 bg-zinc-900/50 p-5">
                <div className="flex items-baseline justify-between mb-3">
                  <h3 className="font-semibold">{r.race ?? r.office}</h3>
                  {r.election_date && <span className="text-xs text-zinc-500">{r.election_date}</span>}
                </div>
                <ul className="space-y-1.5">
                  {(r.candidates ?? []).map((c) => (
                    <li key={c.name} className="flex items-center justify-between text-sm">
                      <span>
                        {c.name} {c.party && <span className="text-zinc-500">({c.party})</span>}
                      </span>
                      <Link href={`/p/${slugify(c.name)}`} className="text-xs text-emerald-400 hover:underline">
                        ground truth →
                      </Link>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
