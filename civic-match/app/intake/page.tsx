"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { CLUSTERS, ISSUES } from "@/lib/issues";
import { savePrefs } from "@/lib/prefs";
import type { VoterProfile } from "@/lib/types";

const MIN_PICKS = 3;
const CLUSTER_LABELS: Record<string, string> = {
  economy: "Economy & Fiscal",
  society: "Society & Services",
  security: "Safety & Security",
  governance: "Government & Technology",
};
const IMPORTANCE = [
  { label: "Somewhat important", mult: 0.6 },
  { label: "Very important", mult: 1.0 },
  { label: "Deal-breaker", mult: 1.5 },
];
const AGE_BRACKETS = ["18-24", "25-34", "35-49", "50-64", "65+"] as const;
const INCOME_BRACKETS = ["<30k", "30-60k", "60-100k", "100-200k", "200k+"] as const;
const FLAG_LABELS: { key: keyof VoterProfile["flags"]; label: string }[] = [
  { key: "homeowner", label: "Homeowner" },
  { key: "renter", label: "Renter" },
  { key: "kids_in_public_school", label: "Kids in public school" },
  { key: "veteran", label: "Veteran" },
  { key: "small_business_owner", label: "Small business owner" },
  { key: "student", label: "Student" },
];
const HEALTHCARE = [
  { key: "employer", label: "Employer insurance" },
  { key: "aca", label: "ACA / marketplace" },
  { key: "medicare", label: "Medicare / Medicaid" },
  { key: "uninsured", label: "Uninsured" },
] as const;

export default function IntakePage() {
  const router = useRouter();
  const [step, setStep] = useState<"profile" | "pick" | "tradeoffs">("profile");
  const [profile, setProfile] = useState<VoterProfile>({ flags: {} });
  const [zip, setZip] = useState("");
  const [picked, setPicked] = useState<string[]>([]);
  const [positions, setPositions] = useState<Record<string, number | null>>({});
  const [importance, setImportance] = useState<Record<string, number>>({});
  const [idx, setIdx] = useState(0);
  const [pendingScalar, setPendingScalar] = useState<number | null | undefined>(undefined);

  const toggle = (id: string) =>
    setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]));

  const selectAll = () => setPicked(ISSUES.map((i) => i.id));
  const clearAll = () => setPicked([]);

  const currentIssue = useMemo(
    () => (step === "tradeoffs" ? ISSUES.find((i) => i.id === picked[idx]) : undefined),
    [step, picked, idx]
  );

  const finish = (
    finalPositions: Record<string, number | null>,
    finalImportance: Record<string, number>
  ) => {
    // Weight = rank order × importance intensity.
    const weights: Record<string, number> = {};
    picked.forEach((id, i) => {
      const rankWeight = (picked.length - i) / picked.length;
      weights[id] = rankWeight * (finalImportance[id] ?? 1.0);
    });
    savePrefs({
      zip: zip || undefined,
      profile,
      priority_weights: weights,
      issue_positions: finalPositions,
    });
    router.push("/results");
  };

  const submitIssue = (imp: number) => {
    const issueId = picked[idx];
    const nextPositions = { ...positions, [issueId]: pendingScalar ?? null };
    const nextImportance = { ...importance, [issueId]: imp };
    setPositions(nextPositions);
    setImportance(nextImportance);
    setPendingScalar(undefined);
    if (idx + 1 < picked.length) setIdx(idx + 1);
    else finish(nextPositions, nextImportance);
  };

  if (step === "profile") {
    const setFlag = (key: keyof VoterProfile["flags"], value: boolean) =>
      setProfile((p) => ({ ...p, flags: { ...p.flags, [key]: value || undefined } }));
    return (
      <div className="mx-auto max-w-2xl px-4 py-10">
        <h1 className="text-2xl font-bold mb-1">A little about you</h1>
        <p className="text-zinc-400 text-sm mb-6">
          All optional. This stays in your browser and is only used to explain what
          candidates&apos; positions mean <em>for your situation</em> — never to
          target or persuade you.
        </p>

        <div className="space-y-5">
          <div className="grid grid-cols-2 gap-3">
            <label className="block">
              <span className="text-xs text-zinc-500">First name (optional)</span>
              <input
                value={profile.name ?? ""}
                onChange={(e) => setProfile((p) => ({ ...p, name: e.target.value || undefined }))}
                placeholder="e.g. Sam"
                className="mt-1 w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm outline-none focus:border-emerald-400/60"
              />
            </label>
            <label className="block">
              <span className="text-xs text-zinc-500">ZIP code (optional)</span>
              <input
                value={zip}
                onChange={(e) => setZip(e.target.value.replace(/\D/g, "").slice(0, 5))}
                placeholder="78666"
                className="mt-1 w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm outline-none focus:border-emerald-400/60"
              />
            </label>
          </div>

          <label className="block">
            <span className="text-xs text-zinc-500">Occupation (optional)</span>
            <input
              value={profile.occupation ?? ""}
              onChange={(e) => setProfile((p) => ({ ...p, occupation: e.target.value || undefined }))}
              placeholder="e.g. nurse, teacher, software engineer, rancher"
              className="mt-1 w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm outline-none focus:border-emerald-400/60"
            />
          </label>

          <div>
            <span className="text-xs text-zinc-500">Age</span>
            <div className="mt-1 flex flex-wrap gap-2">
              {AGE_BRACKETS.map((a) => (
                <button
                  key={a}
                  onClick={() => setProfile((p) => ({ ...p, age_bracket: p.age_bracket === a ? undefined : a }))}
                  className={`rounded-full border px-3 py-1.5 text-sm ${
                    profile.age_bracket === a
                      ? "border-emerald-400 bg-emerald-500/15 text-emerald-300"
                      : "border-zinc-700 text-zinc-400 hover:border-zinc-500"
                  }`}
                >
                  {a}
                </button>
              ))}
            </div>
          </div>

          <div>
            <span className="text-xs text-zinc-500">Household income</span>
            <div className="mt-1 flex flex-wrap gap-2">
              {INCOME_BRACKETS.map((b) => (
                <button
                  key={b}
                  onClick={() => setProfile((p) => ({ ...p, income_bracket: p.income_bracket === b ? undefined : b }))}
                  className={`rounded-full border px-3 py-1.5 text-sm ${
                    profile.income_bracket === b
                      ? "border-emerald-400 bg-emerald-500/15 text-emerald-300"
                      : "border-zinc-700 text-zinc-400 hover:border-zinc-500"
                  }`}
                >
                  {b}
                </button>
              ))}
            </div>
          </div>

          <div>
            <span className="text-xs text-zinc-500">Applies to you</span>
            <div className="mt-1 flex flex-wrap gap-2">
              {FLAG_LABELS.map((f) => (
                <button
                  key={f.key}
                  onClick={() => setFlag(f.key, !profile.flags[f.key])}
                  className={`rounded-full border px-3 py-1.5 text-sm ${
                    profile.flags[f.key]
                      ? "border-emerald-400 bg-emerald-500/15 text-emerald-300"
                      : "border-zinc-700 text-zinc-400 hover:border-zinc-500"
                  }`}
                >
                  {f.label}
                </button>
              ))}
            </div>
          </div>

          <div>
            <span className="text-xs text-zinc-500">Health coverage</span>
            <div className="mt-1 flex flex-wrap gap-2">
              {HEALTHCARE.map((h) => (
                <button
                  key={h.key}
                  onClick={() =>
                    setProfile((p) => ({
                      ...p,
                      flags: { ...p.flags, healthcare: p.flags.healthcare === h.key ? undefined : h.key },
                    }))
                  }
                  className={`rounded-full border px-3 py-1.5 text-sm ${
                    profile.flags.healthcare === h.key
                      ? "border-emerald-400 bg-emerald-500/15 text-emerald-300"
                      : "border-zinc-700 text-zinc-400 hover:border-zinc-500"
                  }`}
                >
                  {h.label}
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className="mt-8 flex items-center gap-4">
          <button
            onClick={() => setStep("pick")}
            className="rounded-lg bg-emerald-500 px-6 py-2.5 font-medium text-zinc-950 hover:bg-emerald-400"
          >
            Next: your issues
          </button>
          <button onClick={() => setStep("pick")} className="text-sm text-zinc-500 hover:text-zinc-300">
            Skip
          </button>
        </div>
      </div>
    );
  }

  if (step === "pick") {
    return (
      <div className="mx-auto max-w-3xl px-4 py-10">
        <h1 className="text-2xl font-bold mb-1">What matters most to you?</h1>
        <p className="text-zinc-400 text-sm mb-4">
          Pick at least {MIN_PICKS} issues — as many as you want, most important
          first. Order sets the base weight; you&apos;ll refine each one next.
        </p>
        <div className="flex gap-2 mb-6 text-xs">
          <button onClick={selectAll} className="rounded border border-zinc-700 px-3 py-1.5 text-zinc-300 hover:border-zinc-500">
            Select all 30
          </button>
          <button onClick={clearAll} className="rounded border border-zinc-800 px-3 py-1.5 text-zinc-500 hover:border-zinc-600">
            Clear
          </button>
        </div>

        {Object.entries(CLUSTERS).map(([cluster, ids]) => (
          <div key={cluster} className="mb-6">
            <h2 className="text-xs uppercase tracking-wider text-zinc-500 mb-2">
              {CLUSTER_LABELS[cluster] ?? cluster}
            </h2>
            <div className="flex flex-wrap gap-2">
              {ids.map((id) => {
                const issue = ISSUES.find((i) => i.id === id)!;
                const pos = picked.indexOf(id);
                const selected = pos !== -1;
                return (
                  <button
                    key={id}
                    onClick={() => toggle(id)}
                    title={issue.voterQuestion}
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
          </div>
        ))}

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
          Question {idx + 1} of {picked.length} · your priority #{idx + 1}
        </div>
        <div className="h-1 rounded bg-zinc-800">
          <div
            className="h-1 rounded bg-emerald-400 transition-all"
            style={{ width: `${(idx / picked.length) * 100}%` }}
          />
        </div>
      </div>

      <h1 className="text-xl font-bold mb-1">{currentIssue.name}</h1>
      <p className="text-zinc-500 text-sm mb-1">{currentIssue.voterQuestion}</p>
      <p className="text-zinc-300 mb-5">{currentIssue.tradeoffQuestion}</p>

      <div className="space-y-3 mb-6">
        {currentIssue.options.map((o) => (
          <button
            key={o.key}
            onClick={() => setPendingScalar(o.scalar)}
            className={`w-full rounded-xl border px-5 py-4 text-left transition ${
              pendingScalar === o.scalar
                ? "border-emerald-400 bg-emerald-500/10"
                : "border-zinc-700 bg-zinc-900/50 hover:border-zinc-500"
            }`}
          >
            <span className="mr-3 font-mono text-emerald-400">{o.key}.</span>
            {o.label}
          </button>
        ))}
        <button
          onClick={() => setPendingScalar(null)}
          className={`w-full rounded-xl border border-dashed px-5 py-3 text-left text-sm transition ${
            pendingScalar === null
              ? "border-emerald-400/60 text-emerald-300"
              : "border-zinc-800 text-zinc-500 hover:border-zinc-600"
          }`}
        >
          Not sure / don&apos;t use this answer in my match score
        </button>
      </div>

      <div className={pendingScalar === undefined ? "opacity-40 pointer-events-none" : ""}>
        <p className="text-sm text-zinc-400 mb-2">How important is this to your vote?</p>
        <div className="grid grid-cols-3 gap-2">
          {IMPORTANCE.map((im) => (
            <button
              key={im.label}
              onClick={() => submitIssue(im.mult)}
              className="rounded-lg border border-zinc-700 px-3 py-2.5 text-sm hover:border-emerald-400/60 hover:bg-zinc-900"
            >
              {im.label}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
