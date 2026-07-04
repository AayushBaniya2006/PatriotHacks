// Repair pass:
// 1. Re-derive null position scalars from existing stance evidence (no web
//    search — the evidence is already indexed; this is pure classification).
// 2. Fix display names to the ballot names from the election file.
// Usage: npx tsx scripts/repair.ts
import { config } from "dotenv";
config({ path: ".env.local" });

import { promises as fs } from "fs";
import path from "path";
import { listPoliticians, savePolitician, slugify } from "../lib/db";
import { chat, extractJSON, FAST_MODEL } from "../lib/llm";
import { getIssueMap } from "../lib/config";

async function ballotNames(): Promise<Map<string, string>> {
  const map = new Map<string, string>();
  try {
    const races = JSON.parse(
      await fs.readFile(path.join(process.cwd(), "data", "elections", "texas.json"), "utf-8")
    );
    for (const r of races)
      for (const c of r.candidates) map.set(slugify(c.name), c.name);
  } catch {
    /* no election file */
  }
  return map;
}

async function main() {
  const names = await ballotNames();
  const profiles = await listPoliticians();

  for (const p of profiles) {
    let changed = false;

    // 2. Display name = ballot name
    const ballot = names.get(p.id);
    if (ballot && p.name !== ballot) {
      console.log(`[name] ${p.name} → ${ballot}`);
      p.name = ballot;
      changed = true;
    }

    // 1. Re-derive null scalars from indexed evidence
    const nulls = p.stances.filter((s) => s.position_scalar === null);
    if (nulls.length > 0) {
      console.log(`[scalars] ${p.id}: re-deriving ${nulls.length} null placements`);
      const items = nulls.map((s) => ({
        issue_id: s.issue_id,
        axis: `0.0=${getIssueMap()[s.issue_id].axis0} ... 1.0=${getIssueMap()[s.issue_id].axis1}`,
        position: s.position_label,
        summary: s.summary,
      }));
      const out = await chat(
        [
          {
            role: "user",
            content: `For each stance below, place the described position on its 0.0-1.0 axis. Use null ONLY if the direction is genuinely unclear from the description. Return ONLY JSON: [{"issue_id": "...", "position_scalar": number|null}]

${JSON.stringify(items)}`,
          },
        ],
        { model: FAST_MODEL, maxTokens: 2048, timeoutMs: 90_000 }
      );
      try {
        const fixes = extractJSON<{ issue_id: string; position_scalar: number | null }[]>(out);
        for (const f of fixes) {
          const s = p.stances.find((s) => s.issue_id === f.issue_id);
          if (s && typeof f.position_scalar === "number") {
            s.position_scalar = Math.max(0, Math.min(1, f.position_scalar));
            changed = true;
          }
        }
      } catch (e) {
        console.error(`  parse failed for ${p.id}:`, e instanceof Error ? e.message : e);
      }
    }

    if (changed) {
      await savePolitician(p);
      const remaining = p.stances.filter((s) => s.position_scalar === null).length;
      console.log(`[saved] ${p.id} (${remaining} scalars still null)`);
    }
  }
  console.log("Repair complete.");
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
