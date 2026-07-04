import Link from "next/link";
import { notFound } from "next/navigation";
import { getPolitician } from "@/lib/db";
import { getIssueMap, getUI } from "@/lib/config";
import { missingDataNote, profileCoverage } from "@/lib/coverage";
import QABox from "./qa-box";

export const dynamic = "force-dynamic";

export default async function PoliticianPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const p = await getPolitician(id);
  if (!p) notFound();
  const ISSUE_MAP = getIssueMap();
  const ui = getUI();
  const QUAL_LABELS = ui.qualitative_labels;
  const cov = profileCoverage(p);
  const gaps = missingDataNote(cov);

  return (
    <div className="mx-auto max-w-3xl px-4 py-10">
      <div className="mb-8">
        <div className="flex items-baseline gap-3 mb-1">
          <h1 className="text-3xl font-bold">{p.name}</h1>
          {p.party && <span className="text-zinc-400">({p.party})</span>}
        </div>
        <p className="text-sm text-zinc-400">
          {[p.current_office, p.jurisdiction].filter(Boolean).join(" · ")}
        </p>
        {p.bio && <p className="mt-3 text-zinc-300 max-w-2xl">{p.bio}</p>}
        <div className="mt-3 flex gap-4 text-xs text-zinc-500">
          <span>{p.stances.length} sourced positions</span>
          <span>coverage {(p.source_coverage_score * 100).toFixed(0)}% of 30 issues</span>
          <span>researched {new Date(p.researched_at).toLocaleDateString()}</span>
          {p.campaign_website && (
            <a href={p.campaign_website} target="_blank" className="text-emerald-400 hover:underline">
              campaign site ↗
            </a>
          )}
        </div>
      </div>

      {cov.tier !== "full" && (
        <div className="mb-8 rounded-xl border border-dashed border-yellow-500/40 bg-yellow-500/5 p-4">
          <div className="text-sm font-medium text-yellow-300 mb-1">
            {cov.tier === "minimal"
              ? "Limited data — research pending"
              : "Partial data — research in progress"}
          </div>
          <p className="text-xs text-zinc-400">
            {cov.researched
              ? `Our research set has ${cov.stances} sourced position${cov.stances === 1 ? "" : "s"} for this candidate so far.`
              : "Our research swarm hasn't found verifiable, sourced evidence for this candidate yet."}{" "}
            {gaps.length > 0 && <>Not yet in our set: {gaps.join(", ")}.</>}{" "}
            Gaps here reflect our research coverage — not the candidate&apos;s actual record.
          </p>
        </div>
      )}

      {p.qualitative && p.qualitative.length > 0 && (
        <section className="mb-10">
          <h2 className="text-lg font-semibold mb-3">Record quality (qualitative)</h2>
          <div className="grid gap-3 sm:grid-cols-2">
            {p.qualitative.map((q) => (
              <details key={q.id} className="rounded-xl border border-zinc-800 bg-zinc-900/50 p-4">
                <summary className="cursor-pointer list-none">
                  <div className="flex items-center justify-between mb-1">
                    <span className="font-medium">{QUAL_LABELS[q.id] ?? q.id}</span>
                    <span className="font-mono text-lg">{Math.round(q.score * 100)}</span>
                  </div>
                  <p className="text-xs text-zinc-400">{q.summary}</p>
                </summary>
                <div className="mt-3 border-t border-zinc-800 pt-3 space-y-1">
                  {q.sources.map((s) => (
                    <a
                      key={s.source_id}
                      href={s.url}
                      target="_blank"
                      className="block text-xs text-emerald-400 hover:underline"
                    >
                      {s.title} — {s.publisher}
                      {s.published_at ? ` (${s.published_at})` : ""} ↗
                    </a>
                  ))}
                  <p className="text-[10px] text-zinc-600">
                    confidence {Math.round(q.confidence * 100)}%
                  </p>
                </div>
              </details>
            ))}
          </div>
        </section>
      )}

      <section className="mb-10">
        <h2 className="text-lg font-semibold mb-3">Positions ({p.stances.length})</h2>
        {p.stances.length === 0 && (
          <p className="rounded-xl border border-dashed border-zinc-800 bg-zinc-900/30 p-4 text-sm text-zinc-500">
            No sourced positions in our research set yet — research pending. This does
            not mean the candidate has no positions; we haven&apos;t verified any against
            primary sources yet (no source, no claim).
          </p>
        )}
        <div className="space-y-3">
          {p.stances.map((s) => {
            const issue = ISSUE_MAP[s.issue_id];
            return (
              <details
                key={s.stance_id}
                className="rounded-xl border border-zinc-800 bg-zinc-900/50 p-4"
              >
                <summary className="cursor-pointer list-none">
                  <div className="flex items-center justify-between gap-3 mb-1">
                    <span className="text-xs uppercase tracking-wide text-zinc-500">
                      {issue?.name ?? s.issue_id}
                    </span>
                    <span className="text-[10px] rounded-full border border-zinc-700 px-2 py-0.5 text-zinc-400">
                      {s.evidence_type.replace(/_/g, " ")} · conf {Math.round(s.confidence * 100)}%
                    </span>
                  </div>
                  <div className="font-medium">{s.position_label}</div>
                  <p className="text-sm text-zinc-400 mt-1">{s.summary}</p>
                </summary>
                <div className="mt-3 border-t border-zinc-800 pt-3">
                  {issue && s.position_scalar !== null && (
                    <div className="mb-3">
                      <div className="flex justify-between text-[10px] text-zinc-600 mb-1">
                        <span className="max-w-[45%]">{issue.axis0}</span>
                        <span className="max-w-[45%] text-right">{issue.axis1}</span>
                      </div>
                      <div className="relative h-1.5 rounded bg-zinc-800">
                        <div
                          className="absolute -top-[3px] h-3 w-3 rounded-full bg-emerald-400"
                          style={{ left: `calc(${s.position_scalar * 100}% - 6px)` }}
                        />
                      </div>
                    </div>
                  )}
                  <div className="space-y-2">
                    {s.sources.map((src) => (
                      <div key={src.source_id} className="rounded-lg bg-zinc-950 p-3 text-xs">
                        <div className="flex items-center justify-between gap-2">
                          <a href={src.url} target="_blank" className="text-emerald-400 hover:underline">
                            {src.title} ↗
                          </a>
                          <span className="shrink-0 text-zinc-600">
                            {src.primary_source ? "primary" : "secondary"}
                          </span>
                        </div>
                        <div className="text-zinc-500 mt-0.5">
                          {src.publisher}
                          {src.published_at ? ` · ${src.published_at}` : ""}
                        </div>
                        {src.quote && (
                          <blockquote className="mt-1.5 border-l-2 border-zinc-700 pl-2 italic text-zinc-400">
                            “{src.quote}”
                          </blockquote>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              </details>
            );
          })}
        </div>
      </section>

      {p.finance && (p.finance.top_donors.length > 0 || p.finance.total_raised) && (
        <section className="mb-10">
          <h2 className="text-lg font-semibold mb-1">Follow the money</h2>
          <p className="text-xs text-zinc-500 mb-3">
            Who funds this campaign, and where funding lines up with positions.
            Overlaps are correlations in public records — not proof of causation.
          </p>
          {p.finance.total_raised && (
            <p className="text-sm text-zinc-300 mb-3">
              Raised: <b>{p.finance.total_raised}</b>
              {p.finance.cash_on_hand && <> · Cash on hand: <b>{p.finance.cash_on_hand}</b></>}
              {p.finance.as_of && <span className="text-zinc-500"> (as of {p.finance.as_of})</span>}
              {p.finance.overview_source && (
                <a href={p.finance.overview_source.url} target="_blank" className="ml-2 text-xs text-emerald-400 hover:underline">
                  {p.finance.overview_source.publisher} ↗
                </a>
              )}
            </p>
          )}
          {p.finance.top_donors.length > 0 && (
            <div className="grid gap-2 sm:grid-cols-2 mb-4">
              {p.finance.top_donors.map((d, i) => (
                <div key={i} className="rounded-lg border border-zinc-800 bg-zinc-900/50 p-3 text-sm flex items-center justify-between gap-2">
                  <div className="min-w-0">
                    <div className="truncate text-zinc-200">{d.name}</div>
                    <div className="text-[10px] uppercase tracking-wide text-zinc-500">{d.kind}</div>
                  </div>
                  <div className="text-right shrink-0">
                    {d.amount && <div className="font-mono text-xs text-zinc-300">{d.amount}</div>}
                    <a href={d.source.url} target="_blank" className="text-[10px] text-emerald-400 hover:underline">
                      {d.source.publisher} ↗
                    </a>
                  </div>
                </div>
              ))}
            </div>
          )}
          {p.finance.correlations.length > 0 && (
            <div className="space-y-2">
              <h3 className="text-sm font-medium text-zinc-300">Money ↔ positions (correlation, not proof)</h3>
              {p.finance.correlations.map((c, i) => (
                <div key={i} className="rounded-lg border border-yellow-500/20 bg-yellow-500/5 p-3 text-sm">
                  <div className="text-zinc-200">
                    <span className="text-zinc-400">{c.donor}</span> ↔{" "}
                    {ISSUE_MAP[c.issue_id]?.name ?? c.issue_id}: {c.position_or_vote}
                  </div>
                  <p className="mt-1 text-xs text-zinc-500 italic">{c.note}</p>
                  <div className="mt-1 flex flex-wrap gap-2">
                    {c.sources.map((s, j) => (
                      <a key={j} href={s.url} target="_blank" className="text-[11px] text-emerald-400 hover:underline">
                        {s.title.slice(0, 50)} ↗
                      </a>
                    ))}
                    <span className="text-[10px] text-zinc-600">confidence {Math.round(c.confidence * 100)}%</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>
      )}

      {p.promise_record && p.promise_record.length > 0 && (
        <section className="mb-10">
          <h2 className="text-lg font-semibold mb-1">Promise vs. record</h2>
          <p className="text-xs text-zinc-500 mb-3">
            What they said, what they did — with receipts. Ground truth on both sides
            of every verdict.
          </p>
          <div className="space-y-3">
            {p.promise_record.map((r, i) => {
              const style =
                r.verdict === "kept"
                  ? "border-emerald-500/40 text-emerald-300 bg-emerald-500/10"
                  : r.verdict === "broken"
                  ? "border-red-500/40 text-red-300 bg-red-500/10"
                  : r.verdict === "partial"
                  ? "border-yellow-500/40 text-yellow-300 bg-yellow-500/10"
                  : "border-zinc-600 text-zinc-400 bg-zinc-800/40";
              return (
                <details key={i} className="rounded-xl border border-zinc-800 bg-zinc-900/50 p-4">
                  <summary className="cursor-pointer list-none">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="text-sm text-zinc-300">
                          <span className="text-zinc-500">Said:</span> {r.promise}
                        </div>
                        <div className="text-sm text-zinc-300 mt-1">
                          <span className="text-zinc-500">Did:</span> {r.action}
                        </div>
                      </div>
                      <span className={`shrink-0 rounded-full border px-2.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide ${style}`}>
                        {r.verdict}
                      </span>
                    </div>
                  </summary>
                  <div className="mt-3 border-t border-zinc-800 pt-3 text-xs space-y-2">
                    <p className="text-zinc-400">{r.explanation}</p>
                    <div className="grid gap-2 sm:grid-cols-2">
                      <div className="rounded-lg bg-zinc-950 p-3">
                        <div className="text-zinc-500 mb-1">
                          Promise receipt {r.promised_at ? `(${r.promised_at})` : ""}
                        </div>
                        <a href={r.promise_source.url} target="_blank" className="text-emerald-400 hover:underline">
                          {r.promise_source.title} — {r.promise_source.publisher} ↗
                        </a>
                        {r.promise_source.quote && (
                          <blockquote className="mt-1 border-l-2 border-zinc-700 pl-2 italic text-zinc-500">
                            “{r.promise_source.quote}”
                          </blockquote>
                        )}
                      </div>
                      <div className="rounded-lg bg-zinc-950 p-3">
                        <div className="text-zinc-500 mb-1">
                          Action receipts {r.action_at ? `(${r.action_at})` : ""}
                        </div>
                        {r.action_sources.length === 0 ? (
                          <span className="text-zinc-600">none yet (untested)</span>
                        ) : (
                          r.action_sources.map((s) => (
                            <a key={s.source_id} href={s.url} target="_blank" className="block text-emerald-400 hover:underline">
                              {s.title} — {s.publisher} ↗
                            </a>
                          ))
                        )}
                      </div>
                    </div>
                    <p className="text-[10px] text-zinc-600">confidence {Math.round(r.confidence * 100)}%</p>
                  </div>
                </details>
              );
            })}
          </div>
        </section>
      )}

      {p.contradictions.length > 0 && (
        <section className="mb-10">
          <h2 className="text-lg font-semibold mb-3">Contradictions detected</h2>
          <ul className="space-y-2 text-sm text-zinc-300">
            {p.contradictions.map((c, i) => (
              <li key={i} className="rounded-lg border border-yellow-500/30 bg-yellow-500/5 p-3">
                <span className="text-xs uppercase text-yellow-500 mr-2">
                  {ISSUE_MAP[c.issue_id]?.name ?? c.issue_id}
                </span>
                {c.description}
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="mb-10">
        <h2 className="text-lg font-semibold mb-2">No reliable evidence found on</h2>
        <p className="text-sm text-zinc-500">
          {p.unknowns.length === 0
            ? "All 30 issues have sourced evidence."
            : p.unknowns.map((u) => ISSUE_MAP[u]?.name ?? u).join(" · ")}
        </p>
        <p className="mt-1 text-xs text-zinc-600">
          Unknowns are shown honestly — they lower confidence rather than inflate the match.
        </p>
      </section>

      <section>
        <h2 className="text-lg font-semibold mb-3">Ask about {p.name.split(" ")[0]}</h2>
        <p className="text-xs text-zinc-500 mb-3">
          Answers come only from the indexed ground truth above — never from model memory.
        </p>
        <QABox politicianId={p.id} suggested={ui.suggested_questions} />
      </section>

      <div className="mt-10">
        <Link href="/results" className="text-sm text-emerald-400 hover:underline">
          ← Back to your matches
        </Link>
      </div>
    </div>
  );
}
