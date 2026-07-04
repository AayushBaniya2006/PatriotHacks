import { NextRequest } from "next/server";
import { getBallot } from "@/lib/dataBackend";

// GET /api/ballot?address=<free text>
// Thin server-to-server proxy to our FastAPI data backend — the browser only
// ever calls this same-origin route, so the backend never needs CORS.
export async function GET(req: NextRequest) {
  const address = req.nextUrl.searchParams.get("address")?.trim();
  if (!address) {
    return Response.json({ error: "An address is required" }, { status: 400 });
  }

  const result = await getBallot(address);
  if (!result.ok) {
    return Response.json({ error: result.reason }, { status: result.status ?? 502 });
  }
  return Response.json(result.data);
}
