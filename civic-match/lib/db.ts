// "DB of politicians" — cached profiles keyed by slug. Backed by Postgres
// (lib/store.ts) so profiles survive redeploys. Public API is unchanged from the
// former file-based version, so callers need no changes.
import { kvGet, kvSet, kvList, NS } from "./store";
import type { PoliticianProfile } from "./types";

export function slugify(name: string): string {
  return name
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

export async function getPolitician(id: string): Promise<PoliticianProfile | null> {
  return kvGet<PoliticianProfile>(NS.politicians, id);
}

export async function savePolitician(profile: PoliticianProfile): Promise<void> {
  await kvSet(NS.politicians, profile.id, profile);
}

export async function listPoliticians(): Promise<PoliticianProfile[]> {
  const profiles = await kvList<PoliticianProfile>(NS.politicians);
  return profiles.sort((a, b) => a.name.localeCompare(b.name));
}
