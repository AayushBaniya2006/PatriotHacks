import { NextRequest } from "next/server";
import { loadGraph, neighborhood } from "@/lib/graph";

// GET /api/graph[?focus=node_id&depth=2] — the cross-level knowledge graph
export async function GET(req: NextRequest) {
  const g = await loadGraph();
  const focus = req.nextUrl.searchParams.get("focus");
  const depth = Number(req.nextUrl.searchParams.get("depth") ?? 2);
  if (focus) return Response.json(neighborhood(g, focus, Math.min(depth, 4)));
  return Response.json(g);
}
