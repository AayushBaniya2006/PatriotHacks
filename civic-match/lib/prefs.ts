// Client-side user preference storage (explicit, editable, minimal — PRD 8.2).
import type { UserPreferences } from "./types";

const KEY = "civicmatch_prefs";

export function loadPrefs(): UserPreferences | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as UserPreferences) : null;
  } catch {
    return null;
  }
}

export function savePrefs(prefs: UserPreferences) {
  localStorage.setItem(KEY, JSON.stringify(prefs));
}

export function clearPrefs() {
  localStorage.removeItem(KEY);
}
