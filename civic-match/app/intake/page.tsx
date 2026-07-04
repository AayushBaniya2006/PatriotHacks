"use client";

import { useEffect, useMemo, useState, use } from "react";
import { useRouter } from "next/navigation";
import { loadPrefs, savePrefs } from "@/lib/prefs";
import type { VoterProfile } from "@/lib/types";
import type { IssueDef } from "@/lib/issues";
import type { UIConfig } from "@/lib/config";
import { getIssueExplainer, type IssueExplainerPole } from "@/lib/issueExplainers";
import {
  CivitasButton,
  CivitasNotice,
  CivitasPage,
  CivitasPanel,
  CivitasProgressPanel,
  CivitasSectionHeading,
  CivitasSelectableChip,
  CivitasTextField,
} from "@/components/civitas-ui";

const intakeSteps = [
  {
    id: "profile",
    label: "Profile",
    detail: "Optional context, stored in your browser.",
  },
  {
    id: "pick",
    label: "Priorities",
    detail: "Choose the issues that should drive scoring.",
  },
  {
    id: "tradeoffs",
    label: "Trade-offs",
    detail: "Set stance and importance issue by issue.",
  },
];

export default function IntakePage({
  searchParams,
}: {
  // Additive, opt-in projector/presentation mode: ?present=1 applies a
  // `.present-mode` wrapper class (styled in globals.css) that scales root
  // text ~115% and bumps key line-heights. Absent, or any value other than
  // "1", leaves presentMode false and every CivitasPage className below
  // byte-identical to before this prop existed.
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const presentMode = use(searchParams)?.present === "1";
  const router = useRouter();
  const [issues, setIssues] = useState<IssueDef[] | null>(null);
  const [ui, setUI] = useState<UIConfig | null>(null);
  useEffect(() => {
    fetch("/api/config")
      .then((r) => r.json())
      .then((c) => {
        setIssues(c.issues);
        setUI(c.ui);
      });
  }, []);
  const [step, setStep] = useState<"profile" | "pick" | "tradeoffs">("profile");
  const [profile, setProfile] = useState<VoterProfile>({ flags: {} });
  const [zip, setZip] = useState("");
  const [address, setAddress] = useState("");
  const [picked, setPicked] = useState<string[]>([]);
  const [positions, setPositions] = useState<Record<string, number | null>>({});
  const [importance, setImportance] = useState<Record<string, number>>({});
  const [idx, setIdx] = useState(0);
  const [pendingScalar, setPendingScalar] = useState<number | null | undefined>(undefined);

  // Rehydrate a previously-saved profile/priorities so re-entering intake
  // (e.g. from "Edit priorities") doesn't wipe everything the voter entered.
  useEffect(() => {
    const saved = loadPrefs();
    if (!saved) return;
    if (saved.profile) setProfile({ ...saved.profile, flags: saved.profile.flags ?? {} });
    if (saved.zip) setZip(saved.zip);
    if (saved.address) setAddress(saved.address);
    if (saved.issue_positions) setPositions(saved.issue_positions);
    const savedPicked = Object.keys(saved.priority_weights ?? {});
    if (savedPicked.length) setPicked(savedPicked);
  }, []);

  const toggle = (id: string) =>
    setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]));

  const selectAll = () => setPicked((issues ?? []).map((i) => i.id));
  const clearAll = () => setPicked([]);

  const currentIssue = useMemo(
    () => (step === "tradeoffs" ? issues?.find((i) => i.id === picked[idx]) : undefined),
    [step, picked, idx, issues]
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
      address: address.trim() || undefined,
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

  if (!ui || !issues) {
    return (
      <CivitasPage eyebrow="Priorities" title="Loading your ballot intake" className={presentMode ? "present-mode" : undefined}>
        <CivitasNotice className="animate-pulse">Loading issue configuration...</CivitasNotice>
      </CivitasPage>
    );
  }

  const MIN_PICKS = ui.intake.min_picks;
  const clusters = issues.reduce((acc, i) => {
    (acc[i.cluster] ||= []).push(i.id);
    return acc;
  }, {} as Record<string, string[]>);

  if (step === "profile") {
    const setFlag = (key: keyof VoterProfile["flags"], value: boolean) =>
      setProfile((p) => ({ ...p, flags: { ...p.flags, [key]: value || undefined } }));
    return (
      <CivitasPage
        eyebrow="Voter profile"
        title="A little about you"
        className={presentMode ? "present-mode" : undefined}
        description={
          <>
          All optional. This stays in your browser and is only used to explain what
          candidates&apos; positions mean <em>for your situation</em> — never to
          target or persuade you.
          </>
        }
      >
        <div className="grid gap-6 lg:grid-cols-[280px_minmax(0,1fr)]">
          <CivitasProgressPanel steps={intakeSteps} currentStep={step} />
          <CivitasPanel className="p-5 sm:p-6">
            <CivitasSectionHeading
              eyebrow="Local context"
              title="Make the explanation fit your life"
              description="Skip anything you do not want used. Empty fields never count against a candidate."
            />

        <div className="space-y-5">
          <div className="grid grid-cols-2 gap-3">
            <CivitasTextField
              label="First name (optional)"
              value={profile.name ?? ""}
              onChange={(e) => setProfile((p) => ({ ...p, name: e.target.value || undefined }))}
              placeholder="e.g. Sam"
            />
            <CivitasTextField
              label="ZIP code (optional)"
              value={zip}
              onChange={(e) => setZip(e.target.value.replace(/\D/g, "").slice(0, 5))}
              placeholder="78666"
              inputMode="numeric"
            />
          </div>

          <CivitasTextField
            label="Street address"
            helper="Optional, but required for the real ballot section: races, districts, candidates, and sourced info."
            value={address}
            onChange={(e) => setAddress(e.target.value)}
            placeholder="e.g. 601 University Dr, San Marcos, TX 78666"
          />

          <CivitasTextField
            label="Occupation (optional)"
            value={profile.occupation ?? ""}
            onChange={(e) => setProfile((p) => ({ ...p, occupation: e.target.value || undefined }))}
            placeholder="e.g. nurse, teacher, software engineer, rancher"
          />

          <div>
            <span className="text-xs font-semibold uppercase tracking-[0.16em] text-white/50">Age</span>
            <div className="mt-1 flex flex-wrap gap-2">
              {(ui.intake.age_brackets as VoterProfile["age_bracket"][]).map((a) => a && (
                <CivitasSelectableChip
                  key={a}
                  selected={profile.age_bracket === a}
                  onClick={() => setProfile((p) => ({ ...p, age_bracket: p.age_bracket === a ? undefined : a }))}
                >
                  {a}
                </CivitasSelectableChip>
              ))}
            </div>
          </div>

          <div>
            <span className="text-xs font-semibold uppercase tracking-[0.16em] text-white/50">Household income</span>
            <div className="mt-1 flex flex-wrap gap-2">
              {(ui.intake.income_brackets as VoterProfile["income_bracket"][]).map((b) => b && (
                <CivitasSelectableChip
                  key={b}
                  selected={profile.income_bracket === b}
                  onClick={() => setProfile((p) => ({ ...p, income_bracket: p.income_bracket === b ? undefined : b }))}
                >
                  {b}
                </CivitasSelectableChip>
              ))}
            </div>
          </div>

          <div>
            <span className="text-xs font-semibold uppercase tracking-[0.16em] text-white/50">Applies to you</span>
            <div className="mt-1 flex flex-wrap gap-2">
              {(ui.intake.flag_labels as { key: keyof VoterProfile["flags"]; label: string }[]).map((f) => (
                <CivitasSelectableChip
                  key={f.key}
                  selected={Boolean(profile.flags[f.key])}
                  onClick={() => setFlag(f.key, !profile.flags[f.key])}
                >
                  {f.label}
                </CivitasSelectableChip>
              ))}
            </div>
          </div>

          <div>
            <span className="text-xs font-semibold uppercase tracking-[0.16em] text-white/50">Health coverage</span>
            <div className="mt-1 flex flex-wrap gap-2">
              {(ui.intake.healthcare_options as { key: NonNullable<VoterProfile["flags"]["healthcare"]>; label: string }[]).map((h) => (
                <CivitasSelectableChip
                  key={h.key}
                  selected={profile.flags.healthcare === h.key}
                  onClick={() =>
                    setProfile((p) => ({
                      ...p,
                      flags: { ...p.flags, healthcare: p.flags.healthcare === h.key ? undefined : h.key },
                    }))
                  }
                >
                  {h.label}
                </CivitasSelectableChip>
              ))}
            </div>
          </div>
        </div>

        <div className="mt-8 flex items-center gap-4">
          <CivitasButton onClick={() => setStep("pick")}>
            Next: your issues
          </CivitasButton>
          <button onClick={() => setStep("pick")} className="py-3 sm:py-0 text-sm text-white/45 hover:text-white">
            Skip
          </button>
        </div>
          </CivitasPanel>
        </div>
      </CivitasPage>
    );
  }

  if (step === "pick") {
    return (
      <CivitasPage
        eyebrow="Priorities"
        title="What matters most to you?"
        className={presentMode ? "present-mode" : undefined}
        description={
          <>
          Pick at least {MIN_PICKS} issues — as many as you want, most important
          first. Order sets the base weight; you&apos;ll refine each one next.
          </>
        }
      >
        <div className="grid gap-6 lg:grid-cols-[280px_minmax(0,1fr)]">
          <CivitasProgressPanel steps={intakeSteps} currentStep={step} />
          <div>
            <CivitasPanel className="mb-6 flex flex-col gap-4 p-4 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <p className="text-sm font-medium text-white">{picked.length} issues selected</p>
                <p className="mt-1 text-xs text-white/45">
                  Selected order becomes the first scoring weight before importance is applied.
                </p>
              </div>
              <div className="flex gap-2 text-xs">
                <button onClick={selectAll} className="rounded-[6px] border border-gold/35 px-3 py-3.5 sm:py-1.5 text-gold hover:border-gold hover:bg-gold/10">
                  Select all 30
                </button>
                <button onClick={clearAll} className="rounded-[6px] border border-white/12 px-3 py-3.5 sm:py-1.5 text-white/45 hover:border-white/25 hover:text-white">
                  Clear
                </button>
              </div>
            </CivitasPanel>

        {Object.entries(clusters).map(([cluster, ids]) => (
          <CivitasPanel key={cluster} className="mb-5 p-4">
            <h2 className="mb-2 text-xs font-semibold uppercase tracking-[0.2em] text-gold/80">
              {ui.intake.cluster_labels[cluster] ?? cluster}
            </h2>
            <div className="flex flex-wrap gap-2">
              {ids.map((id) => {
                const issue = issues.find((i) => i.id === id)!;
                const pos = picked.indexOf(id);
                const selected = pos !== -1;
                return (
                  <CivitasSelectableChip
                    key={id}
                    onClick={() => toggle(id)}
                    title={issue.voterQuestion}
                    selected={selected}
                    rank={selected ? pos + 1 : undefined}
                  >
                    {issue.name}
                  </CivitasSelectableChip>
                );
              })}
            </div>
          </CivitasPanel>
        ))}

        <CivitasButton
          disabled={picked.length < MIN_PICKS}
          onClick={() => setStep("tradeoffs")}
        >
          Next: trade-offs ({picked.length} picked)
        </CivitasButton>
          </div>
        </div>
      </CivitasPage>
    );
  }

  if (!currentIssue) return null;

  return (
    <CivitasPage eyebrow="Trade-offs" title={currentIssue.name} className={presentMode ? "present-mode" : undefined}>
      <div className="grid gap-6 lg:grid-cols-[280px_minmax(0,1fr)]">
        <CivitasProgressPanel steps={intakeSteps} currentStep={step} />
        <CivitasPanel className="p-5 sm:p-6">
      <div className="mb-6">
        <div className="mb-2 text-xs font-semibold uppercase tracking-[0.18em] text-white/45">
          Question {idx + 1} of {picked.length} · your priority #{idx + 1}
        </div>
        <div className="h-1 rounded bg-white/12">
          <div
            className="h-1 rounded bg-gold transition-all"
            style={{ width: `${((idx + 1) / picked.length) * 100}%` }}
          />
        </div>
      </div>

      <p className="mb-1 text-sm text-white/45">{currentIssue.voterQuestion}</p>
      <p className="mb-5 text-white/72">{currentIssue.tradeoffQuestion}</p>

      <IssueImpactExplainer issueId={currentIssue.id} />

      <div className="space-y-3 mb-6">
        {currentIssue.options.map((o) => (
          <button
            key={o.key}
            onClick={() => setPendingScalar(o.scalar)}
            className={`w-full rounded-[10px] border px-5 py-4 text-left transition ${
              pendingScalar === o.scalar
                ? "border-gold bg-gold/10 text-white"
                : "border-white/14 bg-white/[0.035] text-white/72 hover:border-gold/45"
            }`}
          >
            <span className="mr-3 font-mono text-gold">{o.key}.</span>
            {o.label}
          </button>
        ))}
        <button
          onClick={() => setPendingScalar(null)}
          className={`w-full rounded-[10px] border border-dashed px-5 py-3 text-left text-sm transition ${
            pendingScalar === null
              ? "border-gold/60 text-gold"
              : "border-white/12 text-white/45 hover:border-white/25"
          }`}
        >
          Not sure / don&apos;t use this answer in my match score
        </button>
      </div>

      <div className={pendingScalar === undefined ? "opacity-40 pointer-events-none" : ""}>
        <p className="mb-2 text-sm text-white/62">How important is this to your vote?</p>
        <div className="grid grid-cols-3 gap-2">
          {ui.intake.importance_levels.map((im) => (
            <button
              key={im.label}
              onClick={() => submitIssue(im.mult)}
              className="rounded-[8px] border border-white/14 px-3 py-3 sm:py-2.5 text-sm text-white/72 hover:border-gold/60 hover:bg-gold/10"
            >
              {im.label}
            </button>
          ))}
        </div>
      </div>
        </CivitasPanel>
      </div>
    </CivitasPage>
  );
}

// Neutral, both-sides "how does this affect me?" read for the issue currently
// on screen. Purely additive/informational — it never reads or writes
// pendingScalar or any position-selection state above. Renders nothing when
// the issue has no explainer entry (data/config/issue_explainers.json).
function IssueImpactExplainer({ issueId }: { issueId: string }) {
  const explainer = getIssueExplainer(issueId);
  if (!explainer) return null;
  return (
    <CivitasPanel as="details" className="mb-5 p-4">
      <summary className="cursor-pointer py-3.5 sm:py-0 text-xs font-semibold uppercase tracking-[0.18em] text-gold/85">
        How does this affect me?
      </summary>
      <div className="mt-3 space-y-4 border-t border-white/10 pt-3">
        <p className="text-sm leading-6 text-white/72">{explainer.plain_summary}</p>
        {/* Same component, same classes, only the data differs — pole_a and
            pole_c must look identical so neither side reads as favored. */}
        <div className="grid gap-3 sm:grid-cols-2">
          <ExplainerPoleCard letter="A" pole={explainer.pole_a} />
          <ExplainerPoleCard letter="C" pole={explainer.pole_c} />
        </div>
        <p className="text-[11px] leading-5 text-white/40">
          These are general effects, not guarantees — everyone&apos;s situation is different, and
          neither direction is presented here as the &quot;right&quot; one.
        </p>
      </div>
    </CivitasPanel>
  );
}

function ExplainerPoleCard({ letter, pole }: { letter: "A" | "C"; pole: IssueExplainerPole }) {
  return (
    <div className="rounded-[8px] border border-white/10 bg-navy-dark/50 p-3">
      <div className="mb-2.5 flex items-baseline gap-2">
        <span className="font-mono text-sm text-gold">{letter}.</span>
        <p className="text-sm font-semibold leading-5 text-white/86">{pole.label}</p>
      </div>
      <div className="mb-3">
        <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-white/50">
          Could help you if
        </p>
        <ul className="list-disc space-y-1 pl-4 text-xs leading-5 text-white/62">
          {pole.could_help_you_if.map((bullet, i) => (
            <li key={i}>{bullet}</li>
          ))}
        </ul>
      </div>
      <div>
        <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-white/50">
          Could cost you if
        </p>
        <ul className="list-disc space-y-1 pl-4 text-xs leading-5 text-white/62">
          {pole.could_cost_you_if.map((bullet, i) => (
            <li key={i}>{bullet}</li>
          ))}
        </ul>
      </div>
    </div>
  );
}
