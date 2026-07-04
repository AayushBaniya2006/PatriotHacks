import { NextRequest } from "next/server";
import { researchPolitician } from "@/lib/agents";
import { getPolitician, slugify } from "@/lib/db";
import type { ResearchEvent } from "@/lib/types";

export const maxDuration = 300;

// POST /api/research { name, force? } → SSE stream of ResearchEvent
export async function POST(req: NextRequest) {
  const { name, force } = await req.json();
  if (!name || typeof name !== "string") {
    return Response.json({ error: "name required" }, { status: 400 });
  }

  const encoder = new TextEncoder();
  const stream = new ReadableStream({
    async start(controller) {
      const send = (e: ResearchEvent & { profile_id?: string }) =>
        controller.enqueue(encoder.encode(`data: ${JSON.stringify(e)}\n\n`));
      try {
        // Latency: serve from db of politicians if already researched
        const existing = await getPolitician(slugify(name));
        if (existing && !force) {
          send({
            type: "complete",
            message: "Loaded from cache",
            progress: 1,
            profile_id: existing.id,
          });
          controller.close();
          return;
        }
        const profile = await researchPolitician(name, send);
        send({ type: "complete", message: "done", progress: 1, profile_id: profile.id });
      } catch (err) {
        send({ type: "error", message: err instanceof Error ? err.message : "Research failed" });
      }
      controller.close();
    },
  });

  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
    },
  });
}
