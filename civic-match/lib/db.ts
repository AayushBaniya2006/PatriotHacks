// Simple file-backed "db of politicians" (sketch: cached profiles keyed by slug).
import { promises as fs } from "fs";
import path from "path";
import type { PoliticianProfile } from "./types";

const DATA_DIR = path.join(process.cwd(), "data", "politicians");

export function slugify(name: string): string {
  return name
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

async function ensureDir() {
  await fs.mkdir(DATA_DIR, { recursive: true });
}

export async function getPolitician(id: string): Promise<PoliticianProfile | null> {
  try {
    const raw = await fs.readFile(path.join(DATA_DIR, `${id}.json`), "utf-8");
    return JSON.parse(raw) as PoliticianProfile;
  } catch {
    return null;
  }
}

export async function savePolitician(profile: PoliticianProfile): Promise<void> {
  await ensureDir();
  await fs.writeFile(
    path.join(DATA_DIR, `${profile.id}.json`),
    JSON.stringify(profile, null, 2),
    "utf-8"
  );
}

export async function listPoliticians(): Promise<PoliticianProfile[]> {
  await ensureDir();
  const files = await fs.readdir(DATA_DIR);
  const profiles: PoliticianProfile[] = [];
  for (const f of files) {
    if (!f.endsWith(".json")) continue;
    try {
      const raw = await fs.readFile(path.join(DATA_DIR, f), "utf-8");
      profiles.push(JSON.parse(raw));
    } catch {
      // skip corrupt entries
    }
  }
  return profiles.sort((a, b) => a.name.localeCompare(b.name));
}
