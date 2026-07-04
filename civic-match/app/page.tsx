import Link from "next/link";
import { getCachedElection } from "@/lib/discovery";
import { listPoliticians, slugify } from "@/lib/db";
import { getUI } from "@/lib/config";
import StakesBanner from "@/components/stakes-banner";

export const dynamic = "force-dynamic";

export default async function Home() {
  const ui = getUI();
  const [races, politicians] = await Promise.all([
    getCachedElection(ui.default_state),
    listPoliticians(),
  ]);
  const byId = new Map(politicians.map((p) => [p.id, p]));

  return (
    <div className="mx-auto max-w-5xl px-4 py-12">
      <section className="mb-12">
        <h1 className="text-4xl font-bold tracking-tight mb-3">
          {ui.landing.hero_title}{" "}
          <span className="text-emerald-400">{ui.landing.hero_highlight}</span>
        </h1>
        <p className="text-zinc-400 max-w-2xl mb-6">{ui.landing.hero_subtitle}</p>
        <div className="flex gap-3">
          <Link
            href="/intake"
            className="rounded-lg bg-emerald-500 px-5 py-2.5 font-medium text-zinc-950 hover:bg-emerald-400"
          >
            {ui.landing.cta_primary}
          </Link>
          <Link
            href="/results"
            className="rounded-lg border border-zinc-700 px-5 py-2.5 font-medium hover:border-zinc-500"
          >
            {ui.landing.cta_secondary}
          </Link>
        </div>
      </section>

      <StakesBanner />

      <section className="mb-12">
        <div className="flex items-baseline justify-between mb-4">
          <h2 className="text-xl font-semibold">{ui.election_title}</h2>
          <span className="text-xs text-zinc-500">
            Auto-discovered from public sources
          </span>
        </div>
        {!races || races.length === 0 ? (
          <p className="text-zinc-500 text-sm border border-dashed border-zinc-800 rounded-lg p-6">
            Election data is being discovered. Run{" "}
            <code className="text-zinc-300">npm run seed</code> or refresh shortly.
          </p>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2">
            {races.map((r) => (
              <div
                key={r.race}
                className="rounded-xl border border-zinc-800 bg-zinc-900/50 p-5"
              >
                <div className="flex items-baseline justify-between mb-3">
                  <h3 className="font-semibold">{r.race}</h3>
                  <span className="text-xs text-zinc-500">{r.election_date}</span>
                </div>
                <ul className="space-y-2">
                  {r.candidates.map((c) => {
                    const p = byId.get(slugify(c.name));
                    return (
                      <li key={c.name} className="flex items-center justify-between">
                        <span className="text-sm">
                          {c.name}{" "}
                          <span className="text-zinc-500">({c.party})</span>
                        </span>
                        {p ? (
                          <Link
                            href={`/p/${p.id}`}
                            className="text-xs text-emerald-400 hover:underline"
                          >
                            {p.stances.length} sourced positions →
                          </Link>
                        ) : (
                          <span className="text-xs text-zinc-600">researching…</span>
                        )}
                      </li>
                    );
                  })}
                </ul>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="grid gap-4 sm:grid-cols-3 text-sm">
        {ui.landing.features.map((f) => (
          <div key={f.title} className="rounded-xl border border-zinc-800 p-4">
            <div className="font-medium mb-1">{f.title}</div>
            <div className="text-zinc-400">{f.description}</div>
          </div>
        ))}
      </section>
    </div>
  );
}
