"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Image from "next/image";
import {
  BookOpen,
  Building2,
  Car,
  Check,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  ClipboardList,
  DollarSign,
  GraduationCap,
  HeartPulse,
  Home,
  Landmark,
  Lock,
  MapPin,
  Plus,
  Scale,
  Shield,
  Star,
  TreePine,
  Vote,
  type LucideIcon,
} from "lucide-react";
import CivitasDashboard from "@/components/civitas/CivitasDashboard";
import { buildCivitasDashboard, type CivitasBallotLike } from "@/lib/civitasView";
import { slugify } from "@/lib/db-client";
import { loadPrefs, savePrefs } from "@/lib/prefs";
import type { Candidate as BackendCandidate, Districts, Race as BackendRace } from "@/lib/dataBackend";
import type { IssueDef } from "@/lib/issues";
import type { MatchResult, UserPreferences, VoterProfile } from "@/lib/types";

type WizardStep =
  | "location"
  | "found"
  | "focus"
  | "priorities"
  | "stance"
  | "tradeoff"
  | "dealbreakers"
  | "review"
  | "matches";

type BallotCandidate = Partial<BackendCandidate> & { name: string };

type BallotRace = Partial<Omit<BackendRace, "candidates">> & {
  race_id?: string;
  race?: string;
  office?: string;
  level?: string;
  district?: string | null;
  election_date?: string;
  candidates?: BallotCandidate[];
  context?: {
    last_result?: string;
    sources?: string[];
    [key: string]: unknown;
  };
};

interface BallotData {
  mode?: string;
  warning?: string;
  matched_address?: string;
  districts?: Partial<Districts>;
  races: BallotRace[];
}

interface PoliticianSummary {
  id: string;
  name: string;
  party?: string;
}

type MatchState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "done"; results: MatchResult[] };

const heroImage = "/images/statue-of-liberty.png";
const maxPriorities = 5;

const priorityIssueIds = [
  "housing",
  "taxes",
  "education",
  "crime",
  "healthcare",
  "climate",
  "infrastructure",
  "ethics",
];

const issueLabelOverrides: Record<string, string> = {
  taxes: "Taxes & Spending",
  crime: "Public Safety",
  climate: "Environment",
  infrastructure: "Transportation",
  ethics: "Gov. Transparency",
};

const issueIcons: Record<string, LucideIcon> = {
  housing: Home,
  taxes: DollarSign,
  education: GraduationCap,
  crime: Shield,
  healthcare: HeartPulse,
  climate: TreePine,
  infrastructure: Car,
  ethics: Scale,
};

const focusOptions: {
  id: string;
  title: string;
  subtitle: string;
  icon: LucideIcon;
}[] = [
  { id: "full", title: "Full ballot", subtitle: "All races and measures", icon: ClipboardList },
  { id: "federal", title: "U.S. House", subtitle: "Federal representation", icon: Landmark },
  { id: "state", title: "Statewide races", subtitle: "Texas leadership", icon: Building2 },
  { id: "local", title: "Local races", subtitle: "District and down-ballot", icon: MapPin },
  { id: "measures", title: "Ballot measures", subtitle: "Propositions and initiatives", icon: BookOpen },
];

const stanceOptions = [
  { label: "Oppose", value: 0 },
  { label: "Lean oppose", value: 0.25 },
  { label: "Neutral", value: 0.5 },
  { label: "Lean support", value: 0.75 },
  { label: "Support", value: 1 },
];

const tradeoffOptions = [
  "Keep taxes lower, even if services grow slower.",
  "Fund more services, even if taxes or fees rise.",
  "Depends on the service.",
  "Not sure.",
];

const dealbreakerOptions = [
  "Tax increases",
  "Abortion policy",
  "Gun policy",
  "Immigration enforcement",
  "School curriculum",
];

function cn(...classes: Array<string | false | null | undefined>) {
  return classes.filter(Boolean).join(" ");
}

function raceKey(race: BallotRace, index: number) {
  return race.race_id ?? slugify(race.office ?? race.race ?? `race-${index}`);
}

function raceTitle(race?: BallotRace | null) {
  return race?.office ?? race?.race ?? "Selected election";
}

function raceSubtitle(race: BallotRace) {
  const candidateCount = race.candidates?.length ?? 0;
  if (race.district) return `${race.district} · ${candidateCount} candidate${candidateCount === 1 ? "" : "s"}`;
  return `${candidateCount} candidate${candidateCount === 1 ? "" : "s"}`;
}

function issueLabel(issue: IssueDef) {
  return issueLabelOverrides[issue.id] ?? issue.name;
}

function displayLocation(ballot: BallotData | null, fallback: string) {
  if (ballot?.matched_address) return ballot.matched_address;
  const districts = ballot?.districts;
  if (districts) {
    const parts = [districts.cd, districts.sd, districts.hd, districts.county].filter(Boolean);
    if (parts.length) return parts.join(" · ");
  }
  return fallback;
}

function progressFor(step: WizardStep) {
  switch (step) {
    case "location":
      return 1;
    case "found":
      return 2;
    case "focus":
      return 3;
    case "priorities":
    case "stance":
      return 4;
    case "tradeoff":
    case "dealbreakers":
    case "review":
    case "matches":
      return 5;
    default:
      return 0;
  }
}

function filterRacesByFocus(races: BallotRace[], focus: string) {
  if (focus === "full") return races;
  if (focus === "federal") {
    return races.filter((race) => race.level === "federal" || /u\.?s\.?|congress|house/i.test(raceTitle(race)));
  }
  if (focus === "state") {
    return races.filter((race) => race.level === "state" || /governor|attorney|senate/i.test(raceTitle(race)));
  }
  if (focus === "local") {
    return races.filter((race) => race.level === "state_leg" || /district|county|city|school/i.test(raceTitle(race)));
  }
  if (focus === "measures") {
    return races.filter((race) => /measure|proposition|initiative|amendment/i.test(raceTitle(race)));
  }
  return races;
}

function normalizeBallotCandidate(
  candidate: BallotCandidate,
  race: BallotRace,
  index: number
): BackendCandidate {
  const office = raceTitle(race);
  const fallbackId = `${slugify(office)}-${slugify(candidate.name || `candidate-${index + 1}`)}`;
  return {
    candidate_id: candidate.candidate_id ?? fallbackId,
    name: candidate.name || `Candidate ${index + 1}`,
    party: candidate.party,
    office: candidate.office ?? office,
    district: candidate.district ?? race.district ?? null,
    incumbent: candidate.incumbent,
    fec_id: candidate.fec_id,
    finance: candidate.finance,
    record: candidate.record,
    positions: candidate.positions ?? [],
    sources: candidate.sources ?? [],
    data_missing: candidate.data_missing ?? !candidate.candidate_id,
    data_quality: candidate.data_quality,
  };
}

function normalizeBallotRace(race: BallotRace, index: number): BackendRace {
  const office = raceTitle(race);
  const id = race.race_id ?? slugify(office || `race-${index + 1}`);
  return {
    race_id: id,
    office,
    level: race.level ?? "state",
    district: race.district ?? null,
    context: race.context ?? {},
    candidates: (race.candidates ?? []).map((candidate, candidateIndex) =>
      normalizeBallotCandidate(candidate, race, candidateIndex)
    ),
    data_quality: race.data_quality,
  };
}

function normalizeBallotForCivitas(ballot: BallotData): CivitasBallotLike {
  return {
    matched_address: ballot.matched_address,
    districts: ballot.districts,
    races: ballot.races.map(normalizeBallotRace),
    mode: ballot.mode,
    warning: ballot.warning,
  };
}

function StepLayout({
  children,
  onBack,
  step,
}: {
  children: React.ReactNode;
  onBack?: () => void;
  step: WizardStep;
}) {
  const progress = progressFor(step);
  const sectionRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    sectionRef.current?.scrollTo({ top: 0, left: 0, behavior: "auto" });
  }, [step]);

  return (
    <section ref={sectionRef} className="flex min-h-full flex-1 flex-col overflow-y-auto px-5 py-5 sm:px-7 sm:py-6 md:px-8 md:py-7 lg:px-10 lg:py-8">
      <div className="mb-7 flex h-8 items-center">
        {onBack && (
          <button
            type="button"
            onClick={onBack}
            className="-ml-2 rounded-full p-2 text-white/75 transition hover:bg-white/5 hover:text-white"
            aria-label="Go back"
          >
            <ChevronLeft className="h-5 w-5" />
          </button>
        )}
        {progress > 0 && (
          <div className={cn("flex flex-1 gap-2", onBack ? "ml-3" : "")}>
            {[1, 2, 3, 4, 5].map((bar) => (
              <div
                key={bar}
                className={cn(
                  "h-1 flex-1 rounded-full transition-colors",
                  bar <= progress ? "bg-[#d8a15b]" : "bg-white/12"
                )}
              />
            ))}
          </div>
        )}
      </div>
      <div className="flex flex-1 flex-col">{children}</div>
    </section>
  );
}

function PrimaryButton({
  children,
  disabled,
  onClick,
  type = "button",
}: {
  children: React.ReactNode;
  disabled?: boolean;
  onClick?: () => void;
  type?: "button" | "submit";
}) {
  return (
    <button
      type={type}
      disabled={disabled}
      onClick={onClick}
      className="w-full rounded-[10px] bg-[#d8a15b] px-5 py-3 text-xs font-black uppercase tracking-[0.22em] text-[#091320] shadow-[0_10px_28px_rgba(216,161,91,0.24)] transition hover:bg-[#e7b56f] disabled:cursor-not-allowed disabled:opacity-45"
    >
      {children}
    </button>
  );
}

function CivitasLogo({ compact = false }: { compact?: boolean }) {
  return (
    <div className="flex items-center gap-2 text-[#d8a15b]">
      <Star className={cn("fill-current", compact ? "h-5 w-5" : "h-7 w-7")} />
      <div>
        <div className={cn("font-serif font-semibold tracking-[0.32em] text-white", compact ? "text-sm" : "text-base")}>
          CIVITAS
        </div>
        <div className="text-[0.42rem] uppercase tracking-[0.24em] text-white/55">Data for Democracy</div>
      </div>
    </div>
  );
}

function Field({
  label,
  value,
  placeholder,
  helper,
  onChange,
}: {
  label: string;
  value: string;
  placeholder: string;
  helper?: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="block">
      <span className="mb-2 block text-xs font-medium text-white/80">{label}</span>
      <input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        className="h-12 w-full rounded-[8px] border border-white/16 bg-[#071629]/80 px-3 text-sm text-white outline-none transition placeholder:text-white/30 focus:border-[#d8a15b]/70"
      />
      {helper && <span className="mt-2 block text-xs text-white/45">{helper}</span>}
    </label>
  );
}

function SelectableCard({
  title,
  subtitle,
  icon: Icon,
  selected,
  onClick,
}: {
  title: string;
  subtitle: string;
  icon: LucideIcon;
  selected?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={selected}
      className={cn(
        "flex w-full items-center rounded-[10px] border p-3 text-left transition",
        selected
          ? "border-[#d8a15b] bg-[#d8a15b]/10"
          : "border-white/14 bg-white/[0.035] hover:border-white/28"
      )}
    >
      <span className="mr-3 flex h-10 w-10 shrink-0 items-center justify-center rounded-[8px] border border-white/10 bg-black/10 text-[#d8a15b]">
        <Icon className="h-5 w-5" strokeWidth={1.6} />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-semibold text-white">{title}</span>
        <span className="block truncate text-xs text-white/55">{subtitle}</span>
      </span>
      <ChevronRight className={cn("ml-3 h-5 w-5", selected ? "text-[#d8a15b]" : "text-white/35")} />
    </button>
  );
}

function DesktopRail({
  step,
  locationDisplay,
  selectedRace,
  priorities,
  issues,
  tradeoffStyle,
}: {
  step: WizardStep;
  locationDisplay: string;
  selectedRace: BallotRace | null;
  priorities: string[];
  issues: IssueDef[];
  tradeoffStyle: string | null;
}) {
  const progress = progressFor(step);
  const priorityLabels = priorities
    .map((id) => {
      const issue = issues.find((item) => item.id === id);
      return issue ? issueLabel(issue) : id;
    })
    .join(", ");

  return (
    <aside className="relative hidden h-full min-h-0 flex-col justify-between overflow-hidden bg-[#06192d] p-5 md:flex xl:p-6">
      <Image
        src={heroImage}
        alt=""
        fill
        loading="eager"
        fetchPriority="high"
        className="object-cover object-[25%_50%] opacity-20 grayscale"
        sizes="360px"
      />
      <div className="absolute inset-0 bg-gradient-to-b from-[#06192d]/92 via-[#06192d]/84 to-[#04111f]" />
      <div className="relative z-10">
        <CivitasLogo />
        <div className="mt-8">
          <p className="text-xs font-semibold uppercase tracking-[0.24em] text-[#d8a15b]">Guided comparison</p>
          <h2 className="mt-3 font-serif text-3xl leading-tight text-white">
            Ballot first.
            <br />
            Matches second.
          </h2>
          <p className="mt-4 max-w-[260px] text-sm leading-5 text-white/62">
            Resolve the voter&apos;s races, choose the comparison scope, then score candidates from explicit priorities.
          </p>
        </div>

        <div className="mt-7 space-y-2">
          {[
            ["Location", locationDisplay || "Not entered"],
            ["Election", raceTitle(selectedRace)],
            ["Priorities", priorityLabels || "Not selected"],
            ["Tradeoff", tradeoffStyle ?? "Not selected"],
          ].map(([label, value], index) => (
            <div key={label} className="rounded-[10px] border border-white/10 bg-white/[0.035] p-3">
              <div className="flex items-center gap-2">
                <span
                  className={cn(
                    "flex h-6 w-6 items-center justify-center rounded-full border text-[10px] font-bold",
                    progress > index ? "border-[#d8a15b] text-[#d8a15b]" : "border-white/18 text-white/40"
                  )}
                >
                  {index + 1}
                </span>
                <span className="text-xs font-semibold uppercase tracking-[0.18em] text-white/55">{label}</span>
              </div>
              <p className="mt-2 line-clamp-1 text-sm leading-5 text-white/78">{value}</p>
            </div>
          ))}
        </div>
      </div>

      <div className="relative z-10 rounded-[10px] border border-[#d8a15b]/25 bg-[#d8a15b]/10 p-2.5">
        <div className="flex items-center gap-2 text-[#d8a15b]">
          <Lock className="h-4 w-4" />
          <span className="text-xs font-semibold uppercase tracking-[0.16em]">Privacy: local only</span>
        </div>
        <p className="sr-only">
          Address and priorities stay in this browser except during lookup.
        </p>
      </div>
    </aside>
  );
}

export default function BallotPage() {
  const [issues, setIssues] = useState<IssueDef[] | null>(null);
  const [step, setStep] = useState<WizardStep>("location");
  const [location, setLocation] = useState(() => {
    if (typeof window === "undefined") return { street: "", cityState: "", zip: "" };
    const saved = loadPrefs();
    const urlAddr = new URLSearchParams(window.location.search).get("address")?.trim() ?? "";
    // Prefer a previously-saved full address over a bare URL param (often just a
    // ZIP) so the voter never has to re-type what they already entered.
    return { street: saved?.address || urlAddr, cityState: "", zip: saved?.zip ?? "" };
  });
  const [ballot, setBallot] = useState<BallotData | null>(null);
  const [lookupLoading, setLookupLoading] = useState(false);
  const [lookupError, setLookupError] = useState<string | null>(null);
  const [selectedRaceKey, setSelectedRaceKey] = useState<string | null>(null);
  const [focus, setFocus] = useState("full");
  const [priorities, setPriorities] = useState<string[]>([]);
  const [positions, setPositions] = useState<Record<string, number | null>>({});
  const [stanceIndex, setStanceIndex] = useState(0);
  const [tradeoffStyle, setTradeoffStyle] = useState<string | null>(null);
  const [dealbreakers, setDealbreakers] = useState<string[]>([]);
  const [matchState, setMatchState] = useState<MatchState>({ status: "idle" });

  useEffect(() => {
    window.scrollTo({ top: 0, left: 0, behavior: "auto" });
  }, [step]);

  useEffect(() => {
    fetch("/api/config")
      .then((res) => res.json())
      .then((config) => setIssues(config.issues ?? []))
      .catch(() => setIssues([]));
  }, []);

  const fullAddress = useMemo(
    () => [location.street, location.cityState, location.zip].filter(Boolean).join(", "),
    [location]
  );

  const lookupAddress = useCallback(async (targetAddress: string) => {
    const trimmed = targetAddress.trim();
    if (!trimmed) return;
    setLookupLoading(true);
    setLookupError(null);
    try {
      const res = await fetch(`/api/ballot?address=${encodeURIComponent(trimmed)}`);
      const data = await res.json();
      if (!res.ok) {
        setLookupError(data.error ?? data.detail ?? "Address could not be matched.");
        return;
      }
      const normalized: BallotData = { ...data, races: data.races ?? [] };
      setBallot(normalized);
      setSelectedRaceKey(normalized.races[0] ? raceKey(normalized.races[0], 0) : null);
      setStep("found");
      // Persist the resolved address so a reload / return to /ballot restores it.
      const prev = loadPrefs();
      savePrefs({ ...(prev ?? { priority_weights: {}, issue_positions: {} }), address: trimmed });
    } catch {
      setLookupError("Lookup failed. Try again.");
    } finally {
      setLookupLoading(false);
    }
  }, []);

  useEffect(() => {
    const saved = loadPrefs();
    const urlAddr = new URLSearchParams(window.location.search).get("address")?.trim();
    // Prefer the saved full address (a real street address that geocodes) over a
    // bare URL param, so a reload / return to /ballot restores the voter's ballot
    // instead of forcing a re-entry.
    const restore = saved?.address?.trim() || urlAddr;
    if (saved?.issue_positions) setPositions(saved.issue_positions);
    const savedPicked = Object.keys(saved?.priority_weights ?? {});
    if (savedPicked.length) setPriorities(savedPicked);
    if (!restore) return;
    const timer = window.setTimeout(() => {
      void lookupAddress(restore);
    }, 0);
    return () => window.clearTimeout(timer);
  }, [lookupAddress]);

  const races = useMemo(() => ballot?.races ?? [], [ballot]);
  const selectedRace = useMemo(
    () => races.find((race, index) => raceKey(race, index) === selectedRaceKey) ?? races[0] ?? null,
    [races, selectedRaceKey]
  );

  const selectedIssueDefs = useMemo(() => {
    if (!issues) return [];
    return priorityIssueIds
      .map((id) => issues.find((issue) => issue.id === id))
      .filter((issue): issue is IssueDef => Boolean(issue));
  }, [issues]);

  const currentStanceIssue = useMemo(() => {
    if (!issues || !priorities.length) return null;
    return issues.find((issue) => issue.id === priorities[stanceIndex]) ?? null;
  }, [issues, priorities, stanceIndex]);

  const locationDisplay = displayLocation(ballot, [location.street, location.cityState, location.zip].filter(Boolean).join(", "));

  const goBack = () => {
    if (step === "found") setStep("location");
    if (step === "focus") setStep("found");
    if (step === "priorities") setStep("focus");
    if (step === "stance") {
      if (stanceIndex > 0) setStanceIndex((index) => index - 1);
      else setStep("priorities");
    }
    if (step === "tradeoff") setStep("stance");
    if (step === "dealbreakers") setStep("tradeoff");
    if (step === "review") setStep("dealbreakers");
    if (step === "matches") setStep("review");
  };

  const togglePriority = (id: string) => {
    setPriorities((current) => {
      if (current.includes(id)) return current.filter((item) => item !== id);
      if (current.length >= maxPriorities) return current;
      return [...current, id];
    });
  };

  const continueFromFocus = () => {
    const scopedRaces = filterRacesByFocus(races, focus);
    if (scopedRaces.length) {
      const firstScopedIndex = races.findIndex((race) => race === scopedRaces[0]);
      setSelectedRaceKey(raceKey(scopedRaces[0], Math.max(firstScopedIndex, 0)));
    }
    setStep("priorities");
  };

  const continueFromStance = () => {
    if (stanceIndex + 1 < priorities.length) {
      setStanceIndex((index) => index + 1);
      return;
    }
    setStep("tradeoff");
  };

  const buildPrefs = (): UserPreferences => {
    const weights: Record<string, number> = {};
    const issuePositions: Record<string, number | null> = {};
    priorities.forEach((id, index) => {
      weights[id] = (priorities.length - index) / Math.max(priorities.length, 1);
      issuePositions[id] = positions[id] ?? null;
    });
    const profile: VoterProfile = { flags: {} };
    return {
      address: fullAddress || undefined,
      zip: location.zip || undefined,
      profile,
      priority_weights: weights,
      issue_positions: issuePositions,
    };
  };

  const dashboardPrefs = buildPrefs();
  const dashboardView = useMemo(() => {
    if (!ballot) return null;
    return buildCivitasDashboard(
      normalizeBallotForCivitas(ballot),
      matchState.status === "done" ? matchState.results : []
    );
  }, [ballot, matchState]);

  const loadMatches = async () => {
    const prefs = dashboardPrefs;
    savePrefs(prefs);
    setStep("matches");
    setMatchState({ status: "loading" });
    try {
      const politicians = (await fetch("/api/politicians").then((res) => res.json())) as PoliticianSummary[];
      const response = await fetch("/api/match", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prefs, politician_ids: politicians.map((politician) => politician.id) }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.error ?? "Could not score candidates.");
      const allResults = (body.results ?? []) as MatchResult[];
      setMatchState({
        status: "done",
        results: allResults,
      });
    } catch (error) {
      setMatchState({
        status: "error",
        message: error instanceof Error ? error.message : "Could not score candidates.",
      });
    }
  };

  if (!issues) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#020d19] px-4 text-sm text-white/55">
        Loading ballot flow…
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#020d19] bg-[radial-gradient(circle_at_75%_10%,rgba(29,87,115,0.32),transparent_34%),radial-gradient(circle_at_10%_90%,rgba(142,76,48,0.16),transparent_32%)] px-3 py-4 text-white sm:px-6 sm:py-8 md:px-0 md:py-0">
      <main className="mx-auto grid min-h-[calc(100svh-2rem)] w-full max-w-[420px] md:h-screen md:min-h-screen md:max-w-none md:grid-cols-[320px_minmax(0,1fr)] md:overflow-hidden md:rounded-none md:border-0 md:bg-transparent md:shadow-none xl:grid-cols-[360px_minmax(0,1fr)]">
        <DesktopRail
          step={step}
          locationDisplay={locationDisplay}
          selectedRace={selectedRace}
          priorities={priorities}
          issues={issues}
          tradeoffStyle={tradeoffStyle}
        />
        <div className="flex min-h-[calc(100svh-2rem)] w-full flex-col overflow-hidden rounded-[24px] border border-[#d8a15b]/35 bg-[#051628] shadow-[0_28px_90px_rgba(0,0,0,0.45)] sm:min-h-[680px] md:h-full md:min-h-0 md:rounded-none md:border-0 md:border-l md:border-white/10 md:shadow-none">
        {step === "location" && (
          <StepLayout step={step}>
            <form
              className="flex flex-1 flex-col"
              onSubmit={(event) => {
                event.preventDefault();
                void lookupAddress(fullAddress);
              }}
            >
              <h1 className="font-serif text-3xl leading-tight text-white">Where do you vote?</h1>
              <p className="mt-4 text-sm leading-6 text-white/68">
                Enter your voting address so we can find your districts and ballot.
              </p>
              <div className="mt-7 grid gap-5">
                <Field
                  label="Street address"
                  value={location.street}
                  onChange={(street) => setLocation((current) => ({ ...current, street }))}
                  placeholder="123 Main St"
                />
                <Field
                  label="City, State"
                  value={location.cityState}
                  onChange={(cityState) => setLocation((current) => ({ ...current, cityState }))}
                  placeholder="Austin, Texas"
                />
                <Field
                  label="ZIP code (optional)"
                  value={location.zip}
                  onChange={(zip) => setLocation((current) => ({ ...current, zip: zip.replace(/\D/g, "").slice(0, 5) }))}
                  placeholder="78701"
                  helper="Use ZIP for approximate results"
                />
              </div>
              {lookupError && (
                <p className="mt-5 rounded-[10px] border border-red-400/35 bg-red-500/10 p-3 text-sm text-red-200">
                  {lookupError}
                </p>
              )}
              <div className="mt-auto space-y-4 pt-8">
                <PrimaryButton type="submit" disabled={!location.street.trim() || lookupLoading}>
                  {lookupLoading ? "Finding election" : "Find my election"}
                </PrimaryButton>
                <div className="flex items-center justify-center gap-2 text-xs text-white/55">
                  <Lock className="h-4 w-4 text-[#d8a15b]" />
                  <span>Used only for election lookup.</span>
                </div>
              </div>
            </form>
          </StepLayout>
        )}

        {step === "found" && (
          <StepLayout step={step} onBack={goBack}>
            <h1 className="font-serif text-3xl leading-tight text-white">We found your ballot</h1>
            <p className="mt-3 text-sm text-white/65">{locationDisplay}</p>
            {ballot?.warning && (
              <p className="mt-4 rounded-[10px] border border-gold/30 bg-gold/10 p-3 text-xs leading-5 text-gold">
                {ballot.warning}
              </p>
            )}
            <div className="mt-7 grid flex-1 content-start gap-3 overflow-y-auto pr-1 md:grid-cols-2">
              {races.length > 0 ? (
                races.slice(0, 7).map((race, index) => (
                  <SelectableCard
                    key={raceKey(race, index)}
                    title={raceTitle(race)}
                    subtitle={raceSubtitle(race)}
                    icon={race.level === "federal" ? Landmark : race.level === "state" ? Building2 : Vote}
                    selected={selectedRaceKey === raceKey(race, index)}
                    onClick={() => setSelectedRaceKey(raceKey(race, index))}
                  />
                ))
              ) : (
                <p className="rounded-[10px] border border-white/14 bg-white/[0.035] p-4 text-sm text-white/60">
                  We reached the lookup service, but it did not return races for this address.
                </p>
              )}
            </div>
            <div className="mt-7">
              <PrimaryButton disabled={!selectedRaceKey && races.length > 0} onClick={() => setStep("focus")}>
                Choose an election
              </PrimaryButton>
            </div>
          </StepLayout>
        )}

        {step === "focus" && (
          <StepLayout step={step} onBack={goBack}>
            <h1 className="font-serif text-3xl leading-tight text-white">What do you want to compare first?</h1>
            <p className="mt-4 text-sm leading-6 text-white/68">You can always explore the rest later.</p>
            <div className="mt-7 grid flex-1 content-start gap-3 md:grid-cols-2">
              {focusOptions.map((option) => (
                <SelectableCard
                  key={option.id}
                  title={option.title}
                  subtitle={option.subtitle}
                  icon={option.icon}
                  selected={focus === option.id}
                  onClick={() => setFocus(option.id)}
                />
              ))}
            </div>
            <div className="mt-7">
              <PrimaryButton onClick={continueFromFocus}>Continue</PrimaryButton>
            </div>
          </StepLayout>
        )}

        {step === "priorities" && (
          <StepLayout step={step} onBack={goBack}>
            <h1 className="font-serif text-3xl leading-tight text-white">What should we weigh most?</h1>
            <p className="mt-4 text-sm leading-6 text-white/68">
              Pick up to 5 issues. You can change this later.
            </p>
            <div className="mt-7 grid flex-1 grid-cols-2 content-start gap-3 lg:grid-cols-4">
              {selectedIssueDefs.map((issue) => {
                const Icon = issueIcons[issue.id] ?? Scale;
                const selected = priorities.includes(issue.id);
                const disabled = !selected && priorities.length >= maxPriorities;
                return (
                  <button
                    key={issue.id}
                    type="button"
                    disabled={disabled}
                    aria-pressed={selected}
                    onClick={() => togglePriority(issue.id)}
                    className={cn(
                      "relative flex min-h-[84px] flex-col items-start justify-between rounded-[10px] border p-3 text-left transition",
                      selected
                        ? "border-[#d8a15b] bg-[#d8a15b]/10 text-[#d8a15b]"
                        : "border-white/14 bg-white/[0.035] text-white/82 hover:border-white/28",
                      disabled && "cursor-not-allowed opacity-45"
                    )}
                  >
                    {selected && (
                      <CheckCircle2 className="absolute right-2 top-2 h-5 w-5 fill-[#d8a15b] text-[#071320]" />
                    )}
                    <Icon className="h-6 w-6" strokeWidth={1.55} />
                    <span className="pr-4 text-xs font-semibold leading-snug">{issueLabel(issue)}</span>
                  </button>
                );
              })}
            </div>
            <div className="mt-5 text-sm text-white/65">{priorities.length} of {maxPriorities} selected</div>
            <div className="mt-4">
              <PrimaryButton
                disabled={priorities.length === 0}
                onClick={() => {
                  setStanceIndex(0);
                  setStep("stance");
                }}
              >
                Continue
              </PrimaryButton>
            </div>
          </StepLayout>
        )}

        {step === "stance" && currentStanceIssue && (
          <StepLayout step={step} onBack={goBack}>
            <div className="text-sm font-medium tracking-wide text-[#d8a15b]">
              Question {stanceIndex + 1} of {priorities.length}
            </div>
            <h1 className="mt-4 font-serif text-3xl leading-tight text-white">{issueLabel(currentStanceIssue)}</h1>
            <p className="mt-4 text-base leading-7 text-white/76">{currentStanceIssue.tradeoffQuestion}</p>
            <div className="flex flex-1 flex-col justify-center py-10">
              <div
                className="relative flex items-start justify-between"
                role="radiogroup"
                aria-label={`${issueLabel(currentStanceIssue)} position`}
              >
                <div className="absolute left-5 right-5 top-3 h-px bg-white/20" />
                {stanceOptions.map((option) => {
                  const selected = positions[currentStanceIssue.id] === option.value;
                  return (
                    <button
                      key={option.label}
                      type="button"
                      role="radio"
                      aria-checked={selected}
                      onClick={() =>
                        setPositions((current) => ({ ...current, [currentStanceIssue.id]: option.value }))
                      }
                      className="relative z-10 flex w-14 flex-col items-center gap-3"
                    >
                      <span
                        className={cn(
                          "flex rounded-full border-2 bg-[#051628] transition-all",
                          selected
                            ? "h-8 w-8 border-[#d8a15b] p-1.5"
                            : "mt-1 h-6 w-6 border-white/45 hover:border-white/70"
                        )}
                      >
                        {selected && <span className="h-full w-full rounded-full bg-[#d8a15b]" />}
                      </span>
                      <span className={cn("text-center text-[10px] leading-4", selected ? "text-[#d8a15b]" : "text-white/56")}>
                        {option.label}
                      </span>
                    </button>
                  );
                })}
              </div>
              <div className="mt-10 grid grid-cols-2 gap-3 text-[11px] leading-4 text-white/45">
                <span>{currentStanceIssue.axis0}</span>
                <span className="text-right">{currentStanceIssue.axis1}</span>
              </div>
            </div>
            <div className="mt-auto flex gap-3">
              <button
                type="button"
                onClick={() => {
                  setPositions((current) => ({ ...current, [currentStanceIssue.id]: null }));
                  continueFromStance();
                }}
                className="flex-1 rounded-[10px] px-4 py-3 text-xs font-black uppercase tracking-[0.22em] text-[#d8a15b] transition hover:bg-[#d8a15b]/10"
              >
                Skip
              </button>
              <div className="flex-1">
                <PrimaryButton onClick={continueFromStance}>
                  {stanceIndex + 1 < priorities.length ? "Next" : "Continue"}
                </PrimaryButton>
              </div>
            </div>
          </StepLayout>
        )}

        {step === "tradeoff" && (
          <StepLayout step={step} onBack={goBack}>
            <h1 className="font-serif text-3xl leading-tight text-white">
              When policy conflicts, what do you usually prefer?
            </h1>
            <p className="mt-7 font-serif text-lg text-white/90">Taxes and services</p>
            <div className="mt-5 flex-1 space-y-3" role="radiogroup" aria-label="Taxes and services tradeoff">
              {tradeoffOptions.map((option) => {
                const selected = tradeoffStyle === option;
                return (
                  <button
                    key={option}
                    type="button"
                    role="radio"
                    aria-checked={selected}
                    onClick={() => setTradeoffStyle(option)}
                    className={cn(
                      "flex w-full items-center rounded-[10px] border p-4 text-left text-sm leading-5 transition",
                      selected
                        ? "border-[#d8a15b] bg-[#d8a15b]/10 text-white"
                        : "border-white/14 bg-white/[0.035] text-white/78 hover:border-white/28"
                    )}
                  >
                    <span
                      className={cn(
                        "mr-3 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border",
                        selected ? "border-[#d8a15b]" : "border-white/45"
                      )}
                    >
                      {selected && <span className="h-2.5 w-2.5 rounded-full bg-[#d8a15b]" />}
                    </span>
                    {option}
                  </button>
                );
              })}
            </div>
            <div className="mt-7">
              <PrimaryButton disabled={!tradeoffStyle} onClick={() => setStep("dealbreakers")}>
                Continue
              </PrimaryButton>
            </div>
          </StepLayout>
        )}

        {step === "dealbreakers" && (
          <StepLayout step={step} onBack={goBack}>
            <h1 className="font-serif text-3xl leading-tight text-white">Anything we should never recommend?</h1>
            <p className="mt-4 text-sm leading-6 text-white/68">
              Optional. Add any positions that should strongly count against a candidate.
            </p>
            <div className="mt-7 flex-1 space-y-3">
              {dealbreakerOptions.map((option) => {
                const selected = dealbreakers.includes(option);
                return (
                  <button
                    key={option}
                    type="button"
                    aria-pressed={selected}
                    onClick={() =>
                      setDealbreakers((current) =>
                        selected ? current.filter((item) => item !== option) : [...current, option]
                      )
                    }
                    className={cn(
                      "flex w-full items-center justify-between rounded-[10px] border p-4 text-sm transition",
                      selected
                        ? "border-[#d8a15b] bg-[#d8a15b]/10 text-[#d8a15b]"
                        : "border-white/14 bg-white/[0.035] text-white/78 hover:border-white/28"
                    )}
                  >
                    <span>{option}</span>
                    {selected ? <Check className="h-5 w-5" /> : <Plus className="h-5 w-5 text-white/40" />}
                  </button>
                );
              })}
            </div>
            <div className="mt-7 flex gap-3">
              <button
                type="button"
                onClick={() => setStep("review")}
                className="flex-1 rounded-[10px] px-3 py-3 text-[11px] font-black uppercase tracking-[0.18em] text-[#d8a15b] transition hover:bg-[#d8a15b]/10"
              >
                Skip for now
              </button>
              <div className="flex-1">
                <PrimaryButton onClick={() => setStep("review")}>Continue</PrimaryButton>
              </div>
            </div>
          </StepLayout>
        )}

        {step === "review" && (
          <StepLayout step={step} onBack={goBack}>
            <h1 className="font-serif text-3xl leading-tight text-white">Your comparison settings</h1>
            <p className="mt-4 text-sm leading-6 text-white/68">
              You can edit anything before we show your matches.
            </p>
            <div className="mt-7 flex-1 space-y-3">
              {[
                {
                  title: "Election",
                  value: raceTitle(selectedRace),
                  icon: Vote,
                  action: () => setStep("found"),
                },
                {
                  title: "Top priorities",
                  value:
                    priorities
                      .map((id) => {
                        const issue = issues.find((item) => item.id === id);
                        return issue ? issueLabel(issue) : id;
                      })
                      .join(", ") || "None selected",
                  icon: Star,
                  action: () => setStep("priorities"),
                },
                {
                  title: "Tradeoff style",
                  value: tradeoffStyle ?? "Not selected",
                  icon: Scale,
                  action: () => setStep("tradeoff"),
                },
                {
                  title: "Dealbreakers",
                  value: dealbreakers.length ? dealbreakers.join(", ") : "None added",
                  icon: Shield,
                  action: () => setStep("dealbreakers"),
                },
              ].map((item) => {
                const Icon = item.icon;
                return (
                  <div key={item.title} className="flex items-start gap-3 rounded-[10px] border border-white/12 bg-white/[0.035] p-4">
                    <Icon className="mt-1 h-5 w-5 shrink-0 text-[#d8a15b]" strokeWidth={1.6} />
                    <div className="min-w-0 flex-1">
                      <div className="text-sm font-semibold text-white">{item.title}</div>
                      <div className="mt-1 text-xs leading-5 text-white/55">{item.value}</div>
                    </div>
                    <button
                      type="button"
                      onClick={item.action}
                      className="text-xs font-medium text-[#d8a15b] hover:underline"
                    >
                      Change
                    </button>
                  </div>
                );
              })}
            </div>
            <div className="mt-7">
              <PrimaryButton onClick={() => void loadMatches()}>See my matches</PrimaryButton>
            </div>
          </StepLayout>
        )}

        {step === "matches" && (
          dashboardView ? (
            matchState.status === "loading" ? (
              <section className="flex min-h-full flex-1 flex-col bg-navy px-5 py-6 text-white md:px-8 md:py-7 lg:px-10 lg:py-8">
                <CivitasLogo compact />
                <div
                  role="status"
                  aria-live="polite"
                  className="mt-16 max-w-xl rounded-[10px] border border-white/12 bg-white/[0.035] p-5"
                >
                  <p className="text-xs font-semibold uppercase tracking-[0.22em] text-[#d8a15b]">
                    Building dashboard
                  </p>
                  <h1 className="mt-4 font-serif text-4xl leading-tight text-white">
                    Scoring candidates from your stated priorities.
                  </h1>
                  <p className="mt-4 text-sm leading-6 text-white/58">
                    The ballot is resolved. Alignment rows will appear as soon as the local scoring
                    engine finishes.
                  </p>
                </div>
              </section>
            ) : matchState.status === "error" ? (
              <section className="flex min-h-full flex-1 flex-col bg-navy px-5 py-6 text-white md:px-8 md:py-7 lg:px-10 lg:py-8">
                <CivitasLogo compact />
                <div
                  role="alert"
                  className="mt-16 max-w-xl rounded-[10px] border border-red-400/35 bg-red-500/10 p-5 text-sm text-red-100"
                >
                  {matchState.message}
                  <div className="mt-5">
                    <button
                      type="button"
                      onClick={goBack}
                      className="text-xs font-semibold uppercase tracking-[0.18em] text-[#d8a15b] hover:underline"
                    >
                      Edit settings
                    </button>
                  </div>
                </div>
              </section>
            ) : (
              <CivitasDashboard
                view={dashboardView}
                initialRaceId={selectedRaceKey}
                profile={dashboardPrefs.profile}
                onEditSettings={goBack}
              />
            )
          ) : (
            <section className="flex min-h-full flex-1 flex-col bg-navy px-5 py-6 text-white md:px-8 md:py-7 lg:px-10 lg:py-8">
              <CivitasLogo compact />
              <div className="mt-16 max-w-xl rounded-[10px] border border-white/12 bg-white/[0.035] p-5 text-sm text-white/58">
                No ballot data is available yet. Go back and run the address lookup again.
              </div>
            </section>
          )
        )}
        </div>
      </main>
    </div>
  );
}
