import { getIssues, getUI } from "@/lib/config";

// All frontend content/config is pulled from the file DB (data/config/*.json).
export async function GET() {
  return Response.json({ issues: getIssues(), ui: getUI() });
}
