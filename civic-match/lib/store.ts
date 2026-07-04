// Key-value store: Postgres (single JSONB table) when DATABASE_URL is set —
// runtime-written data survives Railway redeploys (ephemeral filesystem) — with
// a file-DB fallback (data/<namespace>/<key>.json) when it isn't, so local dev
// and the committed-ground-truth demo path work with zero infrastructure.
// Every value is a whole-object blob keyed by (namespace, key), mirroring the
// original one-file-per-record layout; callers keep read/write-whole-object
// semantics on both backends.
//
// Railway injects DATABASE_URL automatically when a Postgres plugin is attached.
import { Pool } from "pg";
import { promises as fs } from "fs";
import path from "path";

const usePostgres = () => !!process.env.DATABASE_URL;

// ---------- file backend (fallback, matches the committed data/ layout) ----------

const DATA_DIR = path.join(process.cwd(), "data");

function fileFor(namespace: string, key: string): string {
  // guard against path traversal in keys
  const safe = key.replace(/[^a-zA-Z0-9._-]/g, "_");
  return path.join(DATA_DIR, namespace, `${safe}.json`);
}

async function fileGet<T>(namespace: string, key: string): Promise<T | null> {
  try {
    return JSON.parse(await fs.readFile(fileFor(namespace, key), "utf-8")) as T;
  } catch {
    return null;
  }
}

async function fileSet(namespace: string, key: string, value: unknown): Promise<void> {
  const file = fileFor(namespace, key);
  await fs.mkdir(path.dirname(file), { recursive: true });
  // atomic: write temp then rename, so concurrent readers never see partial JSON
  const tmp = `${file}.${process.pid}.${Date.now()}.tmp`;
  await fs.writeFile(tmp, JSON.stringify(value, null, 2), "utf-8");
  await fs.rename(tmp, file);
}

async function fileList<T>(namespace: string): Promise<T[]> {
  const dir = path.join(DATA_DIR, namespace);
  let files: string[];
  try {
    files = (await fs.readdir(dir)).filter((f) => f.endsWith(".json")).sort();
  } catch {
    return [];
  }
  const out: T[] = [];
  for (const f of files) {
    try {
      out.push(JSON.parse(await fs.readFile(path.join(dir, f), "utf-8")) as T);
    } catch {
      // skip corrupt entries
    }
  }
  return out;
}

async function fileDelete(namespace: string, key: string): Promise<void> {
  try {
    await fs.unlink(fileFor(namespace, key));
  } catch {
    // already gone
  }
}

// ---------- postgres backend ----------

// Pool is created lazily on first use (not at import time) so standalone scripts
// that load DATABASE_URL via dotenv at runtime still connect — ES imports are
// hoisted above dotenv's config() call, so the env var isn't set yet at import.
let pool: Pool | null = null;
function getPool(): Pool {
  if (!pool) {
    const connectionString = process.env.DATABASE_URL;
    if (!connectionString) {
      // Guard: getPool() is only reached when usePostgres() is true, so this
      // should never fire. Kept as a safety net.
      throw new Error("DATABASE_URL is not set — expected the file backend instead.");
    }
    // Railway's managed Postgres presents a self-signed chain, so we relax cert
    // verification for non-local connections. Local dev (localhost) uses no SSL.
    const isLocal = /@(localhost|127\.0\.0\.1)/.test(connectionString);
    pool = new Pool({
      connectionString,
      ssl: isLocal ? undefined : { rejectUnauthorized: false },
      max: 5,
    });
  }
  return pool;
}

// Lazily create the table once per process, then reuse the same promise.
let ready: Promise<void> | null = null;
function init(): Promise<void> {
  if (!ready) {
    ready = getPool()
      .query(
        `CREATE TABLE IF NOT EXISTS kv (
           namespace  text        NOT NULL,
           key        text        NOT NULL,
           value      jsonb       NOT NULL,
           updated_at timestamptz NOT NULL DEFAULT now(),
           PRIMARY KEY (namespace, key)
         )`
      )
      .then(() => undefined)
      .catch((err) => {
        // Reset so a transient failure (e.g. DB not ready yet) can retry.
        ready = null;
        throw err;
      });
  }
  return ready;
}

export async function kvGet<T>(namespace: string, key: string): Promise<T | null> {
  if (!usePostgres()) return fileGet<T>(namespace, key);
  await init();
  const res = await getPool().query(
    "SELECT value FROM kv WHERE namespace = $1 AND key = $2",
    [namespace, key]
  );
  return res.rows[0] ? (res.rows[0].value as T) : null;
}

export async function kvSet(namespace: string, key: string, value: unknown): Promise<void> {
  if (!usePostgres()) return fileSet(namespace, key, value);
  await init();
  await getPool().query(
    `INSERT INTO kv (namespace, key, value, updated_at)
     VALUES ($1, $2, $3::jsonb, now())
     ON CONFLICT (namespace, key)
     DO UPDATE SET value = EXCLUDED.value, updated_at = now()`,
    [namespace, key, JSON.stringify(value)]
  );
}

/** All values in a namespace, ordered by key (stable, mirrors sorted readdir). */
export async function kvList<T>(namespace: string): Promise<T[]> {
  if (!usePostgres()) return fileList<T>(namespace);
  await init();
  const res = await getPool().query(
    "SELECT value FROM kv WHERE namespace = $1 ORDER BY key",
    [namespace]
  );
  return res.rows.map((r) => r.value as T);
}

export async function kvDelete(namespace: string, key: string): Promise<void> {
  if (!usePostgres()) return fileDelete(namespace, key);
  await init();
  await getPool().query("DELETE FROM kv WHERE namespace = $1 AND key = $2", [namespace, key]);
}

// Namespace constants — one per former data/<dir>.
export const NS = {
  politicians: "politicians",
  scenarios: "scenarios",
  graph: "graph",
  elections: "elections",
  explanations: "explanations",
  motivations: "motivations",
  debates: "debates",
} as const;
