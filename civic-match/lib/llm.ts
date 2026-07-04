// OpenRouter LLM helpers. Latency-first: small default models, parallel calls,
// strict JSON extraction, short prompts.

const OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions";

// Kimi swarm: all agents run on Kimi K2 via OpenRouter.
// Research agents get web search (":online" enables the OpenRouter web plugin);
// the verifier/output/Q&A agents run plain Kimi K2 for speed.
export const RESEARCH_MODEL =
  process.env.RESEARCH_MODEL || "moonshotai/kimi-k2-0905:online";
export const FAST_MODEL = process.env.FAST_MODEL || "moonshotai/kimi-k2-0905";

export interface ChatMessage {
  role: "system" | "user" | "assistant";
  content: string;
}

export async function chat(
  messages: ChatMessage[],
  opts: { model?: string; temperature?: number; maxTokens?: number; timeoutMs?: number } = {}
): Promise<string> {
  const apiKey = process.env.OPENROUTER_API_KEY;
  if (!apiKey) throw new Error("Missing OPENROUTER_API_KEY");

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), opts.timeoutMs ?? 120_000);
  try {
    const res = await fetch(OPENROUTER_URL, {
      method: "POST",
      signal: controller.signal,
      headers: {
        Authorization: `Bearer ${apiKey}`,
        "Content-Type": "application/json",
        "HTTP-Referer": "https://civicmatch.local",
        "X-Title": "Civic Match",
      },
      body: JSON.stringify({
        model: opts.model ?? FAST_MODEL,
        messages,
        temperature: opts.temperature ?? 0.2,
        max_tokens: opts.maxTokens ?? 4096,
      }),
    });
    if (!res.ok) {
      const body = await res.text();
      throw new Error(`OpenRouter ${res.status}: ${body.slice(0, 300)}`);
    }
    const data = await res.json();
    return data.choices?.[0]?.message?.content ?? "";
  } finally {
    clearTimeout(timeout);
  }
}

/** Extract the first JSON object/array from model output (tolerates fences/prose). */
export function extractJSON<T>(text: string): T {
  const fenced = text.match(/```(?:json)?\s*([\s\S]*?)```/);
  const candidate = fenced ? fenced[1] : text;
  const start = candidate.search(/[[{]/);
  if (start === -1) throw new Error("No JSON found in model output");
  // Find matching close by scanning
  const open = candidate[start];
  const close = open === "[" ? "]" : "}";
  let depth = 0;
  let inStr = false;
  let esc = false;
  for (let i = start; i < candidate.length; i++) {
    const ch = candidate[i];
    if (esc) { esc = false; continue; }
    if (ch === "\\") { esc = true; continue; }
    if (ch === '"') inStr = !inStr;
    if (inStr) continue;
    if (ch === open) depth++;
    else if (ch === close) {
      depth--;
      if (depth === 0) {
        return JSON.parse(candidate.slice(start, i + 1)) as T;
      }
    }
  }
  throw new Error("Unbalanced JSON in model output");
}
