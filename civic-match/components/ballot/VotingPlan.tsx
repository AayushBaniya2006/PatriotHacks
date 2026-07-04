"use client";

// Renders after the ballot: a simple, client-only "make a voting plan" card
// (P1 #1, local-only/competitive-analysis/improvements.md; design spec §5).
// Two choices -- Election Day or early voting -- plus a time window, and an
// "Add to calendar" button that builds a .ics file entirely in the browser
// (no server round-trip, nothing persisted, nothing sent anywhere). Renders
// unconditionally once the ballot section is showing, but styled more
// prominently once the voter has reviewed every race on their ballot -- the
// same district-keyed readiness store BallotSection's readiness bar reads
// (lib/readiness.ts), read independently here so no prop plumbing changes
// to BallotSection are needed. Never gated on that state; the plan is fully
// usable at any point, reviewed or not.
//
// AESTHETIC QA PASS: text-zinc-500/600 -> text-zinc-400 and
// border-zinc-700/800 -> border-zinc-500, same measured reason as the other
// two files in this module (old shades measured 1.2-3.8:1 against this
// card's zinc-900/50-on-navy / zinc-950 surfaces, under the WCAG AA 3:1 /
// 4.5:1 floors; the new shades clear both with margin). The "ballot-ready"
// card's own accent border was border-emerald-500/30 (1.7:1 against the
// page -- effectively invisible, so the one card meant to feel celebratory
// didn't visibly have a border at all); bumped to solid border-emerald-400
// (9.5:1), which is also the exact token this file already uses for every
// other "active/selected" state (the Election Day / Early voting toggle,
// the time-window select's sibling controls), so the ready-state border
// now reads as the same accent language instead of a separate, fainter one.
//
// No polling place is ever claimed here (Do-Not-Build: "Full polling-place
// map") -- the card always points to VoteTexas.gov to confirm one. Early
// voting dates are county-specific and NOT present anywhere in this repo's
// data (checked before writing this: data/tx/*.json has no early-voting
// date field; schema.md's voting_info.early_vote_sites[] shape carries only
// {name, address, hours} per site, never a date; see this lane's report for
// the full check). So an "Early voting" selection never invents a date --
// the generated .ics is always anchored to Election Day itself, the one
// date this whole app is built around, with the description honestly
// saying so and pointing at VoteTexas.gov for the voter's real early-voting
// window.
import { useState, useSyncExternalStore } from "react";
import type { Districts, Race } from "@/lib/dataBackend";
import { getReviewed, readinessKey, subscribeReviewed } from "@/lib/readiness";

const EMPTY_REVIEWED: ReadonlySet<string> = new Set();

// Texas General Election, 2026 -- matches app/api/motivate/route.ts's cta
// ("Election day is November 3, 2026...") and the approved design spec.
const ELECTION_DATE = "2026-11-03";
const ELECTION_DATE_LABEL = "Tue, Nov 3, 2026";
const VOTE_TEXAS_URL = "https://www.votetexas.gov/";

export type ElectionTiming = "election_day" | "early_voting";

export interface TimeWindow {
  id: string;
  label: string;
  startHour: number; // 24h, local/floating time
  endHour: number;
}

// Plain hour-of-day windows, per improvements.md P1 #1 -- deliberately
// coarse (no minutes shown to the voter) so the choice stays a 5-second
// decision, not a scheduling exercise.
export const TIME_WINDOWS: TimeWindow[] = [
  { id: "morning", label: "Morning (8–10am)", startHour: 8, endHour: 10 },
  { id: "midday", label: "Midday (11am–1pm)", startHour: 11, endHour: 13 },
  { id: "afternoon", label: "Afternoon (2–4pm)", startHour: 14, endHour: 16 },
  { id: "evening", label: "Evening (5–7pm)", startHour: 17, endHour: 19 },
];

function pad2(n: number): string {
  return n.toString().padStart(2, "0");
}

// Floating local date-time (RFC 5545 §3.3.5 -- no trailing "Z", no TZID):
// the event fires at this wall-clock hour in whatever calendar/timezone the
// voter's own device is set to, which is exactly what "8-10am" should mean
// for a voting reminder (Texas alone spans Central and Mountain time).
function floatingDateTime(dateISO: string, hour: number, minute: number): string {
  return `${dateISO.replace(/-/g, "")}T${pad2(hour)}${pad2(minute)}00`;
}

// UTC "Zulu" generation timestamp for DTSTAMP -- required by RFC 5545, and
// only records when the file was built, never anything about the voter.
function utcStamp(d: Date): string {
  return (
    `${d.getUTCFullYear()}${pad2(d.getUTCMonth() + 1)}${pad2(d.getUTCDate())}` +
    `T${pad2(d.getUTCHours())}${pad2(d.getUTCMinutes())}${pad2(d.getUTCSeconds())}Z`
  );
}

// RFC 5545 §3.3.11 TEXT escaping -- backslash first, then the rest, then
// newlines as the literal two-character escape "\n".
function icsEscapeText(text: string): string {
  return text
    .replace(/\\/g, "\\\\")
    .replace(/;/g, "\\;")
    .replace(/,/g, "\\,")
    .replace(/\r\n|\r|\n/g, "\\n");
}

// Pure and DOM-free by construction: its only inputs are the timing choice,
// the chosen time window, and a clock reading. There is no address,
// profile, race, or candidate data anywhere in scope for this function to
// leak into the file -- by construction, not merely by omission -- which is
// exactly what "NO polling place claimed" / no-profile-data-inside means in
// practice for a calendar file a voter might forward to someone else.
export function buildVotingPlanICS(timing: ElectionTiming, window: TimeWindow, now: Date = new Date()): string {
  const dtStamp = utcStamp(now);
  const dtStart = floatingDateTime(ELECTION_DATE, window.startHour, 0);
  const dtEnd = floatingDateTime(ELECTION_DATE, window.endHour, 0);
  // Random, not sequential/derived from anything voter-specific -- just
  // needs to be unique enough that re-importing the same file updates
  // rather than duplicates the event in most calendar apps.
  const uid = `civic-match-voting-plan-${now.getTime()}-${Math.random().toString(36).slice(2, 10)}@civicmatch.local`;

  const descriptionLines =
    timing === "early_voting"
      ? [
          "You planned to vote early. Early-voting dates vary by county and aren't in our data set, so this " +
            "reminder is set for Election Day instead.",
          "Confirm your polling location (and your county's early-voting dates/hours) at VoteTexas.gov.",
          VOTE_TEXAS_URL,
        ]
      : ["Your voting plan: Election Day.", "Confirm your polling location at VoteTexas.gov.", VOTE_TEXAS_URL];

  const lines = [
    "BEGIN:VCALENDAR",
    "VERSION:2.0",
    "PRODID:-//Civic Match//Voting Plan//EN",
    "CALSCALE:GREGORIAN",
    "METHOD:PUBLISH",
    "BEGIN:VEVENT",
    `UID:${uid}`,
    `DTSTAMP:${dtStamp}`,
    `DTSTART:${dtStart}`,
    `DTEND:${dtEnd}`,
    "SUMMARY:Vote — Texas General Election",
    `DESCRIPTION:${icsEscapeText(descriptionLines.join("\n"))}`,
    `URL:${VOTE_TEXAS_URL}`,
    "END:VEVENT",
    "END:VCALENDAR",
  ];
  // RFC 5545 §3.1: CRLF line endings, trailing CRLF at EOF. Every line here
  // is short (well under the 75-octet fold limit) so no folding is needed.
  return lines.join("\r\n") + "\r\n";
}

function downloadICS(content: string, filename: string): void {
  const blob = new Blob([content], { type: "text/calendar;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  // Deferred revoke so Safari/Firefox have a moment to actually start the
  // download before the blob URL is invalidated.
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

export function VotingPlan({
  races,
  districts,
}: {
  races: Race[];
  // OPTIONAL: same district triple BallotSection/InsightsPanel key their
  // readiness state by (lib/readiness.ts) -- lets this card independently
  // read the same "reviewed X of N" state to decide how prominent to
  // render, without threading new props through BallotSection.
  districts?: Districts | null;
}) {
  const [timing, setTiming] = useState<ElectionTiming>("election_day");
  const [windowId, setWindowId] = useState<string>(TIME_WINDOWS[0].id);
  const [downloaded, setDownloaded] = useState(false);

  const reviewKey = readinessKey(districts);
  const reviewed = useSyncExternalStore(
    subscribeReviewed,
    () => getReviewed(reviewKey),
    () => EMPTY_REVIEWED
  );
  const raceIds = new Set(races.map((r) => r.race_id));
  const reviewedCount = Array.from(reviewed).filter((id) => raceIds.has(id)).length;
  const ballotReady = races.length > 0 && reviewedCount >= races.length;

  const selectedWindow = TIME_WINDOWS.find((w) => w.id === windowId) ?? TIME_WINDOWS[0];

  const handleAddToCalendar = () => {
    const ics = buildVotingPlanICS(timing, selectedWindow);
    downloadICS(ics, "civic-match-vote-reminder.ics");
    setDownloaded(true);
  };

  return (
    <div
      className={
        ballotReady
          ? "rounded-2xl border border-emerald-400 bg-gradient-to-br from-emerald-500/10 to-transparent p-5 transition"
          : "rounded-xl border border-zinc-500 bg-zinc-900/50 p-5 transition"
      }
    >
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-semibold">Make a voting plan</h3>
        {ballotReady && (
          <span className="rounded-full border border-emerald-400 bg-emerald-500/15 px-2.5 py-1 text-[11px] font-medium text-emerald-300">
            You&apos;ve reviewed your ballot — lock in a plan ✓
          </span>
        )}
      </div>

      <div className="space-y-4">
        <div>
          <div className="mb-2 text-xs uppercase tracking-wider text-zinc-400">When are you voting?</div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => setTiming("election_day")}
              aria-pressed={timing === "election_day"}
              className={`rounded-lg border px-3 py-1.5 text-sm font-medium transition ${
                timing === "election_day"
                  ? "border-emerald-400 bg-emerald-500/15 text-emerald-300"
                  : "border-zinc-500 text-zinc-300 hover:border-emerald-400/60"
              }`}
            >
              Election Day ({ELECTION_DATE_LABEL})
            </button>
            <button
              type="button"
              onClick={() => setTiming("early_voting")}
              aria-pressed={timing === "early_voting"}
              className={`rounded-lg border px-3 py-1.5 text-sm font-medium transition ${
                timing === "early_voting"
                  ? "border-emerald-400 bg-emerald-500/15 text-emerald-300"
                  : "border-zinc-500 text-zinc-300 hover:border-emerald-400/60"
              }`}
            >
              Early voting (check dates at VoteTexas.gov)
            </button>
          </div>
        </div>

        <div>
          <label htmlFor="voting-plan-window" className="mb-2 block text-xs uppercase tracking-wider text-zinc-400">
            What time works?
          </label>
          <select
            id="voting-plan-window"
            value={windowId}
            onChange={(e) => {
              setWindowId(e.target.value);
              setDownloaded(false);
            }}
            className="w-full max-w-xs rounded-lg border border-zinc-500 bg-zinc-950 px-3 py-2 text-sm text-zinc-200"
          >
            {TIME_WINDOWS.map((w) => (
              <option key={w.id} value={w.id}>
                {w.label}
              </option>
            ))}
          </select>
        </div>

        {timing === "early_voting" && (
          <p className="max-w-prose text-xs text-zinc-400">
            We don&apos;t have your county&apos;s specific early-voting dates, so the calendar reminder below is set
            for Election Day instead — check VoteTexas.gov for your actual early-voting window.
          </p>
        )}

        <div className="flex flex-wrap items-center gap-3 pt-1">
          <button
            type="button"
            onClick={handleAddToCalendar}
            className="rounded-lg bg-emerald-500 px-5 py-2.5 text-sm font-semibold text-zinc-950 hover:bg-emerald-400"
          >
            Add to calendar
          </button>
          {downloaded && <span className="text-xs text-emerald-400">Calendar file downloaded ✓</span>}
        </div>

        <p className="max-w-prose text-xs text-zinc-400">
          Downloads a .ics reminder for {ELECTION_DATE_LABEL}, {selectedWindow.label.toLowerCase()} — works with
          Google Calendar, Apple Calendar, Outlook, and most calendar apps.{" "}
          <a
            href={VOTE_TEXAS_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="text-emerald-400 hover:underline"
          >
            Confirm your polling location at VoteTexas.gov ↗
          </a>
        </p>
      </div>
    </div>
  );
}

export default VotingPlan;
