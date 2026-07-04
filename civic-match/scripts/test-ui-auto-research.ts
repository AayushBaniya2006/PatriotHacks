#!/usr/bin/env tsx
/**
 * UI E2E Test with Playwright - Auto-Research Feature
 * Tests the full user journey with browser automation
 */

import { chromium, type Browser, type Page } from "playwright";
import { promises as fs } from "fs";
import path from "path";

const FRONTEND_URL = process.env.FRONTEND_URL || "https://civic-match-production.up.railway.app";
const BACKEND_URL = process.env.BACKEND_URL || "https://web-production-17c3f.up.railway.app";

interface TestResult {
  name: string;
  status: "pass" | "fail";
  duration: number;
  error?: string;
  screenshot?: string;
}

interface PoliticianApiSummary {
  id: string;
  name: string;
  stances?: unknown[];
}

const results: TestResult[] = [];

function test(name: string, fn: () => Promise<void>) {
  return async () => {
    const start = Date.now();
    try {
      await fn();
      const duration = Date.now() - start;
      results.push({ name, status: "pass", duration });
      console.log(`✓ ${name} (${duration}ms)`);
    } catch (error) {
      const duration = Date.now() - start;
      const errorMsg = error instanceof Error ? error.message : String(error);
      results.push({ name, status: "fail", duration, error: errorMsg });
      console.error(`✗ ${name} (${duration}ms):`);
      console.error(`  ${errorMsg}`);
    }
  };
}

async function takeScreenshot(page: Page, name: string) {
  const screenshotDir = path.join(process.cwd(), "test-results", "screenshots");
  await fs.mkdir(screenshotDir, { recursive: true });
  const filename = path.join(screenshotDir, `${name}-${Date.now()}.png`);
  await page.screenshot({ path: filename, fullPage: true });
  console.log(`  📸 Screenshot: ${filename}`);
  return filename;
}

async function runUITests() {
  console.log("\n🎭 AUTO-RESEARCH UI E2E TEST SUITE (PLAYWRIGHT)\n");
  console.log(`Frontend: ${FRONTEND_URL}`);
  console.log(`Backend:  ${BACKEND_URL}\n`);

  let browser: Browser | null = null;
  let page: Page | null = null;

  try {
    browser = await chromium.launch({ 
      headless: true,
      args: ['--no-sandbox', '--disable-setuid-sandbox']
    });
    const context = await browser.newContext({
      viewport: { width: 1280, height: 720 },
    });
    page = await context.newPage();

    // Test 1: Homepage loads
    await test("Frontend homepage loads", async () => {
      const response = await page!.goto(FRONTEND_URL, { waitUntil: 'networkidle' });
      if (!response || response.status() !== 200) {
        throw new Error(`Frontend returned ${response?.status()}`);
      }
      await takeScreenshot(page!, "01-homepage");
    })();

    // Test 2: Navigate to ballot page
    await test("Navigate to ballot page", async () => {
      await page!.goto(`${FRONTEND_URL}/ballot`, { waitUntil: 'networkidle' });
      await takeScreenshot(page!, "02-ballot-page");
    })();

    // Test 3: Load politician profile with insufficient data
    await test("Load politician profile with insufficient data", async () => {
      const politiciansResponse = await fetch(`${FRONTEND_URL}/api/politicians`);
      const politicians = (await politiciansResponse.json()) as PoliticianApiSummary[];
      const insufficientData = politicians.find((p) => (p.stances?.length || 0) < 8);
      
      if (!insufficientData) {
        console.log("  ⚠ All politicians have sufficient data");
        return;
      }
      
      console.log(`  → Testing with: ${insufficientData.name} (${insufficientData.stances?.length || 0} stances)`);
      await page!.goto(`${FRONTEND_URL}/p/${insufficientData.id}`, { waitUntil: 'networkidle' });
      await takeScreenshot(page!, "03-profile-insufficient-data");
    })();

    // Test 4: Check results page
    await test("Navigate to results page", async () => {
      await page!.evaluate(() => {
        const mockPrefs = {
          preferences: [],
          profile: { flags: {} },
          address: "Austin, TX"
        };
        localStorage.setItem('civic-match-prefs', JSON.stringify(mockPrefs));
      });
      
      await page!.goto(`${FRONTEND_URL}/results`, { waitUntil: 'networkidle', timeout: 30000 });
      await page!.waitForTimeout(2000);
      await takeScreenshot(page!, "04-results-page");
    })();

    // Test 5: Final screenshot
    await test("Capture final state", async () => {
      await takeScreenshot(page!, "05-final-state");
    })();

  } finally {
    if (page) await page.close();
    if (browser) await browser.close();
  }

  // Summary
  console.log("\n" + "=".repeat(60));
  console.log("UI TEST SUMMARY");
  console.log("=".repeat(60));

  const passed = results.filter((r) => r.status === "pass").length;
  const failed = results.filter((r) => r.status === "fail").length;
  const total = results.length;

  console.log(`\nTotal: ${total} | Passed: ${passed} | Failed: ${failed}`);
  console.log(`Success Rate: ${((passed / total) * 100).toFixed(1)}%\n`);

  if (failed > 0) {
    console.log("Failed Tests:");
    results.filter((r) => r.status === "fail").forEach((r) => {
      console.log(`  ✗ ${r.name}`);
      console.log(`    ${r.error}`);
    });
  }

  const resultsFile = path.join(process.cwd(), "test-results", `ui-test-${Date.now()}.json`);
  await fs.writeFile(
    resultsFile,
    JSON.stringify(
      {
        timestamp: new Date().toISOString(),
        frontend_url: FRONTEND_URL,
        backend_url: BACKEND_URL,
        summary: { total, passed, failed, success_rate: (passed / total) * 100 },
        results,
      },
      null,
      2
    )
  );
  console.log(`Results saved to: ${resultsFile}\n`);

  process.exit(failed > 0 ? 1 : 0);
}

runUITests().catch((err) => {
  console.error("Fatal error:", err);
  process.exit(1);
});
