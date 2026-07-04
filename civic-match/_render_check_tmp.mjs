// Read-only visual verification: seed localStorage prefs for the San Marcos
// golden address, load /results on the already-running dev server, wait for
// the ballot section to actually render, then screenshot at 1280px and
// 375px. Does not modify any project file; only navigates a browser tab.
// (Temporary script, deleted after use -- not part of the app.)
import { chromium } from "playwright";

const BASE = process.argv[2] || "http://127.0.0.1:3001";
const OUT_DIR = process.argv[3] || ".";

const prefs = {
  address: "601 University Dr, San Marcos, TX 78666",
  profile: {
    name: "Jordan",
    occupation: "Teacher",
    age_bracket: "35-49",
    income_bracket: "60-100k",
    flags: { veteran: true },
  },
  priority_weights: {},
  issue_positions: {},
};

async function main() {
  const browser = await chromium.launch({ headless: true, args: ["--no-sandbox"] });
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await context.newPage();

  const logs = [];
  page.on("console", (msg) => logs.push(`[console:${msg.type()}] ${msg.text()}`));
  page.on("pageerror", (err) => logs.push(`[pageerror] ${err.message}`));
  page.on("requestfailed", (req) => logs.push(`[reqfailed] ${req.url()} ${req.failure()?.errorText}`));
  page.on("response", (res) => {
    if (res.url().includes("/api/")) logs.push(`[response] ${res.status()} ${res.url()}`);
  });

  await page.goto(`${BASE}/`, { waitUntil: "domcontentloaded", timeout: 30000 });
  await page.evaluate((p) => {
    localStorage.setItem("civicmatch_prefs", JSON.stringify(p));
  }, prefs);
  const readBack = await page.evaluate(() => localStorage.getItem("civicmatch_prefs"));
  logs.push(`[localStorage readback len] ${readBack?.length ?? "null"}`);

  await page.goto(`${BASE}/results`, { waitUntil: "networkidle", timeout: 30000 }).catch((e) => logs.push(`[goto] ${e.message.split("\n")[0]}`));
  await page.waitForTimeout(2000);
  await page.reload({ waitUntil: "networkidle", timeout: 30000 }).catch((e) => logs.push(`[reload] ${e.message.split("\n")[0]}`));

  await page
    .waitForSelector("text=Scoring cached candidate profiles", { state: "detached", timeout: 20000 })
    .catch((e) => logs.push(`[wait-scoring-gone] ${e.message.split("\n")[0]}`));
  await page.waitForSelector("text=Your ballot", { timeout: 20000 }).catch((e) => logs.push(`[wait-your-ballot] ${e.message}`));
  await page.waitForSelector("text=Featured race", { timeout: 20000 }).catch((e) => logs.push(`[wait-featured] ${e.message}`));
  await page.waitForTimeout(1500);

  // Scroll to "Your ballot" (the section I actually edited) and screenshot
  // just that region in slices, rather than one giant full-page image
  // dominated by the ~96 unrelated match-score cards above it.
  const ballotHeading = page.locator("text=Your ballot").first();
  await ballotHeading.scrollIntoViewIfNeeded().catch(() => {});
  await page.waitForTimeout(300);
  await page.screenshot({ path: `${OUT_DIR}/ballot_1280_a_readiness_featured.png` });
  await page.mouse.wheel(0, 850);
  await page.waitForTimeout(200);
  await page.screenshot({ path: `${OUT_DIR}/ballot_1280_b_featured_cont.png` });
  await page.mouse.wheel(0, 850);
  await page.waitForTimeout(200);
  await page.screenshot({ path: `${OUT_DIR}/ballot_1280_c_secondary_races.png` });
  await page.mouse.wheel(0, 850);
  await page.waitForTimeout(200);
  await page.screenshot({ path: `${OUT_DIR}/ballot_1280_d_insights_votingplan.png` });

  await page.setViewportSize({ width: 375, height: 812 });
  await page.waitForTimeout(400);
  await ballotHeading.scrollIntoViewIfNeeded().catch(() => {});
  await page.waitForTimeout(300);
  await page.screenshot({ path: `${OUT_DIR}/ballot_375_a_readiness_featured.png` });
  await page.mouse.wheel(0, 700);
  await page.waitForTimeout(200);
  await page.screenshot({ path: `${OUT_DIR}/ballot_375_b_featured_cont.png` });
  await page.mouse.wheel(0, 700);
  await page.waitForTimeout(200);
  await page.screenshot({ path: `${OUT_DIR}/ballot_375_c_secondary_races.png` });
  await page.mouse.wheel(0, 700);
  await page.waitForTimeout(200);
  await page.screenshot({ path: `${OUT_DIR}/ballot_375_d_more.png` });

  const bodyText = await page.textContent("body").catch(() => "");
  const hasFeatured = bodyText?.includes("Featured race") ?? false;
  const hasReadiness = bodyText?.includes("Reviewed") || bodyText?.includes("ballot-ready");
  const hasHowWeKnow = bodyText?.includes("How we know");

  console.log(JSON.stringify({
    hasFeatured,
    hasReadiness,
    hasHowWeKnow,
    bodyTextLength: bodyText?.length ?? 0,
    consoleLogs: logs.filter((l) => !l.includes("webpack-hmr") && !l.includes("React DevTools")).slice(0, 40),
  }, null, 2));

  await browser.close();
}

main().catch((err) => {
  console.error("SCRIPT_ERROR", err);
  process.exit(1);
});
