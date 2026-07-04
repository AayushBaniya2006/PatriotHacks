import Link from "next/link";
import { notFound } from "next/navigation";
import { getPolitician } from "@/lib/db";
import { getIssueMap, getUI } from "@/lib/config";
import { CivitasPage, CivitasPanel, SourceLink, StatusPill } from "@/components/civitas-ui";
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

  return (
    <CivitasPage
      eyebrow="Candidate record"
      title={
        <>
          {p.name} {p.party && <span className="text-gold">({p.party})</span>}
        </>
      }
      description={[p.current_office, p.jurisdiction].filter(Boolean).join(" · ")}
    >
      <div className="mb-8">
        {p.bio && <p className="max-w-2xl text-base leading-7 text-white/70">{p.bio}</p>}
        <div className="mt-4 flex flex-wrap gap-3 text-xs text-white/45">
          <StatusPill tone="gold">{p.stances.length} sourced positions</StatusPill>
          <StatusPill>coverage {(p.source_coverage_score * 100).toFixed(0)}% of 30 issues</StatusPill>
          <StatusPill>researched {new Date(p.researched_at).toLocaleDateString()}</StatusPill>
          {p.campaign_website && (
            <SourceLink href={p.campaign_website}>
              campaign site
            </SourceLink>
          )}
        </div>
      </div>
      {p.qualitative && p.qualitative.length > 0 && (
        <section className="mb-10">
          <h2 className="mb-3 font-serif text-2xl font-normal text-white">Record quality (qualitative)</h2>
          <div className="grid gap-3 sm:grid-cols-2">
            {p.qualitative.map((q) => (
              <CivitasPanel key={q.id} as="details" className="p-4">
                <summary className="cursor-pointer list-none">
                  <div className="flex items-center justify-between mb-1">
                    <span className="font-medium text-white/82">{QUAL_LABELS[q.id] ?? q.id}</span>
                    <span className="font-mono text-lg text-gold">{Math.round(q.score * 100)}</span>
                  </div>
                  <p className="text-xs leading-5 text-white/55">{q.summary}</p>
                </summary>
                <div className="mt-3 space-y-1 border-t border-white/10 pt-3">
                  {q.sources.map((s) => (
                    <SourceLink
                      key={s.source_id}
                      href={s.url}
                      className="block text-xs"
                    >
                      {s.title} — {s.publisher}
                      {s.published_at ? ` (${s.published_at})` : ""}
                    </SourceLink>
                  ))}
                  <p className="text-[10px] text-white/35">
                    confidence {Math.round(q.confidence * 100)}%
                  </p>
                </div>
              </CivitasPanel>
            ))}
          </div>
        </section>
      )}

      <section className="mb-10">
        <h2 className="mb-3 font-serif text-2xl font-normal text-white">Positions ({p.stances.length})</h2>
        <div className="space-y-3">
          {p.stances.map((s) => {
            const issue = ISSUE_MAP[s.issue_id];
            return (
              <CivitasPanel
                key={s.stance_id}
                as="details"
                className="p-4"
              >
                <summary className="cursor-pointer list-none">
                  <div className="flex items-center justify-between gap-3 mb-1">
                    <span className="text-xs font-semibold uppercase tracking-[0.18em] text-gold/80">
                      {issue?.name ?? s.issue_id}
                    </span>
                    <StatusPill>
                      {s.evidence_type.replace(/_/g, " ")} · conf {Math.round(s.confidence * 100)}%
                    </StatusPill>
                  </div>
                  <div className="font-medium text-white/86">{s.position_label}</div>
                  <p className="mt-1 text-sm leading-6 text-white/55">{s.summary}</p>
                </summary>
                <div className="mt-3 border-t border-white/10 pt-3">
                  {issue && s.position_scalar !== null && (
                    <div className="mb-3">
                      <div className="mb-1 flex justify-between text-[10px] text-white/35">
                        <span className="max-w-[45%]">{issue.axis0}</span>
                        <span className="max-w-[45%] text-right">{issue.axis1}</span>
                      </div>
                      <div className="relative h-1.5 rounded bg-white/10">
                        <div
                          className="absolute -top-[3px] h-3 w-3 rounded-full bg-gold"
                          style={{ left: `calc(${s.position_scalar * 100}% - 6px)` }}
                        />
                      </div>
                    </div>
                  )}
                  <div className="space-y-2">
                    {s.sources.map((src) => (
                      <div key={src.source_id} className="rounded-[8px] border border-white/10 bg-navy-dark/60 p-3 text-xs">
                        <div className="flex items-center justify-between gap-2">
                          <SourceLink href={src.url}>{src.title}</SourceLink>
                          <span className="shrink-0 text-white/35">
                            {src.primary_source ? "primary" : "secondary"}
                          </span>
                        </div>
                        <div className="mt-0.5 text-white/42">
                          {src.publisher}
                          {src.published_at ? ` · ${src.published_at}` : ""}
                        </div>
                        {src.quote && (
                          <blockquote className="mt-1.5 border-l-2 border-gold/35 pl-2 italic text-white/55">
                            “{src.quote}”
                          </blockquote>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              </CivitasPanel>
            );
          })}
        </div>
      </section>

      {p.finance && (p.finance.top_donors.length > 0 || p.finance.total_raised) && (
        <section className="mb-10">
          <h2 className="mb-1 font-serif text-2xl font-normal text-white">Follow the money</h2>
          <p className="mb-3 text-xs leading-5 text-white/45">
            Who funds this campaign, and where funding lines up with positions.
            Overlaps are correlations in public records — not proof of causation.
          </p>
          {p.finance.total_raised && (
            <p className="mb-3 text-sm text-white/72">
              Raised: <b>{p.finance.total_raised}</b>
              {p.finance.cash_on_hand && <> · Cash on hand: <b>{p.finance.cash_on_hand}</b></>}
              {p.finance.as_of && <span className="text-white/42"> (as of {p.finance.as_of})</span>}
              {p.finance.overview_source && (
                <SourceLink href={p.finance.overview_source.url} className="ml-2 text-xs">
                  {p.finance.overview_source.publisher}
                </SourceLink>
              )}
            </p>
          )}
          {p.finance.top_donors.length > 0 && (
            <div className="grid gap-2 sm:grid-cols-2 mb-4">
              {p.finance.top_donors.map((d, i) => (
                <CivitasPanel key={i} className="flex items-center justify-between gap-2 p-3 text-sm">
                  <div className="min-w-0">
                    <div className="truncate text-white/82">{d.name}</div>
                    <div className="text-[10px] uppercase tracking-[0.16em] text-white/42">{d.kind}</div>
                  </div>
                  <div className="text-right shrink-0">
                    {d.amount && <div className="font-mono text-xs text-white/72">{d.amount}</div>}
                    <SourceLink href={d.source.url} className="text-[10px]">
                      {d.source.publisher}
                    </SourceLink>
                  </div>
                </CivitasPanel>
              ))}
            </div>
          )}
          {p.finance.correlations.length > 0 && (
            <div className="space-y-2">
              <h3 className="text-sm font-medium text-white/72">Money and positions (correlation, not proof)</h3>
              {p.finance.correlations.map((c, i) => (
                <CivitasPanel key={i} className="p-3 text-sm">
                  <div className="text-white/78">
                    <span className="text-white/52">{c.donor}</span>:{" "}
                    {ISSUE_MAP[c.issue_id]?.name ?? c.issue_id}: {c.position_or_vote}
                  </div>
                  <p className="mt-1 text-xs italic text-white/45">{c.note}</p>
                  <div className="mt-1 flex flex-wrap gap-2">
                    {c.sources.map((s, j) => (
                      <SourceLink key={j} href={s.url} className="text-[11px]">
                        {s.title.slice(0, 50)}
                      </SourceLink>
                    ))}
                    <span className="text-[10px] text-white/35">confidence {Math.round(c.confidence * 100)}%</span>
                  </div>
                </CivitasPanel>
              ))}
            </div>
          )}
        </section>
      )}

      {p.promise_record && p.promise_record.length > 0 && (
        <section className="mb-10">
          <h2 className="mb-1 font-serif text-2xl font-normal text-white">Promise vs. record</h2>
          <p className="mb-3 text-xs leading-5 text-white/45">
            What they said, what they did — with receipts. Ground truth on both sides
            of every verdict.
          </p>
          <div className="space-y-3">
            {p.promise_record.map((r, i) => {
              const tone = r.verdict === "broken" ? "red" : r.verdict === "kept" || r.verdict === "partial" ? "gold" : "neutral";
              return (
                <CivitasPanel key={i} as="details" className="p-4">
                  <summary className="cursor-pointer list-none">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="text-sm text-white/72">
                          <span className="text-white/42">Said:</span> {r.promise}
                        </div>
                        <div className="mt-1 text-sm text-white/72">
                          <span className="text-white/42">Did:</span> {r.action}
                        </div>
                      </div>
                      <StatusPill tone={tone}>{r.verdict}</StatusPill>
                    </div>
                  </summary>
                  <div className="mt-3 space-y-2 border-t border-white/10 pt-3 text-xs">
                    <p className="text-white/62">{r.explanation}</p>
                    <div className="grid gap-2 sm:grid-cols-2">
                      <div className="rounded-[8px] border border-white/10 bg-navy-dark/60 p-3">
                        <div className="mb-1 text-white/42">
                          Promise receipt {r.promised_at ? `(${r.promised_at})` : ""}
                        </div>
                        <SourceLink href={r.promise_source.url}>
                          {r.promise_source.title} — {r.promise_source.publisher}
                        </SourceLink>
                        {r.promise_source.quote && (
                          <blockquote className="mt-1 border-l-2 border-gold/35 pl-2 italic text-white/45">
                            “{r.promise_source.quote}”
                          </blockquote>
                        )}
                      </div>
                      <div className="rounded-[8px] border border-white/10 bg-navy-dark/60 p-3">
                        <div className="mb-1 text-white/42">
                          Action receipts {r.action_at ? `(${r.action_at})` : ""}
                        </div>
                        {r.action_sources.length === 0 ? (
                          <span className="text-white/35">none yet (untested)</span>
                        ) : (
                          r.action_sources.map((s) => (
                            <SourceLink key={s.source_id} href={s.url} className="block">
                              {s.title} — {s.publisher}
                            </SourceLink>
                          ))
                        )}
                      </div>
                    </div>
                    <p className="text-[10px] text-white/35">confidence {Math.round(r.confidence * 100)}%</p>
                  </div>
                </CivitasPanel>
              );
            })}
          </div>
        </section>
      )}

      {p.contradictions.length > 0 && (
        <section className="mb-10">
          <h2 className="mb-3 font-serif text-2xl font-normal text-white">Contradictions detected</h2>
          <ul className="space-y-2 text-sm text-white/72">
            {p.contradictions.map((c, i) => (
              <li key={i} className="rounded-[8px] border border-gold/30 bg-gold/10 p-3">
                <span className="mr-2 text-xs uppercase text-gold">
                  {ISSUE_MAP[c.issue_id]?.name ?? c.issue_id}
                </span>
                {c.description}
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="mb-10">
        <h2 className="mb-2 font-serif text-2xl font-normal text-white">No reliable evidence found on</h2>
        <p className="text-sm text-white/52">
          {p.unknowns.length === 0
            ? "All 30 issues have sourced evidence."
            : p.unknowns.map((u) => ISSUE_MAP[u]?.name ?? u).join(" · ")}
        </p>
        <p className="mt-1 text-xs text-white/35">
          Unknowns are shown honestly — they lower confidence rather than inflate the match.
        </p>
      </section>

      <section>
        <h2 className="mb-3 font-serif text-2xl font-normal text-white">Ask about {p.name.split(" ")[0]}</h2>
        <p className="mb-3 text-xs text-white/45">
          Answers come only from the indexed ground truth above — never from model memory.
        </p>
        <QABox politicianId={p.id} suggested={ui.suggested_questions} />
      </section>

      <div className="mt-10">
        <Link href="/results" className="text-sm font-semibold uppercase tracking-[0.16em] text-gold hover:text-white">
          Back to your matches
        </Link>
      </div>
    </CivitasPage>
  );
}
